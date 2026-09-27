"""
Tavily web search adapter. Server-side credential (not BYOK): search is a shared service for the
whole app, independent of each user's Gemini quota — unlike Gemini's own Search grounding, a user's
free-tier Gemini quota being exhausted no longer takes web search down with it.
"""
import logging
from dataclasses import dataclass

import aiohttp

from src.shared.utils.errors import ProviderError

logger = logging.getLogger(__name__)


@dataclass
class SearchHit:
    title: str
    url: str
    content: str


class TavilyAdapter:
    """Adapter for the Tavily Search REST API (https://docs.tavily.com)."""

    BASE_URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str, timeout: int = 15):
        self.api_key = api_key
        self.timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        if not self.api_key:
            raise ProviderError("Web search is not configured on this server.")

        payload = {
            "query": query,
            "max_results": max(1, min(max_results, 10)),
            "search_depth": "basic",
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.BASE_URL,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as response:
                    body = await response.json()
                    if response.status != 200:
                        message = body.get("detail") or body.get("error") or response.reason
                        logger.error(f"Tavily search error {response.status}: {message}")
                        raise ProviderError(f"Web search failed: {message}")
                    return [
                        SearchHit(
                            title=item.get("title") or item.get("url", ""),
                            url=item["url"],
                            content=(item.get("content") or "")[:1500],
                        )
                        for item in body.get("results", [])
                        if item.get("url")
                    ]
        except aiohttp.ClientError as e:
            logger.error(f"HTTP error calling Tavily: {e}")
            raise ProviderError("Web search is temporarily unavailable.") from e

    async def health_check(self) -> dict:
        if not self.api_key:
            return {"status": "unhealthy", "message": "API key not configured"}
        try:
            await self.search("test", max_results=1)
            return {"status": "healthy"}
        except ProviderError as e:
            return {"status": "unhealthy", "message": e.message}
