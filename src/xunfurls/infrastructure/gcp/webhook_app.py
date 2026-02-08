"""Cloud Run webhook handler for Slack events."""

import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, HTTPException, Request

from shared.domain.dtos import XUnfurlJobDto
from shared.domain.repositories.job_queue_repository import JobQueueProducer
from shared.infrastructure.logging import ensure_trace_id, log_event, setup_logging
from xunfurls.infrastructure.gcp.pubsub_job_queue import PubSubJobQueue
from xunfurls.infrastructure.gcp.slack_client import SlackHttpClient

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="X Unfurls Webhook",
    description="Cloud Run webhook handler for Slack link_shared events",
    version="0.1.0",
)

# CQ-3: Injectable job queue (supports DI for testing)
_job_queue: JobQueueProducer | None = None

# Lazy-initialized Slack client for modal interactions
_slack_client: SlackHttpClient | None = None


def set_job_queue(queue: JobQueueProducer) -> None:
    """Inject a job queue instance (useful for testing).

    Args:
        queue: A JobQueueProducer implementation to use
    """
    global _job_queue
    _job_queue = queue


def get_job_queue() -> JobQueueProducer:
    """Get or create the job queue instance."""
    global _job_queue
    if _job_queue is None:
        _job_queue = PubSubJobQueue()
    return _job_queue


def set_slack_client(client: SlackHttpClient) -> None:
    """Inject a Slack client instance (useful for testing)."""
    global _slack_client
    _slack_client = client


def get_slack_client() -> SlackHttpClient:
    """Get or create the Slack client instance."""
    global _slack_client
    if _slack_client is None:
        _slack_client = SlackHttpClient()
    return _slack_client


# X domain patterns
X_DOMAINS = {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}
STATUS_PATTERN = re.compile(r"/(?:status|statuses)/(\d+)")
# Slack wraps URLs as <URL> or <URL|display> in message text
SLACK_URL_PATTERN = re.compile(r"<(https?://[^|>]+)(?:\|[^>]*)?>")
# X/Twitter URL pattern for matching in message text
X_URL_PATTERN = re.compile(r"https?://(?:www\.)?(?:x\.com|twitter\.com)/\w+/status(?:es)?/\d+")


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
    # Check timestamp to prevent replay attacks (BUG-2: handle missing/invalid)
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False
    if abs(time.time() - ts) > 300:
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
    # Extract username from path if possible (BUG-5: check for empty path)
    path_parts = parsed.path.strip("/").split("/")
    if path_parts and path_parts[0]:
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


@app.get("/health/ready")
async def health_ready() -> dict[str, str]:
    """Readiness check with dependency verification."""
    return {"status": "ready", "service": "webhook"}


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
        elif event.get("type") == "message" and not event.get("subtype"):
            await handle_message(payload, event)

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


def extract_urls_from_text(text: str) -> list[str]:
    """Extract X/Twitter URLs from Slack message text.

    Slack wraps URLs as <URL> or <URL|display> in message text.

    Args:
        text: Raw Slack message text

    Returns:
        List of X/Twitter URLs found in the text
    """
    urls = SLACK_URL_PATTERN.findall(text)
    return [url for url in urls if is_x_link(url) and extract_status_id(url)]


async def handle_message(payload: dict[str, Any], event: dict[str, Any]) -> None:
    """Handle message events by detecting X links and enqueueing unfurl jobs.

    Only processes regular user messages (no subtypes) to avoid bot loops.

    Args:
        payload: Full Slack event payload
        event: The message event
    """
    # Skip bot messages to prevent infinite loops
    if event.get("bot_id"):
        return

    text = event.get("text", "")
    if not text:
        return

    x_urls = extract_urls_from_text(text)
    if not x_urls:
        return

    team_id = payload.get("team_id", "")
    channel_id = event.get("channel", "")
    message_ts = event.get("ts", "")

    # Deduplicate by status_id to avoid multiple jobs for the same post
    seen_status_ids: set[str] = set()

    for url in x_urls:
        status_id = extract_status_id(url)
        if not status_id or status_id in seen_status_ids:
            continue
        seen_status_ids.add(status_id)

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
            "Enqueued X unfurl job from message",
            event="message_job_enqueued",
            job_id=job.job_id,
            status_id=status_id,
            message_id=message_id,
        )


@app.post("/slack/interactive")
async def slack_interactive(request: Request) -> dict[str, Any]:
    """Handle Slack interactive component callbacks.

    Processes button clicks and modal submissions.
    Slack sends the payload as form-encoded: payload=<JSON>.

    Args:
        request: FastAPI request

    Returns:
        Response for Slack
    """
    ensure_trace_id()

    # CQ-4: Validate Slack signature on interactive endpoint
    body = await request.body()
    signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "")
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not validate_slack_signature(body, timestamp, signature, signing_secret):
        log_event(logger, logging.WARNING, "Invalid Slack signature", event="auth_failed")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse the interactive payload (form-encoded as payload=JSON)
    form_data = parse_qs(body.decode("utf-8"))
    payload_str = form_data.get("payload", [""])[0]
    if not payload_str:
        return {"ok": True}

    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError:
        return {"ok": True}

    # Dispatch on payload type
    payload_type = payload.get("type")
    if payload_type == "block_actions":
        await _handle_block_actions(payload)
    elif payload_type == "view_submission":
        await _handle_view_submission(payload)

    return {"ok": True}


