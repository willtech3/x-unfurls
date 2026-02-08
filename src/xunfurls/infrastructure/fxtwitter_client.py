"""FxTwitter client for fetching reliable video thumbnail URLs."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_STATUS_PATH_RE = re.compile(r"^/([^/]+)/status/(\d+)")

API_BASE = "https://api.fxtwitter.com"


class FxTwitterClient:
    """Lightweight client that fetches video thumbnail URLs from the FxTwitter API."""

    def __init__(self, timeout: float = 5.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=API_BASE,
            timeout=timeout,
            follow_redirects=True,
        )

    async def fetch_video_thumbnails(self, canonical_url: str) -> list[str]:
        """Return ordered list of video thumbnail URLs for a post.

        Parses the handle and status ID from the canonical URL, calls the
        FxTwitter API, and extracts ``tweet.media.videos[].thumbnail_url``.

        Returns an empty list on any failure (network, parsing, missing data).
        """
        parsed = _parse_status_url(canonical_url)
        if parsed is None:
            return []

        handle, status_id = parsed
        try:
            resp = await self._client.get(f"/{handle}/status/{status_id}")
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.debug("FxTwitter request failed for %s", canonical_url, exc_info=True)
            return []

        return _extract_video_thumbnails(data)

    async def close(self) -> None:
        await self._client.aclose()


def _parse_status_url(url: str) -> tuple[str, str] | None:
    """Extract (handle, status_id) from an X/Twitter URL."""
    parsed = urlparse(url)
    if parsed.hostname not in ("x.com", "twitter.com", "www.x.com", "www.twitter.com"):
        return None
    m = _STATUS_PATH_RE.match(parsed.path)
    if m is None:
        return None
    return m.group(1), m.group(2)


def _extract_video_thumbnails(data: dict) -> list[str]:
    """Walk the FxTwitter response and return video thumbnail URLs."""
    try:
        videos = data["tweet"]["media"]["videos"]
    except (KeyError, TypeError):
        return []

    thumbnails: list[str] = []
    for video in videos:
        thumb = video.get("thumbnail_url")
        if isinstance(thumb, str) and thumb:
            thumbnails.append(thumb)
    return thumbnails
