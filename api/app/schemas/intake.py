from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.malaysia import normalize_malaysia_location
from app.schemas.analysis import DecisionAnalysisRequest


IntakeFieldName = Literal[
    "location",
    "crop",
    "expected_harvest_days",
    "farm_size_hectares",
    "labor_flexibility_pct",
    "candidate_crops",
]
IntakeStatus = Literal["needs_input", "complete"]

REQUIRED_INTAKE_FIELDS: tuple[IntakeFieldName, ...] = (
    "location",
    "crop",
    "expected_harvest_days",
    "farm_size_hectares",
    "labor_flexibility_pct",
    "candidate_crops",
)


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned:
        raise ValueError("value must not be empty")
    return cleaned


def _normalize_candidate_crops(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None

    normalized: list[str] = []
    seen: set[str] = set()

    for crop in value:
        cleaned = crop.strip()
        if not cleaned or cleaned in seen:
            continue
        normalized.append(cleaned)
        seen.add(cleaned)

    return normalized


class IntakeFieldUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    location: str | None = None
    crop: str | None = None
    expected_harvest_days: int | None = Field(default=None, ge=1, le=365)
    farm_size_hectares: float | None = Field(default=None, gt=0)
    labor_flexibility_pct: int | None = Field(default=None, ge=0, le=100)
    candidate_crops: list[str] | None = None

    @field_validator("location", "crop")
    @classmethod
    def validate_text_fields(cls, value: str | None) -> str | None:
        return _normalize_text(value)

    @field_validator("location")
    @classmethod
    def validate_location(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_malaysia_location(value)

    @field_validator("candidate_crops")
    @classmethod
    def validate_candidate_crops(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_candidate_crops(value)


class IntakeState(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    location: str | None = None
    crop: str | None = None
    expected_harvest_days: int | None = Field(default=None, ge=1, le=365)
    farm_size_hectares: float | None = Field(default=None, gt=0)
    labor_flexibility_pct: int | None = Field(default=None, ge=0, le=100)
    candidate_crops: list[str] = Field(default_factory=list)
    filled_fields: list[IntakeFieldName] = Field(default_factory=list)
    missing_fields: list[IntakeFieldName] = Field(default_factory=list)
    is_complete: bool = False

    @field_validator("location", "crop")
    @classmethod
    def validate_text_fields(cls, value: str | None) -> str | None:
        return _normalize_text(value)

    @field_validator("location")
    @classmethod
    def validate_location(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_malaysia_location(value)

    @field_validator("candidate_crops")
    @classmethod
    def validate_candidate_crops(cls, value: list[str]) -> list[str]:
        return _normalize_candidate_crops(value) or []


class IntakeQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    field_name: IntakeFieldName
    prompt: str


class IntakeTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str | None = Field(
        default=None,
        validation_alias=AliasChoices("message", "user_message"),
    )
    state: IntakeState | None = None
    extracted_fields: IntakeFieldUpdate = Field(default_factory=IntakeFieldUpdate)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()
        return cleaned or None


class IntakeTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: IntakeStatus
    state: IntakeState
    next_question: IntakeQuestion | None = None
    analysis_request: DecisionAnalysisRequest | None = None

    @model_validator(mode="after")
    def validate_response_shape(self) -> "IntakeTurnResponse":
        if self.status == "complete":
            if self.next_question is not None:
                raise ValueError("complete responses cannot include a next_question")
            if self.analysis_request is None:
                raise ValueError("complete responses must include analysis_request")
            return self

        if self.next_question is None:
            raise ValueError("needs_input responses must include next_question")
        if self.analysis_request is not None:
            raise ValueError("needs_input responses cannot include analysis_request")
        return self
