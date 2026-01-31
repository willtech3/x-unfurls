"""Protocol definitions for Slack repository interfaces."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SlackUnfurlRepository(Protocol):
    """Protocol for Slack unfurl operations."""

    async def unfurl_links(
        self, channel_id: str, message_ts: str, unfurls: dict[str, dict[str, Any]]
    ) -> None:
        """Attach unfurls to a message.

        Args:
            channel_id: Channel containing the message
            message_ts: Timestamp of the message
            unfurls: Mapping of URL to unfurl content (blocks)
        """
        ...
