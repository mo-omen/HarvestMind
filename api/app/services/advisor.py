from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import ValidationError

from app.clients.glm import GLMMissingAPIKeyError, GLMRequestError
from app.core.config import settings
from app.db.postgres import PostgresDatabase
from app.repositories.profiles import PostgresFarmerProfileRepository
from app.repositories.recommendations import RecommendationRepository, RecommendationRunRecord
from app.repositories.signals import SignalSnapshotRecord, SignalSnapshotRepository
from app.schemas.advisor import (
    AdvisorGroundedContext,
    AdvisorMessageRequest,
    AdvisorMessageResponse,
    SignalFreshness,
)
from app.schemas.intake import IntakeFieldUpdate

FRESHNESS_WINDOW_HOURS = 12.0
_ALLOWED_UPDATE_FIELDS = {
    "location",
    "crop",
    "expected_harvest_days",
    "farm_size_hectares",
    "labor_flexibility_pct",
    "candidate_crops",
}


class AdvisorServiceError(RuntimeError):
    """Base error raised by the grounded advisor service."""


class AdvisorProfileNotFoundError(AdvisorServiceError):
    """Raised when a follow-up request references an unknown farmer."""


class AdvisorGLMClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key or settings.ilmu_api_key
        self.model = model or settings.glm_model
        self.base_url = (base_url or settings.ilmu_base_url).rstrip("/")
        self.timeout = timeout

    async def answer(
        self,
        *,
        request: AdvisorMessageRequest,
        context: AdvisorGroundedContext,
        latest_run: RecommendationRunRecord | None,
        freshness: list[SignalFreshness],
        suggested_updates: IntakeFieldUpdate | None,
    ) -> str:
        if not self.api_key:
            raise GLMMissingAPIKeyError("ILMU_API_KEY is not configured.")

        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are AgriPivot's farmer advisor. Answer only from the provided "
                        "farmer profile, latest decision run, evidence summaries, and freshness "
                        "metadata. Do not invent prices, weather, or news. If the user asks to "
                        "change farm configuration, explain the proposed change and that a rerun "
                        "is needed. Keep the answer concise and practical."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "question": request.message,
                            "recent_history": [
                                item.model_dump(mode="json") for item in request.history[-6:]
                            ],
                            "grounded_context": context.model_dump(mode="json"),
                            "latest_run": _latest_run_summary(latest_run),
                            "data_freshness": [
                                item.model_dump(mode="json") for item in freshness
                            ],
                            "suggested_config_updates": (
                                suggested_updates.model_dump(exclude_none=True)
                                if suggested_updates is not None
                                else None
                            ),
                        },
                        ensure_ascii=True,
                    ),
                },
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GLMRequestError(str(exc)) from exc

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise GLMRequestError("GLM advisor response was not usable.") from exc

        return str(content).strip() or "I could not produce a grounded answer from the current context."


class AdvisorService:
    def __init__(
        self,
        database: PostgresDatabase,
        *,
        glm_client: AdvisorGLMClient | None = None,
    ) -> None:
        self._profile_repository = PostgresFarmerProfileRepository(conninfo=database.config.dsn)
        self._recommendation_repository = RecommendationRepository(database)
        self._signal_repository = SignalSnapshotRepository(database)
        self._glm_client = glm_client or AdvisorGLMClient()

    async def answer(self, payload: AdvisorMessageRequest) -> AdvisorMessageResponse:
        profile = self._profile_repository.get_profile(payload.farmer_id)
        if profile is None:
            raise AdvisorProfileNotFoundError(f"Profile '{payload.farmer_id}' was not found.")

        latest_run = _first_or_none(
            self._recommendation_repository.fetch_history(payload.farmer_id, limit=1)
        )
        signal_history = self._signal_repository.fetch_history(payload.farmer_id, limit=30)
        freshness = _build_freshness(signal_history)
        suggested_updates = _extract_config_updates(payload.message)
        context = _build_context(
            farmer_id=payload.farmer_id,
            profile=profile,
            latest_run=latest_run,
        )

        try:
            answer = await self._glm_client.answer(
                request=payload,
                context=context,
                latest_run=latest_run,
                freshness=freshness,
                suggested_updates=suggested_updates,
            )
        except Exception:
            answer = _fallback_answer(
                message=payload.message,
                context=context,
                freshness=freshness,
                suggested_updates=suggested_updates,
            )

        return AdvisorMessageResponse(
            answer=answer,
            grounded_context=context,
            suggested_config_updates=suggested_updates,
            needs_rerun=suggested_updates is not None,
            data_freshness=freshness,
        )


