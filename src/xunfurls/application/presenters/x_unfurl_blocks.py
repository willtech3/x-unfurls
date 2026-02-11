"""Deterministic Slack block builder for X unfurls.

Builds visually rich Slack Block Kit messages from X post snapshots.
Uses header, section, context, image, divider, and actions blocks
wrapped in a colored attachment for a polished layout.
"""

import re
from datetime import UTC, datetime
from typing import Any

from xunfurls.domain.entities import XMetrics, XParentPost, XPostSnapshot


class XUnfurlBlocksBuilder:
    """Builds Slack blocks from X post snapshots."""

    # X brand blue — used as the attachment left-bar accent color
    ACCENT_COLOR = "#1D9BF0"

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

        # ── 1. Bold header: 𝕏  Name  ✓ ─────────────────────────────
        badge = "  ✓" if snapshot.verified else ""
        blocks.append(
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"𝕏  {snapshot.author_name}{badge}",
                    "emoji": True,
                },
            }
        )

        # ── 2. Author context: avatar + @handle · time ─────────────
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
        author_elements.append({"type": "mrkdwn", "text": f"*@{handle}*  ·  {time_str}"})
        blocks.append({"type": "context", "elements": author_elements})

        # ── 2b. Parent post context (for replies) ────────────────
        if snapshot.parent_post is not None:
            blocks.append(self._build_parent_post_block(snapshot.parent_post))

        # ── 3. Post text ────────────────────────────────────────────
        sanitized_text = self._sanitize_text(snapshot.text)
        if sanitized_text.strip():
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": sanitized_text}})

        # ── 4. Media ────────────────────────────────────────────────
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
                if self._is_valid_image_url(media.thumbnail_url):
                    blocks.append(
                        {
                            "type": "image",
                            "image_url": media.thumbnail_url,
                            "alt_text": media.alt_text or "Video thumbnail",
                        }
                    )
                blocks.append(
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": "▶️ *Video* — tap to watch on X"}],
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

        # ── 5. Metrics (compact with real emoji) ────────────────────
        metrics_line = self._build_metrics_line(snapshot.metrics)
        if metrics_line:
            blocks.append(
                {"type": "context", "elements": [{"type": "mrkdwn", "text": metrics_line}]}
            )

        # ── 6. Top replies ──────────────────────────────────────────
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
                                    f"💬 *{reply.author_name}*{badge}  @{reply_handle}"
                                    f"\n› {reply_text}"
                                ),
                            }
                        ],
                    }
                )

        # ── 7. Grok summary ────────────────────────────────────────
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

        # ── 8. Actions ─────────────────────────────────────────────
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
                    "style": "primary",
                }
            )
        blocks.append({"type": "actions", "elements": action_elements})

        # ── 9. Footer ──────────────────────────────────────────────
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "✦ Powered by Grok  ·  x.ai"},
                ],
            }
        )

        return blocks

    # ── Helpers ────────────────────────────────────────────────────────

    def _build_metrics_line(self, metrics: XMetrics) -> str:
        """Build a compact single-line metrics string.

        Emoji-only, no text labels — keeps it compact on mobile.
        Order matches Twitter's native UI: replies → reposts → likes → views.

        Returns an empty string when all metrics are zero/None so the
        caller can skip the block entirely.
        """
        parts: list[str] = []
        if metrics.replies:
            parts.append(f"💬 *{self._format_number(metrics.replies)}*")
        if metrics.reposts:
            parts.append(f"🔁 *{self._format_number(metrics.reposts)}*")
        if metrics.likes:
            parts.append(f"💚 *{self._format_number(metrics.likes)}*")
        if metrics.views:
            parts.append(f"👁️ *{self._format_number(metrics.views)}*")
        return "  ·  ".join(parts)

    _PARENT_TEXT_MAX = 280

    def _build_parent_post_block(self, parent: XParentPost) -> dict[str, Any]:
        """Build a rich_text block with a block-quote for the parent post."""
        handle = self._clean_handle(parent.author_handle)
        text = self._truncate(self._sanitize_text(parent.text), self._PARENT_TEXT_MAX)
        return {
            "type": "rich_text",
            "elements": [
                {
                    "type": "rich_text_quote",
                    "elements": [
                        {"type": "text", "text": parent.author_name, "style": {"bold": True}},
                        {"type": "text", "text": f"  @{handle}\n"},
                        {"type": "text", "text": text},
                    ],
                }
            ],
        }

    _VIDEO_EXTENSIONS = (".mp4", ".m3u8", ".webm", ".mov", ".avi")

    def _is_valid_url(self, url: str | None) -> bool:
        """Check if a URL is non-empty and uses http(s)."""
        return url is not None and url.startswith(("http://", "https://"))

    def _is_valid_image_url(self, url: str | None) -> bool:
        """Check if a URL is valid and points to an image (not a video).

        Rejects URLs ending with video file extensions.
        """
        if not self._is_valid_url(url):
            return False
        assert url is not None  # narrowed by _is_valid_url
        path = url.split("?")[0].lower()
        return not path.endswith(self._VIDEO_EXTENSIONS)

    def _clean_handle(self, handle: str) -> str:
        """Strip leading @ from handle if xAI included it."""
        return handle.lstrip("@")

    # Pattern for Slack special mentions: <@U123>, <!subteam^S123>, <#C123>
    _SLACK_MENTION_RE = re.compile(r"<([@!#])")

    def _sanitize_text(self, text: str) -> str:
        """Sanitize text to prevent Slack mention spam.

        Handles broadcast mentions (@channel/@here/@everyone) and
        targeted mentions (<@USER_ID>, <!subteam^ID>, <#CHANNEL>).
        """
        text = text.replace("@channel", "@\u200bchannel")
        text = text.replace("@here", "@\u200bhere")
        text = text.replace("@everyone", "@\u200beveryone")
        # Break <@U…>, <!subteam…>, <#C…> patterns
        text = self._SLACK_MENTION_RE.sub("<\u200b\\1", text)
        return self._truncate(text, 3000)

    def _truncate(self, text: str, max_length: int) -> str:
        """Truncate text with ellipsis."""
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."

    def _format_timestamp(self, dt: datetime) -> str:
        """Format timestamp using Slack's native date formatting.

        Uses <!date^{unix_ts}^{format}|fallback> syntax which auto-updates
        and respects the viewer's timezone.
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        unix_ts = int(dt.timestamp())
        fallback = dt.strftime("%b %d, %Y")
        return f"<!date^{unix_ts}^{{date_short_pretty}} at {{time}}|{fallback}>"

    def _format_number(self, n: int) -> str:
        """Format large numbers (e.g., 1.2K, 3.4M)."""
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)
