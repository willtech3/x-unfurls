"""Tests for XUnfurlBlocksBuilder."""

from datetime import UTC, datetime

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


# ---------------------------------------------------------------------------
# Helper for concise snapshot creation in new tests
# ---------------------------------------------------------------------------


def _make_snapshot(**kw: object) -> XPostSnapshot:
    defaults = {
        "author_name": "Test User",
        "author_handle": "testuser",
        "author_avatar_url": None,
        "verified": False,
        "created_at": datetime(2024, 6, 1, 10, 0),
        "text": "Hello",
        "media": [],
        "metrics": XMetrics(),
        "top_replies": [],
        "summary": None,
    }
    defaults.update(kw)
    return XPostSnapshot(**defaults)


# ---------------------------------------------------------------------------
# Basic block structure
# ---------------------------------------------------------------------------


def test_build_unfurl_blocks_basic(
    builder: XUnfurlBlocksBuilder, sample_snapshot: XPostSnapshot
) -> None:
    """Test building basic unfurl blocks with all sections."""
    blocks = builder.build_unfurl_blocks(sample_snapshot, "https://x.com/johndoe/status/123")

    assert len(blocks) > 0
    block_types = [b["type"] for b in blocks]

    # Layout: context (author), section (text), image, context (metrics),
    # divider, context (reply), divider, section (summary), actions, context (footer)
    assert block_types[0] == "context"  # author line is first
    assert "section" in block_types
    assert "image" in block_types
    assert "divider" in block_types
    assert "actions" in block_types


def test_author_line_contains_name_and_handle(builder: XUnfurlBlocksBuilder) -> None:
    """Author context should contain name, badge, and handle."""
    snap = _make_snapshot(author_name="Elon Musk", author_handle="elonmusk", verified=True)
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    author = blocks[0]
    assert author["type"] == "context"
    text = author["elements"][-1]["text"]
    assert "Elon Musk" in text
    assert "✓" in text
    assert "@elonmusk" in text


def test_no_badge_when_unverified(builder: XUnfurlBlocksBuilder) -> None:
    snap = _make_snapshot(verified=False)
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    author = blocks[0]
    text = author["elements"][-1]["text"]
    assert "✓" not in text


def test_footer_present(builder: XUnfurlBlocksBuilder) -> None:
    """Footer should have Grok branding."""
    snap = _make_snapshot()
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    footer = blocks[-1]
    assert footer["type"] == "context"
    assert "Powered by Grok" in footer["elements"][0]["text"]


# ---------------------------------------------------------------------------
# Text handling
# ---------------------------------------------------------------------------


def test_sanitize_text(builder: XUnfurlBlocksBuilder) -> None:
    """Test text sanitization."""
    text = "@channel @here @everyone normal text"
    sanitized = builder._sanitize_text(text)
    assert "@\u200bchannel" in sanitized
    assert "@\u200bhere" in sanitized
    assert "@\u200beveryone" in sanitized


def test_truncate_text(builder: XUnfurlBlocksBuilder) -> None:
    """Test text truncation."""
    long_text = "a" * 100
    truncated = builder._truncate(long_text, 50)
    assert len(truncated) == 50
    assert truncated.endswith("...")


def test_empty_text_skips_section(builder: XUnfurlBlocksBuilder) -> None:
    """Posts with no text should not produce an empty section block."""
    snap = _make_snapshot(text="")
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    for b in blocks:
        if b["type"] == "section" and "text" in b:
            assert b["text"]["text"].strip() != ""


def test_whitespace_only_text_skips_section(builder: XUnfurlBlocksBuilder) -> None:
    """Posts with only whitespace should not produce a section block."""
    snap = _make_snapshot(text="   \n  ")
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    for b in blocks:
        if b["type"] == "section" and "text" in b:
            assert b["text"]["text"].strip() != ""


# ---------------------------------------------------------------------------
# Number formatting
# ---------------------------------------------------------------------------


def test_format_number(builder: XUnfurlBlocksBuilder) -> None:
    """Test number formatting."""
    assert builder._format_number(500) == "500"
    assert builder._format_number(1500) == "1.5K"
    assert builder._format_number(1500000) == "1.5M"


