from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import ValidationError

from app.clients.market import FAMAMarketPriceClient, MARKET_CROPS, MarketPriceRecord
from app.core.config import settings
from app.db.postgres import PostgresDatabase
from app.repositories.signals import SignalSnapshotCreate, SignalSnapshotRepository
from app.schemas.market import (
    MarketSignalCard,
    MarketSignalsResponse,
    MarketSummaryItem,
    MarketSummaryResponse,
)

MARKET_LOCATION = "Malaysia"
MARKET_SIGNAL_SOURCE = "glm_market_weekly"


class MarketService:
    def __init__(
        self,
        database: PostgresDatabase,
        *,
        price_client: FAMAMarketPriceClient | None = None,
    ) -> None:
        self._signals = SignalSnapshotRepository(database)
        self._price_client = price_client or FAMAMarketPriceClient()

    async def refresh_market_prices(self) -> MarketSummaryResponse:
        records = await self._price_client.fetch_market_prices()
        items = [self._store_price_record(record) for record in records]
        return MarketSummaryResponse(items=items, generated_at=_utc_now())

    async def get_or_refresh_market_summary(self) -> MarketSummaryResponse:
        summary = self.get_market_summary()
        if any(item.updated_at is not None for item in summary.items):
            return summary
        return await self.refresh_market_prices()

    def get_market_summary(self) -> MarketSummaryResponse:
        items: list[MarketSummaryItem] = []
        for crop in MARKET_CROPS:
            record = self._signals.fetch_latest_context(
                signal_type="price",
                crop=crop.crop,
                location=MARKET_LOCATION,
            )
            if record is None:
                continue
            items.append(_summary_item_from_payload(record.normalized_payload, record.created_at))

        if not items:
            items = [_summary_item_from_price_record(record) for record in _fallback_price_records()]
        return MarketSummaryResponse(items=items, generated_at=_utc_now())

    async def generate_weekly_signals(self) -> MarketSignalsResponse:
        summary = self.get_market_summary()
        cards = await _glm_market_cards(summary.items)
        payload = {
            "cards": [card.model_dump(mode="json") for card in cards],
            "generated_at": _utc_now().isoformat(),
        }
        self._signals.create(
            SignalSnapshotCreate(
                signal_type="news",
                source=MARKET_SIGNAL_SOURCE,
                normalized_payload=payload,
                raw_payload={"market_summary": summary.model_dump(mode="json")},
                farmer_id=None,
                crop=None,
                location=MARKET_LOCATION,
            )
        )
        return MarketSignalsResponse(cards=cards, generated_at=_utc_now(), source=MARKET_SIGNAL_SOURCE)

    def get_weekly_signals(self) -> MarketSignalsResponse:
        record = self._signals.fetch_latest_by_source(MARKET_SIGNAL_SOURCE)
        if record is None:
            cards = _fallback_market_cards(self.get_market_summary().items)
            return MarketSignalsResponse(cards=cards, generated_at=_utc_now(), source="fallback")

        payload = record.normalized_payload
        cards = [MarketSignalCard.model_validate(item) for item in payload.get("cards", [])]
        generated_at = _parse_datetime(payload.get("generated_at")) or record.created_at
        return MarketSignalsResponse(cards=cards, generated_at=generated_at, source=record.source)

    def _store_price_record(self, record: MarketPriceRecord) -> MarketSummaryItem:
        item = _summary_item_from_price_record(record)
        self._signals.create(
            SignalSnapshotCreate(
                signal_type="price",
                source=record.source,
                normalized_payload=item.model_dump(mode="json"),
                raw_payload={"matches": record.raw_matches, "notes": record.notes},
                farmer_id=None,
                crop=record.crop,
                location=MARKET_LOCATION,
            )
        )
        return item


def _summary_item_from_price_record(record: MarketPriceRecord) -> MarketSummaryItem:
    trend = _trend_from_change(record.change_30d_pct)
    return MarketSummaryItem(
        crop=record.crop,
        display_name=record.display_name,
        emoji=record.emoji,
        price_min_rm_per_kg=record.price_min_rm_per_kg,
        price_max_rm_per_kg=record.price_max_rm_per_kg,
        trend=trend,
        trend_score=_trend_score(record.change_30d_pct),
        change_30d_pct=record.change_30d_pct,
        signal=_signal_from_change(record.change_30d_pct),
        confidence=0.78 if record.source == "fama_scrape" else 0.45,
        source=record.source,
        source_urls=record.source_urls,
        as_of=record.as_of,
        notes=record.notes,
    )


