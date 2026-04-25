from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


SignalType = Literal["price", "weather", "news"]


class SignalSnapshotItem(BaseModel):
    snapshot_id: str
    signal_type: SignalType
    farmer_id: str | None = None
    crop: str | None = None
    location: str | None = None
    source: str
    normalized_payload: dict[str, Any]
    raw_payload: dict[str, Any] | None = None
    created_at: datetime


class SignalHistoryResponse(BaseModel):
    farmer_id: str
    items: list[SignalSnapshotItem]


class LatestSignalsResponse(BaseModel):
    farmer_id: str
    price: SignalSnapshotItem | None = None
    weather: SignalSnapshotItem | None = None
    news: SignalSnapshotItem | None = None
