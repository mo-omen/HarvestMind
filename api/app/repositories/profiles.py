from __future__ import annotations

import os
from datetime import date
from typing import Any, Literal, NotRequired, Protocol, TypedDict
from uuid import uuid4

try:
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    from psycopg.types.json import Json, Jsonb
except ImportError:  # pragma: no cover - exercised only when dependency is absent.
    psycopg = None
    sql = None
    dict_row = None
    Json = None
    Jsonb = None


class FarmerProfileUpsertInput(TypedDict):
    location: str
    preferred_crops: list[str]
    farm_size_hectares: float | None
    current_crop: NotRequired[str | None]
    current_price_rm_per_kg: NotRequired[float | None]
    expected_harvest_date: NotRequired[date | str | None]
    expected_harvest_days: NotRequired[int | None]
    labor_flexibility_pct: NotRequired[int | None]
    candidate_crops: NotRequired[list[str]]
    latest_intake_state: NotRequired[dict[str, Any] | None]
    farmer_id: NotRequired[str | None]


class FarmerProfileRecord(TypedDict):
    farmer_id: str
    location: str
    preferred_crops: list[str]
    current_crop: str | None
    current_price_rm_per_kg: float | None
    expected_harvest_date: date | None
    farm_size_hectares: float | None
    expected_harvest_days: int | None
    labor_flexibility_pct: int | None
    candidate_crops: list[str]


class FarmerProfileSavedRecord(FarmerProfileRecord):
    saved: Literal[True]


class FarmerProfileRepository(Protocol):
    def upsert_profile(self, payload: FarmerProfileUpsertInput) -> FarmerProfileSavedRecord:
        ...

    def get_profile(self, farmer_id: str) -> FarmerProfileRecord | None:
        ...


class ProfileRepositoryError(RuntimeError):
    """Base repository failure for farmer profile persistence."""


class ProfileRepositoryConfigurationError(ProfileRepositoryError):
    """Raised when the repository cannot resolve database configuration."""


