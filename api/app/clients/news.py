from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, Sequence

import httpx

from app.core.malaysia import MALAYSIA_CANONICAL, malaysia_region_terms


GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
_DEFAULT_CONTEXT_TERMS = (
    "agriculture",
    "farm",
    "crop",
    "harvest",
    "price",
    "market",
)
_MALAYSIA_CONTEXT_TERMS = (
    "Malaysia",
    "Malaysian",
    "Bernama",
    "MARDI",
    "FAMA",
    "DOA",
    "monsoon",
    "plantation",
    "padi",
    "durian",
    "smallholder",
    "agrofood",
)
_INTERNATIONAL_MARKET_TERMS = (
    "global",
    "international",
    "ASEAN",
    "commodity",
    "commodities",
    "export",
    "import",
    "trade",
    "wholesale",
    "retail",
    "supply chain",
    "shipping",
    "food security",
)
_EVENT_TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "price_signal": ("price", "market", "revenue", "wholesale", "retail"),
    "supply_shock": ("oversupply", "shortage", "supply gap", "stockpile"),
    "demand_shift": ("demand", "consumption", "buying", "orders"),
    "trade_policy": ("export", "import", "tariff", "quota", "trade"),
    "policy_support": ("subsidy", "support price", "loan", "grant", "relief"),
    "weather_risk": ("drought", "flood", "storm", "heatwave", "rainfall"),
    "pest_disease": ("pest", "disease", "blight", "locust", "outbreak"),
    "logistics": ("port", "shipping", "rail", "road", "logistics"),
    "crop_calendar": ("planting", "sowing", "harvest", "harvesting"),
}


class NewsClientError(RuntimeError):
    pass


@dataclass(slots=True)
class NewsSearchRequest:
    crop: str
    region: str
    country: str | None = None
    days_back: int = 14
    max_items: int = 10
    extra_terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.crop = self.crop.strip()
        self.region = self.region.strip()
        self.country = self.country.strip() if self.country else MALAYSIA_CANONICAL
        self.extra_terms = tuple(term.strip() for term in self.extra_terms if term.strip())
        if not self.crop:
            raise ValueError("crop must not be empty")
        if not self.region:
            raise ValueError("region must not be empty")
        if self.days_back < 1:
            raise ValueError("days_back must be >= 1")
        if self.max_items < 1:
            raise ValueError("max_items must be >= 1")


@dataclass(slots=True)
class NormalizedNewsItem:
    title: str
    url: str
    source: str
    domain: str | None
    summary: str
    published_at: datetime | None
    language: str | None
    source_country: str | None
    crop: str
    region: str
    event_tags: tuple[str, ...]
    tone: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NewsSearchResponse:
    source: str
    query: str
    requested_at: datetime
    items: list[NormalizedNewsItem]


