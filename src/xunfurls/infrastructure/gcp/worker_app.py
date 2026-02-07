"""Cloud Run worker application for processing Pub/Sub push messages."""

import base64
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from shared.domain.dtos import XUnfurlJobDto
from shared.infrastructure.logging import log_event, setup_logging, trace_id_var
from shared.infrastructure.observability import (
    get_tracer,
    record_job_processed,
    setup_observability,
)
from xunfurls.app import create_managed_unfurl_service

setup_logging()
logger = logging.getLogger(__name__)

# Initialize observability (noop exporters when GCP creds are absent)
setup_observability(
    service_name="x-unfurls-worker",
    use_gcp_exporter=bool(os.environ.get("GOOGLE_CLOUD_PROJECT")),
)

# Errors that indicate a permanently unprocessable message.
# Returning 200 for these ACKs the message so Pub/Sub does not retry.
_PERMANENT_ERRORS = (ValueError, json.JSONDecodeError, KeyError, TypeError)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifecycle: create service on startup, close on shutdown."""
    async with create_managed_unfurl_service() as service:
        app.state.unfurl_service = service
        logger.info("Worker started, unfurl service ready")
        yield
    logger.info("Worker shut down, resources released")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "worker"}


@app.get("/health/ready")
async def health_ready(request: Request) -> dict[str, str]:
    """Readiness check verifying the unfurl service is initialized."""
    service = getattr(request.app.state, "unfurl_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    return {"status": "ready", "service": "worker"}


@app.post("/pubsub")
async def process_pubsub_message(request: Request) -> dict[str, str]:
    """Handle Pub/Sub push messages.

    Pub/Sub sends messages in this format:
    {
        "message": {
            "data": "<base64-encoded-job-json>",
            "messageId": "...",
            "publishTime": "..."
        },
        "subscription": "projects/.../subscriptions/..."
    }

    Return 2xx for success (message acknowledged).
    Return 5xx for failure (message will be retried).

    Error classification:
    - Permanent errors (bad payload, missing fields) -> 200 (ACK, don't retry)
    - Transient errors (timeouts, connectivity) -> 500 (NACK, retry)

    Args:
        request: FastAPI request

    Returns:
        Success or permanent-error response (200), or raises HTTPException (500)
    """
    envelope = await request.json()

    if not envelope or "message" not in envelope:
        raise HTTPException(status_code=400, detail="Invalid Pub/Sub message format")

    message = envelope["message"]
    message_id = message.get("messageId", "unknown")

    if "data" not in message:
        raise HTTPException(status_code=400, detail="Missing message data")

    # ------------------------------------------------------------------
    # SF-4: Validate and decode the message; poison pills get ACKed (200)
    # ------------------------------------------------------------------
    try:
        job_data = base64.b64decode(message["data"]).decode("utf-8")
        job_dict = json.loads(job_data)
        job = XUnfurlJobDto(**job_dict)
    except Exception as e:
        logger.error("Invalid message format, ACKing to prevent retry: %s", e, exc_info=True)
        return {"status": "invalid_message", "messageId": message_id}

    # Set trace context
    trace_id_var.set(job.trace_id or job.job_id)

    log_event(
        logger,
        logging.INFO,
        "Processing X unfurl job",
        event="job_received",
        job_id=job.job_id,
        status_id=job.status_id,
        action=job.action,
        message_id=message_id,
    )

    # ------------------------------------------------------------------
    # BUG-1: Use the singleton service from app.state (created in lifespan)
    # SF-1: Classify processing errors as permanent vs transient
    # CQ-5: Never leak internal error details in the response
    # ------------------------------------------------------------------
    tracer = get_tracer()
    try:
        unfurl_service = request.app.state.unfurl_service

        start_time = time.monotonic()
        with tracer.start_as_current_span(
            "process_unfurl_job",
            attributes={
                "job.id": job.job_id,
                "job.action": job.action,
                "job.status_id": job.status_id,
            },
        ):
            await unfurl_service.process_unfurl_job(job)
        duration_ms = (time.monotonic() - start_time) * 1000

        record_job_processed(action=job.action, status="ok", duration_ms=duration_ms)

        log_event(
            logger,
            logging.INFO,
            "Job completed",
            event="job_completed",
            job_id=job.job_id,
            duration_ms=int(duration_ms),
        )

        return {"status": "ok", "messageId": message_id}

    except _PERMANENT_ERRORS as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        record_job_processed(action=job.action, status="permanent_error", duration_ms=duration_ms)
        logger.error(
            "Permanent error processing job %s, ACKing message: %s",
            job.job_id,
            e,
            exc_info=True,
        )
        return {"status": "permanent_error", "messageId": message_id}

    except Exception as e:
        duration_ms = (time.monotonic() - start_time) * 1000
        record_job_processed(action=job.action, status="transient_error", duration_ms=duration_ms)
        logger.error(
            "Transient error processing job %s, NACKing for retry: %s",
            job.job_id,
            e,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal processing error") from e
