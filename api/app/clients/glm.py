from __future__ import annotations

import json
import os
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.schemas.analysis import (
    DecisionAnalysisRequest,
    DecisionAnalysisResponse,
    DecisionType,
    EvidencePacket,
    PriceOutlook,
    RiskLevel,
)

DEFAULT_ZAI_MODEL = "ilmu-glm-5.1"


class GLMClientError(Exception):
    """Base error for GLM recommendation client failures."""


class GLMMissingAPIKeyError(GLMClientError):
    """Raised when the Z AI API key is not configured."""


class GLMRequestError(GLMClientError):
    """Raised when the chat completions request fails."""


class GLMInvalidJSONError(GLMClientError):
    """Raised when the model or API response is not valid JSON."""


class GLMSchemaValidationError(GLMClientError):
    """Raised when the model output cannot be validated against the response schema."""


class _ChatCompletionMessage(BaseModel):
    content: str | None = None


class _ChatCompletionChoice(BaseModel):
    message: _ChatCompletionMessage


class _ChatCompletionResponse(BaseModel):
    choices: list[_ChatCompletionChoice] = Field(default_factory=list)


class _RecommendationPayload(BaseModel):
    decision: DecisionType
    price_outlook: PriceOutlook
    revenue_risk: RiskLevel
    confidence: float = Field(ge=0, le=1)
    summary: str
    reasons: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_review_days: int = Field(ge=1, le=30)


class GLMDecisionClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = (
            api_key
            or settings.ilmu_api_key
            or os.getenv("ILMU_API_KEY")
            or os.getenv("ZAI_API_KEY")
        )
        self.model = model or settings.glm_model or DEFAULT_ZAI_MODEL
        self.base_url = base_url or settings.ilmu_base_url
        self.endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        self.timeout = timeout

    async def analyze(
        self,
        request: DecisionAnalysisRequest,
        evidence: EvidencePacket,
    ) -> DecisionAnalysisResponse:
        self._ensure_api_key()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.endpoint,
                    headers=self._headers(),
                    json=self._request_payload(request, evidence),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GLMRequestError(self._request_error_message(exc)) from exc

        return self._parse_response(response, evidence)

    def analyze_sync(
        self,
        request: DecisionAnalysisRequest,
        evidence: EvidencePacket,
    ) -> DecisionAnalysisResponse:
        self._ensure_api_key()

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.endpoint,
                    headers=self._headers(),
                    json=self._request_payload(request, evidence),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GLMRequestError(self._request_error_message(exc)) from exc

        return self._parse_response(response, evidence)

    def _ensure_api_key(self) -> None:
        if not self.api_key:
            raise GLMMissingAPIKeyError(
                "ILMU_API_KEY is not configured; set ILMU_API_KEY or the legacy ZAI_API_KEY environment variable."
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request_payload(
        self,
        request: DecisionAnalysisRequest,
        evidence: EvidencePacket,
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": self._system_prompt(),
                },
                {
                    "role": "user",
                    "content": self._user_prompt(request, evidence),
                },
            ],
        }

    def _system_prompt(self) -> str:
        return (
            "You are AgriPivot's decision engine. "
            "Use only the structured request and evidence summaries provided. "
            "Do not invent missing facts. "
            "Optimize for revenue-aware crop decisions with pricing as a first-class signal. "
            "Return only one JSON object with keys: "
            "decision, price_outlook, revenue_risk, confidence, summary, reasons, actions, risks, next_review_days. "
            "Allowed decision values: persevere, pivot_partially, harvest_early. "
            "Allowed price_outlook values: increase, stable, decrease. "
            "Allowed revenue_risk values: low, medium, high. "
            "Keep reasons, actions, and risks concise."
        )

    def _user_prompt(
        self,
        request: DecisionAnalysisRequest,
        evidence: EvidencePacket,
    ) -> str:
        prompt_payload = {
            "request": self._request_summary(request),
            "evidence": self._evidence_summary(evidence),
            "response_rules": {
                "summary_max_sentences": 2,
                "reason_count": 3,
                "action_count": 3,
                "risk_count": 3,
                "confidence_range": [0, 1],
                "next_review_days_range": [1, 30],
                "pricing_must_be_reflected": True,
            },
        }
        return json.dumps(prompt_payload, ensure_ascii=True, separators=(",", ":"))

    def _request_summary(self, request: DecisionAnalysisRequest) -> dict[str, Any]:
        return {
            "location": request.location,
            "crop": request.crop,
            "candidate_crops": request.candidate_crops,
            "expected_harvest_days": request.expected_harvest_days,
            "farm_size_hectares": request.farm_size_hectares,
            "labor_flexibility_pct": request.labor_flexibility_pct,
            "price_trend_hint": request.price_trend_hint,
            "weather_risk_level": request.weather_risk_level,
            "news_signals": request.news_signals,
        }

    def _evidence_summary(self, evidence: EvidencePacket) -> dict[str, Any]:
        price_snapshot = evidence.price_snapshot
        weather_snapshot = evidence.weather_snapshot

        result: dict[str, Any] = {
            "signals": {
                "price_signal": evidence.price_signal,
                "weather_signal": evidence.weather_signal,
                "news_signal": evidence.news_signal,
                "hedge_crop": evidence.hedge_crop,
            },
            "price_snapshot": {
                "crop": price_snapshot.crop,
                "region": price_snapshot.region,
                "market": price_snapshot.market,
                "source": price_snapshot.source,
                "as_of": price_snapshot.as_of.isoformat(),
                "direction": price_snapshot.direction,
                "direction_basis": price_snapshot.direction_basis,
                "current_price": self._price_point_summary(price_snapshot.current_price),
                "recent_history": [
                    self._price_point_summary(point)
                    for point in price_snapshot.history[-4:]
                ],
                "notes": price_snapshot.notes[:4],
            },
            "news_items": [
                {
                    "title": item.title,
                    "source": item.source,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                    "summary": item.summary,
                    "event_tags": item.event_tags[:4],
                    "tone": item.tone,
                    "crop": item.crop,
                    "region": item.region,
                }
                for item in evidence.news_signals[:5]
            ],
        }

        if weather_snapshot is not None:
            result["weather_snapshot"] = {
                "source": weather_snapshot.source,
                "fetched_at": weather_snapshot.fetched_at.isoformat(),
                "location": {
                    "name": weather_snapshot.resolved_location.name,
                    "country": weather_snapshot.resolved_location.country,
                    "admin1": weather_snapshot.resolved_location.admin1,
                    "timezone": weather_snapshot.resolved_location.timezone,
                },
                "current": {
                    "observed_at": weather_snapshot.current.observed_at.isoformat(),
                    "temperature_c": weather_snapshot.current.temperature_c,
                    "precipitation_mm": weather_snapshot.current.precipitation_mm,
                    "relative_humidity_pct": weather_snapshot.current.relative_humidity_pct,
                    "wind_speed_10m_kph": weather_snapshot.current.wind_speed_10m_kph,
                    "wind_gusts_10m_kph": weather_snapshot.current.wind_gusts_10m_kph,
                    "weather_code": weather_snapshot.current.weather_code,
                },
                "forecast": [
                    {
                        "date": day.date.isoformat(),
                        "temperature_max_c": day.temperature_max_c,
                        "temperature_min_c": day.temperature_min_c,
                        "precipitation_sum_mm": day.precipitation_sum_mm,
                        "precipitation_probability_max_pct": day.precipitation_probability_max_pct,
                        "wind_speed_10m_max_kph": day.wind_speed_10m_max_kph,
                        "wind_gusts_10m_max_kph": day.wind_gusts_10m_max_kph,
                        "weather_code": day.weather_code,
                    }
                    for day in weather_snapshot.forecast[:5]
                ],
            }

        return result

    def _price_point_summary(self, point: Any) -> dict[str, Any] | None:
        if point is None:
            return None
        return {
            "observed_at": point.observed_at.isoformat(),
            "price": point.price,
            "currency": point.currency,
            "unit": point.unit,
            "source": point.source,
            "market": point.market,
        }

    def _parse_response(
        self,
        response: httpx.Response,
        evidence: EvidencePacket,
    ) -> DecisionAnalysisResponse:
        try:
            payload = _ChatCompletionResponse.model_validate(response.json())
        except (ValidationError, json.JSONDecodeError) as exc:
            raise GLMInvalidJSONError("GLM API response was not valid JSON.") from exc

        content = self._first_message_content(payload.choices)
        if not content:
            raise GLMInvalidJSONError("GLM API response did not contain a chat completion message.")

        try:
            parsed_json = json.loads(self._normalize_json_content(content))
        except json.JSONDecodeError as exc:
            raise GLMInvalidJSONError("GLM model output was not valid JSON.") from exc

        try:
            recommendation = _RecommendationPayload.model_validate(parsed_json)
        except ValidationError as exc:
            raise GLMSchemaValidationError(
                "GLM model output did not match the recommendation contract."
            ) from exc

        try:
            return DecisionAnalysisResponse(
                decision=recommendation.decision,
                price_outlook=recommendation.price_outlook,
                revenue_risk=recommendation.revenue_risk,
                confidence=recommendation.confidence,
                summary=recommendation.summary,
                reasons=recommendation.reasons,
                actions=recommendation.actions,
                risks=recommendation.risks,
                evidence=evidence,
                next_review_days=recommendation.next_review_days,
            )
        except ValidationError as exc:
            raise GLMSchemaValidationError(
                "GLM recommendation could not be validated against DecisionAnalysisResponse."
            ) from exc

    def _first_message_content(self, choices: Sequence[_ChatCompletionChoice]) -> str | None:
        if not choices:
            return None
        return choices[0].message.content

    def _normalize_json_content(self, content: str) -> str:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
        return cleaned

    def _request_error_message(self, exc: httpx.HTTPError) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            response_text = exc.response.text.strip()
            if response_text:
                response_text = f" Body: {response_text[:500]}"
            return (
                f"GLM request failed with status {exc.response.status_code} "
                f"for {exc.request.url!s}.{response_text}"
            )
        if isinstance(exc, httpx.RequestError):
            return f"GLM request failed before receiving a response: {exc!s}"
        return f"GLM request failed: {exc!s}"


__all__ = [
    "DEFAULT_ZAI_MODEL",
    "GLMDecisionClient",
    "GLMClientError",
    "GLMInvalidJSONError",
    "GLMMissingAPIKeyError",
    "GLMRequestError",
    "GLMSchemaValidationError",
    "ZAI_CHAT_COMPLETIONS_URL",
]
