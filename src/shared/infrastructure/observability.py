"""OpenTelemetry observability setup for metrics, traces, and health checks.

Provides a single setup_observability() function that configures:
- Distributed tracing (Cloud Trace in GCP, console/noop in dev)
- Metrics (request counts, durations, error rates)
- FastAPI auto-instrumentation

Usage:
    from shared.infrastructure.observability import setup_observability
    setup_observability(service_name="webhook")
"""

import logging

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

logger = logging.getLogger(__name__)

# Module-level references set during setup
_tracer: trace.Tracer | None = None
_meter: metrics.Meter | None = None

# Metric instruments
_request_counter: metrics.Counter | None = None
_request_duration: metrics.Histogram | None = None
_job_counter: metrics.Counter | None = None
_job_duration: metrics.Histogram | None = None


def setup_observability(
    service_name: str = "x-unfurls",
    use_gcp_exporter: bool = True,
) -> None:
    """Configure OpenTelemetry tracing and metrics.

    Args:
        service_name: Name of the service for resource attribution
        use_gcp_exporter: If True, export to GCP Cloud Trace/Monitoring.
                          If False, use noop exporters (for dev/test).
    """
    global _tracer, _meter
    global _request_counter, _request_duration, _job_counter, _job_duration

    resource = Resource.create({"service.name": service_name})

    # Tracing setup
    tracer_provider = TracerProvider(resource=resource)

    if use_gcp_exporter:
        try:
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            tracer_provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter()))
        except Exception:
            logger.warning("Could not initialize GCP trace exporter, using noop")

    trace.set_tracer_provider(tracer_provider)
    _tracer = trace.get_tracer(service_name)

    # Metrics setup
    meter_provider = MeterProvider(resource=resource)
    metrics.set_meter_provider(meter_provider)
    _meter = metrics.get_meter(service_name)

    # Create metric instruments
    _request_counter = _meter.create_counter(
        "http.server.request.count",
        description="Total HTTP requests received",
    )
    _request_duration = _meter.create_histogram(
        "http.server.request.duration",
        description="HTTP request duration in milliseconds",
        unit="ms",
    )
    _job_counter = _meter.create_counter(
        "worker.job.count",
        description="Total jobs processed by the worker",
    )
    _job_duration = _meter.create_histogram(
        "worker.job.duration",
        description="Job processing duration in milliseconds",
        unit="ms",
    )


def get_tracer() -> trace.Tracer:
    """Get the configured tracer instance."""
    if _tracer is None:
        return trace.get_tracer("x-unfurls-fallback")
    return _tracer


def get_meter() -> metrics.Meter:
    """Get the configured meter instance."""
    if _meter is None:
        return metrics.get_meter("x-unfurls-fallback")
    return _meter


def record_request(method: str, path: str, status_code: int, duration_ms: float) -> None:
    """Record an HTTP request metric.

    Args:
        method: HTTP method (GET, POST, etc.)
        path: Request path
        status_code: Response status code
        duration_ms: Request duration in milliseconds
    """
    attrs: dict[str, str | int] = {
        "http.method": method,
        "http.route": path,
        "http.status_code": status_code,
    }
    if _request_counter:
        _request_counter.add(1, attrs)
    if _request_duration:
        _request_duration.record(duration_ms, attrs)


def record_job_processed(action: str, status: str, duration_ms: float) -> None:
    """Record a job processing metric.

    Args:
        action: Job action type (generate, summarize, refresh)
        status: Job outcome (ok, permanent_error, transient_error)
        duration_ms: Processing duration in milliseconds
    """
    attrs = {"job.action": action, "job.status": status}
    if _job_counter:
        _job_counter.add(1, attrs)
    if _job_duration:
        _job_duration.record(duration_ms, attrs)
