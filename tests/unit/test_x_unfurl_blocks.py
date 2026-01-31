"""Tests for XUnfurlBlocksBuilder."""

from datetime import datetime

import pytest

from xunfurls.application.presenters.x_unfurl_blocks import XUnfurlBlocksBuilder
from xunfurls.domain.entities import XMedia, XMetrics, XPostSnapshot, XReply


@pytest.fixture
def builder() -> XUnfurlBlocksBuilder:
    """Create a blocks builder instance."""
    return XUnfurlBlocksBuilder()


@pytest.fixture
def sample_snapshot() -> XPostSnapshot:
    """Create a sample post snapshot."""
    return XPostSnapshot(
        author_name="John Doe",
        author_handle="johndoe",
        author_avatar_url="https://example.com/avatar.jpg",
        verified=True,
        created_at=datetime(2024, 1, 15, 12, 30),
        text="This is a test post with @channel mention",
        media=[
            XMedia(
                type="image",
                url="https://example.com/image.jpg",
                alt_text="Test image",
            )
        ],
        metrics=XMetrics(likes=100, reposts=50, replies=25, views=1000),
        top_replies=[
            XReply(
                author_name="Jane Smith",
                author_handle="janesmith",
                text="Great post!",
                verified=False,
            )
        ],
        summary="A test post about testing.",
    )


def test_build_unfurl_blocks_basic(
    builder: XUnfurlBlocksBuilder, sample_snapshot: XPostSnapshot
) -> None:
    """Test building basic unfurl blocks."""
    blocks = builder.build_unfurl_blocks(sample_snapshot, "https://x.com/johndoe/status/123")

    assert len(blocks) > 0
    # Should have context, section, image, metrics, divider, reply, summary, actions
    assert any(block["type"] == "context" for block in blocks)
    assert any(block["type"] == "section" for block in blocks)
    assert any(block["type"] == "image" for block in blocks)
    assert any(block["type"] == "divider" for block in blocks)
    assert any(block["type"] == "actions" for block in blocks)


def test_sanitize_text(builder: XUnfurlBlocksBuilder) -> None:
    """Test text sanitization."""
    text = "@channel @here @everyone normal text"
    sanitized = builder._sanitize_text(text)

    # Should contain zero-width space to prevent mentions
    assert "@\u200bchannel" in sanitized
    assert "@\u200bhere" in sanitized
    assert "@\u200beveryone" in sanitized


def test_truncate_text(builder: XUnfurlBlocksBuilder) -> None:
    """Test text truncation."""
    long_text = "a" * 100
    truncated = builder._truncate(long_text, 50)

    assert len(truncated) == 50
    assert truncated.endswith("...")


def test_format_number(builder: XUnfurlBlocksBuilder) -> None:
    """Test number formatting."""
    assert builder._format_number(500) == "500"
    assert builder._format_number(1500) == "1.5K"
    assert builder._format_number(1500000) == "1.5M"


def test_build_unfurl_blocks_with_summary(
    builder: XUnfurlBlocksBuilder, sample_snapshot: XPostSnapshot
) -> None:
    """Test building blocks with Grok summary."""
    blocks = builder.build_unfurl_blocks(sample_snapshot, "https://x.com/johndoe/status/123")

    # Should include summary context block
    summary_blocks = [b for b in blocks if b.get("type") == "context"]
    summary_text = "\n".join(
        str(elem.get("text", "")) for block in summary_blocks for elem in block.get("elements", [])
    )
    assert "Grok summary" in summary_text
