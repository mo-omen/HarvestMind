from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.db.postgres import PostgresDatabase, to_jsonb


@dataclass(frozen=True, slots=True)
class SignalSnapshotCreate:
    signal_type: str
    source: str
    normalized_payload: dict[str, Any]
    raw_payload: dict[str, Any] | None
    farmer_id: str | None = None
    crop: str | None = None
    location: str | None = None


@dataclass(frozen=True, slots=True)
class SignalSnapshotRecord:
    snapshot_id: str
    signal_type: str
    source: str
    normalized_payload: dict[str, Any]
    raw_payload: dict[str, Any] | None
    farmer_id: str | None
    crop: str | None
    location: str | None
    created_at: datetime


_INSERT_SIGNAL_SQL = """
INSERT INTO signal_snapshots (
    farmer_id,
    signal_type,
    crop,
    location,
    source,
    normalized_payload,
    raw_payload
)
VALUES (%s, %s, %s, %s, %s, %s, %s)
RETURNING
    snapshot_id::text AS snapshot_id,
    farmer_id,
    signal_type,
    crop,
    location,
    source,
    normalized_payload,
    raw_payload,
    created_at
"""

_FETCH_LATEST_SIGNAL_SQL = """
SELECT
    snapshot_id::text AS snapshot_id,
    farmer_id,
    signal_type,
    crop,
    location,
    source,
    normalized_payload,
    raw_payload,
    created_at
FROM signal_snapshots
WHERE farmer_id = %s
  AND signal_type = %s
ORDER BY created_at DESC
LIMIT 1
"""

_FETCH_SIGNAL_HISTORY_SQL = """
SELECT
    snapshot_id::text AS snapshot_id,
    farmer_id,
    signal_type,
    crop,
    location,
    source,
    normalized_payload,
    raw_payload,
    created_at
FROM signal_snapshots
WHERE farmer_id = %s
ORDER BY created_at DESC
LIMIT %s
"""

_FETCH_LATEST_CONTEXT_SQL = """
SELECT
    snapshot_id::text AS snapshot_id,
    farmer_id,
    signal_type,
    crop,
    location,
    source,
    normalized_payload,
    raw_payload,
    created_at
FROM signal_snapshots
WHERE signal_type = %s
  AND (%s::text IS NULL OR crop = %s)
  AND (%s::text IS NULL OR location = %s)
  AND (%s::text IS NULL OR source = %s)
ORDER BY created_at DESC
LIMIT 1
"""

_FETCH_LATEST_BY_SOURCE_SQL = """
SELECT
    snapshot_id::text AS snapshot_id,
    farmer_id,
    signal_type,
    crop,
    location,
    source,
    normalized_payload,
    raw_payload,
    created_at
FROM signal_snapshots
WHERE source = %s
ORDER BY created_at DESC
LIMIT 1
"""


class SignalSnapshotRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def create(self, payload: SignalSnapshotCreate) -> SignalSnapshotRecord:
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    _INSERT_SIGNAL_SQL,
                    (
                        payload.farmer_id,
                        payload.signal_type,
                        payload.crop,
                        payload.location,
                        payload.source,
                        to_jsonb(payload.normalized_payload),
                        to_jsonb(payload.raw_payload) if payload.raw_payload is not None else None,
                    ),
                )
                row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Signal snapshot insert did not return a row.")
        return _record_from_row(row)

    def fetch_latest(self, farmer_id: str, signal_type: str) -> SignalSnapshotRecord | None:
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(_FETCH_LATEST_SIGNAL_SQL, (farmer_id, signal_type))
                row = cursor.fetchone()
        if row is None:
            return None
        return _record_from_row(row)

    def fetch_history(self, farmer_id: str, *, limit: int = 25) -> list[SignalSnapshotRecord]:
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(_FETCH_SIGNAL_HISTORY_SQL, (farmer_id, limit))
                rows = cursor.fetchall()
        return [_record_from_row(row) for row in rows]

    def fetch_latest_context(
        self,
        *,
        signal_type: str,
        crop: str | None = None,
        location: str | None = None,
        source: str | None = None,
    ) -> SignalSnapshotRecord | None:
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    _FETCH_LATEST_CONTEXT_SQL,
                    (signal_type, crop, crop, location, location, source, source),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return _record_from_row(row)

    def fetch_latest_by_source(self, source: str) -> SignalSnapshotRecord | None:
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(_FETCH_LATEST_BY_SOURCE_SQL, (source,))
                row = cursor.fetchone()
        if row is None:
            return None
        return _record_from_row(row)


def _record_from_row(row: dict[str, Any]) -> SignalSnapshotRecord:
    return SignalSnapshotRecord(
        snapshot_id=str(row["snapshot_id"]),
        signal_type=str(row["signal_type"]),
        source=str(row["source"]),
        normalized_payload=dict(row["normalized_payload"]),
        raw_payload=dict(row["raw_payload"]) if row["raw_payload"] is not None else None,
        farmer_id=str(row["farmer_id"]) if row["farmer_id"] is not None else None,
        crop=str(row["crop"]) if row["crop"] is not None else None,
        location=str(row["location"]) if row["location"] is not None else None,
        created_at=row["created_at"],
    )