def _build_context(
    *,
    farmer_id: str,
    profile: dict[str, Any],
    latest_run: RecommendationRunRecord | None,
) -> AdvisorGroundedContext:
    input_payload = latest_run.input_payload if latest_run is not None else {}
    evidence = latest_run.evidence_packet if latest_run is not None else {}

    crop = _text_or_none(profile.get("current_crop")) or _text_or_none(input_payload.get("crop"))
    candidate_crops = _string_list(profile.get("candidate_crops")) or _string_list(
        input_payload.get("candidate_crops")
    )

    return AdvisorGroundedContext(
        farmer_id=farmer_id,
        location=str(profile.get("location") or input_payload.get("location") or ""),
        crop=crop,
        candidate_crops=candidate_crops,
        latest_decision=latest_run.decision if latest_run is not None else None,
        latest_confidence=latest_run.confidence if latest_run is not None else None,
        evidence_summary=_evidence_summary(evidence),
    )


def _build_freshness(records: list[SignalSnapshotRecord]) -> list[SignalFreshness]:
    latest_by_type: dict[str, SignalSnapshotRecord] = {}
    for record in records:
        if record.signal_type not in latest_by_type:
            latest_by_type[record.signal_type] = record

    result: list[SignalFreshness] = []
    now = datetime.now(UTC)
    for signal_type in ("price", "weather", "news"):
        record = latest_by_type.get(signal_type)
        if record is None:
            result.append(SignalFreshness(signal_type=signal_type))
            continue

        created_at = record.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        age_hours = max((now - created_at.astimezone(UTC)).total_seconds() / 3600, 0)
        result.append(
            SignalFreshness(
                signal_type=signal_type,
                last_updated_at=created_at,
                age_hours=round(age_hours, 2),
                is_stale=age_hours > FRESHNESS_WINDOW_HOURS,
                source=record.source,
            )
        )
    return result


def _extract_config_updates(message: str) -> IntakeFieldUpdate | None:
    text = message.strip()
    lower = text.casefold()
    update_markers = (
        "change",
        "update",
        "set",
        "switch",
        "modify",
        "edit",
        "actually",
        "correction",
    )
    if not any(marker in lower for marker in update_markers):
        return None

    candidate: dict[str, Any] = {}

    crop = _extract_after_patterns(
        text,
        (
            r"(?:current\s+crop|main\s+crop|crop)\s+(?:to|is|as)\s+([A-Za-z][A-Za-z\s-]{1,40})",
            r"(?:switch|change|set)\s+(?:to\s+)?([A-Za-z][A-Za-z\s-]{1,40})(?:\s+as\s+)?(?:my\s+)?(?:current\s+)?crop",
        ),
    )
    if crop:
        candidate["crop"] = crop

    location = _extract_after_patterns(
        text,
        (
            r"(?:location|farm\s+location|area)\s+(?:to|is|as)\s+([A-Za-z][A-Za-z\s,.-]{2,80})",
        ),
    )
    if location:
        candidate["location"] = location

    harvest = _extract_number(
        lower,
        (
            r"(?:harvest|harvest\s+window|harvesting).*?(\d{1,3})\s*(?:days?|d)\b",
            r"(\d{1,3})\s*(?:days?|d)\s+(?:to|until|before)\s+harvest",
        ),
    )
    if harvest is not None:
        candidate["expected_harvest_days"] = harvest

    farm_size = _extract_float(
        lower,
        (
            r"(?:farm\s+size|size|area).*?(\d+(?:\.\d+)?)\s*(?:ha|hectares?)\b",
            r"(\d+(?:\.\d+)?)\s*(?:ha|hectares?)",
        ),
    )
    if farm_size is not None:
        candidate["farm_size_hectares"] = farm_size

    labor = _extract_number(
        lower,
        (
            r"(?:labor|labour).*?(\d{1,3})\s*%",
            r"(\d{1,3})\s*%\s+(?:labor|labour)",
        ),
    )
    if labor is not None:
        candidate["labor_flexibility_pct"] = labor

    candidates = _extract_candidate_crops(text)
    if candidates:
        candidate["candidate_crops"] = candidates

    if not candidate:
        return None

    filtered = {key: value for key, value in candidate.items() if key in _ALLOWED_UPDATE_FIELDS}
    try:
        return IntakeFieldUpdate(**filtered)
    except ValidationError:
        return None