class GDELTNewsClient:
    def __init__(
        self,
        *,
        base_url: str = GDELT_DOC_API_URL,
        timeout: float = 10.0,
        async_client: httpx.AsyncClient | None = None,
        sync_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self._async_client = async_client
        self._sync_client = sync_client
        self._owns_async_client = async_client is None
        self._owns_sync_client = sync_client is None

    async def search(self, request: NewsSearchRequest) -> NewsSearchResponse:
        client = self._get_async_client()
        params = self._build_params(request)
        try:
            response = await client.get(self.base_url, params=params)
            response.raise_for_status()
            payload = response.json()
        except ValueError as exc:
            raise NewsClientError(f"GDELT returned invalid JSON: {exc}") from exc
        except httpx.HTTPError as exc:
            raise NewsClientError(f"GDELT request failed: {exc}") from exc
        return self._normalize_response(request, payload)

    def search_sync(self, request: NewsSearchRequest) -> NewsSearchResponse:
        client = self._get_sync_client()
        params = self._build_params(request)
        try:
            response = client.get(self.base_url, params=params)
            response.raise_for_status()
            payload = response.json()
        except ValueError as exc:
            raise NewsClientError(f"GDELT returned invalid JSON: {exc}") from exc
        except httpx.HTTPError as exc:
            raise NewsClientError(f"GDELT request failed: {exc}") from exc
        return self._normalize_response(request, payload)

    async def aclose(self) -> None:
        if self._async_client is not None and self._owns_async_client:
            await self._async_client.aclose()
            self._async_client = None
        if self._sync_client is not None and self._owns_sync_client:
            self._sync_client.close()
            self._sync_client = None

    def close(self) -> None:
        if self._sync_client is not None and self._owns_sync_client:
            self._sync_client.close()
            self._sync_client = None

    def _get_async_client(self) -> httpx.AsyncClient:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=self.timeout)
        return self._async_client

    def _get_sync_client(self) -> httpx.Client:
        if self._sync_client is None:
            self._sync_client = httpx.Client(timeout=self.timeout)
        return self._sync_client

    def _build_params(self, request: NewsSearchRequest) -> dict[str, str | int]:
        end = datetime.now(UTC)
        start = end - timedelta(days=request.days_back)
        return {
            "query": self._build_query(request),
            "mode": "ArtList",
            "format": "json",
            "sort": "DateDesc",
            "maxrecords": min(request.max_items, 50),
            "startdatetime": start.strftime("%Y%m%d%H%M%S"),
            "enddatetime": end.strftime("%Y%m%d%H%M%S"),
        }

    def _build_query(self, request: NewsSearchRequest) -> str:
        location_terms = malaysia_region_terms(request.region)
        if request.country:
            location_terms.append(request.country)
        location_clause = " OR ".join(f'"{term}"' for term in _dedupe_terms(location_terms))
        extra_terms = _dedupe_terms(
            (
                *_DEFAULT_CONTEXT_TERMS,
                *_MALAYSIA_CONTEXT_TERMS,
                *_INTERNATIONAL_MARKET_TERMS,
                *request.extra_terms,
            )
        )
        context_clause = " OR ".join(f'"{term}"' for term in extra_terms)
        international_clause = (
            f'"{request.crop}" AND ("global" OR "international" OR "ASEAN" OR '
            '"export" OR "import" OR "trade" OR "commodity" OR "price" OR "market")'
        )
        return (
            f'("{request.crop}" AND ({location_clause}) AND ({context_clause})) '
            f'OR ({international_clause})'
        )

    def _normalize_response(
        self, request: NewsSearchRequest, payload: dict[str, Any]
    ) -> NewsSearchResponse:
        articles = payload.get("articles")
        if not isinstance(articles, list):
            raise NewsClientError("GDELT response did not contain an article list")

        items: list[NormalizedNewsItem] = []
        seen_urls: set[str] = set()

        for article in articles:
            if not isinstance(article, dict):
                continue
            try:
                item = self._normalize_item(article, request)
            except NewsClientError:
                continue
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            items.append(item)

        items.sort(
            key=lambda item: self._relevance_score(item, request),
            reverse=True,
        )

        return NewsSearchResponse(
            source="gdelt_doc_api",
            query=self._build_query(request),
            requested_at=datetime.now(UTC),
            items=items[: request.max_items],
        )

    def _normalize_item(
        self, article: dict[str, Any], request: NewsSearchRequest
    ) -> NormalizedNewsItem:
        title = _first_non_empty(article.get("title"), article.get("url")) or "Untitled"
        url = str(article.get("url") or "").strip()
        if not url:
            raise NewsClientError("GDELT article missing url")
        summary = (
            _first_non_empty(
                article.get("snippet"),
                article.get("excerpt"),
                article.get("summary"),
                title,
            )
            or ""
        )
        source = _first_non_empty(
            article.get("sourcecountry"),
            article.get("domain"),
            article.get("source"),
        ) or "unknown"

        return NormalizedNewsItem(
            title=title,
            url=url,
            source=source,
            domain=_string_or_none(article.get("domain")),
            summary=summary,
            published_at=_parse_datetime(
                _first_non_empty(
                    article.get("seendate"),
                    article.get("published"),
                    article.get("date"),
                )
            ),
            language=_string_or_none(article.get("language")),
            source_country=_string_or_none(article.get("sourcecountry")),
            crop=request.crop,
            region=request.region,
            event_tags=self._extract_event_tags(article, request),
            tone=_coerce_float(article.get("tone")),
            raw=dict(article),
        )

    def _extract_event_tags(
        self, article: dict[str, Any], request: NewsSearchRequest
    ) -> tuple[str, ...]:
        text = " ".join(
            str(value)
            for value in (
                article.get("title"),
                article.get("snippet"),
                article.get("excerpt"),
                article.get("summary"),
            )
            if value
        ).lower()
        tags = {
            f"crop:{_slugify(request.crop)}",
            f"region:{_slugify(request.region)}",
        }
        if request.country:
            tags.add(f"country:{_slugify(request.country)}")

        for tag, keywords in _EVENT_TAG_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                tags.add(tag)

        return tuple(sorted(tags))

    def _relevance_score(self, item: NormalizedNewsItem, request: NewsSearchRequest) -> int:
        score = 0
        searchable_text = " ".join(
            part.casefold()
            for part in (
                item.title,
                item.summary,
                item.source,
                item.domain or "",
                item.source_country or "",
            )
            if part
        )
        for term in malaysia_region_terms(request.region):
            lowered_term = term.casefold()
            if lowered_term in searchable_text:
                score += 3 if lowered_term != MALAYSIA_CANONICAL.casefold() else 1
        if item.source_country and item.source_country.casefold() == MALAYSIA_CANONICAL.casefold():
            score += 4
        if item.domain and item.domain.casefold().endswith(".my"):
            score += 3
        if request.crop.casefold() in searchable_text:
            score += 2
        if any(
            token in searchable_text
            for token in (
                "global",
                "international",
                "asean",
                "export",
                "import",
                "trade",
                "commodity",
                "market",
                "price",
                "shipping",
                "supply chain",
            )
        ):
            score += 2
        if any(tag.startswith("region:") or tag.startswith("country:") for tag in item.event_tags):
            score += 1
        return score


