"""Tests for Grok button interactive flow (Ask Grok modal)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

SIGNING_SECRET = "test_signing_secret_for_grok_button"


def _make_valid_signature(body: bytes, ts: str) -> str:
    basestring = f"v0:{ts}:{body.decode('utf-8')}"
    return (
        "v0=" + hmac.new(SIGNING_SECRET.encode(), basestring.encode(), hashlib.sha256).hexdigest()
    )


def _make_interactive_payload(
    action_id: str = "x_unfurl_ask_grok",
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
    """Test the /slack/interactive endpoint handling for Ask Grok button."""

    @patch("xunfurls.infrastructure.gcp.webhook_app._SIGNING_SECRET", SIGNING_SECRET)
    def test_ask_grok_action_opens_modal(self) -> None:
        """Clicking 'Ask Grok' should open a modal via views.open."""
        from xunfurls.infrastructure.gcp.webhook_app import app, set_slack_client

        mock_slack = AsyncMock()
        mock_slack.open_modal = AsyncMock()
        set_slack_client(mock_slack)

        client = TestClient(app)
        payload = _make_interactive_payload()
        resp = _post_interactive(client, payload)

        assert resp.status_code == 200
        mock_slack.open_modal.assert_called_once()
        call_args = mock_slack.open_modal.call_args
        trigger_id = call_args[0][0]
        view = call_args[0][1]
        assert trigger_id == "trigger-123"
        assert view["callback_id"] == "ask_grok_modal"
        assert view["type"] == "modal"

    @patch("xunfurls.infrastructure.gcp.webhook_app._SIGNING_SECRET", SIGNING_SECRET)
    def test_unknown_action_returns_ok(self) -> None:
        """Unknown action_ids should be silently accepted (no error)."""
        from xunfurls.infrastructure.gcp.webhook_app import app

        client = TestClient(app)
        payload = _make_interactive_payload(action_id="some_other_action")
        resp = _post_interactive(client, payload)

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    @patch("xunfurls.infrastructure.gcp.webhook_app._SIGNING_SECRET", SIGNING_SECRET)
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

    @patch("xunfurls.infrastructure.gcp.webhook_app._SIGNING_SECRET", SIGNING_SECRET)
    def test_ask_grok_modal_metadata_includes_canonical_url(self) -> None:
        """The modal private_metadata should contain canonical_url for submission."""
        from xunfurls.infrastructure.gcp.webhook_app import app, set_slack_client

        mock_slack = AsyncMock()
        mock_slack.open_modal = AsyncMock()
        set_slack_client(mock_slack)

        client = TestClient(app)
        payload = _make_interactive_payload(value="https://x.com/elonmusk/status/9876543210")
        resp = _post_interactive(client, payload)

        assert resp.status_code == 200
        view = mock_slack.open_modal.call_args[0][1]
        metadata = json.loads(view["private_metadata"])
        assert metadata["canonical_url"] == "https://x.com/elonmusk/status/9876543210"

    @patch("xunfurls.infrastructure.gcp.webhook_app._SIGNING_SECRET", SIGNING_SECRET)
    def test_ask_grok_no_trigger_id_logs_warning(self) -> None:
        """If trigger_id is missing, the modal should not be opened."""
        from xunfurls.infrastructure.gcp.webhook_app import app, set_slack_client

        mock_slack = AsyncMock()
        mock_slack.open_modal = AsyncMock()
        set_slack_client(mock_slack)

        client = TestClient(app)
        payload = _make_interactive_payload()
        payload["trigger_id"] = ""  # Remove trigger_id
        resp = _post_interactive(client, payload)

        assert resp.status_code == 200
        mock_slack.open_modal.assert_not_called()
