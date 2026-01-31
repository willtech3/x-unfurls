"""Cloud Run worker application for processing Pub/Sub push messages."""

import base64
import json
import logging
import time

from fastapi import FastAPI, HTTPException, Request

from shared.domain.dtos import XUnfurlJobDto
from shared.infrastructure.logging import log_event, setup_logging, trace_id_var
from xunfurls.app import create_unfurl_service

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI()


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "worker"}


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

    Args:
        request: FastAPI request

    Returns:
        Success response
    """
    try:
        envelope = await request.json()

        if not envelope or "message" not in envelope:
            raise HTTPException(status_code=400, detail="Invalid Pub/Sub message format")

        message = envelope["message"]
        message_id = message.get("messageId", "unknown")

        if "data" not in message:
            raise HTTPException(status_code=400, detail="Missing message data")

        # Decode and parse job
        job_data = base64.b64decode(message["data"]).decode("utf-8")
        job_dict = json.loads(job_data)
        job = XUnfurlJobDto(**job_dict)

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

        # Process the job
        unfurl_service = create_unfurl_service()

        start_time = time.monotonic()
        await unfurl_service.process_unfurl_job(job)
        duration_ms = int((time.monotonic() - start_time) * 1000)

        log_event(
            logger,
            logging.INFO,
            "Job completed",
            event="job_completed",
            job_id=job.job_id,
            duration_ms=duration_ms,
        )

        return {"status": "ok", "messageId": message_id}

    except Exception as e:
        logger.exception(f"Error processing Pub/Sub message: {e}")
        # Return 500 to trigger Pub/Sub retry
        raise HTTPException(status_code=500, detail=str(e)) from e
