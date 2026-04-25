from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings


@dataclass(frozen=True, slots=True)
class MarketCrop:
    crop: str
    display_name: str
    emoji: str
    aliases: tuple[str, ...]
    fallback_range: tuple[float, float]
    fallback_change_pct: float


MARKET_CROPS: tuple[MarketCrop, ...] = (
    MarketCrop("chili", "Chili (Red)", "\U0001f336", ("cili", "chili", "red chili", "cili merah"), (3.50, 6.00), -18.0),
    MarketCrop("ginger", "Ginger", "\U0001fada", ("halia", "ginger", "halia tua"), (4.00, 7.50), 12.0),
    MarketCrop("kangkung", "Kangkung", "\U0001f96c", ("kangkung",), (1.20, 2.50), 0.0),
    MarketCrop("tomato", "Tomato", "\U0001f345", ("tomato", "tomato buah"), (2.80, 5.00), 8.0),
    MarketCrop("durian", "Durian (Musang King)", "\U0001f348", ("durian", "musang king"), (35.00, 80.00), 22.0),
    MarketCrop("banana", "Banana (Berangan)", "\U0001f34c", ("pisang", "banana", "berangan"), (1.50, 3.20), -9.0),
    MarketCrop("turmeric", "Turmeric", "\U0001f9c4", ("kunyit", "turmeric"), (3.00, 5.50), 6.0),
    MarketCrop("cucumber", "Cucumber", "\U0001f952", ("timun", "cucumber"), (1.00, 2.20), -14.0),
)


class MarketClientError(RuntimeError):
    pass


@dataclass(slots=True)
class MarketPriceRecord:
    crop: str
    display_name: str
    emoji: str
    price_min_rm_per_kg: float
    price_max_rm_per_kg: float
    change_30d_pct: float
    source: str
    source_urls: list[str]
    as_of: date
    raw_matches: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class FAMAMarketPriceClient:
    def __init__(
        self,
        *,
        urls: list[str] | None = None,
        timeout: float = 15.0,
        firecrawl_client: Optional["FirecrawlClient"] = None,
    ) -> None:
        self.urls = urls if urls is not None else settings.fama_price_urls
        self.timeout = timeout
        from app.clients.firecrawl import FirecrawlClient
        self.firecrawl = firecrawl_client or FirecrawlClient()

    async def fetch_market_prices(self) -> list[MarketPriceRecord]:
        pages: list[tuple[str, str]] = []
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            for url in self.urls:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    pages.append((url, response.text))
                except httpx.HTTPError as exc:
                    errors.append(f"{url}: {exc}")

        parsed = _records_from_pages(pages)
        if parsed:
            return parsed

        # Try Firecrawl as secondary fallback before seeding
        try:
            fc_client = FirecrawlMarketClient(self.firecrawl)
            fc_records = await fc_client.fetch_market_prices()
            if fc_records:
                return fc_records
        except Exception as exc:
            errors.append(f"Firecrawl fallback failed: {exc}")

        records = _fallback_records()
        reason = "FAMA page did not expose parseable table rows."
        if errors:
            reason = f"{reason} Fetch errors: {'; '.join(errors[:2])}."
        for record in records:
            record.notes.append(reason)
        return records


class FirecrawlMarketClient:
    def __init__(self, client: "FirecrawlClient") -> None:
        self.client = client

    async def fetch_market_prices(self) -> list[MarketPriceRecord]:
        records: list[MarketPriceRecord] = []
        # We fetch for a subset of major crops to avoid too many searches
        for crop in MARKET_CROPS[:4]: 
            query = f"current market price of {crop.display_name} in Malaysia RM per kg"
            try:
                search_results = await self.client.search(query, limit=2)
                data = search_results.get("data") or search_results.get("results") or []
                if not data:
                    continue

                # Use the first result's snippet/description for a basic record
                entry = data[0]
                url = entry.get("url") or entry.get("link")
                snippet = entry.get("description") or entry.get("snippet") or ""

                # Simple extraction from snippet if possible, otherwise use fallback range
                low, high = crop.fallback_range
                prices = _extract_prices(snippet)
                if prices:
                    low, high = _reasonable_range(prices, crop.fallback_range)

                records.append(
                    MarketPriceRecord(
                        crop=crop.crop,
                        display_name=crop.display_name,
                        emoji=crop.emoji,
                        price_min_rm_per_kg=low,
                        price_max_rm_per_kg=high,
                        change_30d_pct=crop.fallback_change_pct,
                        source="firecrawl_market_search",
                        source_urls=[url] if url else [],
                        as_of=date.today(),
                        notes=[f"Live search result: {snippet[:200]}..."],
                    )
                )
            except Exception:
                continue
        return records


