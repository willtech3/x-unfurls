"""Data Transfer Objects for X unfurl jobs."""

from dataclasses import dataclass


@dataclass
class XUnfurlJobDto:
    """DTO for X unfurl generation job."""

    job_id: str
    channel_id: str
    message_ts: str
    team_id: str
    original_url: str
    canonical_url: str
    status_id: str
    action: str  # "generate" | "refresh" | "summarize"
    trace_id: str = ""
    unfurl_id: str | None = None
    created_at: str = ""
