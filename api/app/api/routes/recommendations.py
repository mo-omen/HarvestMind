from fastapi import APIRouter, HTTPException, status

from app.db.runtime import ensure_schema_ready
from app.db.postgres import PostgresDependencyMissingError
from app.repositories.recommendations import RecommendationRepository
from app.schemas.recommendation import RecommendationHistoryItem, RecommendationHistoryResponse


router = APIRouter(prefix="/recommendations", tags=["recommendations"])


def _get_recommendation_repository() -> RecommendationRepository:
    database = ensure_schema_ready()
    return RecommendationRepository(database)


@router.get("/{farmer_id}", response_model=RecommendationHistoryResponse)
async def get_recommendation_history(
    farmer_id: str,
    limit: int = 50,
) -> RecommendationHistoryResponse:
    repository = _get_recommendation_repository()
    try:
        records = repository.fetch_history(farmer_id, limit=limit)
    except PostgresDependencyMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch recommendation history: {exc}",
        ) from exc

    return RecommendationHistoryResponse(
        farmer_id=farmer_id,
        items=[
            RecommendationHistoryItem(
                recommendation_id=record.recommendation_id,
                farmer_id=record.farmer_id,
                recorded_at=record.recorded_at,
                decision=record.decision,
                confidence=record.confidence,
                input_payload=record.input_payload,
                evidence_packet=record.evidence_packet,
                created_at=record.created_at,
            )
            for record in records
        ],
    )