# ---------------------------------------------------------------------------
# Metrics rendering (compact single-line)
# ---------------------------------------------------------------------------


def test_metrics_rendered_as_compact_line(builder: XUnfurlBlocksBuilder) -> None:
    """Metrics should be rendered as a compact single-line context block."""
    snap = _make_snapshot(metrics=XMetrics(likes=100, reposts=50, replies=25, views=1000))
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    # Find the metrics context block (has ♡ symbol)
    metrics_blocks = [
        b
        for b in blocks
        if b["type"] == "context" and any("♡" in e.get("text", "") for e in b.get("elements", []))
    ]
    assert len(metrics_blocks) == 1
    text = metrics_blocks[0]["elements"][0]["text"]
    assert "♡" in text
    assert "↻" in text
    assert "↩" in text
    assert "◎" in text


def test_zero_metrics_omitted(builder: XUnfurlBlocksBuilder) -> None:
    """When all metrics are zero, no metrics block should appear."""
    snap = _make_snapshot(metrics=XMetrics(likes=0, reposts=0, replies=0, views=0))
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    metrics_blocks = [
        b
        for b in blocks
        if b["type"] == "context" and any("♡" in e.get("text", "") for e in b.get("elements", []))
    ]
    assert len(metrics_blocks) == 0


def test_partial_metrics_only_nonzero_shown(builder: XUnfurlBlocksBuilder) -> None:
    """Only non-zero metrics should appear in the line."""
    snap = _make_snapshot(metrics=XMetrics(likes=100, reposts=0, replies=0, views=0))
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    metrics_blocks = [
        b
        for b in blocks
        if b["type"] == "context" and any("♡" in e.get("text", "") for e in b.get("elements", []))
    ]
    assert len(metrics_blocks) == 1
    text = metrics_blocks[0]["elements"][0]["text"]
    assert "♡" in text
    assert "↻" not in text  # reposts should not appear


# ---------------------------------------------------------------------------
# Media handling
# ---------------------------------------------------------------------------


def test_video_media_shows_thumbnail(builder: XUnfurlBlocksBuilder) -> None:
    snap = _make_snapshot(
        media=[
            XMedia(
                type="video",
                url="https://x.co/v.mp4",
                thumbnail_url="https://x.co/thumb.jpg",
                alt_text="vid",
            )
        ]
    )
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    imgs = [b for b in blocks if b["type"] == "image"]
    assert len(imgs) == 1
    assert imgs[0]["image_url"] == "https://x.co/thumb.jpg"
    texts = [
        e.get("text", "") for b in blocks if b["type"] == "context" for e in b.get("elements", [])
    ]
    assert any("Video" in t for t in texts)


def test_video_without_thumbnail_skips_image_block(builder: XUnfurlBlocksBuilder) -> None:
    snap = _make_snapshot(
        media=[XMedia(type="video", url="https://x.co/video.mp4", thumbnail_url=None)]
    )
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    imgs = [b for b in blocks if b["type"] == "image"]
    assert len(imgs) == 0
    ctx = [
        b
        for b in blocks
        if b["type"] == "context"
        and any("Video" in e.get("text", "") for e in b.get("elements", []))
    ]
    assert len(ctx) == 1


def test_gif_media_rendered_as_image(builder: XUnfurlBlocksBuilder) -> None:
    snap = _make_snapshot(media=[XMedia(type="gif", url="https://x.co/funny.gif", alt_text="GIF")])
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    imgs = [b for b in blocks if b["type"] == "image"]
    assert len(imgs) == 1
    assert imgs[0]["image_url"] == "https://x.co/funny.gif"


def test_mixed_media_types_all_rendered(builder: XUnfurlBlocksBuilder) -> None:
    snap = _make_snapshot(
        media=[
            XMedia(type="image", url="https://x.co/i.jpg"),
            XMedia(type="video", url="https://x.co/v.mp4", thumbnail_url="https://x.co/vt.jpg"),
            XMedia(type="gif", url="https://x.co/g.gif"),
        ]
    )
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    img_urls = [b["image_url"] for b in blocks if b["type"] == "image"]
    assert "https://x.co/i.jpg" in img_urls
    assert "https://x.co/vt.jpg" in img_urls
    assert "https://x.co/g.gif" in img_urls


