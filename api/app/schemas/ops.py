from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


SyncSource = Literal["market", "weather", "news"]
SyncStatus = Literal["queued", "running", "completed", "failed"]


class ReadinessCheck(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, str]


class SyncJobRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source: SyncSource
    farmer_id: str | None = None
    location: str | None = None
    crop: str | None = None


class SyncJobResponse(BaseModel):
    job_id: str
    source: SyncSource
    status: SyncStatus
    farmer_id: str | None = None
    location: str | None = None
    crop: str | None = None
    summary: str | None = None
    result_payload: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class SyncJobListResponse(BaseModel):
    items: list[SyncJobResponse]