def _extract_after_patterns(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = _clean_extracted_text(match.group(1))
            if value:
                return value
    return None


def _extract_number(text: str, patterns: tuple[str, ...]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _extract_float(text: str, patterns: tuple[str, ...]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _extract_candidate_crops(text: str) -> list[str] | None:
    match = re.search(
        r"(?:candidate|alternative|pivot|consider)\s+crops?\s+(?:to|are|as|include)?\s*([A-Za-z][A-Za-z\s,/-]{2,120})",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    raw = match.group(1)
    parts = re.split(r",|/|\band\b|\bor\b", raw, flags=re.IGNORECASE)
    crops = [_clean_extracted_text(part) for part in parts]
    return [crop for crop in crops if crop]


def _clean_extracted_text(value: str) -> str | None:
    cleaned = re.split(
        r"\b(?:with|and|but|because|for|in|from|please|thanks|thank)\b",
        value.strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    cleaned = cleaned.strip(" .,;:-")
    return cleaned or None


def _fallback_answer(
    *,
    message: str,
    context: AdvisorGroundedContext,
    freshness: list[SignalFreshness],
    suggested_updates: IntakeFieldUpdate | None,
) -> str:
    stale = [item.signal_type for item in freshness if item.is_stale]
    stale_note = (
        f" Data freshness warning: {', '.join(stale)} signals are older than 12 hours or unavailable."
        if stale
        else " Price, weather, and news signals are within the expected 12-hour freshness window."
    )

    if suggested_updates is not None:
        changes = suggested_updates.model_dump(exclude_none=True)
        return (
            "I found a farm configuration change in your message. "
            f"Proposed updates: {json.dumps(changes, ensure_ascii=True)}. "
            "Confirm the edit and rerun analysis before acting on a new recommendation."
            f"{stale_note}"
        )

    decision = context.latest_decision or "no completed recommendation yet"
    crop = context.crop or "the current crop"
    evidence = " ".join(context.evidence_summary[:3])
    return (
        f"Based on the latest saved context for {crop}, the current decision is {decision}. "
        f"{evidence or 'No evidence summary is available yet.'} "
        f"For your question, use the latest recommendation as the source of truth and rerun analysis if the farm setup has changed."
        f"{stale_note}"
    )


def _evidence_summary(evidence: dict[str, Any]) -> list[str]:
    summary: list[str] = []
    for key in ("price_signal", "weather_signal", "news_signal", "seasonal_weather_context"):
        value = evidence.get(key)
        if isinstance(value, str) and value.strip():
            summary.append(value.strip())
    return summary


def _latest_run_summary(latest_run: RecommendationRunRecord | None) -> dict[str, Any] | None:
    if latest_run is None:
        return None
    return {
        "decision": latest_run.decision,
        "confidence": latest_run.confidence,
        "recorded_at": latest_run.recorded_at.isoformat(),
        "input_payload": latest_run.input_payload,
        "evidence_summary": _evidence_summary(latest_run.evidence_packet),
    }


def _first_or_none(records: list[RecommendationRunRecord]) -> RecommendationRunRecord | None:
    return records[0] if records else None


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
