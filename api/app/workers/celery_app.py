import asyncio

from celery import Celery

from app.db.runtime import ensure_schema_ready
from app.core.config import settings
from app.schemas.ops import SyncJobRequest
from app.services.market import MarketService
from app.services.ops import OperationsService


celery_app = Celery("agripivot", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.timezone = "Asia/Singapore"
celery_app.conf.beat_schedule = {
    "refresh-market-prices-daily": {
        "task": "app.workers.celery_app.sync_market_data",
        "schedule": 60 * 60 * 24,
        "args": (),
    },
    "generate-market-signals-weekly": {
        "task": "app.workers.celery_app.generate_market_signals",
        "schedule": 60 * 60 * 24 * 7,
        "args": (),
    },
}


def _run_sync_job(source: str, *, farmer_id: str | None, crop: str | None, location: str | None) -> dict:
    database = ensure_schema_ready()
    service = OperationsService(database)
    record = asyncio.run(
        service.run_sync(
            SyncJobRequest(
                source=source,
                farmer_id=farmer_id,
                crop=crop,
                location=location,
            )
        )
    )
    return record.__dict__


@celery_app.task
def sync_market_data(
    farmer_id: str | None = None,
    crop: str | None = None,
    location: str | None = None,
) -> dict:
    return _run_sync_job("market", farmer_id=farmer_id, crop=crop, location=location)


@celery_app.task
def sync_weather_data(
    farmer_id: str | None = None,
    crop: str | None = None,
    location: str | None = None,
) -> dict:
    return _run_sync_job("weather", farmer_id=farmer_id, crop=crop, location=location)


@celery_app.task
def sync_news_data(
    farmer_id: str | None = None,
    crop: str | None = None,
    location: str | None = None,
) -> dict:
    return _run_sync_job("news", farmer_id=farmer_id, crop=crop, location=location)


@celery_app.task
def generate_market_signals() -> dict:
    database = ensure_schema_ready()
    service = MarketService(database)
    response = asyncio.run(service.generate_weekly_signals())
    return response.model_dump(mode="json")
