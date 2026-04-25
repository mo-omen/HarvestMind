from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.analysis import DecisionAnalysisRequest
from app.schemas.intake import IntakeState, IntakeTurnResponse


class IntakeTranscriptEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    role: str
    text: str
    created_at: datetime


class IntakeSessionCreateRequest(BaseModel):
    farmer_id: str | None = None


class IntakeSessionResponse(BaseModel):
    session_id: str
    farmer_id: str | None = None
    state: IntakeState
    analysis_request: DecisionAnalysisRequest | None = None
    transcript: list[IntakeTranscriptEntry] = Field(default_factory=list)
    status: str
    created_at: datetime
    updated_at: datetime


class IntakeSessionMessageRequest(BaseModel):
    message: str


class IntakeSessionTurnResponse(BaseModel):
    session: IntakeSessionResponse
    turn: IntakeTurnResponse
