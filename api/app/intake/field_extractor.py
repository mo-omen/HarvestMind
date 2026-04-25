from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.malaysia import is_malaysia_relevant_location
from app.core.config import settings
from app.schemas.intake import IntakeFieldName, IntakeFieldUpdate, IntakeState


DEFAULT_ZAI_MODEL = "ilmu-glm-5.1"
ExtractionSource = Literal["glm", "fallback"]
logger = logging.getLogger(__name__)


class FieldExtractorError(RuntimeError):
    """Raised when GLM-backed intake extraction is unavailable or invalid."""

_FIELD_ALIASES: dict[str, IntakeFieldName] = {
    "location": "location",
    "crop": "crop",
    "current_crop": "crop",
    "current crop": "crop",
    "expected_harvest_days": "expected_harvest_days",
    "expected harvest days": "expected_harvest_days",
    "expected_harvest_window": "expected_harvest_days",
    "expected harvest window": "expected_harvest_days",
    "harvest_days": "expected_harvest_days",
    "harvest days": "expected_harvest_days",
    "harvest_window": "expected_harvest_days",
    "harvest window": "expected_harvest_days",
    "farm_size_hectares": "farm_size_hectares",
    "farm_size": "farm_size_hectares",
    "farm size": "farm_size_hectares",
    "labor_flexibility_pct": "labor_flexibility_pct",
    "labor flexibility pct": "labor_flexibility_pct",
    "labor_flexibility": "labor_flexibility_pct",
    "labor flexibility": "labor_flexibility_pct",
    "candidate_crops": "candidate_crops",
    "candidate crops": "candidate_crops",
    "candidate_crop": "candidate_crops",
    "alternative_crops": "candidate_crops",
    "alternative crops": "candidate_crops",
}
_MONTH_PATTERN = re.compile(
    r"\b("
    r"january|february|march|april|may|june|july|august|"
    r"september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
    r")\b",
    re.IGNORECASE,
)
_LOCATION_PREFIXES = (
    "i am in ",
    "i'm in ",
    "we are in ",
    "we're in ",
    "located in ",
    "based in ",
    "farming in ",
    "farm in ",
    "at ",
    "in ",
    "near ",
    "around ",
)
_CROP_PREFIXES = (
    "i grow ",
    "we grow ",
    "i'm growing ",
    "we're growing ",
    "growing ",
    "planted ",
    "planting ",
    "my crop is ",
    "our crop is ",
    "it is ",
    "it's ",
    "mostly ",
    "mainly ",
    "currently ",
)
_LIST_PREFIXES = (
    "candidate crops are ",
    "candidate crop is ",
    "i can switch to ",
    "we can switch to ",
    "considering ",
    "thinking about ",
    "options are ",
    "maybe ",
    "perhaps ",
)


class FieldExtractionResult(BaseModel):
    asked_field: IntakeFieldName
    updates: IntakeFieldUpdate
    source: ExtractionSource
    model: str | None = None
    warnings: list[str] = Field(default_factory=list)


class _GLMExtractionPayload(BaseModel):
    updates: IntakeFieldUpdate


