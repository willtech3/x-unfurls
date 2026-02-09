"""Tests for observability: OpenTelemetry setup, health checks, metrics (ARCH-6, ARCH-8, SF-5)."""

from __future__ import annotations

from shared.infrastructure.observability import (
    get_meter,
    get_tracer,
    record_job_processed,
    record_request,
    setup_observability,
)


class _CounterSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict[str, str | int]]] = []

    def add(self, value: int, attrs: dict[str, str | int]) -> None:
        self.calls.append((value, attrs))


class _HistogramSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[float, dict[str, str | int]]] = []

    def record(self, value: float, attrs: dict[str, str | int]) -> None:
        self.calls.append((value, attrs))


class TestObservabilitySetup:
    """ARCH-6: OTel initialization should work without GCP credentials."""

    def test_setup_returns_without_error(self) -> None:
        """Setup should not raise even outside GCP."""
        setup_observability(service_name="test-service", use_gcp_exporter=False)

    def test_get_tracer_returns_tracer(self) -> None:
        setup_observability(service_name="test-service", use_gcp_exporter=False)
        tracer = get_tracer()
        assert tracer is not None

    def test_get_meter_returns_meter(self) -> None:
        setup_observability(service_name="test-service", use_gcp_exporter=False)
        meter = get_meter()
        assert meter is not None


class TestMetricsRecording:
    """ARCH-6: Custom metrics should be recordable without error."""

    def test_record_request_emits_counter_and_histogram(self, monkeypatch) -> None:
        from shared.infrastructure import observability

        counter = _CounterSpy()
        histogram = _HistogramSpy()
        monkeypatch.setattr(observability, "_request_counter", counter)
        monkeypatch.setattr(observability, "_request_duration", histogram)

        record_request(method="POST", path="/pubsub", status_code=200, duration_ms=42.5)

        assert counter.calls == [
            (1, {"http.method": "POST", "http.route": "/pubsub", "http.status_code": 200})
        ]
        assert histogram.calls == [
            (42.5, {"http.method": "POST", "http.route": "/pubsub", "http.status_code": 200})
        ]

    def test_record_job_processed_emits_counter_and_histogram(self, monkeypatch) -> None:
        from shared.infrastructure import observability

        counter = _CounterSpy()
        histogram = _HistogramSpy()
        monkeypatch.setattr(observability, "_job_counter", counter)
        monkeypatch.setattr(observability, "_job_duration", histogram)

        record_job_processed(action="generate", status="ok", duration_ms=1500.0)

        expected_attrs = {"job.action": "generate", "job.status": "ok"}
        assert counter.calls == [(1, expected_attrs)]
        assert histogram.calls == [(1500.0, expected_attrs)]

    def test_record_job_processed_emits_error_status(self, monkeypatch) -> None:
        from shared.infrastructure import observability

        counter = _CounterSpy()
        histogram = _HistogramSpy()
        monkeypatch.setattr(observability, "_job_counter", counter)
        monkeypatch.setattr(observability, "_job_duration", histogram)

        record_job_processed(action="summarize", status="permanent_error", duration_ms=50.0)

        expected_attrs = {"job.action": "summarize", "job.status": "permanent_error"}
        assert counter.calls == [(1, expected_attrs)]
        assert histogram.calls == [(50.0, expected_attrs)]


class TestHealthCheckReady:
    """ARCH-8: /health/ready should verify dependencies."""

    def test_worker_health_ready_when_service_present(self) -> None:
        from contextlib import asynccontextmanager
        from unittest.mock import patch as _patch

        from starlette.testclient import TestClient

        from xunfurls.application.presenters.x_unfurl_blocks import XUnfurlBlocksBuilder
        from xunfurls.application.services.x_unfurl_service import XUnfurlService

        class FakeXAI:
            async def fetch_post_snapshot(self, *a, **kw):  # noqa: ANN001, ANN002, ANN003
                pass

            async def close(self) -> None:
                pass

        class FakeSlack:
            async def unfurl_links(self, *a, **kw):  # noqa: ANN001, ANN002, ANN003
                pass

            async def close(self) -> None:
                pass

        service = XUnfurlService(
            x_repo=FakeXAI(), slack_repo=FakeSlack(), blocks_builder=XUnfurlBlocksBuilder()
        )

        @asynccontextmanager
        async def _managed():  # type: ignore[override]
            yield service

        with _patch(
            "xunfurls.infrastructure.gcp.worker_app.create_managed_unfurl_service",
            _managed,
        ):
            from xunfurls.infrastructure.gcp.worker_app import app

            with TestClient(app) as client:
                resp = client.get("/health/ready")
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "ready"
                assert data["service"] == "worker"

    def test_webhook_health_ready_returns_ready(self) -> None:
        from starlette.testclient import TestClient

        from xunfurls.infrastructure.gcp.webhook_app import app

        client = TestClient(app)
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["service"] == "webhook"
