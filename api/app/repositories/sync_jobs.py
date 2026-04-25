from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.db.postgres import PostgresDatabase, to_jsonb


@dataclass(frozen=True, slots=True)
class SyncJobCreate:
    source: str
    status: str
    farmer_id: str | None = None
    crop: str | None = None
    location: str | None = None
    summary: str | None = None
    result_payload: dict[str, Any] | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SyncJobRecord:
    job_id: str
    source: str
    status: str
    farmer_id: str | None
    crop: str | None
    location: str | None
    summary: str | None
    result_payload: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


_CREATE_JOB_SQL = """
INSERT INTO sync_jobs (
    source,
    status,
    farmer_id,
    crop,
    location,
    summary,
    result_payload,
    error
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
RETURNING
    job_id::text AS job_id,
    source,
    status,
    farmer_id,
    crop,
    location,
    summary,
    result_payload,
    error,
    created_at,
    updated_at
"""

_UPDATE_JOB_SQL = """
UPDATE sync_jobs
SET
    status = %s,
    summary = %s,
    result_payload = %s,
    error = %s,
    updated_at = NOW()
WHERE job_id = %s
RETURNING
    job_id::text AS job_id,
    source,
    status,
    farmer_id,
    crop,
    location,
    summary,
    result_payload,
    error,
    created_at,
    updated_at
"""

_LIST_JOBS_SQL = """
SELECT
    job_id::text AS job_id,
    source,
    status,
    farmer_id,
    crop,
    location,
    summary,
    result_payload,
    error,
    created_at,
    updated_at
FROM sync_jobs
ORDER BY created_at DESC
LIMIT %s
"""


class SyncJobRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def create(self, payload: SyncJobCreate) -> SyncJobRecord:
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    _CREATE_JOB_SQL,
                    (
                        payload.source,
                        payload.status,
                        payload.farmer_id,
                        payload.crop,
                        payload.location,
                        payload.summary,
                        to_jsonb(payload.result_payload) if payload.result_payload is not None else None,
                        payload.error,
                    ),
                )
                row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Sync job insert did not return a row.")
        return _record_from_row(row)

    def update(
        self,
        job_id: str,
        *,
        status: str,
        summary: str | None,
        result_payload: dict[str, Any] | None,
        error: str | None,
    ) -> SyncJobRecord:
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    _UPDATE_JOB_SQL,
                    (
                        status,
                        summary,
                        to_jsonb(result_payload) if result_payload is not None else None,
                        error,
                        job_id,
                    ),
                )
                row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Sync job update did not return a row.")
        return _record_from_row(row)

    def list(self, *, limit: int = 20) -> list[SyncJobRecord]:
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(_LIST_JOBS_SQL, (limit,))
                rows = cursor.fetchall()
        return [_record_from_row(row) for row in rows]


def _record_from_row(row: dict[str, Any]) -> SyncJobRecord:
    return SyncJobRecord(
        job_id=str(row["job_id"]),
        source=str(row["source"]),
        status=str(row["status"]),
        farmer_id=str(row["farmer_id"]) if row["farmer_id"] is not None else None,
        crop=str(row["crop"]) if row["crop"] is not None else None,
        location=str(row["location"]) if row["location"] is not None else None,
        summary=str(row["summary"]) if row["summary"] is not None else None,
        result_payload=dict(row["result_payload"]) if row["result_payload"] is not None else None,
        error=str(row["error"]) if row["error"] is not None else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
