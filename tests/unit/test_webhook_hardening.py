"""Tests for webhook hardening: BUG-2, BUG-5, CQ-1, CQ-2, CQ-3, CQ-4."""

import hashlib
import hmac
import time
from typing import get_type_hints
from unittest.mock import patch

from fastapi.testclient import TestClient

from shared.domain.dtos import XUnfurlJobDto
from xunfurls.infrastructure.gcp.webhook_app import (
    canonicalize_url,
    extract_status_id,
    validate_slack_signature,
)

SIGNING_SECRET = "test_signing_secret_1234567890"


def _make_valid_signature(body: bytes, timestamp: str) -> str:
    """Create a valid Slack signature for testing."""
    basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    sig = hmac.new(
        SIGNING_SECRET.encode(),
        basestring.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"v0={sig}"


class TestBug2MissingHeaders:
    """BUG-2: validate_slack_signature must return False on bad input."""

    def test_empty_timestamp_returns_false(self) -> None:
        result = validate_slack_signature(
            body=b"hello",
            timestamp="",
            signature="v0=abc",
            signing_secret=SIGNING_SECRET,
        )
        assert result is False

    def test_missing_signature_returns_false(self) -> None:
        ts = str(int(time.time()))
        result = validate_slack_signature(
            body=b"hello",
            timestamp=ts,
            signature="",
            signing_secret=SIGNING_SECRET,
        )
        assert result is False

    def test_non_numeric_timestamp_returns_false(self) -> None:
        result = validate_slack_signature(
            body=b"hello",
            timestamp="abc",
            signature="v0=abc",
            signing_secret=SIGNING_SECRET,
        )
        assert result is False

    def test_none_timestamp_returns_false(self) -> None:
        result = validate_slack_signature(
            body=b"hello",
            timestamp="None",
            signature="v0=abc",
            signing_secret=SIGNING_SECRET,
        )
        assert result is False

    def test_valid_signature_still_works(self) -> None:
        body = b'{"type":"url_verification"}'
        ts = str(int(time.time()))
        sig = _make_valid_signature(body, ts)
        result = validate_slack_signature(
            body=body,
            timestamp=ts,
            signature=sig,
            signing_secret=SIGNING_SECRET,
        )
        assert result is True


class TestBug5CanonicalizeUrl:
    """BUG-5: canonicalize_url fallback for root-only URLs."""

    def test_canonicalize_url_empty_path(self) -> None:
        result = canonicalize_url("https://x.com/", "123456789")
        assert result == "https://x.com/i/status/123456789"

    def test_canonicalize_url_root_only(self) -> None:
        result = canonicalize_url("https://x.com", "123456789")
        assert result == "https://x.com/i/status/123456789"

    def test_canonicalize_url_preserves_username(self) -> None:
        result = canonicalize_url("https://x.com/elonmusk/status/123456789", "123456789")
        assert result == "https://x.com/elonmusk/status/123456789"

    def test_canonicalize_url_with_i_prefix(self) -> None:
        result = canonicalize_url("https://x.com/i/status/123456789", "123456789")
        assert result == "https://x.com/i/status/123456789"


class TestCQ1ActionEnum:
    """CQ-1: XUnfurlJobDto.action should use Literal type."""

    def test_job_dto_with_valid_action(self) -> None:
        dto = XUnfurlJobDto(
            job_id="j1",
            channel_id="C1",
            message_ts="1.1",
            team_id="T1",
            original_url="https://x.com/u/status/1",
            canonical_url="https://x.com/u/status/1",
            status_id="1",
            action="generate",
        )
        assert dto.action == "generate"

    def test_job_dto_action_type_is_constrained(self) -> None:
        hints = get_type_hints(XUnfurlJobDto)
        action_type = hints["action"]
        assert hasattr(action_type, "__args__"), (
            f"action field should be Literal[...], got {action_type}"
        )
        assert set(action_type.__args__) == {"generate", "refresh", "summarize"}

    def test_job_dto_all_valid_actions(self) -> None:
        for action in ("generate", "refresh", "summarize"):
            dto = XUnfurlJobDto(
                job_id="j1",
                channel_id="C1",
                message_ts="1.1",
                team_id="T1",
                original_url="u",
                canonical_url="u",
                status_id="1",
                action=action,
            )
            assert dto.action == action


class TestCQ2RegexDomainSafety:
    """CQ-2: is_x_link guards against non-X domains."""

    def test_extract_status_id_matches_any_url_with_status_path(self) -> None:
        result = extract_status_id("https://example.com/status/123")
        assert result == "123"

    def test_is_x_link_guards_before_extract(self) -> None:
        from xunfurls.infrastructure.gcp.webhook_app import is_x_link

        assert is_x_link("https://example.com/status/123") is False
        assert is_x_link("https://x.com/user/status/123") is True

    def test_extract_status_id_rejects_non_status_url(self) -> None:
        assert extract_status_id("https://x.com/user/profile") is None
        assert extract_status_id("https://x.com/settings") is None


class TestCQ3DependencyInjection:
    """CQ-3: webhook app must support injected job queue."""

    def test_webhook_uses_dependency_injection(self) -> None:
        from xunfurls.infrastructure.gcp.webhook_app import (
            get_job_queue,
            set_job_queue,
        )

        class MockQueue:
            async def enqueue_job(self, job: XUnfurlJobDto) -> str:
                return "mock-msg-id"

        mock_q = MockQueue()
        set_job_queue(mock_q)
        assert get_job_queue() is mock_q

    def test_get_job_queue_returns_injected_queue(self) -> None:
        from xunfurls.infrastructure.gcp.webhook_app import (
            get_job_queue,
            set_job_queue,
        )

        class AnotherMock:
            async def enqueue_job(self, job: XUnfurlJobDto) -> str:
                return "another-id"

        q = AnotherMock()
        set_job_queue(q)
        assert get_job_queue() is q


class TestCQ4InteractiveEndpoint:
    """CQ-4: /slack/interactive must validate Slack signature."""

    def _get_client(self) -> TestClient:
        from xunfurls.infrastructure.gcp.webhook_app import app

        return TestClient(app)

    @patch.dict("os.environ", {"SLACK_SIGNING_SECRET": SIGNING_SECRET})
    def test_interactive_endpoint_validates_signature(self) -> None:
        client = self._get_client()
        response = client.post(
            "/slack/interactive",
            content=b"payload=test",
            headers={
                "X-Slack-Request-Timestamp": "0",
                "X-Slack-Signature": "v0=invalid",
            },
        )
        assert response.status_code == 401

    @patch.dict("os.environ", {"SLACK_SIGNING_SECRET": SIGNING_SECRET})
    def test_interactive_missing_headers_returns_401(self) -> None:
        client = self._get_client()
        response = client.post(
            "/slack/interactive",
            content=b"payload=test",
        )
        assert response.status_code == 401

    @patch.dict("os.environ", {"SLACK_SIGNING_SECRET": SIGNING_SECRET})
    def test_interactive_endpoint_accepts_valid_request(self) -> None:
        client = self._get_client()
        body = b"payload=test"
        ts = str(int(time.time()))
        sig = _make_valid_signature(body, ts)
        response = client.post(
            "/slack/interactive",
            content=body,
            headers={
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
            },
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}
