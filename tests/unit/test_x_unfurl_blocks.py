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
# BUG-3: Video and GIF media handling
# ---------------------------------------------------------------------------


def test_video_media_shows_thumbnail(builder: XUnfurlBlocksBuilder) -> None:
    snap = _make_snapshot(media=[XMedia(type="video", url="https://x.co/v.mp4", thumbnail_url="https://x.co/thumb.jpg", alt_text="vid")])
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    imgs = [b for b in blocks if b["type"] == "image"]
    assert len(imgs) == 1
    assert imgs[0]["image_url"] == "https://x.co/thumb.jpg"
    texts = [e.get("text", "") for b in blocks if b["type"] == "context" for e in b.get("elements", [])]
    assert any("Video" in t for t in texts)


def test_video_falls_back_to_url_when_no_thumbnail(builder: XUnfurlBlocksBuilder) -> None:
    snap = _make_snapshot(media=[XMedia(type="video", url="https://x.co/poster.jpg", thumbnail_url=None)])
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    imgs = [b for b in blocks if b["type"] == "image"]
    assert imgs[0]["image_url"] == "https://x.co/poster.jpg"


def test_gif_media_rendered_as_image(builder: XUnfurlBlocksBuilder) -> None:
    snap = _make_snapshot(media=[XMedia(type="gif", url="https://x.co/funny.gif", alt_text="GIF")])
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    imgs = [b for b in blocks if b["type"] == "image"]
    assert len(imgs) == 1
    assert imgs[0]["image_url"] == "https://x.co/funny.gif"


def test_mixed_media_types_all_rendered(builder: XUnfurlBlocksBuilder) -> None:
    snap = _make_snapshot(media=[
        XMedia(type="image", url="https://x.co/i.jpg"),
        XMedia(type="video", url="https://x.co/v.mp4", thumbnail_url="https://x.co/vt.jpg"),
        XMedia(type="gif", url="https://x.co/g.gif"),
    ])
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    img_urls = [b["image_url"] for b in blocks if b["type"] == "image"]
    assert "https://x.co/i.jpg" in img_urls
    assert "https://x.co/vt.jpg" in img_urls
    assert "https://x.co/g.gif" in img_urls


# ---------------------------------------------------------------------------
# UI-1: Author avatar
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


# ---------------------------------------------------------------------------
# UI-4: Zero metrics handling
# ---------------------------------------------------------------------------


def test_zero_metrics_block_omitted(builder: XUnfurlBlocksBuilder) -> None:
    snap = _make_snapshot(metrics=XMetrics(likes=0, reposts=0, replies=0, views=0))
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    for b in blocks:
        if b["type"] == "context":
            for e in b.get("elements", []):
                text = e.get("text", "")
                assert "💬" not in text
                assert "🔁" not in text
                assert "❤️" not in text
                assert "👁" not in text


def test_partial_metrics_only_nonzero_shown(builder: XUnfurlBlocksBuilder) -> None:
    snap = _make_snapshot(metrics=XMetrics(likes=100, reposts=0, replies=0, views=0))
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    metrics_block = None
    for b in blocks:
        if b["type"] == "context":
            for e in b.get("elements", []):
                if "❤️" in e.get("text", ""):
                    metrics_block = b
    assert metrics_block is not None
    text = metrics_block["elements"][0]["text"]
    assert "❤️" in text
    assert "💬" not in text
    assert "🔁" not in text


# ---------------------------------------------------------------------------
# UI-7: Grok summary button (opt-in)
# ---------------------------------------------------------------------------


def test_summarize_button_present_when_no_summary(builder: XUnfurlBlocksBuilder) -> None:
    """When summary is None, the actions block should include 'Summarize with Grok'."""
    snap = _make_snapshot(summary=None)
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/999")
    actions_blocks = [b for b in blocks if b["type"] == "actions"]
    assert len(actions_blocks) == 1
    buttons = actions_blocks[0]["elements"]
    action_ids = [btn["action_id"] for btn in buttons]
    assert "x_unfurl_open" in action_ids
    assert "x_unfurl_summarize" in action_ids


def test_summarize_button_absent_when_summary_present(builder: XUnfurlBlocksBuilder) -> None:
    """When summary is present, 'Summarize with Grok' button should NOT appear."""
    snap = _make_snapshot(summary="This is a Grok-generated summary.")
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/999")
    actions_blocks = [b for b in blocks if b["type"] == "actions"]
    assert len(actions_blocks) == 1
    buttons = actions_blocks[0]["elements"]
    action_ids = [btn["action_id"] for btn in buttons]
    assert "x_unfurl_open" in action_ids
    assert "x_unfurl_summarize" not in action_ids


def test_summarize_button_value_contains_canonical_url(builder: XUnfurlBlocksBuilder) -> None:
    """The summarize button value should contain the canonical URL for re-fetching."""
    snap = _make_snapshot(summary=None)
    url = "https://x.com/testuser/status/42"
    blocks = builder.build_unfurl_blocks(snap, url)
    actions_blocks = [b for b in blocks if b["type"] == "actions"]
    summarize_btn = [
        btn for btn in actions_blocks[0]["elements"]
        if btn["action_id"] == "x_unfurl_summarize"
    ][0]
    assert summarize_btn["value"] == url


# ---------------------------------------------------------------------------
# UI-3: Relative timestamps
# ---------------------------------------------------------------------------


def test_recent_post_shows_relative_time(builder: XUnfurlBlocksBuilder) -> None:
    """Posts from minutes ago should show relative time like '5 minutes ago'."""
    from datetime import timedelta

    recent = datetime.now(UTC) - timedelta(minutes=5)
    snap = _make_snapshot(created_at=recent)
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    author_block = blocks[0]
    author_text = [
        e.get("text", "") for e in author_block["elements"]
        if e.get("type") == "mrkdwn"
    ][0]
    assert "ago" in author_text


def test_old_post_shows_absolute_date(builder: XUnfurlBlocksBuilder) -> None:
    """Posts older than 7 days should show absolute date like 'Jan 15, 2024'."""
    old = datetime(2024, 1, 15, 12, 0, tzinfo=UTC)
    snap = _make_snapshot(created_at=old)
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    author_block = blocks[0]
    author_text = [
        e.get("text", "") for e in author_block["elements"]
        if e.get("type") == "mrkdwn"
    ][0]
    assert "Jan 15, 2024" in author_text


def test_hours_ago_shown_correctly(builder: XUnfurlBlocksBuilder) -> None:
    """Posts from hours ago should show 'X hours ago'."""
    from datetime import timedelta

    hours_ago = datetime.now(UTC) - timedelta(hours=3)
    snap = _make_snapshot(created_at=hours_ago)
    blocks = builder.build_unfurl_blocks(snap, "https://x.com/t/status/1")
    author_block = blocks[0]
    author_text = [
        e.get("text", "") for e in author_block["elements"]
        if e.get("type") == "mrkdwn"
    ][0]
    assert "hours ago" in author_text
