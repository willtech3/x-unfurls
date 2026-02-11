"""Slack API client implementation."""

import json
import logging
import os
from typing import Any

import httpx

from shared.domain.repositories.slack_repository import SlackUnfurlRepository
from shared.infrastructure.logging import log_event
from shared.infrastructure.observability import get_tracer

logger = logging.getLogger(__name__)

# Slack API errors that indicate a bad request (won't succeed on retry)
_PERMANENT_SLACK_ERRORS = frozenset(
    {
        "invalid_blocks",
        "invalid_attachments",
        "channel_not_found",
        "not_in_channel",
        "invalid_auth",
        "no_text",
        "too_many_attachments",
        "invalid_arguments",
    }
)


class SlackHttpClient(SlackUnfurlRepository):
    """HTTP client for Slack Web API."""

    def __init__(self, bot_token: str | None = None) -> None:
        """Initialize Slack client.

        Args:
            bot_token: Slack bot token (xoxb-...)
        """
        self.bot_token = bot_token or os.environ["SLACK_BOT_TOKEN"]
        self._client = httpx.AsyncClient(
            base_url="https://slack.com/api",
            headers={"Authorization": f"Bearer {self.bot_token}"},
            timeout=30.0,
        )

    async def unfurl_links(
        self, channel_id: str, message_ts: str, unfurls: dict[str, dict[str, Any]]
    ) -> None:
        """Attach unfurls to a message using chat.unfurl.

        Args:
            channel_id: Channel containing the message
            message_ts: Timestamp of the message
            unfurls: Mapping of URL to unfurl content (blocks)
        """
        payload = {"channel": channel_id, "ts": message_ts, "unfurls": unfurls}

        tracer = get_tracer()
        with tracer.start_as_current_span(
            "slack_unfurl_links", attributes={"slack.channel": channel_id}
        ):
            response = await self._client.post("/chat.unfurl", json=payload)
        response.raise_for_status()

        data = response.json()
        if not data.get("ok"):
            error = data.get("error", "unknown_error")
            resp_meta = data.get("response_metadata", {})
            log_event(
                logger,
                logging.ERROR,
                "Slack API error",
                event="slack_api_error",
                error=error,
                channel=channel_id,
                ts=message_ts,
                response_metadata=json.dumps(resp_meta) if resp_meta else None,
                unfurls_json=json.dumps(unfurls)[:2000],
            )
            if error in _PERMANENT_SLACK_ERRORS:
                raise ValueError(f"Slack API error (permanent): {error}")
            raise RuntimeError(f"Slack API error: {error}")

        log_event(
            logger,
            logging.INFO,
            "Successfully unfurled links",
            event="unfurl_success",
            channel=channel_id,
            ts=message_ts,
            url_count=len(unfurls),
        )

    async def post_message(
        self,
        channel_id: str,
        blocks: list[dict[str, Any]],
        text: str = "",
        thread_ts: str = "",
        color: str = "",
    ) -> str:
        """Post a message with blocks to a channel using chat.postMessage.

        When ``color`` is provided, blocks are wrapped inside a Slack
        attachment with a colored left-bar accent.

        Args:
            channel_id: Channel to post to
            blocks: Slack Block Kit blocks
            text: Fallback text for notifications
            thread_ts: If set, posts as a threaded reply to this message
            color: Hex color for attachment left-bar (e.g. "#1D9BF0")

        Returns:
            The message timestamp (ts) of the posted message
        """
        payload: dict[str, Any] = {
            "channel": channel_id,
            "text": text or "X post preview",
            "unfurl_links": False,
            "unfurl_media": False,
        }
        if color:
            payload["attachments"] = [{"color": color, "blocks": blocks}]
        else:
            payload["blocks"] = blocks
        if thread_ts:
            payload["thread_ts"] = thread_ts

        tracer = get_tracer()
        with tracer.start_as_current_span(
            "slack_post_message", attributes={"slack.channel": channel_id}
        ):
            response = await self._client.post("/chat.postMessage", json=payload)
            response.raise_for_status()

        data = response.json()
        if not data.get("ok"):
            error = data.get("error", "unknown_error")
            resp_meta = data.get("response_metadata", {})
            log_event(
                logger,
                logging.ERROR,
                "Slack API error",
                event="slack_post_message_error",
                error=error,
                channel=channel_id,
                response_metadata=json.dumps(resp_meta) if resp_meta else None,
                blocks_json=json.dumps(blocks)[:2000],
            )
            if error in _PERMANENT_SLACK_ERRORS:
                raise ValueError(f"Slack API error (permanent): {error}")
            raise RuntimeError(f"Slack API error: {error}")

        msg_ts: str = data.get("ts", "")
        log_event(
            logger,
            logging.INFO,
            "Successfully posted message",
            event="post_message_success",
            channel=channel_id,
            thread_ts=thread_ts or None,
        )
        return msg_ts

    async def open_modal(self, trigger_id: str, view: dict[str, Any]) -> None:
        """Open a Slack modal using a trigger ID.

        Args:
            trigger_id: Trigger ID from an interactive event (valid for 3s)
            view: Modal view definition
        """
        payload = {"trigger_id": trigger_id, "view": view}

        response = await self._client.post("/views.open", json=payload)
        response.raise_for_status()

        data = response.json()
        if not data.get("ok"):
            error = data.get("error", "unknown_error")
            log_event(
                logger,
                logging.ERROR,
                "Failed to open modal",
                event="modal_open_error",
                error=error,
            )
            raise RuntimeError(f"Slack views.open error: {error}")

        log_event(logger, logging.INFO, "Opened modal", event="modal_opened")

    async def post_ephemeral(
        self, channel_id: str, user_id: str, text: str, thread_ts: str = ""
    ) -> None:
        """Post an ephemeral message visible only to one user.

        Args:
            channel_id: Channel to post in
            user_id: User who will see the message
            text: Message text
            thread_ts: If set, posts in a thread
        """
        payload: dict[str, Any] = {
            "channel": channel_id,
            "user": user_id,
            "text": text,
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts

        response = await self._client.post("/chat.postEphemeral", json=payload)
        response.raise_for_status()

        data = response.json()
        if not data.get("ok"):
            logger.warning("Ephemeral message failed: %s", data.get("error", "unknown_error"))

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