def test_invalid_media_url_skipped(builder: XUnfurlBlocksBuilder) -> None:
    """Media with empty or non-HTTP URLs should be silently skipped."""
    snap = _make_snapshot(
        media=[
            XMedia(type="image", url=""),
            XMedia(type="image", url="not-a-url"),
            XMedia(type="image", url="https://x.co/valid.jpg"),
        ]
    )
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    imgs = [b for b in blocks if b["type"] == "image"]
    assert len(imgs) == 1
    assert imgs[0]["image_url"] == "https://x.co/valid.jpg"


# ---------------------------------------------------------------------------
# Author avatar
# ---------------------------------------------------------------------------


def test_author_avatar_displayed(builder: XUnfurlBlocksBuilder) -> None:
    snap = _make_snapshot(author_avatar_url="https://x.co/avatar.jpg", author_name="Jane")
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    author_block = blocks[0]
    img_elems = [e for e in author_block["elements"] if e.get("type") == "image"]
    assert len(img_elems) == 1
    assert img_elems[0]["image_url"] == "https://x.co/avatar.jpg"
    assert img_elems[0]["alt_text"] == "Jane avatar"


def test_missing_avatar_no_image_element(builder: XUnfurlBlocksBuilder) -> None:
    snap = _make_snapshot(author_avatar_url=None)
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    author_block = blocks[0]
    img_elems = [e for e in author_block["elements"] if e.get("type") == "image"]
    assert len(img_elems) == 0


def test_invalid_avatar_url_no_image_element(builder: XUnfurlBlocksBuilder) -> None:
    """Invalid avatar URLs should not produce an image element."""
    snap = _make_snapshot(author_avatar_url="not-a-url")
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    author_block = blocks[0]
    img_elems = [e for e in author_block["elements"] if e.get("type") == "image"]
    assert len(img_elems) == 0


# ---------------------------------------------------------------------------
# Handle cleaning
# ---------------------------------------------------------------------------


def test_handle_at_prefix_stripped(builder: XUnfurlBlocksBuilder) -> None:
    """If xAI returns @handle with @ prefix, we should strip it."""
    snap = _make_snapshot(author_handle="@elonmusk")
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    author_block = blocks[0]
    author_text = [
        e.get("text", "") for e in author_block["elements"] if e.get("type") == "mrkdwn"
    ][0]
    assert "@elonmusk" in author_text
    assert "@@elonmusk" not in author_text


# ---------------------------------------------------------------------------
# Ask Grok button
# ---------------------------------------------------------------------------


def test_ask_grok_button_present_when_no_summary(builder: XUnfurlBlocksBuilder) -> None:
    """When summary is None, the actions block should include 'Ask Grok'."""
    snap = _make_snapshot(summary=None)
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/999")
    actions_blocks = [b for b in blocks if b["type"] == "actions"]
    assert len(actions_blocks) == 1
    buttons = actions_blocks[0]["elements"]
    action_ids = [btn["action_id"] for btn in buttons]
    assert "x_unfurl_open" in action_ids
    assert "x_unfurl_ask_grok" in action_ids


def test_ask_grok_button_absent_when_summary_present(builder: XUnfurlBlocksBuilder) -> None:
    """When summary is present, 'Ask Grok' button should NOT appear."""
    snap = _make_snapshot(summary="This is a Grok-generated summary.")
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/999")
    actions_blocks = [b for b in blocks if b["type"] == "actions"]
    assert len(actions_blocks) == 1
    buttons = actions_blocks[0]["elements"]
    action_ids = [btn["action_id"] for btn in buttons]
    assert "x_unfurl_open" in action_ids
    assert "x_unfurl_ask_grok" not in action_ids


