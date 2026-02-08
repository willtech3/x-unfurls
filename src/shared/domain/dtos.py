"""Data Transfer Objects for X unfurl jobs."""

from dataclasses import dataclass
from typing import Literal

# CQ-1: Constrained action type instead of bare str
ActionType = Literal["generate", "refresh", "summarize", "ask_grok"]


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
    action: ActionType
    trace_id: str = ""
    unfurl_id: str | None = None
    created_at: str = ""
    user_prompt: str = ""
    user_id: str = ""
