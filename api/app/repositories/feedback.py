from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.db.postgres import PostgresDatabase


@dataclass(frozen=True, slots=True)
class RecommendationFeedbackCreate:
    farmer_id: str
    recommendation_id: str | None
    rating: int | None
    outcome_label: str
    notes: str | None
    actual_decision: str | None
    actual_revenue_change_pct: float | None


@dataclass(frozen=True, slots=True)
class RecommendationFeedbackRecord:
    feedback_id: str
    farmer_id: str
    recommendation_id: str | None
    rating: int | None
    outcome_label: str
    notes: str | None
    actual_decision: str | None
    actual_revenue_change_pct: float | None
    created_at: datetime


_INSERT_FEEDBACK_SQL = """
INSERT INTO recommendation_feedback (
    recommendation_id,
    farmer_id,
    rating,
    outcome_label,
    notes,
    actual_decision,
    actual_revenue_change_pct
)
VALUES (
    %s,
    %s,
    %s,
    %s,
    %s,
    %s,
    %s
)
RETURNING
    feedback_id::text AS feedback_id,
    farmer_id,
    recommendation_id::text AS recommendation_id,
    rating,
    outcome_label,
    notes,
    actual_decision,
    actual_revenue_change_pct,
    created_at
"""

_FETCH_FEEDBACK_SQL = """
SELECT
    feedback_id::text AS feedback_id,
    farmer_id,
    recommendation_id::text AS recommendation_id,
    rating,
    outcome_label,
    notes,
    actual_decision,
    actual_revenue_change_pct,
    created_at
FROM recommendation_feedback
WHERE farmer_id = %s
ORDER BY created_at DESC
LIMIT %s
"""


class RecommendationFeedbackRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def create(self, payload: RecommendationFeedbackCreate) -> RecommendationFeedbackRecord:
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    _INSERT_FEEDBACK_SQL,
                    (
                        payload.recommendation_id,
                        payload.farmer_id,
                        payload.rating,
                        payload.outcome_label,
                        payload.notes,
                        payload.actual_decision,
                        payload.actual_revenue_change_pct,
                    ),
                )
                row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Recommendation feedback insert did not return a row.")
        return _record_from_row(row)

    def fetch_history(self, farmer_id: str, *, limit: int = 50) -> list[RecommendationFeedbackRecord]:
        with self._database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(_FETCH_FEEDBACK_SQL, (farmer_id, limit))
                rows = cursor.fetchall()
        return [_record_from_row(row) for row in rows]


def _record_from_row(row: dict[str, Any]) -> RecommendationFeedbackRecord:
    return RecommendationFeedbackRecord(
        feedback_id=str(row["feedback_id"]),
        farmer_id=str(row["farmer_id"]),
        recommendation_id=str(row["recommendation_id"]) if row["recommendation_id"] is not None else None,
        rating=int(row["rating"]) if row["rating"] is not None else None,
        outcome_label=str(row["outcome_label"]),
        notes=str(row["notes"]) if row["notes"] is not None else None,
        actual_decision=str(row["actual_decision"]) if row["actual_decision"] is not None else None,
        actual_revenue_change_pct=(
            float(row["actual_revenue_change_pct"])
            if row["actual_revenue_change_pct"] is not None
            else None
        ),
        created_at=row["created_at"],
    )
