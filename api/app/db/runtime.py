from pathlib import Path
from datetime import date

from fastapi import HTTPException, status

from app.core.config import settings
from app.db import PostgresConfig, PostgresDatabase, PostgresDependencyMissingError, apply_sql_file


_database: PostgresDatabase | None = None
_schema_ready = False


def get_database() -> PostgresDatabase:
    global _database

    if _database is None:
        if not settings.database_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DATABASE_URL is not configured.",
            )
        _database = PostgresDatabase(PostgresConfig(dsn=settings.database_url))
    return _database


def ensure_schema_ready() -> PostgresDatabase:
    global _schema_ready

    database = get_database()
    if _schema_ready:
        return database

    migration_path = Path(__file__).resolve().parents[2] / "sql" / "001_init.sql"
    try:
        apply_sql_file(database, migration_path)
        _seed_demo_data(database)
    except PostgresDependencyMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database initialization failed: {exc}",
        ) from exc

    _schema_ready = True
    return database


def _seed_demo_data(database: PostgresDatabase) -> None:
    from app.repositories.profiles import PostgresFarmerProfileRepository
    repo = PostgresFarmerProfileRepository(conninfo=database.config.dsn)
    
    # Check if demo farmer already exists
    if repo.get_profile(settings.demo_farmer_id) is not None:
        return

    # Seed initial demo farmer
    repo.upsert_profile({
        "farmer_id": settings.demo_farmer_id,
        "location": "Muar, Johor",
        "preferred_crops": ["chili"],
        "current_crop": "chili",
        "current_price_rm_per_kg": 4.50,
        "expected_harvest_date": date.today(),
        "farm_size_hectares": 2.5,
        "expected_harvest_days": 30,
        "labor_flexibility_pct": 25,
        "candidate_crops": ["ginger", "tomato"],
        "latest_intake_state": {"completed": True}
    })
