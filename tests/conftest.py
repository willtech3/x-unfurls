"""Shared test configuration and fixtures used across all test types."""

import os

import pytest

# Set TESTING=1 before any application modules are imported, so that
# webhook_app.py's startup validation for SLACK_SIGNING_SECRET is skipped.
os.environ.setdefault("TESTING", "1")


@pytest.fixture
def sample_x_url() -> str:
    """A canonical X post URL for testing."""
    return "https://x.com/testuser/status/1234567890"


@pytest.fixture
def sample_twitter_url() -> str:
    """A legacy Twitter post URL for testing."""
    return "https://twitter.com/testuser/status/1234567890"


@pytest.fixture
def sample_status_id() -> str:
    """A sample X status ID for testing."""
    return "1234567890"


@pytest.fixture
def sample_channel_id() -> str:
    """A sample Slack channel ID for testing."""
    return "C0123456789"


@pytest.fixture
def sample_message_ts() -> str:
    """A sample Slack message timestamp for testing."""
    return "1700000000.000100"


@pytest.fixture
def sample_team_id() -> str:
    """A sample Slack team ID for testing."""
    return "T0123456789"
