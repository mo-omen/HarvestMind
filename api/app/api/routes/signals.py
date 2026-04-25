from fastapi import APIRouter, HTTPException, status

from app.db.runtime import ensure_schema_ready
from app.repositories.signals import SignalSnapshotRepository
from app.schemas.signal import LatestSignalsResponse, SignalHistoryResponse, SignalSnapshotItem


router = APIRouter(prefix="/signals", tags=["signals"])


def _get_signal_repository() -> SignalSnapshotRepository:
    database = ensure_schema_ready()
    return SignalSnapshotRepository(database)


@router.get("/{farmer_id}/latest", response_model=LatestSignalsResponse)
async def get_latest_signals(farmer_id: str) -> LatestSignalsResponse:
    repository = _get_signal_repository()
    latest = {
        signal_type: repository.fetch_latest(farmer_id, signal_type)
        for signal_type in ("price", "weather", "news")
    }
    if not any(latest.values()):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No signal snapshots found for farmer '{farmer_id}'.",
        )
    return LatestSignalsResponse(
        farmer_id=farmer_id,
        price=_to_signal_item(latest["price"]),
        weather=_to_signal_item(latest["weather"]),
        news=_to_signal_item(latest["news"]),
    )


@router.get("/{farmer_id}/history", response_model=SignalHistoryResponse)
async def get_signal_history(farmer_id: str, limit: int = 25) -> SignalHistoryResponse:
    repository = _get_signal_repository()
    records = repository.fetch_history(farmer_id, limit=limit)
    return SignalHistoryResponse(
        farmer_id=farmer_id,
        items=[_to_signal_item(record) for record in records],
    )


import dataclasses

def _to_signal_item(record) -> SignalSnapshotItem | None:
    if record is None:
        return None
    return SignalSnapshotItem.model_validate(dataclasses.asdict(record))
