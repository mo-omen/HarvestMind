from fastapi import APIRouter, HTTPException, status

from app.db.runtime import ensure_schema_ready
from app.repositories.feedback import RecommendationFeedbackCreate, RecommendationFeedbackRepository
from app.schemas.feedback import (
    RecommendationFeedbackHistoryResponse,
    RecommendationFeedbackRecord,
    RecommendationFeedbackRequest,
    RecommendationFeedbackResponse,
)


router = APIRouter(prefix="/feedback", tags=["feedback"])


def _get_feedback_repository() -> RecommendationFeedbackRepository:
    database = ensure_schema_ready()
    return RecommendationFeedbackRepository(database)


@router.post("", response_model=RecommendationFeedbackResponse)
async def create_feedback(
    payload: RecommendationFeedbackRequest,
) -> RecommendationFeedbackResponse:
    repository = _get_feedback_repository()
    try:
        record = repository.create(
            RecommendationFeedbackCreate(
                farmer_id=payload.farmer_id,
                recommendation_id=payload.recommendation_id,
                rating=payload.rating,
                outcome_label=payload.outcome_label,
                notes=payload.notes,
                actual_decision=payload.actual_decision,
                actual_revenue_change_pct=payload.actual_revenue_change_pct,
            )
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist feedback: {exc}",
        ) from exc

    return RecommendationFeedbackResponse(item=RecommendationFeedbackRecord.model_validate(record.__dict__))


@router.get("/{farmer_id}", response_model=RecommendationFeedbackHistoryResponse)
async def get_feedback_history(farmer_id: str, limit: int = 50) -> RecommendationFeedbackHistoryResponse:
    repository = _get_feedback_repository()
    try:
        records = repository.fetch_history(farmer_id, limit=limit)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch feedback history: {exc}",
        ) from exc

    return RecommendationFeedbackHistoryResponse(
        farmer_id=farmer_id,
        items=[RecommendationFeedbackRecord.model_validate(record.__dict__) for record in records],
    )
