"""Protocol for retrieving enriched video thumbnail URLs."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class VideoThumbnailRepository(Protocol):
    """Interface for thumbnail lookups keyed by canonical X post URL."""

    async def fetch_video_thumbnails(self, canonical_url: str) -> list[str]:
        """Fetch ordered video thumbnail URLs for a post."""
        ...
