import httpx
from typing import Any, Optional
from app.core.config import settings

class FirecrawlClientError(Exception):
    """Base error for Firecrawl client failures."""

class FirecrawlClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or settings.firecrawl_api_key
        self.base_url = base_url or settings.firecrawl_api_url
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def scrape_url(self, url: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Scrape a single URL."""
        endpoint = f"{self.base_url.rstrip('/')}/scrape"
        payload = {"url": url}
        if params:
            payload.update(params)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    endpoint,
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise FirecrawlClientError(f"Firecrawl scrape failed: {exc}") from exc

    async def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Search for content using Firecrawl."""
        # Note: Local Firecrawl may use /search or /map depending on version.
        # Cloud uses /search.
        endpoint = f"{self.base_url.rstrip('/')}/search"
        payload = {"query": query, "limit": limit}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    endpoint,
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            # Fallback to /map if /search fails (some local versions use /map)
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
                return await self._map_fallback(query, limit)
            raise FirecrawlClientError(f"Firecrawl search failed: {exc}") from exc

    async def _map_fallback(self, query: str, limit: int = 5) -> dict[str, Any]:
        endpoint = f"{self.base_url.rstrip('/')}/map"
        payload = {"search": query, "limit": limit}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    endpoint,
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
             raise FirecrawlClientError(f"Firecrawl search/map fallback failed: {exc}") from exc