def _summary_item_from_payload(payload: dict[str, Any], created_at: datetime) -> MarketSummaryItem:
    item = MarketSummaryItem.model_validate(payload)
    return item.model_copy(update={"updated_at": created_at})


def _fallback_price_records() -> list[MarketPriceRecord]:
    from app.clients.market import _fallback_records

    return _fallback_records()


async def _glm_market_cards(items: list[MarketSummaryItem]) -> list[MarketSignalCard]:
    if not settings.ilmu_api_key:
        return _fallback_market_cards(items)

    payload = {
        "model": settings.glm_model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Create weekly Malaysian crop market signal cards from the provided structured data. "
                    "Use only the data provided and return JSON with key cards. Each card must have "
                    "label, severity (risk/opportunity/watch), title, summary, and source_urls."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "market_summary": [item.model_dump(mode="json") for item in items],
                        "card_count": 6,
                    },
                    ensure_ascii=True,
                ),
            },
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.ilmu_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.ilmu_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            cards = [MarketSignalCard.model_validate(item) for item in parsed.get("cards", [])]
            return cards[:6] or _fallback_market_cards(items)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, ValidationError):
        return _fallback_market_cards(items)


def _fallback_market_cards(items: list[MarketSummaryItem]) -> list[MarketSignalCard]:
    sorted_items = sorted(items, key=lambda item: item.change_30d_pct)
    weakest = sorted_items[0] if sorted_items else None
    strongest = sorted_items[-1] if sorted_items else None
    cards: list[MarketSignalCard] = []
    if weakest:
        cards.append(
            MarketSignalCard(
                label="Risk Alert",
                severity="risk",
                title=f"{weakest.display_name} price pressure",
                summary=f"{weakest.display_name} is showing a {weakest.change_30d_pct:.1f}% 30-day move. Watch buyer demand before committing more acreage.",
                source_urls=weakest.source_urls,
            )
        )
    if strongest and strongest is not weakest:
        cards.append(
            MarketSignalCard(
                label="Opportunity",
                severity="opportunity",
                title=f"{strongest.display_name} strengthening",
                summary=f"{strongest.display_name} is the strongest tracked crop this cycle at {strongest.change_30d_pct:.1f}% over 30 days.",
                source_urls=strongest.source_urls,
            )
        )
    cards.append(
        MarketSignalCard(
            label="Watch",
            severity="watch",
            title="Refresh local quotes before selling",
            summary="Use these prices as indicative signals only; confirm with FAMA, local buyers, or wet-market quotes before acting.",
            source_urls=settings.fama_price_urls,
        )
    )
    
    # Add extra general signals to reach 6
    cards.append(
        MarketSignalCard(
            label="Regional",
            severity="watch",
            title="Monsoon season patterns",
            summary="Heavy rainfall expected in some regions; monitor transport routes and storage humidity levels.",
            source_urls=[],
        )
    )
    cards.append(
        MarketSignalCard(
            label="Inventory",
            severity="opportunity",
            title="Off-season planting window",
            summary="Some crops show higher off-season resilience. Review your planting schedule for potential early cycles.",
            source_urls=[],
        )
    )
    cards.append(
        MarketSignalCard(
            label="Advice",
            severity="watch",
            title="Sustainable fertilizer use",
            summary="Market input costs are shifting. Consult local agricultural guidelines for optimized application.",
            source_urls=[],
        )
    )
    return cards[:6]


def _trend_from_change(change: float) -> str:
    if change >= 3:
        return "rising"
    if change <= -3:
        return "falling"
    return "stable"


def _trend_score(change: float) -> int:
    return max(5, min(95, int(round(50 + change * 2))))


def _signal_from_change(change: float) -> str:
    if change >= 6:
        return "buy"
    if change <= -8:
        return "watch"
    return "hold"


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _utc_now() -> datetime:
    return datetime.now(UTC)
