"""Domain entities for X post data."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class XStatusRef:
    """Reference to an X post."""

    original_url: str
    canonical_url: str
    status_id: str
    author_handle_hint: str | None = None


@dataclass
class XMedia:
    """Media attachment on an X post."""

    type: str  # "image" | "video" | "gif"
    url: str
    thumbnail_url: str | None = None
    alt_text: str | None = None


@dataclass
class XMetrics:
    """Engagement metrics for an X post."""

    likes: int = 0
    reposts: int = 0
    replies: int = 0
    views: int | None = None
    bookmarks: int | None = None


@dataclass
class XReply:
    """A reply to an X post."""

    author_name: str
    author_handle: str
    text: str
    verified: bool = False


@dataclass
class XPostSnapshot:
    """Snapshot of an X post with all relevant data."""

    author_name: str
    author_handle: str
    author_avatar_url: str | None
    verified: bool
    created_at: datetime
    text: str
    media: list[XMedia]
    metrics: XMetrics
    top_replies: list[XReply]
    summary: str | None = None