def test_ask_grok_button_value_contains_canonical_url(builder: XUnfurlBlocksBuilder) -> None:
    """The ask grok button value should contain the canonical URL."""
    snap = _make_snapshot(summary=None)
    url = "https://x.com/testuser/status/42"
    blocks = builder.build_unfurl_blocks(snap, url)
    actions_blocks = [b for b in blocks if b["type"] == "actions"]
    ask_btn = [
        btn for btn in actions_blocks[0]["elements"] if btn["action_id"] == "x_unfurl_ask_grok"
    ][0]
    assert ask_btn["value"] == url


# ---------------------------------------------------------------------------
# Grok summary rendering
# ---------------------------------------------------------------------------


def test_build_unfurl_blocks_with_summary(
    builder: XUnfurlBlocksBuilder, sample_snapshot: XPostSnapshot
) -> None:
    """Test building blocks with Grok summary."""
    blocks = builder.build_unfurl_blocks(sample_snapshot, "https://x.com/johndoe/status/123")

    summary_sections = [
        b for b in blocks if b["type"] == "section" and "Grok" in b.get("text", {}).get("text", "")
    ]
    assert len(summary_sections) == 1
    assert "✦" in summary_sections[0]["text"]["text"]


# ---------------------------------------------------------------------------
# Replies rendering (context blocks)
# ---------------------------------------------------------------------------


def test_replies_rendered_as_context_blocks(builder: XUnfurlBlocksBuilder) -> None:
    """Replies should be rendered as compact context blocks."""
    snap = _make_snapshot(
        top_replies=[
            XReply(author_name="Alice", author_handle="alice", text="Great!", verified=True),
            XReply(author_name="Bob", author_handle="bob", text="Thanks!", verified=False),
        ]
    )
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")

    divider_idx = next(i for i, b in enumerate(blocks) if b["type"] == "divider")
    reply_blocks = [b for b in blocks[divider_idx + 1 :] if b["type"] == "context"]
    reply_blocks = [b for b in reply_blocks if "Powered by" not in b["elements"][0].get("text", "")]

    assert len(reply_blocks) == 2
    assert "Alice" in reply_blocks[0]["elements"][0]["text"]
    assert "✓" in reply_blocks[0]["elements"][0]["text"]
    assert "Bob" in reply_blocks[1]["elements"][0]["text"]
    assert "✓" not in reply_blocks[1]["elements"][0]["text"]


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


def test_recent_post_shows_relative_time(builder: XUnfurlBlocksBuilder) -> None:
    """Posts from minutes ago should show compact relative time."""
    from datetime import timedelta

    recent = datetime.now(UTC) - timedelta(minutes=5)
    snap = _make_snapshot(created_at=recent)
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    author_block = blocks[0]
    author_text = [
        e.get("text", "") for e in author_block["elements"] if e.get("type") == "mrkdwn"
    ][0]
    assert "5m ago" in author_text


def test_old_post_shows_absolute_date(builder: XUnfurlBlocksBuilder) -> None:
    """Posts older than 7 days should show absolute date like 'Jan 15, 2024'."""
    old = datetime(2024, 1, 15, 12, 0, tzinfo=UTC)
    snap = _make_snapshot(created_at=old)
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    author_block = blocks[0]
    author_text = [
        e.get("text", "") for e in author_block["elements"] if e.get("type") == "mrkdwn"
    ][0]
    assert "Jan 15, 2024" in author_text


def test_hours_ago_shown_correctly(builder: XUnfurlBlocksBuilder) -> None:
    """Posts from hours ago should show compact format like '3h ago'."""
    from datetime import timedelta

    hours_ago = datetime.now(UTC) - timedelta(hours=3)
    snap = _make_snapshot(created_at=hours_ago)
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    author_block = blocks[0]
    author_text = [
        e.get("text", "") for e in author_block["elements"] if e.get("type") == "mrkdwn"
    ][0]
    assert "3h ago" in author_text


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


def test_is_valid_url(builder: XUnfurlBlocksBuilder) -> None:
    """URL validation helper checks for http/https prefix."""
    assert builder._is_valid_url("https://example.com/img.jpg") is True
    assert builder._is_valid_url("http://example.com/img.jpg") is True
    assert builder._is_valid_url("") is False
    assert builder._is_valid_url(None) is False
    assert builder._is_valid_url("ftp://example.com") is False
    assert builder._is_valid_url("not-a-url") is False