class PostgresFarmerProfileRepository:
    def __init__(self, conninfo: str | None = None, table_name: str = "farmers") -> None:
        self._conninfo = conninfo or _resolve_conninfo()
        self._table_name = table_name

    def upsert_profile(self, payload: FarmerProfileUpsertInput) -> FarmerProfileSavedRecord:
        farmer_id = payload.get("farmer_id") or str(uuid4())
        params = {
            "farmer_id": farmer_id,
            "location": payload["location"],
            "preferred_crops": self._encode_json(payload.get("preferred_crops", [])),
            "farm_size_hectares": payload.get("farm_size_hectares"),
            "current_crop": payload.get("current_crop"),
            "current_price_rm_per_kg": payload.get("current_price_rm_per_kg"),
            "expected_harvest_date": payload.get("expected_harvest_date"),
            "expected_harvest_days": payload.get("expected_harvest_days"),
            "labor_flexibility_pct": payload.get("labor_flexibility_pct"),
            "candidate_crops": self._encode_json(payload.get("candidate_crops", [])),
            "latest_intake_state": self._encode_json(payload.get("latest_intake_state")),
        }

        query = sql.SQL(
            """
            INSERT INTO {table} (
                farmer_id,
                location,
                preferred_crops,
                current_crop,
                current_price_rm_per_kg,
                expected_harvest_date,
                farm_size_hectares,
                expected_harvest_days,
                labor_flexibility_pct,
                candidate_crops,
                latest_intake_state
            ) VALUES (
                %(farmer_id)s,
                %(location)s,
                %(preferred_crops)s,
                %(current_crop)s,
                %(current_price_rm_per_kg)s,
                %(expected_harvest_date)s,
                %(farm_size_hectares)s,
                %(expected_harvest_days)s,
                %(labor_flexibility_pct)s,
                %(candidate_crops)s,
                %(latest_intake_state)s
            )
            ON CONFLICT (farmer_id) DO UPDATE
            SET
                location = EXCLUDED.location,
                preferred_crops = EXCLUDED.preferred_crops,
                current_crop = EXCLUDED.current_crop,
                current_price_rm_per_kg = EXCLUDED.current_price_rm_per_kg,
                expected_harvest_date = EXCLUDED.expected_harvest_date,
                farm_size_hectares = EXCLUDED.farm_size_hectares,
                expected_harvest_days = EXCLUDED.expected_harvest_days,
                labor_flexibility_pct = EXCLUDED.labor_flexibility_pct,
                candidate_crops = EXCLUDED.candidate_crops,
                latest_intake_state = EXCLUDED.latest_intake_state,
                updated_at = NOW()
            RETURNING
                farmer_id,
                location,
                preferred_crops,
                current_crop,
                current_price_rm_per_kg,
                expected_harvest_date,
                farm_size_hectares,
                expected_harvest_days,
                labor_flexibility_pct,
                candidate_crops
            """
        ).format(table=self._table_identifier())

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()

        if row is None:
            raise ProfileRepositoryError("Profile upsert did not return a persisted row.")

        record = _row_to_profile_record(row)
        return FarmerProfileSavedRecord(**record, saved=True)

    def get_profile(self, farmer_id: str) -> FarmerProfileRecord | None:
        query = sql.SQL(
            """
            SELECT
                farmer_id,
                location,
                preferred_crops,
                current_crop,
                current_price_rm_per_kg,
                expected_harvest_date,
                farm_size_hectares,
                expected_harvest_days,
                labor_flexibility_pct,
                candidate_crops
            FROM {table}
            WHERE farmer_id = %(farmer_id)s
            """
        ).format(table=self._table_identifier())

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, {"farmer_id": farmer_id})
                row = cursor.fetchone()

        if row is None:
            return None

        return _row_to_profile_record(row)

    def _table_identifier(self) -> Any:
        schema_name, table_name = self._schema_and_table_name()
        return sql.Identifier(schema_name, table_name)

    def _schema_and_table_name(self) -> tuple[str, str]:
        if "." not in self._table_name:
            return ("public", self._table_name)
        schema_name, table_name = self._table_name.split(".", maxsplit=1)
        return (schema_name, table_name)

    def _connect(self) -> Any:
        if psycopg is None or dict_row is None:
            raise ProfileRepositoryConfigurationError(
                "psycopg is required to use PostgresFarmerProfileRepository."
            )
        return psycopg.connect(self._conninfo, row_factory=dict_row)

    def _encode_json(self, value: Any) -> Any:
        if value is None:
            return None
        if Jsonb is not None:
            return Jsonb(value)
        if Json is not None:
            return Json(value)
        raise ProfileRepositoryConfigurationError(
            "psycopg JSON support is unavailable."
        )


def _resolve_conninfo() -> str:
    for env_var in ("DATABASE_URL", "POSTGRES_DSN", "POSTGRES_URL"):
        value = os.getenv(env_var)
        if value:
            return value
    raise ProfileRepositoryConfigurationError(
        "Set DATABASE_URL, POSTGRES_DSN, or POSTGRES_URL to use profile persistence."
    )


def _row_to_profile_record(row: dict[str, Any]) -> FarmerProfileRecord:
    return FarmerProfileRecord(
        farmer_id=str(row["farmer_id"]),
        location=str(row["location"]),
        preferred_crops=_normalize_preferred_crops(row.get("preferred_crops")),
        current_crop=_normalize_text(row.get("current_crop")),
        current_price_rm_per_kg=_normalize_farm_size(row.get("current_price_rm_per_kg")),
        expected_harvest_date=_normalize_date(row.get("expected_harvest_date")),
        farm_size_hectares=_normalize_farm_size(row.get("farm_size_hectares")),
        expected_harvest_days=_normalize_int(row.get("expected_harvest_days")),
        labor_flexibility_pct=_normalize_int(row.get("labor_flexibility_pct")),
        candidate_crops=_normalize_preferred_crops(row.get("candidate_crops")),
    )


def _normalize_preferred_crops(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return [str(value)]


def _normalize_farm_size(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _normalize_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _normalize_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
