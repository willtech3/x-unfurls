"""In-memory LRU caching decorator for XRepository.

Wraps any XRepository implementation with TTL-based caching.
Cache key is the status_id. SUMMARY_ONLY mode always bypasses cache
to ensure fresh AI-generated summaries.
"""

import time
from collections import OrderedDict

from xunfurls.domain.entities import XPostSnapshot, XStatusRef
from xunfurls.domain.repositories.x_repository import FetchMode


class CachingXRepository:
    """Decorator that adds in-memory LRU caching to an XRepository."""

    def __init__(
        self,
        inner: object,
        ttl_seconds: int = 3600,
        max_size: int = 100,
    ) -> None:
        self._inner = inner
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._cache: OrderedDict[str, tuple[float, XPostSnapshot]] = OrderedDict()

    async def fetch_post_snapshot(
        self, status_ref: XStatusRef, mode: FetchMode
    ) -> XPostSnapshot:
        """Fetch with caching. SUMMARY_ONLY bypasses cache."""
        key = status_ref.status_id

        # Always bypass cache for summary requests (fresh AI generation)
        if mode != FetchMode.SUMMARY_ONLY:
            cached = self._get(key)
            if cached is not None:
                return cached

        snapshot = await self._inner.fetch_post_snapshot(status_ref, mode)
        self._put(key, snapshot)
        return snapshot

    def _get(self, key: str) -> XPostSnapshot | None:
        if key not in self._cache:
            return None
        ts, snapshot = self._cache[key]
        if time.monotonic() - ts > self._ttl:
            del self._cache[key]
            return None
        # Move to end (most recently used)
        self._cache.move_to_end(key)
        return snapshot

    def _put(self, key: str, snapshot: XPostSnapshot) -> None:
        self._cache[key] = (time.monotonic(), snapshot)
        self._cache.move_to_end(key)
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
