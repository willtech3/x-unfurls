"""Deterministic Slack block builder for X unfurls.

Builds visually rich Slack Block Kit messages from X post snapshots.
Uses header, section (with fields), context, image, divider, and
actions blocks for a polished layout on both desktop and mobile.
"""

from datetime import UTC, datetime
from typing import Any

from xunfurls.domain.entities import XMetrics, XPostSnapshot


class XUnfurlBlocksBuilder:
    """Builds Slack blocks from X post snapshots."""

    # Slack client errors that will never succeed on retry
    PERMANENT_SLACK_ERRORS = frozenset(
        {"invalid_blocks", "channel_not_found", "not_in_channel", "invalid_auth", "no_text"}
    )

    def build_unfurl_blocks(
        self, snapshot: XPostSnapshot, canonical_url: str
    ) -> list[dict[str, Any]]:
        """Build Slack blocks for an X post unfurl.

        Deterministic rendering - no LLM-generated blocks.

        Args:
            snapshot: X post snapshot with all data
            canonical_url: Canonical URL for the post

        Returns:
            List of Slack block objects
        """
        blocks: list[dict[str, Any]] = []

        # ── 1. Header ──────────────────────────────────────────────────
        header_text = f"𝕏  {snapshot.author_name}"
        if snapshot.verified:
            header_text += "  ✓"
        blocks.append(
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": self._truncate(header_text, 150),
                    "emoji": True,
                },
            }
        )

        # ── 2. Author context: avatar + handle + timestamp ────────────
        handle = self._clean_handle(snapshot.author_handle)
        time_str = self._format_timestamp(snapshot.created_at)

        author_elements: list[dict[str, Any]] = []
        if self._is_valid_url(snapshot.author_avatar_url):
            author_elements.append(
                {
                    "type": "image",
                    "image_url": snapshot.author_avatar_url,
                    "alt_text": f"{snapshot.author_name} avatar",
                }
            )
        author_elements.append({"type": "mrkdwn", "text": f"@{handle}  ·  {time_str}"})
        blocks.append({"type": "context", "elements": author_elements})

        # ── 3. Post text ──────────────────────────────────────────────
        sanitized_text = self._sanitize_text(snapshot.text)
        if sanitized_text.strip():
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": sanitized_text}})

        # ── 4. Media ──────────────────────────────────────────────────
        for media in snapshot.media[:4]:
            if media.type == "image" and self._is_valid_url(media.url):
                blocks.append(
                    {
                        "type": "image",
                        "image_url": media.url,
                        "alt_text": media.alt_text or "Image from X post",
                    }
                )
            elif media.type == "video":
                thumb = media.thumbnail_url
                if self._is_valid_image_url(thumb):
                    blocks.append(
                        {
                            "type": "image",
                            "image_url": thumb,
                            "alt_text": media.alt_text or "Video thumbnail",
                        }
                    )
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": "▶️  *Video* — watch on X"}],
                    }
                )
            elif media.type == "gif" and self._is_valid_url(media.url):
                blocks.append(
                    {
                        "type": "image",
                        "image_url": media.url,
                        "alt_text": media.alt_text or "GIF from X post",
                    }
                )

        # ── 5. Metrics (2-column field grid) ──────────────────────────
        metrics_fields = self._build_metrics_fields(snapshot.metrics)
        if metrics_fields:
            blocks.append({"type": "section", "fields": metrics_fields})

        # ── 6. Top replies ────────────────────────────────────────────
        valid_replies = snapshot.top_replies[:3]
        if valid_replies:
            blocks.append({"type": "divider"})
            for reply in valid_replies:
                reply_handle = self._clean_handle(reply.author_handle)
                badge = " ✓" if reply.verified else ""
                reply_text = self._truncate(self._sanitize_text(reply.text), 200)
                blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": (
                                    f"💬  *{reply.author_name}*{badge}"
                                    f"  @{reply_handle}\n{reply_text}"
                                ),
                            }
                        ],
                    }
                )

        # ── 7. Grok summary ──────────────────────────────────────────
        if snapshot.summary:
            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"✦  *Grok*\n{snapshot.summary}",
                    },
                }
            )

        # ── 8. Actions ────────────────────────────────────────────────
        action_elements: list[dict[str, Any]] = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "View on 𝕏", "emoji": True},
                "url": canonical_url,
                "action_id": "x_unfurl_open",
            }
        ]
        if not snapshot.summary:
            action_elements.append(
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "✦ Ask Grok",
                        "emoji": True,
                    },
                    "action_id": "x_unfurl_ask_grok",
                    "value": canonical_url,
                }
            )
        blocks.append({"type": "actions", "elements": action_elements})

        # ── 9. Footer ─────────────────────────────────────────────────
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "Powered by Grok  ·  x.ai"},
                ],
            }
        )

        return blocks

    # ── Helpers ────────────────────────────────────────────────────────

    def _build_metrics_fields(self, metrics: XMetrics) -> list[dict[str, Any]]:
        """Build section fields for a 2-column metrics grid.

        Returns an empty list when all metrics are zero/None so the
        caller can skip the section block entirely.
        """
        fields: list[dict[str, Any]] = []
        if metrics.likes:
            fields.append(
                {"type": "mrkdwn", "text": f"❤️  *{self._format_number(metrics.likes)}*\nLikes"}
            )
        if metrics.reposts:
            fields.append(
                {"type": "mrkdwn", "text": f"🔄  *{self._format_number(metrics.reposts)}*\nReposts"}
            )
        if metrics.replies:
            fields.append(
                {"type": "mrkdwn", "text": f"💬  *{self._format_number(metrics.replies)}*\nReplies"}
            )
        if metrics.views:
            fields.append(
                {"type": "mrkdwn", "text": f"👁️  *{self._format_number(metrics.views)}*\nViews"}
            )
        return fields

    _VIDEO_EXTENSIONS = (".mp4", ".m3u8", ".webm", ".mov", ".avi")

    def _is_valid_url(self, url: str | None) -> bool:
        """Check if a URL is non-empty and uses http(s)."""
        return url is not None and url.startswith(("http://", "https://"))

    def _is_valid_image_url(self, url: str | None) -> bool:
        """Check if a URL is valid and points to an image (not a video)."""
        if not self._is_valid_url(url):
            return False
        assert url is not None  # narrowed by _is_valid_url
        path = url.split("?")[0].lower()
        return not path.endswith(self._VIDEO_EXTENSIONS)

    def _clean_handle(self, handle: str) -> str:
        """Strip leading @ from handle if xAI included it."""
        return handle.lstrip("@")

    def _sanitize_text(self, text: str) -> str:
        """Sanitize text to prevent Slack mention spam.

        Args:
            text: Raw text from X post

        Returns:
            Sanitized text safe for Slack
        """
        text = text.replace("@channel", "@\u200bchannel")
        text = text.replace("@here", "@\u200bhere")
        text = text.replace("@everyone", "@\u200beveryone")
        return self._truncate(text, 3000)

    def _truncate(self, text: str, max_length: int) -> str:
        """Truncate text with ellipsis.

        Args:
            text: Text to truncate
            max_length: Maximum length

        Returns:
            Truncated text
        """
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."

    def _format_timestamp(self, dt: datetime) -> str:
        """Format timestamp as relative for recent posts, absolute for older.

        Args:
            dt: Datetime to format

        Returns:
            Formatted time string
        """
        now = datetime.now(UTC)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        delta = now - dt
        seconds = int(delta.total_seconds())

        if seconds < 0:
            return dt.strftime("%b %d, %Y")
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} {'minute' if minutes == 1 else 'minutes'} ago"
        if seconds < 86400:
            hours = seconds // 3600
            return f"{hours} {'hour' if hours == 1 else 'hours'} ago"
        if seconds < 604800:  # 7 days
            days = seconds // 86400
            return f"{days} {'day' if days == 1 else 'days'} ago"
        return dt.strftime("%b %d, %Y")

    def _format_number(self, n: int) -> str:
        """Format large numbers (e.g., 1.2K, 3.4M).

        Args:
            n: Number to format

        Returns:
            Formatted number string
        """
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)
