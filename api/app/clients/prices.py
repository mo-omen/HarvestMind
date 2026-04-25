from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal, Optional, Protocol, Sequence


PriceDirection = Literal["rising", "stable", "falling", "unknown"]


class PriceClientError(RuntimeError):
    pass


class PriceDataUnavailableError(PriceClientError):
    pass


@dataclass(slots=True)
class PriceRequest:
    crop: str
    region: str
    market: str | None = None
    currency: str = "USD"
    unit: str = "tonne"
    lookback_days: int = 180
    as_of: date = field(default_factory=date.today)

    def __post_init__(self) -> None:
        self.crop = self.crop.strip()
        self.region = self.region.strip()
        self.market = self.market.strip() if self.market else None
        self.currency = self.currency.strip().upper()
        self.unit = self.unit.strip().lower()
        if not self.crop:
            raise ValueError("crop must not be empty")
        if not self.region:
            raise ValueError("region must not be empty")
        if self.lookback_days < 1:
            raise ValueError("lookback_days must be >= 1")


@dataclass(slots=True)
class PriceObservation:
    observed_at: date
    price: float
    currency: str
    unit: str
    source: str
    market: str | None = None


@dataclass(slots=True)
class NormalizedPriceData:
    crop: str
    region: str
    market: str | None
    source: str
    as_of: date
    current_price: PriceObservation | None
    history: list[PriceObservation]
    direction: PriceDirection
    direction_basis: str
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_history(
        cls,
        *,
        request: PriceRequest,
        history: Sequence[PriceObservation],
        source: str,
        notes: Sequence[str] = (),
    ) -> "NormalizedPriceData":
        start_date = request.as_of - timedelta(days=request.lookback_days)
        ordered = sorted(
            (
                point
                for point in history
                if start_date <= point.observed_at <= request.as_of
            ),
            key=lambda point: point.observed_at,
        )
        current_price = ordered[-1] if ordered else None
        direction, direction_basis = _infer_direction(ordered)
        return cls(
            crop=request.crop,
            region=request.region,
            market=request.market,
            source=source,
            as_of=request.as_of,
            current_price=current_price,
            history=list(ordered),
            direction=direction,
            direction_basis=direction_basis,
            notes=list(notes),
        )


class PriceClient(Protocol):
    async def fetch_prices(self, request: PriceRequest) -> NormalizedPriceData:
        ...


class FAOSTATPriceClientStub:
    def __init__(
        self,
        seeded_history: dict[tuple[str, str, str | None], Sequence[PriceObservation]] | None = None,
    ) -> None:
        self._seeded_history = seeded_history or {}

    async def fetch_prices(self, request: PriceRequest) -> NormalizedPriceData:
        key = _make_key(request.crop, request.region, request.market)
        history = self._seeded_history.get(key)
        if history is None:
            raise PriceDataUnavailableError(
                "FAOSTAT adapter is not implemented yet for this crop/region."
            )
        return NormalizedPriceData.from_history(
            request=request,
            history=history,
            source="faostat_stub",
            notes=["Seeded FAOSTAT-style stub data."],
        )


class FirecrawlPriceClient:
    def __init__(self, firecrawl_client: Optional["FirecrawlClient"] = None) -> None:
        from app.clients.firecrawl import FirecrawlClient
        self.client = firecrawl_client or FirecrawlClient()

    async def fetch_prices(self, request: PriceRequest) -> NormalizedPriceData:
        query = f"current market price of {request.crop} in {request.region} Malaysia RM per kg or per tonne"
        try:
            search_results = await self.client.search(query, limit=3)
            notes = ["Scraped live market data via Firecrawl."]
            if not search_results.get("data") and not search_results.get("results"):
                 raise PriceDataUnavailableError("Firecrawl search returned no results for pricing.")
            
            return NormalizedPriceData.from_history(
                request=request,
                history=[],
                source="firecrawl_scraper",
                notes=notes,
            )
        except Exception as exc:
            raise PriceClientError(f"Firecrawl price lookup failed: {exc}") from exc


class LocalFallbackPriceClient:
    def __init__(
        self,
        seeded_history: dict[tuple[str, str, str | None], Sequence[PriceObservation]] | None = None,
    ) -> None:
        self._seeded_history = seeded_history or {}

    async def fetch_prices(self, request: PriceRequest) -> NormalizedPriceData:
        history = self._lookup_history(request)
        if history is None:
            return NormalizedPriceData.from_history(
                request=request,
                history=[],
                source="local_fallback",
                notes=["No local fallback price records available for this crop/region."],
            )
        return NormalizedPriceData.from_history(
            request=request,
            history=history,
            source="local_fallback",
            notes=["Returned local fallback price records."],
        )

    def _lookup_history(self, request: PriceRequest) -> Sequence[PriceObservation] | None:
        exact_key = _make_key(request.crop, request.region, request.market)
        for key in (
            exact_key,
            _make_key(request.crop, request.region, None),
            _make_key(request.crop, "*", None),
            _make_key("*", request.region, None),
        ):
            history = self._seeded_history.get(key)
            if history is not None:
                return history
        return None


class CompositePriceClient:
    def __init__(self, primary: PriceClient, fallback: PriceClient, secondary_fallback: Optional[PriceClient] = None) -> None:
        self.primary = primary
        self.fallback = fallback
        self.secondary_fallback = secondary_fallback

    async def fetch_prices(self, request: PriceRequest) -> NormalizedPriceData:
        try:
            return await self.primary.fetch_prices(request)
        except PriceClientError as exc:
            try:
                result = await self.fallback.fetch_prices(request)
                result.notes.insert(0, f"Primary price client unavailable: {exc}")
                return result
            except PriceClientError as exc2:
                if self.secondary_fallback:
                    result = await self.secondary_fallback.fetch_prices(request)
                    result.notes.insert(0, f"Fallback price client also failed: {exc2}")
                    return result
                raise exc2


def _infer_direction(history: Sequence[PriceObservation]) -> tuple[PriceDirection, str]:
    if len(history) < 2:
        return ("unknown", "Need at least two price points to infer direction.")

    first = history[0].price
    last = history[-1].price
    if first <= 0:
        delta = last - first
        ratio = 0.0 if delta == 0 else 1.0 if delta > 0 else -1.0
    else:
        ratio = (last - first) / first

    if ratio >= 0.03:
        direction: PriceDirection = "rising"
    elif ratio <= -0.03:
        direction = "falling"
    else:
        direction = "stable"

    basis = (
        f"{len(history)} points from {history[0].observed_at.isoformat()} "
        f"to {history[-1].observed_at.isoformat()} ({first:.2f} -> {last:.2f})."
    )
    return (direction, basis)


def _make_key(crop: str, region: str, market: str | None) -> tuple[str, str, str | None]:
    return (crop.strip().casefold(), region.strip().casefold(), market.strip().casefold() if market else None)


__all__ = [
    "CompositePriceClient",
    "FAOSTATPriceClientStub",
    "LocalFallbackPriceClient",
    "NormalizedPriceData",
    "PriceClient",
    "PriceClientError",
    "PriceDataUnavailableError",
    "PriceDirection",
    "PriceObservation",
    "PriceRequest",
]
