"""Cloud Run webhook handler for Slack events."""

import hashlib
import hmac
import logging
import os
import re
import time
import uuid
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request

from shared.domain.dtos import XUnfurlJobDto
from shared.infrastructure.logging import ensure_trace_id, log_event, setup_logging
from xunfurls.infrastructure.gcp.pubsub_job_queue import PubSubJobQueue

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="X Unfurls Webhook",
    description="Cloud Run webhook handler for Slack link_shared events",
    version="0.1.0",
)

# Lazy-initialized job queue (created on first use)
_job_queue: PubSubJobQueue | None = None


def get_job_queue() -> PubSubJobQueue:
    """Get or create the job queue instance."""
    global _job_queue
    if _job_queue is None:
        _job_queue = PubSubJobQueue()
    return _job_queue


# X domain patterns
X_DOMAINS = {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}
STATUS_PATTERN = re.compile(r"/(?:status|statuses)/(\d+)")


def validate_slack_signature(
    body: bytes,
    timestamp: str,
    signature: str,
    signing_secret: str,
) -> bool:
    """Validate Slack request signature.

    Args:
        body: Raw request body
        timestamp: X-Slack-Request-Timestamp header
        signature: X-Slack-Signature header
        signing_secret: Slack signing secret

    Returns:
        True if signature is valid
    """
    # Check timestamp to prevent replay attacks
    if abs(time.time() - int(timestamp)) > 300:
        return False

    # Compute expected signature
    basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected = (
        "v0="
        + hmac.new(
            signing_secret.encode(),
            basestring.encode(),
            hashlib.sha256,
        ).hexdigest()
    )

    return hmac.compare_digest(expected, signature)


def extract_status_id(url: str) -> str | None:
    """Extract X status ID from URL.

    Args:
        url: X/Twitter URL

    Returns:
        Status ID or None if not found
    """
    match = STATUS_PATTERN.search(url)
    return match.group(1) if match else None


def canonicalize_url(url: str, status_id: str) -> str:
    """Create canonical X URL.

    Args:
        url: Original URL
        status_id: Extracted status ID

    Returns:
        Canonical URL
    """
    parsed = urlparse(url)
    # Extract username from path if possible
    path_parts = parsed.path.strip("/").split("/")
    if len(path_parts) >= 1:
        username = path_parts[0]
        return f"https://x.com/{username}/status/{status_id}"
    return f"https://x.com/i/status/{status_id}"


def is_x_link(url: str) -> bool:
    """Check if URL is from X/Twitter.

    Args:
        url: URL to check

    Returns:
        True if URL is from X/Twitter
    """
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower() in X_DOMAINS
    except Exception:
        return False


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "webhook"}


@app.post("/slack/events")
async def slack_events(request: Request) -> dict[str, Any]:
    """Handle Slack event callbacks.

    Args:
        request: FastAPI request

    Returns:
        Response for Slack
    """
    ensure_trace_id()

    body = await request.body()

    # Validate signature
    signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "")
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not validate_slack_signature(body, timestamp, signature, signing_secret):
        log_event(logger, logging.WARNING, "Invalid Slack signature", event="auth_failed")
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()

    # Handle URL verification challenge
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    # Handle event callbacks
    if payload.get("type") == "event_callback":
        event = payload.get("event", {})

        if event.get("type") == "link_shared":
            await handle_link_shared(payload, event)

    return {"ok": True}


async def handle_link_shared(payload: dict[str, Any], event: dict[str, Any]) -> None:
    """Handle link_shared event by enqueueing unfurl jobs.

    Args:
        payload: Full Slack event payload
        event: The link_shared event
    """
    team_id = payload.get("team_id", "")
    channel_id = event.get("channel", "")
    message_ts = event.get("message_ts", "")
    links = event.get("links", [])

    for link in links:
        url = link.get("url", "")

        if not is_x_link(url):
            continue

        status_id = extract_status_id(url)
        if not status_id:
            log_event(
                logger,
                logging.DEBUG,
                "Could not extract status ID from URL",
                event="url_parse_failed",
                url=url,
            )
            continue

        canonical_url = canonicalize_url(url, status_id)

        job = XUnfurlJobDto(
            job_id=str(uuid.uuid4()),
            channel_id=channel_id,
            message_ts=message_ts,
            team_id=team_id,
            original_url=url,
            canonical_url=canonical_url,
            status_id=status_id,
            action="generate",
            trace_id=str(uuid.uuid4()),
        )

        message_id = await get_job_queue().enqueue_job(job)

        log_event(
            logger,
            logging.INFO,
            "Enqueued X unfurl job",
            event="job_enqueued",
            job_id=job.job_id,
            status_id=status_id,
            message_id=message_id,
        )


@app.post("/slack/interactive")
async def slack_interactive(request: Request) -> dict[str, Any]:
    """Handle Slack interactive component callbacks.

    Args:
        request: FastAPI request

    Returns:
        Response for Slack
    """
    ensure_trace_id()

    # TODO: Implement action button handlers (refresh, summarize)

    return {"ok": True}
