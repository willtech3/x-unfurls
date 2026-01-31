"""Protocol for X post data fetching."""

from enum import Enum
from typing import Protocol, runtime_checkable

from xunfurls.domain.entities import XPostSnapshot, XStatusRef


class FetchMode(Enum):
    """Controls cost/latency tradeoff for fetching."""

    FAST = "fast"  # Post + minimal metrics
    RICH = "rich"  # Post + media + metrics + top replies
    SUMMARY_ONLY = "summary"  # Use cached thread + generate summary


@runtime_checkable
class XRepository(Protocol):
    """Interface for fetching X post data via xAI."""

    async def fetch_post_snapshot(self, status_ref: XStatusRef, mode: FetchMode) -> XPostSnapshot:
        """Fetch post snapshot from X via xAI.

        Args:
            status_ref: Reference to the X post
            mode: Fetch mode controlling what data to retrieve

        Returns:
            Complete post snapshot with requested data
        """
        ...
