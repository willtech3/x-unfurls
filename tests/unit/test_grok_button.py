"""Tests for Grok summary button interactive flow (UI-7)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from shared.domain.dtos import XUnfurlJobDto

SIGNING_SECRET = "test_signing_secret_for_grok_button"


def _make_valid_signature(body: bytes, ts: str) -> str:
    basestring = f"v0:{ts}:{body.decode('utf-8')}"
    return "v0=" + hmac.new(
        SIGNING_SECRET.encode(), basestring.encode(), hashlib.sha256
    ).hexdigest()


def _make_interactive_payload(
    action_id: str = "x_unfurl_summarize",
    value: str = "https://x.com/testuser/status/123456",
    channel_id: str = "C0123456789",
    message_ts: str = "1700000000.000100",
) -> dict[str, Any]:
    """Build a Slack block_actions interactive payload."""
    return {
        "type": "block_actions",
        "trigger_id": "trigger-123",
        "user": {"id": "U001", "username": "testuser"},
        "channel": {"id": channel_id},
        "container": {
            "type": "message_attachment",
            "message_ts": message_ts,
            "channel_id": channel_id,
        },
        "actions": [
            {
                "action_id": action_id,
                "block_id": "actions-block",
                "type": "button",
                "value": value,
            }
        ],
    }


def _post_interactive(client: TestClient, payload: dict[str, Any]) -> Any:
    """POST an interactive payload with a valid Slack signature."""
    body = f"payload={json.dumps(payload)}".encode()
    ts = str(int(time.time()))
    sig = _make_valid_signature(body, ts)
    return client.post(
        "/slack/interactive",
        content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": sig,
        },
    )


class TestGrokButtonInteractive:
    """Test the /slack/interactive endpoint handling for summarize button."""

    @patch.dict("os.environ", {"SLACK_SIGNING_SECRET": SIGNING_SECRET})
    def test_summarize_action_enqueues_job(self) -> None:
        """Clicking 'Summarize with Grok' should enqueue a summarize job."""
        from xunfurls.infrastructure.gcp.webhook_app import app, set_job_queue

        mock_queue = AsyncMock()
        mock_queue.enqueue_job = AsyncMock(return_value="msg-id-123")
        set_job_queue(mock_queue)

        client = TestClient(app)
        payload = _make_interactive_payload()
        resp = _post_interactive(client, payload)

        assert resp.status_code == 200
        mock_queue.enqueue_job.assert_called_once()
        enqueued_job: XUnfurlJobDto = mock_queue.enqueue_job.call_args[0][0]
        assert enqueued_job.action == "summarize"
        assert enqueued_job.status_id == "123456"
        assert enqueued_job.canonical_url == "https://x.com/testuser/status/123456"
        assert enqueued_job.channel_id == "C0123456789"
        assert enqueued_job.message_ts == "1700000000.000100"

    @patch.dict("os.environ", {"SLACK_SIGNING_SECRET": SIGNING_SECRET})
    def test_unknown_action_returns_ok(self) -> None:
        """Unknown action_ids should be silently accepted (no error)."""
        from xunfurls.infrastructure.gcp.webhook_app import app

        client = TestClient(app)
        payload = _make_interactive_payload(action_id="some_other_action")
        resp = _post_interactive(client, payload)

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    @patch.dict("os.environ", {"SLACK_SIGNING_SECRET": SIGNING_SECRET})
    def test_open_in_x_action_ignored(self) -> None:
        """The 'Open in X' button (link button) shouldn't trigger any job."""
        from xunfurls.infrastructure.gcp.webhook_app import app, set_job_queue

        mock_queue = AsyncMock()
        set_job_queue(mock_queue)

        client = TestClient(app)
        payload = _make_interactive_payload(action_id="x_unfurl_open")
        resp = _post_interactive(client, payload)

        assert resp.status_code == 200
        mock_queue.enqueue_job.assert_not_called()

    @patch.dict("os.environ", {"SLACK_SIGNING_SECRET": SIGNING_SECRET})
    def test_summarize_extracts_status_id_from_canonical_url(self) -> None:
        """Status ID should be parsed from the canonical URL in the button value."""
        from xunfurls.infrastructure.gcp.webhook_app import app, set_job_queue

        mock_queue = AsyncMock()
        mock_queue.enqueue_job = AsyncMock(return_value="msg-id")
        set_job_queue(mock_queue)

        client = TestClient(app)
        payload = _make_interactive_payload(
            value="https://x.com/elonmusk/status/9876543210"
        )
        resp = _post_interactive(client, payload)

        assert resp.status_code == 200
        enqueued_job: XUnfurlJobDto = mock_queue.enqueue_job.call_args[0][0]
        assert enqueued_job.status_id == "9876543210"

    @patch.dict("os.environ", {"SLACK_SIGNING_SECRET": SIGNING_SECRET})
    def test_summarize_with_invalid_url_returns_ok(self) -> None:
        """If the button value has no valid status ID, return OK but don't enqueue."""
        from xunfurls.infrastructure.gcp.webhook_app import app, set_job_queue

        mock_queue = AsyncMock()
        set_job_queue(mock_queue)

        client = TestClient(app)
        payload = _make_interactive_payload(value="https://x.com/nope")
        resp = _post_interactive(client, payload)

        assert resp.status_code == 200
        mock_queue.enqueue_job.assert_not_called()
