"""Tests for worker_app: lifecycle, error classification, poison pills, error detail leaking."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from starlette.testclient import TestClient


def _make_pubsub_envelope(job_dict: dict[str, Any]) -> dict[str, Any]:
    encoded = base64.b64encode(json.dumps(job_dict).encode()).decode()
    return {
        "message": {
            "data": encoded,
            "messageId": "test-msg-123",
            "publishTime": "2024-01-01T00:00:00Z",
        },
        "subscription": "projects/test-project/subscriptions/test-sub",
    }


def _valid_job_dict() -> dict[str, Any]:
    return {
        "job_id": "job-001",
        "channel_id": "C0123456789",
        "message_ts": "1700000000.000100",
        "team_id": "T0123456789",
        "original_url": "https://x.com/testuser/status/1234567890",
        "canonical_url": "https://x.com/testuser/status/1234567890",
        "status_id": "1234567890",
        "action": "generate",
        "trace_id": "trace-001",
    }


@dataclass
class FakeXAIClient:
    close_calls: int = 0

    async def fetch_post_snapshot(self, status_ref: Any, mode: Any) -> Any:
        pass

    async def close(self) -> None:
        self.close_calls += 1


@dataclass
class FakeSlackClient:
    close_calls: int = 0

    async def unfurl_links(self, channel_id: str, message_ts: str, unfurls: Any) -> None:
        pass

    async def post_message(self, channel_id: str, blocks: Any, text: str = "") -> None:
        pass

    async def close(self) -> None:
        self.close_calls += 1


@pytest.fixture
def _fake_clients():
    from contextlib import asynccontextmanager

    from xunfurls.application.presenters.x_unfurl_blocks import XUnfurlBlocksBuilder
    from xunfurls.application.services.x_unfurl_service import XUnfurlService

    xai = FakeXAIClient()
    slack = FakeSlackClient()
    service = XUnfurlService(x_repo=xai, slack_repo=slack, blocks_builder=XUnfurlBlocksBuilder())

    @asynccontextmanager
    async def _managed():
        yield service

    with patch("xunfurls.infrastructure.gcp.worker_app.create_managed_unfurl_service", _managed):
        yield xai, slack, service


@pytest.fixture
def client(_fake_clients):
    from xunfurls.infrastructure.gcp.worker_app import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_xai(_fake_clients):
    return _fake_clients[0]


@pytest.fixture
def fake_slack_client(_fake_clients):
    return _fake_clients[1]


@pytest.fixture
def fake_service(_fake_clients):
    return _fake_clients[2]


class TestServiceLifecycle:
    def test_service_created_once_at_startup(self, client, fake_service):
        from xunfurls.infrastructure.gcp.worker_app import app

        assert app.state.unfurl_service is fake_service

    def test_clients_closed_on_shutdown(self):
        from contextlib import asynccontextmanager
        from unittest.mock import patch as _patch

        from xunfurls.application.presenters.x_unfurl_blocks import XUnfurlBlocksBuilder
        from xunfurls.application.services.x_unfurl_service import XUnfurlService

        xai = FakeXAIClient()
        slack = FakeSlackClient()
        service = XUnfurlService(
            x_repo=xai, slack_repo=slack, blocks_builder=XUnfurlBlocksBuilder()
        )

        @asynccontextmanager
        async def _managed():
            try:
                yield service
            finally:
                await xai.close()
                await slack.close()

        with _patch(
            "xunfurls.infrastructure.gcp.worker_app.create_managed_unfurl_service", _managed
        ):
            from xunfurls.infrastructure.gcp.worker_app import app

            with TestClient(app):
                assert xai.close_calls == 0
                assert slack.close_calls == 0
            assert xai.close_calls == 1
            assert slack.close_calls == 1


class TestErrorClassification:
    def test_permanent_error_returns_200(self, client, fake_service):
        fake_service.process_unfurl_job = AsyncMock(side_effect=ValueError("malformed data"))
        envelope = _make_pubsub_envelope(_valid_job_dict())
        resp = client.post("/pubsub", json=envelope)
        assert resp.status_code == 200

    def test_transient_error_returns_500(self, client, fake_service):
        fake_service.process_unfurl_job = AsyncMock(
            side_effect=ConnectionError("connection refused")
        )
        envelope = _make_pubsub_envelope(_valid_job_dict())
        resp = client.post("/pubsub", json=envelope)
        assert resp.status_code == 500

    def test_timeout_error_returns_500(self, client, fake_service):
        fake_service.process_unfurl_job = AsyncMock(
            side_effect=httpx.TimeoutException("read timeout")
        )
        envelope = _make_pubsub_envelope(_valid_job_dict())
        resp = client.post("/pubsub", json=envelope)
        assert resp.status_code == 500

    def test_json_decode_error_is_permanent(self, client):
        raw_data = base64.b64encode(b"not-valid-json{{{").decode()
        envelope = {
            "message": {
                "data": raw_data,
                "messageId": "bad-json-msg",
                "publishTime": "2024-01-01T00:00:00Z",
            },
            "subscription": "projects/test/subscriptions/test",
        }
        resp = client.post("/pubsub", json=envelope)
        assert resp.status_code == 200

    def test_key_error_is_permanent(self, client):
        incomplete = {"job_id": "incomplete-job"}
        envelope = _make_pubsub_envelope(incomplete)
        resp = client.post("/pubsub", json=envelope)
        assert resp.status_code == 200


class TestPoisonPillMessages:
    def test_invalid_base64_returns_200(self, client):
        envelope = {
            "message": {
                "data": "!!!not-base64!!!",
                "messageId": "poison-1",
                "publishTime": "2024-01-01T00:00:00Z",
            },
            "subscription": "projects/test/subscriptions/test",
        }
        resp = client.post("/pubsub", json=envelope)
        assert resp.status_code == 200

    def test_invalid_json_after_decode_returns_200(self, client):
        raw_data = base64.b64encode(b"not json at all").decode()
        envelope = {
            "message": {
                "data": raw_data,
                "messageId": "poison-2",
                "publishTime": "2024-01-01T00:00:00Z",
            },
            "subscription": "projects/test/subscriptions/test",
        }
        resp = client.post("/pubsub", json=envelope)
        assert resp.status_code == 200

    def test_missing_required_fields_returns_200(self, client):
        partial = {"job_id": "partial", "channel_id": "C123"}
        envelope = _make_pubsub_envelope(partial)
        resp = client.post("/pubsub", json=envelope)
        assert resp.status_code == 200

    def test_valid_message_processed_successfully(self, client, fake_service):
        fake_service.process_unfurl_job = AsyncMock(return_value=None)
        envelope = _make_pubsub_envelope(_valid_job_dict())
        resp = client.post("/pubsub", json=envelope)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        fake_service.process_unfurl_job.assert_called_once()


class TestErrorDetailLeaking:
    def test_error_response_no_internal_details(self, client, fake_service):
        fake_service.process_unfurl_job = AsyncMock(
            side_effect=ConnectionError("secret-internal-db-host:5432 refused")
        )
        envelope = _make_pubsub_envelope(_valid_job_dict())
        resp = client.post("/pubsub", json=envelope)
        body = resp.text
        assert "secret-internal-db-host" not in body
        assert "5432" not in body
        assert "refused" not in body
        assert resp.status_code == 500

    def test_permanent_error_response_no_internal_details(self, client, fake_service):
        fake_service.process_unfurl_job = AsyncMock(
            side_effect=ValueError("secret internal parsing detail xyz")
        )
        envelope = _make_pubsub_envelope(_valid_job_dict())
        resp = client.post("/pubsub", json=envelope)
        body = resp.text
        assert "secret internal parsing detail" not in body

    def test_error_logged_with_details(self, client, fake_service, caplog):
        fake_service.process_unfurl_job = AsyncMock(
            side_effect=ConnectionError("detailed-internal-error-info")
        )
        envelope = _make_pubsub_envelope(_valid_job_dict())
        with caplog.at_level(logging.ERROR):
            resp = client.post("/pubsub", json=envelope)
        assert "detailed-internal-error-info" in caplog.text
        assert "detailed-internal-error-info" not in resp.text
