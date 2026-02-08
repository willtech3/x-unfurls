"""Tests for FxTwitter client: URL parsing, response extraction, error handling."""

from __future__ import annotations

import httpx
import pytest
import respx

from xunfurls.infrastructure.fxtwitter_client import (
    API_BASE,
    FxTwitterClient,
    _extract_video_thumbnails,
    _parse_status_url,
)

# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------


class TestParseStatusUrl:
    def test_standard_x_url(self) -> None:
        assert _parse_status_url("https://x.com/elonmusk/status/123456") == (
            "elonmusk",
            "123456",
        )

    def test_twitter_url(self) -> None:
        assert _parse_status_url("https://twitter.com/jack/status/9999") == ("jack", "9999")

    def test_www_prefix(self) -> None:
        assert _parse_status_url("https://www.x.com/user/status/111") == ("user", "111")

    def test_with_query_params(self) -> None:
        assert _parse_status_url("https://x.com/user/status/555?s=20&t=abc") == ("user", "555")

    def test_invalid_host(self) -> None:
        assert _parse_status_url("https://example.com/user/status/123") is None

    def test_no_status_path(self) -> None:
        assert _parse_status_url("https://x.com/user") is None

    def test_non_numeric_status_id(self) -> None:
        assert _parse_status_url("https://x.com/user/status/abc") is None

    def test_empty_string(self) -> None:
        assert _parse_status_url("") is None


# ---------------------------------------------------------------------------
# Response extraction
# ---------------------------------------------------------------------------


class TestExtractVideoThumbnails:
    def test_single_video(self) -> None:
        data = {
            "tweet": {
                "media": {
                    "videos": [
                        {"thumbnail_url": "https://pbs.twimg.com/thumb1.jpg", "url": "vid.mp4"}
                    ]
                }
            }
        }
        assert _extract_video_thumbnails(data) == ["https://pbs.twimg.com/thumb1.jpg"]

    def test_multiple_videos(self) -> None:
        data = {
            "tweet": {
                "media": {
                    "videos": [
                        {"thumbnail_url": "https://thumb1.jpg"},
                        {"thumbnail_url": "https://thumb2.jpg"},
                    ]
                }
            }
        }
        assert _extract_video_thumbnails(data) == ["https://thumb1.jpg", "https://thumb2.jpg"]

    def test_no_videos_key(self) -> None:
        data = {"tweet": {"media": {"photos": []}}}
        assert _extract_video_thumbnails(data) == []

    def test_no_media_key(self) -> None:
        data = {"tweet": {"text": "hello"}}
        assert _extract_video_thumbnails(data) == []

    def test_no_tweet_key(self) -> None:
        assert _extract_video_thumbnails({}) == []

    def test_none_thumbnail_url_skipped(self) -> None:
        data = {
            "tweet": {
                "media": {
                    "videos": [
                        {"thumbnail_url": None},
                        {"thumbnail_url": "https://valid.jpg"},
                    ]
                }
            }
        }
        assert _extract_video_thumbnails(data) == ["https://valid.jpg"]

    def test_empty_thumbnail_url_skipped(self) -> None:
        data = {"tweet": {"media": {"videos": [{"thumbnail_url": ""}]}}}
        assert _extract_video_thumbnails(data) == []

    def test_missing_thumbnail_url_skipped(self) -> None:
        data = {"tweet": {"media": {"videos": [{"url": "vid.mp4"}]}}}
        assert _extract_video_thumbnails(data) == []


# ---------------------------------------------------------------------------
# HTTP integration (using respx mock)
# ---------------------------------------------------------------------------


class TestFxTwitterClientFetch:
    @pytest.fixture
    def fxtw(self) -> FxTwitterClient:
        return FxTwitterClient(timeout=2.0)

    @respx.mock
    async def test_successful_fetch(self, fxtw: FxTwitterClient) -> None:
        respx.get(f"{API_BASE}/testuser/status/12345").mock(
            return_value=httpx.Response(
                200,
                json={
                    "tweet": {
                        "media": {"videos": [{"thumbnail_url": "https://pbs.twimg.com/thumb.jpg"}]}
                    }
                },
            )
        )
        result = await fxtw.fetch_video_thumbnails("https://x.com/testuser/status/12345")
        assert result == ["https://pbs.twimg.com/thumb.jpg"]
        await fxtw.close()

    @respx.mock
    async def test_http_error_returns_empty(self, fxtw: FxTwitterClient) -> None:
        respx.get(f"{API_BASE}/testuser/status/12345").mock(return_value=httpx.Response(500))
        result = await fxtw.fetch_video_thumbnails("https://x.com/testuser/status/12345")
        assert result == []
        await fxtw.close()

    @respx.mock
    async def test_timeout_returns_empty(self, fxtw: FxTwitterClient) -> None:
        respx.get(f"{API_BASE}/testuser/status/12345").mock(
            side_effect=httpx.TimeoutException("read timeout")
        )
        result = await fxtw.fetch_video_thumbnails("https://x.com/testuser/status/12345")
        assert result == []
        await fxtw.close()

    async def test_invalid_url_returns_empty(self, fxtw: FxTwitterClient) -> None:
        result = await fxtw.fetch_video_thumbnails("https://example.com/not-a-tweet")
        assert result == []
        await fxtw.close()

    @respx.mock
    async def test_404_returns_empty(self, fxtw: FxTwitterClient) -> None:
        respx.get(f"{API_BASE}/testuser/status/99999").mock(
            return_value=httpx.Response(404, json={"error": "not found"})
        )
        result = await fxtw.fetch_video_thumbnails("https://x.com/testuser/status/99999")
        assert result == []
        await fxtw.close()

    @respx.mock
    async def test_malformed_json_returns_empty(self, fxtw: FxTwitterClient) -> None:
        respx.get(f"{API_BASE}/testuser/status/12345").mock(
            return_value=httpx.Response(200, content=b"not json")
        )
        result = await fxtw.fetch_video_thumbnails("https://x.com/testuser/status/12345")
        assert result == []
        await fxtw.close()