def _records_from_pages(pages: list[tuple[str, str]]) -> list[MarketPriceRecord]:
    records: list[MarketPriceRecord] = []
    for crop in MARKET_CROPS:
        values: list[float] = []
        raw_matches: list[dict[str, Any]] = []
        source_urls: list[str] = []

        for url, html in pages:
            soup = BeautifulSoup(html, "html.parser")
            for row in soup.find_all("tr"):
                text = _clean_text(row.get_text(" ", strip=True))
                if not _mentions_crop(text, crop):
                    continue
                prices = _extract_prices(text)
                if prices:
                    values.extend(prices)
                    raw_matches.append({"url": url, "row": text[:500], "prices": prices})
                    source_urls.append(url)

            if not raw_matches:
                text = _clean_text(soup.get_text(" ", strip=True))
                for alias in crop.aliases:
                    pattern = re.compile(rf"(.{{0,80}}{re.escape(alias)}.{{0,140}})", re.IGNORECASE)
                    for match in pattern.finditer(text):
                        snippet = match.group(1)
                        prices = _extract_prices(snippet)
                        if prices:
                            values.extend(prices)
                            raw_matches.append({"url": url, "row": snippet[:500], "prices": prices})
                            source_urls.append(url)

        if not values:
            continue

        low, high = _reasonable_range(values, crop.fallback_range)
        change = _infer_change(crop, low, high)
        records.append(
            MarketPriceRecord(
                crop=crop.crop,
                display_name=crop.display_name,
                emoji=crop.emoji,
                price_min_rm_per_kg=low,
                price_max_rm_per_kg=high,
                change_30d_pct=change,
                source="fama_scrape",
                source_urls=sorted(set(source_urls)),
                as_of=date.today(),
                raw_matches=raw_matches[:5],
                notes=["Parsed from public FAMA market price page."],
            )
        )
    return records


def _fallback_records() -> list[MarketPriceRecord]:
    return [
        MarketPriceRecord(
            crop=crop.crop,
            display_name=crop.display_name,
            emoji=crop.emoji,
            price_min_rm_per_kg=crop.fallback_range[0],
            price_max_rm_per_kg=crop.fallback_range[1],
            change_30d_pct=crop.fallback_change_pct,
            source="seeded_fallback",
            source_urls=list(settings.fama_price_urls),
            as_of=date.today(),
            notes=["Seeded range used until FAMA data can be parsed."],
        )
        for crop in MARKET_CROPS
    ]


def market_crop_by_name(name: str) -> MarketCrop | None:
    normalized = name.strip().casefold()
    for crop in MARKET_CROPS:
        if normalized == crop.crop or normalized in {alias.casefold() for alias in crop.aliases}:
            return crop
    return None


def _mentions_crop(text: str, crop: MarketCrop) -> bool:
    lowered = text.casefold()
    return any(alias.casefold() in lowered for alias in crop.aliases)


def _extract_prices(text: str) -> list[float]:
    values: list[float] = []
    for match in re.finditer(r"(?:RM\s*)?(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:/|per)?\s*(?:kg|kilogram)?", text, re.IGNORECASE):
        value = float(match.group(1).replace(",", "."))
        if 0.2 <= value <= 200:
            values.append(value)
    return values


def _reasonable_range(values: list[float], fallback: tuple[float, float]) -> tuple[float, float]:
    filtered = [value for value in values if 0.2 <= value <= 200]
    if not filtered:
        return fallback
    low = round(min(filtered), 2)
    high = round(max(filtered), 2)
    if high / max(low, 0.01) > 8:
        return fallback
    return (low, high)


def _infer_change(crop: MarketCrop, low: float, high: float) -> float:
    fallback_mid = sum(crop.fallback_range) / 2
    current_mid = (low + high) / 2
    if fallback_mid <= 0:
        return crop.fallback_change_pct
    return round(((current_mid - fallback_mid) / fallback_mid) * 100, 1)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def utc_now() -> datetime:
    return datetime.now(UTC)