class GLMFieldExtractor:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 20.0,
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

    async def extract(
        self,
        asked_field: IntakeFieldName | str,
        intake_state: IntakeState | Mapping[str, Any] | None,
        farmer_answer: str,
    ) -> IntakeFieldUpdate:
        return (await self.extract_result(asked_field, intake_state, farmer_answer)).updates

    async def extract_result(
        self,
        asked_field: IntakeFieldName | str,
        intake_state: IntakeState | Mapping[str, Any] | None,
        farmer_answer: str,
    ) -> FieldExtractionResult:
        canonical_field = _normalize_field_name(asked_field)
        state = _coerce_state(intake_state)
        answer = _clean_text(farmer_answer)

        if not answer:
            return self._fallback_result(
                canonical_field,
                state,
                answer,
                warning="empty_farmer_answer",
            )

        if not self.api_key:
            raise FieldExtractorError(
                "ILMU_API_KEY is not configured, so ILMU-backed intake extraction is unavailable."
            )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.endpoint,
                    headers=self._headers(),
                    json=self._request_payload(canonical_field, state, answer),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise FieldExtractorError(f"GLM intake extraction request failed: {exc}") from exc

        parsed = self._parse_glm_response(response)
        if parsed is None:
            logger.warning(
                "ILMU intake extraction returned an unparseable payload for field '%s': %s",
                canonical_field,
                response.text[:500],
            )
            return self._fallback_result(
                canonical_field,
                state,
                answer,
                warning="invalid_glm_response",
            )

        return FieldExtractionResult(
            asked_field=canonical_field,
            updates=self._merge_with_fallback(
                asked_field=canonical_field,
                state=state,
                farmer_answer=answer,
                updates=self._normalize_updates(parsed.updates, state),
            ),
            source="glm",
            model=self.model,
        )

    def extract_sync(
        self,
        asked_field: IntakeFieldName | str,
        intake_state: IntakeState | Mapping[str, Any] | None,
        farmer_answer: str,
    ) -> IntakeFieldUpdate:
        return self.extract_result_sync(asked_field, intake_state, farmer_answer).updates

    def extract_result_sync(
        self,
        asked_field: IntakeFieldName | str,
        intake_state: IntakeState | Mapping[str, Any] | None,
        farmer_answer: str,
    ) -> FieldExtractionResult:
        canonical_field = _normalize_field_name(asked_field)
        state = _coerce_state(intake_state)
        answer = _clean_text(farmer_answer)

        if not answer:
            return self._fallback_result(
                canonical_field,
                state,
                answer,
                warning="empty_farmer_answer",
            )

        if not self.api_key:
            raise FieldExtractorError(
                "ILMU_API_KEY is not configured, so ILMU-backed intake extraction is unavailable."
            )

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.endpoint,
                    headers=self._headers(),
                    json=self._request_payload(canonical_field, state, answer),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise FieldExtractorError(f"GLM intake extraction request failed: {exc}") from exc

        parsed = self._parse_glm_response(response)
        if parsed is None:
            logger.warning(
                "ILMU intake extraction returned an unparseable payload for field '%s': %s",
                canonical_field,
                response.text[:500],
            )
            return self._fallback_result(
                canonical_field,
                state,
                answer,
                warning="invalid_glm_response",
            )

        return FieldExtractionResult(
            asked_field=canonical_field,
            updates=self._merge_with_fallback(
                asked_field=canonical_field,
                state=state,
                farmer_answer=answer,
                updates=self._normalize_updates(parsed.updates, state),
            ),
            source="glm",
            model=self.model,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _request_payload(
        self,
        asked_field: IntakeFieldName,
        state: IntakeState,
        farmer_answer: str,
    ) -> dict[str, Any]:
        system_prompt = (
            "Extract structured farmer intake updates from one answer. "
            "Return JSON only with the shape {\"updates\": {...}}. "
            "Use only these keys when they are directly supported by the answer: "
            "location, crop, expected_harvest_days, farm_size_hectares, "
            "labor_flexibility_pct, candidate_crops. "
            "Do not output null values. Do not guess. "
            "Convert acres to hectares. "
            "Convert durations like weeks or months into expected_harvest_days when possible. "
            "candidate_crops must be an array of crop names."
        )
        user_prompt = json.dumps(
            {
                "asked_field": asked_field,
                "current_state": state.model_dump(mode="json", exclude_none=True),
                "farmer_answer": farmer_answer,
                "response_schema": {
                    "updates": {
                        "location": "string",
                        "crop": "string",
                        "expected_harvest_days": "integer 1-365",
                        "farm_size_hectares": "number > 0",
                        "labor_flexibility_pct": "integer 0-100",
                        "candidate_crops": ["string"],
                    }
                },
            },
            ensure_ascii=True,
        )
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "stream": False,
            "temperature": 0,
            "max_tokens": 1024,
        }

    def _parse_glm_response(self, response: httpx.Response) -> _GLMExtractionPayload | None:
        try:
            body = response.json()
            content = _extract_completion_content(body)
            if not content:
                return None
            payload = _decode_extraction_payload(content)
            if payload is None:
                return None
            return _GLMExtractionPayload.model_validate(payload)
        except (ValidationError, ValueError, TypeError, IndexError, KeyError):
            return None

    def _normalize_updates(
        self,
        updates: IntakeFieldUpdate,
        state: IntakeState,
    ) -> IntakeFieldUpdate:
        payload: dict[str, Any] = {}

        if "location" in updates.model_fields_set and updates.location:
            payload["location"] = _clean_text(updates.location)
        if "crop" in updates.model_fields_set and updates.crop:
            payload["crop"] = _clean_crop_phrase(updates.crop)
        if (
            "expected_harvest_days" in updates.model_fields_set
            and updates.expected_harvest_days is not None
        ):
            payload["expected_harvest_days"] = updates.expected_harvest_days
        if (
            "farm_size_hectares" in updates.model_fields_set
            and updates.farm_size_hectares is not None
        ):
            payload["farm_size_hectares"] = round(updates.farm_size_hectares, 2)
        if (
            "labor_flexibility_pct" in updates.model_fields_set
            and updates.labor_flexibility_pct is not None
        ):
            payload["labor_flexibility_pct"] = max(0, min(100, updates.labor_flexibility_pct))
        if "candidate_crops" in updates.model_fields_set and updates.candidate_crops is not None:
            payload["candidate_crops"] = _merge_candidate_crops(state, updates.candidate_crops)

        return IntakeFieldUpdate(**payload)

    def _fallback_result(
        self,
        asked_field: IntakeFieldName,
        state: IntakeState,
        farmer_answer: str,
        *,
        warning: str,
    ) -> FieldExtractionResult:
        return FieldExtractionResult(
            asked_field=asked_field,
            updates=self._safe_fallback_extract(asked_field, state, farmer_answer),
            source="fallback",
            warnings=[warning],
        )

    def _merge_with_fallback(
        self,
        *,
        asked_field: IntakeFieldName,
        state: IntakeState,
        farmer_answer: str,
        updates: IntakeFieldUpdate,
    ) -> IntakeFieldUpdate:
        fallback_updates = self._safe_fallback_extract(asked_field, state, farmer_answer)
        payload = fallback_updates.model_dump(exclude_none=True)
        payload.update(updates.model_dump(exclude_none=True))
        try:
            return IntakeFieldUpdate(**payload)
        except ValidationError as exc:
            raise FieldExtractorError(
                f"GLM extracted an invalid value for '{asked_field}': {exc.errors()[0]['msg']}"
            ) from exc

    def _safe_fallback_extract(
        self,
        asked_field: IntakeFieldName,
        state: IntakeState,
        farmer_answer: str,
    ) -> IntakeFieldUpdate:
        try:
            return _fallback_extract(asked_field, state, farmer_answer)
        except ValidationError as exc:
            logger.warning(
                "Fallback intake extraction produced invalid data for field '%s': %s",
                asked_field,
                exc.errors()[0]["msg"],
            )
            return IntakeFieldUpdate()


