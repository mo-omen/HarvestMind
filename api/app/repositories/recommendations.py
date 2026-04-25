from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.db.postgres import PostgresDatabase, to_jsonb

JSONScalar = None | bool | int | float | str
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JSONMapping = Mapping[str, JSONValue]

_ALLOWED_DECISIONS = frozenset({"persevere", "pivot_partially", "harvest_early"})

_UPSERT_FARMER_SQL = """
INSERT INTO farmers (farmer_id)
VALUES (%s)
ON CONFLICT (farmer_id) DO NOTHING
"""

_INSERT_RECOMMENDATION_SQL = """
INSERT INTO recommendation_runs (
    farmer_id,
    recorded_at,
    input_payload,
    evidence_packet,
    decision,
    confidence
)
VALUES (%s, %s, %s, %s, %s, %s)
RETURNING
    recommendation_id::text AS recommendation_id,
    farmer_id,
    recorded_at,
    input_payload,
    evidence_packet,
    decision,
    confidence::float8 AS confidence,
    created_at
"""

_FETCH_HISTORY_SQL = """
SELECT
    recommendation_id::text AS recommendation_id,
    farmer_id,
    recorded_at,
    input_payload,
    evidence_packet,
    decision,
    confidence::float8 AS confidence,
    created_at
FROM recommendation_runs
WHERE farmer_id = %s
ORDER BY recorded_at DESC, created_at DESC
LIMIT %s
"""


@dataclass(frozen=True, slots=True)
class RecommendationRunCreate:
    farmer_id: str
    recorded_at: datetime
    input_payload: JSONMapping
    evidence_packet: JSONMapping
    decision: str
    confidence: float


@dataclass(frozen=True, slots=True)
class RecommendationRunRecord:
    recommendation_id: str
    farmer_id: str
    recorded_at: datetime
    input_payload: dict[str, JSONValue]
    evidence_packet: dict[str, JSONValue]
    decision: str
    confidence: float
    created_at: datetime


class RecommendationRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def create(self, recommendation: RecommendationRunCreate) -> RecommendationRunRecord:
        _validate_recommendation(recommendation)
        farmer_id = recommendation.farmer_id.strip()
        recorded_at = _normalize_timestamp(recommendation.recorded_at)

        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(_UPSERT_FARMER_SQL, (farmer_id,))
                cursor.execute(
                    _INSERT_RECOMMENDATION_SQL,
                    (
                        farmer_id,
                        recorded_at,
                        to_jsonb(dict(recommendation.input_payload)),
                        to_jsonb(dict(recommendation.evidence_packet)),
                        recommendation.decision,
                        recommendation.confidence,
                    ),
                )
                row = cursor.fetchone()

        if row is None:
            raise RuntimeError("Recommendation insert did not return a row.")

        return _record_from_row(row)

    def fetch_history(self, farmer_id: str, *, limit: int = 50) -> list[RecommendationRunRecord]:
        normalized_farmer_id = farmer_id.strip()
        if not normalized_farmer_id:
            raise ValueError("farmer_id must not be empty.")
        if limit < 1:
            raise ValueError("limit must be at least 1.")

        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(_FETCH_HISTORY_SQL, (normalized_farmer_id, limit))
                rows = cursor.fetchall()

        return [_record_from_row(row) for row in rows]


def _validate_recommendation(recommendation: RecommendationRunCreate) -> None:
    if not recommendation.farmer_id.strip():
        raise ValueError("farmer_id must not be empty.")
    if recommendation.decision not in _ALLOWED_DECISIONS:
        raise ValueError(
            "decision must be one of: persevere, pivot_partially, harvest_early."
        )
    if not 0 <= recommendation.confidence <= 1:
        raise ValueError("confidence must be between 0 and 1.")


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _record_from_row(row: Mapping[str, Any]) -> RecommendationRunRecord:
    return RecommendationRunRecord(
        recommendation_id=str(row["recommendation_id"]),
        farmer_id=str(row["farmer_id"]),
        recorded_at=row["recorded_at"],
        input_payload=dict(row["input_payload"]),
        evidence_packet=dict(row["evidence_packet"]),
        decision=str(row["decision"]),
        confidence=float(row["confidence"]),
        created_at=row["created_at"],
    )
