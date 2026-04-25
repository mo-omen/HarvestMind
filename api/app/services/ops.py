from __future__ import annotations

from urllib.parse import urlparse

import redis

from app.clients.news import GDELTNewsClient, NewsSearchRequest
from app.clients.prices import CompositePriceClient, FAOSTATPriceClientStub, LocalFallbackPriceClient, PriceRequest
from app.clients.weather import OpenMeteoWeatherClient
from app.core.config import settings
from app.db.postgres import PostgresDatabase
from app.repositories.signals import SignalSnapshotCreate, SignalSnapshotRepository
from app.repositories.sync_jobs import SyncJobCreate, SyncJobRepository
from app.schemas.ops import ReadinessCheck, SyncJobRequest
from app.services.market import MarketService


class OperationsService:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database
        self._signal_repository = SignalSnapshotRepository(database)
        self._sync_repository = SyncJobRepository(database)
        self._weather_client = OpenMeteoWeatherClient()
        self._news_client = GDELTNewsClient()
        self._price_client = CompositePriceClient(
            primary=FAOSTATPriceClientStub(),
            fallback=LocalFallbackPriceClient(),
        )
        self._market_service = MarketService(database)

    def readiness(self) -> ReadinessCheck:
        checks: dict[str, str] = {}

        try:
            with self._database.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
            checks["postgres"] = "ok"
        except Exception as exc:
            checks["postgres"] = f"error:{exc}"

        try:
            parsed = urlparse(settings.redis_url)
            client = redis.Redis(
                host=parsed.hostname or "redis",
                port=parsed.port or 6379,
                db=int((parsed.path or "/0").strip("/") or "0"),
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            client.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error:{exc}"

        checks["glm_config"] = "ok" if settings.ilmu_api_key else "missing_api_key"
        checks["weather_provider"] = "configured"
        checks["news_provider"] = "configured"

        status = "ok" if all(value == "ok" or value == "configured" for value in checks.values()) else "degraded"
        return ReadinessCheck(status=status, checks=checks)

    async def run_sync(self, request: SyncJobRequest):
        job = self._sync_repository.create(
            SyncJobCreate(
                source=request.source,
                status="running",
                farmer_id=request.farmer_id,
                crop=request.crop,
                location=request.location,
            )
        )
        try:
            result_payload, summary = await self._execute_sync(request)
            return self._sync_repository.update(
                job.job_id,
                status="completed",
                summary=summary,
                result_payload=result_payload,
                error=None,
            )
        except Exception as exc:
            return self._sync_repository.update(
                job.job_id,
                status="failed",
                summary=None,
                result_payload=None,
                error=str(exc),
            )

    def list_jobs(self, *, limit: int = 20):
        return self._sync_repository.list(limit=limit)

    async def _execute_sync(self, request: SyncJobRequest) -> tuple[dict, str]:
        if request.source == "weather":
            if not request.location:
                raise ValueError("location is required for weather sync")
            report = await self._weather_client.get_weather(request.location)
            normalized = report.model_dump(mode="json")
            self._signal_repository.create(
                SignalSnapshotCreate(
                    farmer_id=request.farmer_id,
                    signal_type="weather",
                    crop=request.crop,
                    location=request.location,
                    source=report.source,
                    normalized_payload=normalized,
                    raw_payload=None,
                )
            )
            return normalized, f"Weather snapshot refreshed for {request.location}."

        if request.source == "news":
            if not request.location or not request.crop:
                raise ValueError("location and crop are required for news sync")
            response = await self._news_client.search(
                NewsSearchRequest(crop=request.crop, region=request.location)
            )
            normalized = response.__dict__ | {
                "requested_at": response.requested_at.isoformat(),
                "items": [
                    {
                        "title": item.title,
                        "url": item.url,
                        "source": item.source,
                        "summary": item.summary,
                        "published_at": item.published_at.isoformat() if item.published_at else None,
                        "event_tags": list(item.event_tags),
                        "tone": item.tone,
                    }
                    for item in response.items
                ],
            }
            self._signal_repository.create(
                SignalSnapshotCreate(
                    farmer_id=request.farmer_id,
                    signal_type="news",
                    crop=request.crop,
                    location=request.location,
                    source=response.source,
                    normalized_payload=normalized,
                    raw_payload=None,
                )
            )
            return normalized, f"News snapshot refreshed for {request.crop} in {request.location}."

        if request.source == "market":
            if not request.crop:
                response = await self._market_service.refresh_market_prices()
                return (
                    response.model_dump(mode="json"),
                    f"Market summary refreshed for {len(response.items)} tracked crops.",
                )
            if not request.location:
                raise ValueError("location is required for crop-specific market sync")
            data = self._price_client.fetch_prices(
                PriceRequest(crop=request.crop, region=request.location)
            )
            normalized = {
                "crop": data.crop,
                "region": data.region,
                "market": data.market,
                "source": data.source,
                "as_of": data.as_of.isoformat(),
                "direction": data.direction,
                "direction_basis": data.direction_basis,
                "notes": data.notes,
                "history": [
                    {
                        "observed_at": item.observed_at.isoformat(),
                        "price": item.price,
                        "currency": item.currency,
                        "unit": item.unit,
                        "source": item.source,
                        "market": item.market,
                    }
                    for item in data.history
                ],
            }
            self._signal_repository.create(
                SignalSnapshotCreate(
                    farmer_id=request.farmer_id,
                    signal_type="price",
                    crop=request.crop,
                    location=request.location,
                    source=data.source,
                    normalized_payload=normalized,
                    raw_payload=None,
                )
            )
            return normalized, f"Price snapshot refreshed for {request.crop} in {request.location}."

        raise ValueError(f"Unsupported sync source: {request.source}")
