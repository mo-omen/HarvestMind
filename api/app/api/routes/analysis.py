from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status

from app.clients.glm import GLMClientError
from app.db.runtime import ensure_schema_ready
from app.repositories.recommendations import RecommendationRepository, RecommendationRunCreate
from app.repositories.signals import SignalSnapshotCreate, SignalSnapshotRepository
from app.db.postgres import PostgresDependencyMissingError
from app.schemas.analysis import DecisionAnalysisRequest, ScenarioComparison
from app.schemas.recommendation import PersistedDecisionResponse
from app.services.orchestrator import DecisionOrchestrator


router = APIRouter(prefix="/analysis", tags=["analysis"])
orchestrator = DecisionOrchestrator()


def _get_recommendation_repository() -> RecommendationRepository:
    database = ensure_schema_ready()
    return RecommendationRepository(database)


def _get_signal_repository() -> SignalSnapshotRepository:
    database = ensure_schema_ready()
    return SignalSnapshotRepository(database)


@router.post("/decision", response_model=PersistedDecisionResponse)
async def analyze_decision(
    payload: DecisionAnalysisRequest,
) -> PersistedDecisionResponse:
    if not payload.farmer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="farmer_id is required for persisted decision analysis.",
        )

    try:
        response = await orchestrator.run(payload)
        repository = _get_recommendation_repository()
        signal_repository = _get_signal_repository()
        recorded_at = datetime.now(UTC)
        signal_repository.create(
            SignalSnapshotCreate(
                farmer_id=payload.farmer_id,
                signal_type="price",
                crop=payload.crop,
                location=payload.location,
                source=response.evidence.price_snapshot.source,
                normalized_payload=response.evidence.price_snapshot.model_dump(mode="json"),
                raw_payload=None,
            )
        )
        if response.evidence.weather_snapshot is not None:
            signal_repository.create(
                SignalSnapshotCreate(
                    farmer_id=payload.farmer_id,
                    signal_type="weather",
                    crop=payload.crop,
                    location=payload.location,
                    source=response.evidence.weather_snapshot.source,
                    normalized_payload=response.evidence.weather_snapshot.model_dump(mode="json"),
                    raw_payload=None,
                )
            )
        signal_repository.create(
            SignalSnapshotCreate(
                farmer_id=payload.farmer_id,
                signal_type="news",
                crop=payload.crop,
                location=payload.location,
                source="gdelt_doc_api",
                normalized_payload={
                    "summary": response.evidence.news_signal,
                    "seasonal_weather_context": response.evidence.seasonal_weather_context,
                    "items": [
                        item.model_dump(mode="json")
                        for item in response.evidence.news_signals
                    ],
                },
                raw_payload=None,
            )
        )
        repository.create(
            RecommendationRunCreate(
                farmer_id=payload.farmer_id,
                recorded_at=recorded_at,
                input_payload=payload.model_dump(mode="json"),
                evidence_packet=response.evidence.model_dump(mode="json"),
                decision=response.decision,
                confidence=response.confidence,
            )
        )
    except GLMClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"GLM decision analysis is unavailable: {exc}",
        ) from exc
    except PostgresDependencyMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist recommendation run: {exc}",
        ) from exc

    return PersistedDecisionResponse(
        farmer_id=payload.farmer_id,
        **response.model_dump(),
    )


@router.post("/compare", response_model=list[ScenarioComparison])
async def compare_crop_options(payload: DecisionAnalysisRequest) -> list[ScenarioComparison]:
    if not payload.candidate_crops:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="candidate_crops is required for scenario comparison.",
        )
    return await orchestrator.compare(payload)
