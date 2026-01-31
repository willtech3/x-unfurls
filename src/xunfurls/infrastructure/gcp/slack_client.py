"""Slack API client implementation."""

import logging
import os
from typing import Any

import httpx

from shared.domain.repositories.slack_repository import SlackUnfurlRepository
from shared.infrastructure.logging import log_event

logger = logging.getLogger(__name__)


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

        response = await self._client.post("/chat.unfurl", json=payload)
        response.raise_for_status()

        data = response.json()
        if not data.get("ok"):
            error = data.get("error", "unknown_error")
            log_event(
                logger,
                logging.ERROR,
                "Slack API error",
                event="slack_api_error",
                error=error,
                channel=channel_id,
                ts=message_ts,
            )
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

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