async def _handle_block_actions(payload: dict[str, Any]) -> None:
    """Dispatch block_actions interactive payloads.

    Args:
        payload: Parsed Slack interactive payload
    """
    actions = payload.get("actions", [])
    if not actions:
        return

    action = actions[0]
    action_id = action.get("action_id", "")

    if action_id == "x_unfurl_ask_grok":
        await _handle_ask_grok_action(payload, action)
    elif action_id == "x_unfurl_summarize":
        # Legacy: still handle old summarize action
        await _handle_summarize_action(payload, action)


async def _handle_ask_grok_action(payload: dict[str, Any], action: dict[str, Any]) -> None:
    """Handle 'Ask Grok' button click by opening a modal.

    Uses the trigger_id (valid for 3s) to open a Slack modal where
    the user can type their follow-up question.

    Args:
        payload: Full interactive payload (contains trigger_id)
        action: The specific action that was triggered
    """
    trigger_id = payload.get("trigger_id", "")
    if not trigger_id:
        log_event(logger, logging.WARNING, "No trigger_id", event="ask_grok_no_trigger")
        return

    canonical_url = action.get("value", "")
    channel_id = payload.get("channel", {}).get("id", "")
    message_ts = payload.get("container", {}).get("message_ts", "")

    # Pack context into private_metadata so we can retrieve it on submission
    private_metadata = json.dumps(
        {
            "canonical_url": canonical_url,
            "channel_id": channel_id,
            "message_ts": message_ts,
        }
    )

    modal_view: dict[str, Any] = {
        "type": "modal",
        "callback_id": "ask_grok_modal",
        "title": {"type": "plain_text", "text": "Ask Grok"},
        "submit": {"type": "plain_text", "text": "Ask"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": private_metadata,
        "blocks": [
            {
                "type": "input",
                "block_id": "question_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "question_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "What would you like to know about this post?",
                    },
                },
                "label": {"type": "plain_text", "text": "Your question"},
            }
        ],
    }

    slack = get_slack_client()
    await slack.open_modal(trigger_id, modal_view)

    log_event(
        logger,
        logging.INFO,
        "Opened Ask Grok modal",
        event="ask_grok_modal_opened",
        canonical_url=canonical_url,
    )


async def _handle_view_submission(payload: dict[str, Any]) -> None:
    """Handle modal form submissions.

    Args:
        payload: Parsed Slack view_submission payload
    """
    callback_id = payload.get("view", {}).get("callback_id", "")

    if callback_id == "ask_grok_modal":
        await _handle_ask_grok_submission(payload)


async def _handle_ask_grok_submission(payload: dict[str, Any]) -> None:
    """Handle Ask Grok modal submission.

    Extracts the user's question and enqueues an ask_grok job.

    Args:
        payload: Full view_submission payload
    """
    view = payload.get("view", {})

    # Extract the question from form values
    values = view.get("state", {}).get("values", {})
    question_block = values.get("question_block", {})
    question_input = question_block.get("question_input", {})
    user_prompt = question_input.get("value", "").strip()

    if not user_prompt:
        return

    # Extract context from private_metadata
    try:
        metadata = json.loads(view.get("private_metadata", "{}"))
    except json.JSONDecodeError:
        return

    canonical_url = metadata.get("canonical_url", "")
    channel_id = metadata.get("channel_id", "")
    message_ts = metadata.get("message_ts", "")

    status_id = extract_status_id(canonical_url)
    if not status_id:
        log_event(
            logger,
            logging.WARNING,
            "Could not extract status ID from ask_grok submission",
            event="ask_grok_invalid_url",
            url=canonical_url,
        )
        return

    user_id = payload.get("user", {}).get("id", "")

    job = XUnfurlJobDto(
        job_id=str(uuid.uuid4()),
        channel_id=channel_id,
        message_ts=message_ts,
        team_id="",
        original_url=canonical_url,
        canonical_url=canonical_url,
        status_id=status_id,
        action="ask_grok",
        trace_id=str(uuid.uuid4()),
        user_prompt=user_prompt,
        user_id=user_id,
    )

    message_id = await get_job_queue().enqueue_job(job)

    log_event(
        logger,
        logging.INFO,
        "Enqueued Ask Grok job",
        event="ask_grok_enqueued",
        job_id=job.job_id,
        status_id=status_id,
        message_id=message_id,
        user_id=user_id,
    )


async def _handle_summarize_action(payload: dict[str, Any], action: dict[str, Any]) -> None:
    """Handle legacy 'Summarize with Grok' button click.

    Enqueues a summarize job for the post identified by the button value.

    Args:
        payload: Full interactive payload (contains channel/message context)
        action: The specific action that was triggered
    """
    canonical_url = action.get("value", "")
    status_id = extract_status_id(canonical_url)
    if not status_id:
        log_event(
            logger,
            logging.WARNING,
            "Could not extract status ID from summarize action",
            event="summarize_invalid_url",
            url=canonical_url,
        )
        return

    channel_id = payload.get("channel", {}).get("id", "")
    message_ts = payload.get("container", {}).get("message_ts", "")

    job = XUnfurlJobDto(
        job_id=str(uuid.uuid4()),
        channel_id=channel_id,
        message_ts=message_ts,
        team_id="",
        original_url=canonical_url,
        canonical_url=canonical_url,
        status_id=status_id,
        action="summarize",
        trace_id=str(uuid.uuid4()),
    )

    message_id = await get_job_queue().enqueue_job(job)

    log_event(
        logger,
        logging.INFO,
        "Enqueued Grok summarize job",
        event="summarize_enqueued",
        job_id=job.job_id,
        status_id=status_id,
        message_id=message_id,
    )
