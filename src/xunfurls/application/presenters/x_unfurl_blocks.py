"""Deterministic Slack block builder for X unfurls."""

from typing import Any

from xunfurls.domain.entities import XPostSnapshot


class XUnfurlBlocksBuilder:
    """Builds Slack blocks from X post snapshots."""

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

        # 1. Context: Author info + timestamp
        author_text = f"*{snapshot.author_name}* (@{snapshot.author_handle})"
        if snapshot.verified:
            author_text += " ✓"
        author_text += f" • {snapshot.created_at.strftime('%b %d, %Y')}"

        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": author_text}]})

        # 2. Section: Post text (sanitized)
        sanitized_text = self._sanitize_text(snapshot.text)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": sanitized_text}})

        # 3. Media: Images (up to 4)
        for media in snapshot.media[:4]:
            if media.type == "image":
                blocks.append(
                    {
                        "type": "image",
                        "image_url": media.url,
                        "alt_text": media.alt_text or "Image from X post",
                    }
                )

        # 4. Context: Metrics
        metrics = snapshot.metrics
        metrics_parts = []
        if metrics.replies:
            metrics_parts.append(f"💬 {self._format_number(metrics.replies)}")
        if metrics.reposts:
            metrics_parts.append(f"🔁 {self._format_number(metrics.reposts)}")
        if metrics.likes:
            metrics_parts.append(f"❤️ {self._format_number(metrics.likes)}")
        if metrics.views:
            metrics_parts.append(f"👁 {self._format_number(metrics.views)}")

        if metrics_parts:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": " • ".join(metrics_parts)}],
                }
            )

        # 5. Divider before replies
        if snapshot.top_replies:
            blocks.append({"type": "divider"})

        # 6. Top replies (up to 3)
        for reply in snapshot.top_replies[:3]:
            reply_text = f"*{reply.author_name}* (@{reply.author_handle})"
            if reply.verified:
                reply_text += " ✓"
            reply_text += f": {self._truncate(reply.text, 200)}"
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": reply_text}})

        # 7. Grok summary (if present)
        if snapshot.summary:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"🤖 *Grok summary:* {snapshot.summary}"}
                    ],
                }
            )

        # 8. Actions: Open in X button
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open in X"},
                        "url": canonical_url,
                        "action_id": "x_unfurl_open",
                    }
                ],
            }
        )

        return blocks

    def _sanitize_text(self, text: str) -> str:
        """Sanitize text to prevent Slack mention spam.

        Args:
            text: Raw text from X post

        Returns:
            Sanitized text safe for Slack
        """
        # Escape @channel, @here, @everyone with zero-width space
        text = text.replace("@channel", "@\u200bchannel")
        text = text.replace("@here", "@\u200bhere")
        text = text.replace("@everyone", "@\u200beveryone")
        # Truncate
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
