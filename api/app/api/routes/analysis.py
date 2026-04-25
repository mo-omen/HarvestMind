import json
from datetime import UTC, datetime
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

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


@router.post("/decision")
async def analyze_decision(
    payload: DecisionAnalysisRequest,
) -> StreamingResponse:
    if not payload.farmer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="farmer_id is required for persisted decision analysis.",
        )

    async def event_generator() -> AsyncGenerator[str, None]:
        async def send_status(msg: str):
            yield f"data: {json.dumps({'status': msg})}\n\n"

        try:
            # Create a wrapped status callback
            async def status_callback(msg: str):
                nonlocal current_status
                current_status = msg

            current_status = "Initializing analysis..."

            # Start the orchestrator run in a task
            run_task = asyncio.create_task(orchestrator.run(payload, status_callback))

            last_sent_status = None
            while not run_task.done():
                if current_status != last_sent_status:
                    yield f"data: {json.dumps({'status': current_status})}\n\n"
                    last_sent_status = current_status
                await asyncio.sleep(0.5)

            response = await run_task

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

            final_result = PersistedDecisionResponse(
                farmer_id=payload.farmer_id,
                **response.model_dump(),
            )
            yield f"data: {json.dumps({'result': final_result.model_dump(mode='json')})}\n\n"

        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/compare", response_model=list[ScenarioComparison])
async def compare_crop_options(payload: DecisionAnalysisRequest) -> list[ScenarioComparison]:
    if not payload.candidate_crops:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="candidate_crops is required for scenario comparison.",
        )
    return await orchestrator.compare(payload)

import asyncio # Needed for create_task and sleep
