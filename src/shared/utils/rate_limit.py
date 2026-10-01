"""
In-memory sliding-window rate limiter. Good enough for the single-process API on the droplet; with several
workers each one would count on its own (limits would be N times looser, never stricter).
"""
import time
from collections import deque
from typing import Optional

from fastapi import Request

from .errors import RateLimitedError


class RateLimiter:
    """At most `limit` hits per `window_seconds` for each key."""

    def __init__(self, limit: int, window_seconds: float, max_keys: int = 10_000):
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            return deque()
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if not hits:
            del self._hits[key]
        return hits

    def retry_after(self, key: str) -> Optional[int]:
        """Seconds until `key` may try again, or None when it is under the limit."""
        now = time.monotonic()
        hits = self._prune(key, now)
        if len(hits) < self.limit:
            return None
        return max(1, int(hits[0] + self.window - now) + 1)

    def hit(self, key: str) -> None:
        now = time.monotonic()
        self._prune(key, now)
        if key not in self._hits and len(self._hits) >= self.max_keys:
            self._evict(now)
        self._hits.setdefault(key, deque()).append(now)

    def check_and_hit(self, key: str) -> None:
        """Record a hit, raising RateLimitedError instead when the key is already at the limit."""
        retry_after = self.retry_after(key)
        if retry_after is not None:
            raise RateLimitedError(retry_after)
        self.hit(key)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def _evict(self, now: float) -> None:
        for key in list(self._hits):
            self._prune(key, now)
        while len(self._hits) >= self.max_keys:  # still full: drop the stalest keys
            self._hits.pop(next(iter(self._hits)))


def client_ip(request: Request) -> str:
    """The caller's IP. Behind Caddy this is the real client, since uvicorn runs with --proxy-headers."""
    return request.client.host if request.client else "unknown"