def _normalize_field_name(asked_field: IntakeFieldName | str) -> IntakeFieldName:
    key = str(asked_field).strip().lower()
    if key in _FIELD_ALIASES:
        return _FIELD_ALIASES[key]

    normalized = re.sub(r"[\s\-]+", "_", key)
    alias = _FIELD_ALIASES.get(normalized) or _FIELD_ALIASES.get(normalized.replace("_", " "))
    if alias is None:
        raise ValueError(f"Unsupported intake field: {asked_field}")
    return alias


def _coerce_state(intake_state: IntakeState | Mapping[str, Any] | None) -> IntakeState:
    if isinstance(intake_state, IntakeState):
        return intake_state
    if intake_state is None:
        return IntakeState()

    raw_state = dict(intake_state)
    normalized_state: dict[str, Any] = {}
    for key, value in raw_state.items():
        if value is None and key == "candidate_crops":
            continue
        if key in {"filled_fields", "missing_fields", "is_complete"}:
            normalized_state[key] = value
            continue
        if key == "current_crop":
            normalized_state["crop"] = value
            continue
        normalized_key = _FIELD_ALIASES.get(str(key).strip().lower()) or _FIELD_ALIASES.get(
            re.sub(r"[\s\-]+", "_", str(key).strip().lower())
        )
        if normalized_key is None:
            continue
        normalized_state[normalized_key] = value

    return IntakeState.model_validate(normalized_state)


def _fallback_extract(
    asked_field: IntakeFieldName,
    state: IntakeState,
    farmer_answer: str,
) -> IntakeFieldUpdate:
    text = _clean_text(farmer_answer)
    payload: dict[str, Any] = {}

    if not text:
        return IntakeFieldUpdate()

    if asked_field == "location" or _looks_like_location_answer(text):
        location = _extract_location(text)
        if location:
            payload["location"] = location

    if asked_field == "crop" or _mentions_crop(text):
        crop = _extract_crop(text)
        if crop:
            payload["crop"] = crop

    harvest_days = _extract_harvest_days(text, assume_numeric=asked_field == "expected_harvest_days")
    if harvest_days is not None:
        payload["expected_harvest_days"] = harvest_days

    farm_size = _extract_farm_size_hectares(text)
    if farm_size is not None:
        payload["farm_size_hectares"] = round(farm_size, 2)

    labor_pct = _extract_labor_flexibility_pct(text)
    if labor_pct is not None:
        payload["labor_flexibility_pct"] = labor_pct

    if asked_field == "candidate_crops" or _mentions_candidate_crops(text):
        candidate_crops = _extract_candidate_crops(text)
        if candidate_crops:
            payload["candidate_crops"] = _merge_candidate_crops(state, candidate_crops)

    return IntakeFieldUpdate(**payload)


