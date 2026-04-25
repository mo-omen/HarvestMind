from datetime import datetime

from pydantic import BaseModel

from app.schemas.analysis import DecisionAnalysisResponse, DecisionType


class RecommendationHistoryItem(BaseModel):
    recommendation_id: str
    farmer_id: str
    recorded_at: datetime
    decision: DecisionType
    confidence: float
    input_payload: dict
    evidence_packet: dict
    created_at: datetime


class RecommendationHistoryResponse(BaseModel):
    farmer_id: str
    items: list[RecommendationHistoryItem]


class PersistedDecisionResponse(DecisionAnalysisResponse):
    farmer_id: str
