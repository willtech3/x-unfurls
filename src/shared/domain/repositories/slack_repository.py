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

    async def post_message(
        self,
        channel_id: str,
        blocks: list[dict[str, Any]],
        text: str = "",
        thread_ts: str = "",
    ) -> str:
        """Post a message with blocks to a channel.

        Args:
            channel_id: Channel to post to
            blocks: Slack Block Kit blocks
            text: Fallback text for notifications
            thread_ts: If set, posts as a threaded reply to this message

        Returns:
            The message timestamp (ts) of the posted message
        """
        ...

    async def open_modal(self, trigger_id: str, view: dict[str, Any]) -> None:
        """Open a Slack modal using a trigger ID.

        Args:
            trigger_id: Trigger ID from an interactive event (valid for 3s)
            view: Modal view definition
        """
        ...
