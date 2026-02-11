"""Tests for xAI response parsing and fallback snapshot creation."""

import json
from datetime import UTC, datetime

import pytest

from xunfurls.infrastructure.gcp.xai_client import (
    create_fallback_snapshot,
    parse_xai_response,
)


def _make_xai_response(content_dict: dict | None = None, content_str: str | None = None) -> dict:
    """Build a well-formed xAI Responses API response wrapping the given content."""
    if content_str is None:
        content_str = json.dumps(content_dict or {})
    return {
        "output": [
            {
                "content": [{"type": "output_text", "text": content_str}],
                "id": "msg_test",
            }
        ],
    }


@pytest.fixture
def valid_response_data() -> dict:
    return {
        "author_name": "Elon Musk",
        "author_handle": "elonmusk",
        "author_avatar_url": "https://pbs.twimg.com/avatar.jpg",
        "verified": True,
        "created_at": "2024-06-15T10:30:00Z",
        "text": "Hello world!",
        "media": [
            {
                "type": "image",
                "url": "https://img.x.com/1.jpg",
                "thumbnail_url": None,
                "alt_text": "Photo",
            },
            {
                "type": "video",
                "url": "https://vid.x.com/1.mp4",
                "thumbnail_url": "https://img.x.com/t.jpg",
                "alt_text": None,
            },
        ],
        "metrics": {
            "likes": 5000,
            "reposts": 1200,
            "replies": 300,
            "views": 500000,
            "bookmarks": 42,
        },
        "top_replies": [
            {"author_name": "User1", "author_handle": "user1", "text": "Nice!", "verified": False},
        ],
        "summary": "A greeting to the world.",
    }


# ---------------------------------------------------------------------------
# Timezone awareness (BUG-4)
# ---------------------------------------------------------------------------


class TestTimezoneAwareness:
    def test_fallback_snapshot_has_timezone_aware_datetime(self):
        snap = create_fallback_snapshot()
        assert snap.created_at.tzinfo is not None

    def test_parsed_snapshot_has_timezone_aware_datetime(self, valid_response_data):
        resp = _make_xai_response(valid_response_data)
        snap = parse_xai_response(resp)
        assert snap.created_at.tzinfo is not None

    def test_parsed_snapshot_without_created_at_is_utc(self):
        data = {"author_name": "Test", "author_handle": "test", "text": "hi"}
        resp = _make_xai_response(data)
        snap = parse_xai_response(resp)
        assert snap.created_at.tzinfo is not None

    def test_fallback_and_parsed_datetimes_comparable(self, valid_response_data):
        fallback = create_fallback_snapshot()
        resp = _make_xai_response(valid_response_data)
        parsed = parse_xai_response(resp)
        # Verify comparison doesn't raise TypeError (both must be tz-aware)
        _ = fallback.created_at < parsed.created_at

    def test_z_suffix_parsed_as_utc(self):
        data = {"created_at": "2024-01-15T12:00:00Z"}
        resp = _make_xai_response(data)
        snap = parse_xai_response(resp)
        assert snap.created_at.tzinfo is not None
        assert snap.created_at == datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)

    def test_offset_timestamp_preserved(self):
        data = {"created_at": "2024-01-15T12:00:00+05:00"}
        resp = _make_xai_response(data)
        snap = parse_xai_response(resp)
        assert snap.created_at.tzinfo is not None


# ---------------------------------------------------------------------------
# Valid response parsing
# ---------------------------------------------------------------------------


class TestValidResponseParsing:
    def test_all_fields_mapped_correctly(self, valid_response_data):
        resp = _make_xai_response(valid_response_data)
        snap = parse_xai_response(resp)
        assert snap.author_name == "Elon Musk"
        assert snap.author_handle == "elonmusk"
        assert snap.author_avatar_url == "https://pbs.twimg.com/avatar.jpg"
        assert snap.verified is True
        assert snap.text == "Hello world!"
        assert len(snap.media) == 2
        assert snap.media[0].type == "image"
        assert snap.media[1].type == "video"
        assert snap.metrics.likes == 5000
        assert snap.metrics.views == 500000
        assert len(snap.top_replies) == 1
        assert snap.top_replies[0].author_handle == "user1"
        assert snap.summary == "A greeting to the world."

    def test_minimal_valid_response(self):
        data = {"author_name": "A", "author_handle": "a", "text": "hi"}
        resp = _make_xai_response(data)
        snap = parse_xai_response(resp)
        assert snap.author_name == "A"
        assert snap.text == "hi"
        assert snap.media == []
        assert snap.metrics.likes == 0


# ---------------------------------------------------------------------------
# Malformed responses
# ---------------------------------------------------------------------------


