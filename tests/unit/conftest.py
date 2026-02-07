"""Unit test fixtures: fake repositories and entity factories."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from shared.domain.dtos import XUnfurlJobDto
from shared.domain.repositories.job_queue_repository import JobQueueProducer
from shared.domain.repositories.slack_repository import SlackUnfurlRepository
from xunfurls.domain.entities import (
    XMedia,
    XMetrics,
    XPostSnapshot,
    XReply,
    XStatusRef,
)
from xunfurls.domain.repositories.x_repository import FetchMode, XRepository

# ---------------------------------------------------------------------------
# Fake repositories (record calls for assertion)
# ---------------------------------------------------------------------------


@dataclass
class FakeXRepository:
    """In-memory fake that satisfies the XRepository Protocol.

    Attributes:
        snapshots: Pre-loaded mapping of (status_id, mode) -> snapshot.
        fetch_calls: Every call recorded as (status_ref, mode) tuples.
        default_snapshot: Returned when no matching entry exists.
    """

    snapshots: dict[tuple[str, FetchMode], XPostSnapshot] = field(default_factory=dict)
    fetch_calls: list[tuple[XStatusRef, FetchMode]] = field(default_factory=list)
    default_snapshot: XPostSnapshot | None = None

    def set_response(
        self, status_id: str, snapshot: XPostSnapshot, mode: FetchMode = FetchMode.RICH
    ) -> None:
        self.snapshots[(status_id, mode)] = snapshot

    async def fetch_post_snapshot(self, status_ref: XStatusRef, mode: FetchMode) -> XPostSnapshot:
        self.fetch_calls.append((status_ref, mode))
        key = (status_ref.status_id, mode)
        if key in self.snapshots:
            return self.snapshots[key]
        for (sid, _m), snap in self.snapshots.items():
            if sid == status_ref.status_id:
                return snap
        if self.default_snapshot is not None:
            return self.default_snapshot
        raise LookupError(
            f"FakeXRepository has no snapshot for status_id={status_ref.status_id!r}, "
            f"mode={mode!r}. Register one via set_response() or default_snapshot."
        )


assert isinstance(FakeXRepository(), XRepository), (
    "FakeXRepository must satisfy XRepository Protocol"
)


@dataclass
class UnfurlCall:
    """Record of a single unfurl_links invocation."""

    channel_id: str
    message_ts: str
    unfurls: dict[str, dict[str, Any]]


@dataclass
class FakeSlackUnfurlRepository:
    """In-memory fake that satisfies the SlackUnfurlRepository Protocol."""

    unfurl_calls: list[UnfurlCall] = field(default_factory=list)
    should_raise: Exception | None = None

    async def unfurl_links(
        self,
        channel_id: str,
        message_ts: str,
        unfurls: dict[str, dict[str, Any]],
    ) -> None:
        self.unfurl_calls.append(UnfurlCall(channel_id, message_ts, unfurls))
        if self.should_raise is not None:
            raise self.should_raise


assert isinstance(FakeSlackUnfurlRepository(), SlackUnfurlRepository), (
    "FakeSlackUnfurlRepository must satisfy SlackUnfurlRepository Protocol"
)


@dataclass
class EnqueueCall:
    """Record of a single enqueue_job invocation."""

    job: XUnfurlJobDto
    returned_message_id: str


@dataclass
class FakeJobQueueProducer:
    """In-memory fake that satisfies the JobQueueProducer Protocol."""

    enqueue_calls: list[EnqueueCall] = field(default_factory=list)
    message_id_factory: Callable[[], str] = field(default=lambda: lambda: uuid4().hex)
    should_raise: Exception | None = None

    async def enqueue_job(self, job: XUnfurlJobDto) -> str:
        if self.should_raise is not None:
            raise self.should_raise
        msg_id = self.message_id_factory()
        self.enqueue_calls.append(EnqueueCall(job=job, returned_message_id=msg_id))
        return msg_id


assert isinstance(FakeJobQueueProducer(), JobQueueProducer), (
    "FakeJobQueueProducer must satisfy JobQueueProducer Protocol"
)


# ---------------------------------------------------------------------------
# Fake repository fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_x_repo() -> FakeXRepository:
    return FakeXRepository()


@pytest.fixture
def fake_slack() -> FakeSlackUnfurlRepository:
    return FakeSlackUnfurlRepository()


@pytest.fixture
def fake_queue() -> FakeJobQueueProducer:
    return FakeJobQueueProducer()


# ---------------------------------------------------------------------------
# Entity / DTO factory fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_metrics() -> Callable[..., XMetrics]:
    def _factory(
        *,
        likes: int = 42,
        reposts: int = 7,
        replies: int = 3,
        views: int | None = 1200,
        bookmarks: int | None = 5,
    ) -> XMetrics:
        return XMetrics(
            likes=likes,
            reposts=reposts,
            replies=replies,
            views=views,
            bookmarks=bookmarks,
        )

    return _factory


@pytest.fixture
def make_media() -> Callable[..., XMedia]:
    def _factory(
        *,
        type: str = "image",
        url: str = "https://pbs.twimg.com/media/test_image.jpg",
        thumbnail_url: str | None = None,
        alt_text: str | None = "A test image",
    ) -> XMedia:
        return XMedia(type=type, url=url, thumbnail_url=thumbnail_url, alt_text=alt_text)

    return _factory


@pytest.fixture
def make_reply() -> Callable[..., XReply]:
    def _factory(
        *,
        author_name: str = "Reply Author",
        author_handle: str = "replyauthor",
        text: str = "Interesting thread!",
        verified: bool = False,
    ) -> XReply:
        return XReply(
            author_name=author_name,
            author_handle=author_handle,
            text=text,
            verified=verified,
        )

    return _factory


@pytest.fixture
def make_status_ref() -> Callable[..., XStatusRef]:
    def _factory(
        *,
        original_url: str = "https://x.com/testuser/status/1234567890",
        canonical_url: str = "https://x.com/testuser/status/1234567890",
        status_id: str = "1234567890",
        author_handle_hint: str | None = "testuser",
    ) -> XStatusRef:
        return XStatusRef(
            original_url=original_url,
            canonical_url=canonical_url,
            status_id=status_id,
            author_handle_hint=author_handle_hint,
        )

    return _factory


@pytest.fixture
def make_post_snapshot(
    make_media: Callable[..., XMedia],
    make_metrics: Callable[..., XMetrics],
    make_reply: Callable[..., XReply],
) -> Callable[..., XPostSnapshot]:
    def _factory(
        *,
        author_name: str = "Test Author",
        author_handle: str = "testauthor",
        author_avatar_url: str | None = "https://pbs.twimg.com/profile_images/test/avatar.jpg",
        verified: bool = False,
        created_at: datetime | None = None,
        text: str = "This is a test post from X.",
        media: list[XMedia] | None = None,
        metrics: XMetrics | None = None,
        top_replies: list[XReply] | None = None,
        summary: str | None = None,
    ) -> XPostSnapshot:
        return XPostSnapshot(
            author_name=author_name,
            author_handle=author_handle,
            author_avatar_url=author_avatar_url,
            verified=verified,
            created_at=created_at or datetime.now(UTC),
            text=text,
            media=media if media is not None else [make_media()],
            metrics=metrics or make_metrics(),
            top_replies=top_replies if top_replies is not None else [make_reply()],
            summary=summary,
        )

    return _factory


@pytest.fixture
def make_job_dto() -> Callable[..., XUnfurlJobDto]:
    _counter = 0

    def _factory(
        *,
        job_id: str | None = None,
        channel_id: str = "C0123456789",
        message_ts: str = "1700000000.000100",
        team_id: str = "T0123456789",
        original_url: str = "https://x.com/testuser/status/1234567890",
        canonical_url: str = "https://x.com/testuser/status/1234567890",
        status_id: str = "1234567890",
        action: str = "generate",
        trace_id: str = "",
        unfurl_id: str | None = None,
        created_at: str = "",
    ) -> XUnfurlJobDto:
        nonlocal _counter
        _counter += 1
        return XUnfurlJobDto(
            job_id=job_id or f"test-job-{_counter}",
            channel_id=channel_id,
            message_ts=message_ts,
            team_id=team_id,
            original_url=original_url,
            canonical_url=canonical_url,
            status_id=status_id,
            action=action,
            trace_id=trace_id,
            unfurl_id=unfurl_id,
            created_at=created_at,
        )

    return _factory
