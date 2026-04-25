from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.db.postgres import PostgresDatabase, to_jsonb


@dataclass(frozen=True, slots=True)
class IntakeSessionCreate:
    session_id: str
    farmer_id: str | None
    state: dict[str, Any]
    analysis_request: dict[str, Any] | None
    transcript: list[dict[str, Any]]
    status: str


@dataclass(frozen=True, slots=True)
class IntakeSessionRecord:
    session_id: str
    farmer_id: str | None
    state: dict[str, Any]
    analysis_request: dict[str, Any] | None
    transcript: list[dict[str, Any]]
    status: str
    created_at: datetime
    updated_at: datetime


_UPSERT_SESSION_SQL = """
INSERT INTO intake_sessions (
    session_id,
    farmer_id,
    state,
    analysis_request,
    transcript,
    status
)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (session_id) DO UPDATE
SET
    farmer_id = EXCLUDED.farmer_id,
    state = EXCLUDED.state,
    analysis_request = EXCLUDED.analysis_request,
    transcript = EXCLUDED.transcript,
    status = EXCLUDED.status,
    updated_at = NOW()
RETURNING
    session_id,
    farmer_id,
    state,
    analysis_request,
    transcript,
    status,
    created_at,
    updated_at
"""

_FETCH_SESSION_SQL = """
SELECT
    session_id,
    farmer_id,
    state,
    analysis_request,
    transcript,
    status,
    created_at,
    updated_at
FROM intake_sessions
WHERE session_id = %s
"""


class IntakeSessionRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def save(self, session: IntakeSessionCreate) -> IntakeSessionRecord:
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    _UPSERT_SESSION_SQL,
                    (
                        session.session_id,
                        session.farmer_id,
                        to_jsonb(session.state),
                        to_jsonb(session.analysis_request) if session.analysis_request is not None else None,
                        to_jsonb(session.transcript),
                        session.status,
                    ),
                )
                row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Intake session upsert did not return a row.")
        return _record_from_row(row)

    def get(self, session_id: str) -> IntakeSessionRecord | None:
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(_FETCH_SESSION_SQL, (session_id,))
                row = cursor.fetchone()
        if row is None:
            return None
        return _record_from_row(row)


def _record_from_row(row: dict[str, Any]) -> IntakeSessionRecord:
    return IntakeSessionRecord(
        session_id=str(row["session_id"]),
        farmer_id=str(row["farmer_id"]) if row["farmer_id"] is not None else None,
        state=dict(row["state"]),
        analysis_request=dict(row["analysis_request"]) if row["analysis_request"] is not None else None,
        transcript=list(row["transcript"]),
        status=str(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
