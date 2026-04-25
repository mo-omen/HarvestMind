from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.intake import IntakeFieldUpdate


class AdvisorChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: Literal["assistant", "farmer", "system"]
    text: str

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("message text must not be empty")
        return cleaned


class AdvisorMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    farmer_id: str
    message: str
    history: list[AdvisorChatMessage] = Field(default_factory=list, max_length=12)

    @field_validator("farmer_id", "message")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned


class SignalFreshness(BaseModel):
    signal_type: Literal["price", "weather", "news"]
    last_updated_at: datetime | None = None
    age_hours: float | None = None
    is_stale: bool = True
    source: str | None = None


class AdvisorGroundedContext(BaseModel):
    farmer_id: str
    location: str
    crop: str | None = None
    candidate_crops: list[str] = Field(default_factory=list)
    latest_decision: str | None = None
    latest_confidence: float | None = None
    evidence_summary: list[str] = Field(default_factory=list)


class AdvisorMessageResponse(BaseModel):
    answer: str
    grounded_context: AdvisorGroundedContext
    suggested_config_updates: IntakeFieldUpdate | None = None
    needs_rerun: bool = False
    data_freshness: list[SignalFreshness]
