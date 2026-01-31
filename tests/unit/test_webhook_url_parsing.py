"""Tests for webhook URL parsing utilities."""

import pytest

from xunfurls.infrastructure.gcp.webhook_app import (
    canonicalize_url,
    extract_status_id,
    is_x_link,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://x.com/user/status/123456789", "123456789"),
        ("https://twitter.com/user/status/987654321", "987654321"),
        ("https://x.com/i/status/111222333", "111222333"),
        ("https://www.x.com/user/statuses/444555666", "444555666"),
        ("https://example.com/not-a-status", None),
        ("https://x.com/user/profile", None),
    ],
)
def test_extract_status_id(url: str, expected: str | None) -> None:
    """Test extracting status IDs from various URL formats."""
    assert extract_status_id(url) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://x.com/user/status/123", True),
        ("https://twitter.com/user/status/123", True),
        ("https://www.x.com/user/status/123", True),
        ("https://www.twitter.com/user/status/123", True),
        ("https://example.com/status/123", False),
        ("https://facebook.com/post", False),
    ],
)
def test_is_x_link(url: str, expected: bool) -> None:
    """Test identifying X/Twitter links."""
    assert is_x_link(url) == expected


def test_canonicalize_url() -> None:
    """Test URL canonicalization."""
    url = "https://twitter.com/johndoe/status/123456789?s=20"
    canonical = canonicalize_url(url, "123456789")

    assert canonical == "https://x.com/johndoe/status/123456789"
    assert "twitter.com" not in canonical
    assert "?" not in canonical


def test_canonicalize_url_no_username() -> None:
    """Test canonicalization when username cannot be extracted."""
    url = "https://x.com/i/status/123456789"
    canonical = canonicalize_url(url, "123456789")

    assert canonical == "https://x.com/i/status/123456789"