def _extract_completion_content(body: Any) -> str | None:
    if not isinstance(body, Mapping):
        return None

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None

    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        return None

    message = first_choice.get("message")
    if not isinstance(message, Mapping):
        return None

    content = message.get("content")
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
                continue
            if not isinstance(part, Mapping):
                continue
            if isinstance(part.get("text"), str):
                text_parts.append(part["text"])
                continue
            if isinstance(part.get("content"), str):
                text_parts.append(part["content"])
                continue
            if isinstance(part.get("value"), str):
                text_parts.append(part["value"])
        combined = "".join(text_parts).strip()
        return combined or None

    return None


def _decode_extraction_payload(content: str) -> dict[str, Any] | None:
    cleaned = _strip_code_fences(content).strip()
    if not cleaned:
        return None

    candidates = [cleaned]
    extracted = _extract_first_json_object(cleaned)
    if extracted and extracted != cleaned:
        candidates.append(extracted)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue

        if not isinstance(parsed, Mapping):
            continue

        if "updates" in parsed:
            return dict(parsed)

        direct_fields = {
            key: value
            for key, value in parsed.items()
            if key in IntakeFieldUpdate.model_fields
        }
        if direct_fields:
            return {"updates": direct_fields}

    return None


def _strip_code_fences(value: str) -> str:
    stripped = value.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _extract_first_json_object(value: str) -> str | None:
    start = value.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for index in range(start, len(value)):
        char = value[index]

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return value[start : index + 1]

    return None


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip(" \t\r\n,.;:")


def _looks_like_location_answer(text: str) -> bool:
    lowered = text.lower()
    return lowered.startswith(_LOCATION_PREFIXES) or any(
        token in lowered
        for token in (
            " located ",
            " based ",
            " district",
            " county",
            " province",
            " region",
            " village",
            " state",
        )
    )


def _mentions_crop(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in ("grow", "growing", "crop", "planted", "planting", "harvesting")
    )


def _mentions_candidate_crops(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in ("switch to", "candidate", "options", "considering", "alternatives")
    )


def _extract_location(text: str) -> str | None:
    lowered = text.lower()
    for prefix in _LOCATION_PREFIXES:
        if lowered.startswith(prefix):
            candidate = _clean_text(text[len(prefix) :])
            return candidate if candidate and is_malaysia_relevant_location(candidate) else None

    match = re.search(
        r"\b(?:in|at|near|around)\s+([A-Za-z][A-Za-z .,'-]{1,80})$",
        text,
        re.IGNORECASE,
    )
    if match:
        candidate = _clean_text(match.group(1))
        return candidate if candidate and is_malaysia_relevant_location(candidate) else None

    if len(text.split()) <= 6 and is_malaysia_relevant_location(text):
        return text
    return None


def _extract_crop(text: str) -> str | None:
    lowered = text.lower()
    for prefix in _CROP_PREFIXES:
        if lowered.startswith(prefix):
            return _clean_crop_phrase(text[len(prefix) :])

    match = re.search(
        r"\b(?:grow|growing|planted|planting|harvesting)\s+([A-Za-z][A-Za-z /,&-]{1,60})",
        text,
        re.IGNORECASE,
    )
    if match:
        return _clean_crop_phrase(match.group(1))

    if len(text.split()) <= 5:
        return _clean_crop_phrase(text)
    return None