class CompositeNewsClient:
    def __init__(self, primary: GDELTNewsClient, fallback: Optional[FirecrawlNewsClient] = None) -> None:
        self.primary = primary
        self.fallback = fallback

    async def search(self, request: NewsSearchRequest) -> NewsSearchResponse:
        try:
            response = await self.primary.search(request)
            if response.items:
                return response
        except NewsClientError:
            pass

        if self.fallback:
            return await self.fallback.search(request)
        
        # Final fallback if both fail or primary returned nothing
        return NewsSearchResponse(
            source="empty_fallback",
            query=request.crop,
            requested_at=datetime.now(UTC),
            items=[],
        )


class FirecrawlNewsClient:
    def __init__(self, firecrawl_client: Optional["FirecrawlClient"] = None) -> None:
        from app.clients.firecrawl import FirecrawlClient
        self.client = firecrawl_client or FirecrawlClient()

    async def search(self, request: NewsSearchRequest) -> NewsSearchResponse:
        query = f"recent agricultural news about {request.crop} in {request.region} Malaysia"
        try:
            search_results = await self.client.search(query, limit=request.max_items)
            items: list[NormalizedNewsItem] = []
            
            # Firecrawl returns results in "data" or "results"
            data = search_results.get("data") or search_results.get("results") or []
            
            for entry in data:
                url = entry.get("url") or entry.get("link")
                if not url:
                    continue
                
                items.append(
                    NormalizedNewsItem(
                        title=entry.get("title") or entry.get("metadata", {}).get("title") or "News Item",
                        url=url,
                        source=entry.get("metadata", {}).get("source") or "web",
                        domain=None,
                        summary=entry.get("description") or entry.get("snippet") or entry.get("markdown", "")[:200],
                        published_at=datetime.now(UTC), # Firecrawl doesn't always give us reliable dates
                        language="en",
                        source_country=MALAYSIA_CANONICAL,
                        crop=request.crop,
                        region=request.region,
                        event_tags=(),
                        raw=entry,
                    )
                )
            
            return NewsSearchResponse(
                source="firecrawl_news",
                query=query,
                requested_at=datetime.now(UTC),
                items=items,
            )
        except Exception as exc:
            raise NewsClientError(f"Firecrawl news lookup failed: {exc}") from exc


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).split(",")[0])
    except (TypeError, ValueError):
        return None


def _dedupe_terms(terms: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(term)
    return result


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    for pattern in ("%Y%m%d%H%M%S", "%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(value, pattern)
            return parsed.replace(tzinfo=parsed.tzinfo or UTC)
        except ValueError:
            continue
    return None


def _slugify(value: str) -> str:
    chars = [char.lower() if char.isalnum() else "_" for char in value.strip()]
    slug = "".join(chars).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "unknown"


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


__all__ = [
    "CompositeNewsClient",
    "FirecrawlNewsClient",
    "GDELTNewsClient",
    "GDELT_DOC_API_URL",
    "NewsClientError",
    "NewsSearchRequest",
    "NewsSearchResponse",
    "NormalizedNewsItem",
]
