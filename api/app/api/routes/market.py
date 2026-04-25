from fastapi import APIRouter, HTTPException, status

from app.db.runtime import ensure_schema_ready
from app.schemas.market import MarketSignalsResponse, MarketSummaryResponse
from app.services.market import MarketService


router = APIRouter(prefix="/market", tags=["market"])


def _get_market_service() -> MarketService:
    database = ensure_schema_ready()
    return MarketService(database)


@router.get("/summary", response_model=MarketSummaryResponse)
async def get_market_summary() -> MarketSummaryResponse:
    service = _get_market_service()
    return await service.get_or_refresh_market_summary()


@router.post("/refresh", response_model=MarketSummaryResponse)
async def refresh_market_summary() -> MarketSummaryResponse:
    service = _get_market_service()
    try:
        return await service.refresh_market_prices()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh market summary: {exc}",
        ) from exc


@router.get("/signals", response_model=MarketSignalsResponse)
async def get_market_signals() -> MarketSignalsResponse:
    service = _get_market_service()
    return service.get_weekly_signals()


@router.post("/signals/refresh", response_model=MarketSignalsResponse)
async def refresh_market_signals() -> MarketSignalsResponse:
    service = _get_market_service()
    try:
        return await service.generate_weekly_signals()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh market signals: {exc}",
        ) from exc