class TestMalformedResponses:
    def test_no_output_raises_value_error(self):
        with pytest.raises(ValueError, match="No text output"):
            parse_xai_response({"output": []})

    def test_non_json_content_returns_fallback(self):
        resp = _make_xai_response(content_str="This is not JSON at all")
        snap = parse_xai_response(resp)
        assert snap.author_name == "Unknown"
        assert snap.text == "Preview unavailable"

    def test_empty_content_raises_value_error(self):
        resp = _make_xai_response(content_str="")
        with pytest.raises(ValueError, match="No text output"):
            parse_xai_response(resp)

    def test_missing_required_media_fields_returns_fallback(self):
        data = {"media": [{"not_type": "image"}]}
        resp = _make_xai_response(data)
        snap = parse_xai_response(resp)
        assert snap.author_name == "Unknown"


# ---------------------------------------------------------------------------
# Media parsing
# ---------------------------------------------------------------------------


class TestMediaParsing:
    def test_empty_media_list(self):
        data = {"media": []}
        resp = _make_xai_response(data)
        snap = parse_xai_response(resp)
        assert snap.media == []

    def test_all_media_types_parsed(self):
        data = {
            "media": [
                {"type": "image", "url": "https://img.x.com/1.jpg"},
                {
                    "type": "video",
                    "url": "https://vid.x.com/1.mp4",
                    "thumbnail_url": "https://t.jpg",
                },
                {"type": "gif", "url": "https://gif.x.com/1.gif", "alt_text": "Funny GIF"},
            ]
        }
        resp = _make_xai_response(data)
        snap = parse_xai_response(resp)
        assert len(snap.media) == 3
        assert [m.type for m in snap.media] == ["image", "video", "gif"]
        assert snap.media[2].alt_text == "Funny GIF"


# ---------------------------------------------------------------------------
# Metrics parsing
# ---------------------------------------------------------------------------


class TestMetricsParsing:
    def test_missing_metrics_default_to_zero(self):
        resp = _make_xai_response({})
        snap = parse_xai_response(resp)
        assert snap.metrics.likes == 0
        assert snap.metrics.reposts == 0
        assert snap.metrics.replies == 0
        assert snap.metrics.views is None

    def test_partial_metrics(self):
        data = {"metrics": {"likes": 42}}
        resp = _make_xai_response(data)
        snap = parse_xai_response(resp)
        assert snap.metrics.likes == 42
        assert snap.metrics.reposts == 0


# ---------------------------------------------------------------------------
# Replies parsing
# ---------------------------------------------------------------------------


class TestRepliesParsing:
    def test_replies_parsed_correctly(self):
        data = {
            "top_replies": [
                {"author_name": "Bob", "author_handle": "bob", "text": "Great!", "verified": True},
                {"author_name": "Alice", "author_handle": "alice", "text": "Thanks"},
            ]
        }
        resp = _make_xai_response(data)
        snap = parse_xai_response(resp)
        assert len(snap.top_replies) == 2
        assert snap.top_replies[0].verified is True
        assert snap.top_replies[1].verified is False  # default


# ---------------------------------------------------------------------------
# Special characters
# ---------------------------------------------------------------------------


class TestSpecialCharacters:
    def test_emoji_in_text(self):
        data = {"text": "Hello 🌍 World 🚀"}
        resp = _make_xai_response(data)
        snap = parse_xai_response(resp)
        assert "🌍" in snap.text
        assert "🚀" in snap.text

    def test_newlines_in_text(self):
        data = {"text": "Line 1\nLine 2\nLine 3"}
        resp = _make_xai_response(data)
        snap = parse_xai_response(resp)
        assert "\n" in snap.text


# ---------------------------------------------------------------------------
# Parent post parsing
# ---------------------------------------------------------------------------


class TestParentPostParsing:
    def test_parent_post_parsed_correctly(self):
        data = {
            "text": "This is a reply",
            "parent_post": {
                "author_name": "Original Author",
                "author_handle": "origauthor",
                "text": "Original post text",
                "verified": True,
            },
        }
        resp = _make_xai_response(data)
        snap = parse_xai_response(resp)
        assert snap.parent_post is not None
        assert snap.parent_post.author_name == "Original Author"
        assert snap.parent_post.author_handle == "origauthor"
        assert snap.parent_post.text == "Original post text"
        assert snap.parent_post.verified is True

    def test_parent_post_null_when_not_reply(self):
        data = {
            "text": "This is a top-level post",
            "parent_post": None,
        }
        resp = _make_xai_response(data)
        snap = parse_xai_response(resp)
        assert snap.parent_post is None

    def test_parent_post_absent_defaults_to_none(self):
        data = {"text": "No parent_post key at all"}
        resp = _make_xai_response(data)
        snap = parse_xai_response(resp)
        assert snap.parent_post is None
