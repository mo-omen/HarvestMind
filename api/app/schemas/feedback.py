from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


OutcomeLabel = Literal["helpful", "not_helpful", "too_risky", "too_conservative", "outcome_recorded"]


class RecommendationFeedbackRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    farmer_id: str
    recommendation_id: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    outcome_label: OutcomeLabel
    notes: str | None = None
    actual_decision: str | None = None
    actual_revenue_change_pct: float | None = None


class RecommendationFeedbackRecord(BaseModel):
    feedback_id: str
    farmer_id: str
    recommendation_id: str | None = None
    rating: int | None = None
    outcome_label: OutcomeLabel
    notes: str | None = None
    actual_decision: str | None = None
    actual_revenue_change_pct: float | None = None
    created_at: datetime


class RecommendationFeedbackResponse(BaseModel):
    item: RecommendationFeedbackRecord


class RecommendationFeedbackHistoryResponse(BaseModel):
    farmer_id: str
    items: list[RecommendationFeedbackRecord]