def _clean_crop_phrase(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    cleaned = re.sub(
        r"\b(this season|right now|at the moment|currently|for now)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = _clean_text(re.split(r"\b(?:but|because|since)\b", cleaned, maxsplit=1)[0])
    return cleaned or None


def _extract_harvest_days(text: str, *, assume_numeric: bool = False) -> int | None:
    match = re.search(
        r"\b(?:in|about|around|within|after)?\s*(\d+(?:\.\d+)?)\s*(day|days|week|weeks|month|months)\b",
        text,
        re.IGNORECASE,
    )
    if match:
        amount = float(match.group(1))
        unit = match.group(2).lower()
        if unit.startswith("day"):
            return max(1, round(amount))
        if unit.startswith("week"):
            return max(1, round(amount * 7))
        return max(1, round(amount * 30))

    if assume_numeric and re.fullmatch(r"\d+(?:\.\d+)?", text):
        return max(1, round(float(text)))

    if _MONTH_PATTERN.search(text):
        return None
    return None


def _extract_farm_size_hectares(text: str) -> float | None:
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(ha|hectare|hectares|acre|acres)\b",
        text,
        re.IGNORECASE,
    )
    if match:
        amount = float(match.group(1))
        unit = match.group(2).lower()
        if unit.startswith("ha") or unit.startswith("hectare"):
            return amount
        return amount * 0.404686

    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    return None


def _extract_labor_flexibility_pct(text: str) -> int | None:
    match = re.search(r"\b(\d{1,3})\s*(?:%|percent)\b", text, re.IGNORECASE)
    if match:
        return max(0, min(100, int(match.group(1))))

    fraction_match = re.search(
        r"\b(one[\s-]?quarter|a quarter|quarter|one[\s-]?third|a third|third|two[\s-]?thirds|three[\s-]?quarters)\b",
        text,
        re.IGNORECASE,
    )
    if fraction_match:
        normalized = fraction_match.group(1).lower().replace("-", " ")
        fraction_map = {
            "one quarter": 25,
            "a quarter": 25,
            "quarter": 25,
            "one third": 33,
            "a third": 33,
            "third": 33,
            "two thirds": 67,
            "three quarters": 75,
        }
        return fraction_map.get(normalized)

    lowered = text.lower()
    for phrase, pct in (
        ("all labor", 100),
        ("all workers", 100),
        ("all of them", 100),
        ("entire team", 100),
        ("everyone", 100),
        ("most of", 75),
        ("most workers", 75),
        ("most labor", 75),
        ("half", 50),
        ("about half", 50),
        ("around half", 50),
        ("roughly half", 50),
        ("some of the workers", 30),
        ("some workers", 30),
        ("some labor", 30),
        ("some", 30),
        ("a little", 10),
    ):
        if phrase in lowered:
            return pct

    if any(
        token in lowered
        for token in (
            "not flexible",
            "limited",
            "tight",
            "hardly",
            "low",
            "can't move much",
            "cannot move much",
            "very little",
        )
    ):
        return 20
    if any(
        token in lowered
        for token in (
            "somewhat",
            "moderate",
            "medium",
            "fairly flexible",
            "can move a few",
            "can shift a few",
        )
    ):
        return 50
    if any(
        token in lowered
        for token in (
            "very flexible",
            "high",
            "easy to shift",
            "plenty",
            "can move most",
            "can shift most",
        )
    ):
        return 75
    return None


def _extract_candidate_crops(text: str) -> list[str]:
    lowered = text.lower()
    for prefix in _LIST_PREFIXES:
        if lowered.startswith(prefix):
            text = text[len(prefix) :]
            break

    text = re.sub(
        r"\b(?:instead of|rather than|switch to|move to|go with)\b",
        ",",
        text,
        flags=re.IGNORECASE,
    )
    parts = re.split(r",|/|\bor\b|\band\b", text, flags=re.IGNORECASE)

    results: list[str] = []
    seen: set[str] = set()
    for part in parts:
        crop = _clean_crop_phrase(part)
        if not crop:
            continue
        key = crop.casefold()
        if key in seen:
            continue
        seen.add(key)
        results.append(crop)
    return results


def _merge_candidate_crops(state: IntakeState, new_candidates: list[str]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    current_crop = state.crop.casefold() if state.crop else None

    for candidate in [*state.candidate_crops, *new_candidates]:
        cleaned = _clean_crop_phrase(candidate)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key == current_crop or key in seen:
            continue
        seen.add(key)
        results.append(cleaned)
    return results


default_field_extractor = GLMFieldExtractor()


async def extract_field_updates(
    asked_field: IntakeFieldName | str,
    intake_state: IntakeState | Mapping[str, Any] | None,
    farmer_answer: str,
) -> IntakeFieldUpdate:
    return await default_field_extractor.extract(asked_field, intake_state, farmer_answer)


async def extract_field_updates_result(
    asked_field: IntakeFieldName | str,
    intake_state: IntakeState | Mapping[str, Any] | None,
    farmer_answer: str,
) -> FieldExtractionResult:
    return await default_field_extractor.extract_result(
        asked_field,
        intake_state,
        farmer_answer,
    )


def extract_field_updates_sync(
    asked_field: IntakeFieldName | str,
    intake_state: IntakeState | Mapping[str, Any] | None,
    farmer_answer: str,
) -> IntakeFieldUpdate:
    return default_field_extractor.extract_sync(asked_field, intake_state, farmer_answer)


def extract_field_updates_result_sync(
    asked_field: IntakeFieldName | str,
    intake_state: IntakeState | Mapping[str, Any] | None,
    farmer_answer: str,
) -> FieldExtractionResult:
    return default_field_extractor.extract_result_sync(
        asked_field,
        intake_state,
        farmer_answer,
    )
