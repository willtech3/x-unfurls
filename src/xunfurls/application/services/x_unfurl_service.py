"""Orchestration service for X unfurl generation."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from shared.domain.dtos import XUnfurlJobDto
from shared.domain.repositories.slack_repository import SlackUnfurlRepository
from xunfurls.application.presenters.x_unfurl_blocks import XUnfurlBlocksBuilder
from xunfurls.domain.entities import XMedia, XPostSnapshot, XStatusRef
from xunfurls.domain.repositories.x_repository import FetchMode, XRepository

logger = logging.getLogger(__name__)

_THUMB_VALIDATE_TIMEOUT = 3.0


class XUnfurlService:
    """Orchestrates X unfurl generation."""

    def __init__(
        self,
        x_repo: XRepository,
        slack_repo: SlackUnfurlRepository,
        blocks_builder: XUnfurlBlocksBuilder,
    ) -> None:
        self._x_repo = x_repo
        self._slack_repo = slack_repo
        self._blocks_builder = blocks_builder

    async def process_unfurl_job(self, job: XUnfurlJobDto) -> None:
        """Process an unfurl job.

        Args:
            job: The unfurl job to process
        """
        status_ref = XStatusRef(
            original_url=job.original_url,
            canonical_url=job.canonical_url,
            status_id=job.status_id,
        )

        if job.action == "ask_grok":
            await self._process_ask_grok(job, status_ref)
        else:
            await self._process_unfurl(job, status_ref)

    async def _process_unfurl(self, job: XUnfurlJobDto, status_ref: XStatusRef) -> None:
        """Process a standard unfurl (generate/refresh/summarize)."""
        mode = FetchMode.RICH
        if job.action == "summarize":
            mode = FetchMode.SUMMARY_ONLY

        logger.info("Processing standard unfurl job %s (action=%s)", job.job_id, job.action)

        snapshot = await self._x_repo.fetch_post_snapshot(status_ref, mode)
        await _validate_video_thumbnails(snapshot)

        blocks = self._blocks_builder.build_unfurl_blocks(snapshot, job.canonical_url)

        unfurl_text = f"X post by @{snapshot.author_handle.lstrip('@')}"
        unfurls = {job.original_url: {"blocks": blocks, "text": unfurl_text}}

        try:
            await self._slack_repo.unfurl_links(
                channel_id=job.channel_id,
                message_ts=job.message_ts,
                unfurls=unfurls,
            )
            logger.info("Inline unfurl posted for job %s", job.job_id)
        except Exception:
            logger.warning(
                "Inline unfurl failed for job %s; falling back to post_message",
                job.job_id,
                exc_info=True,
            )
            await self._slack_repo.post_message(
                channel_id=job.channel_id,
                blocks=blocks,
                text=unfurl_text,
                color=self._blocks_builder.ACCENT_COLOR,
            )
            logger.info("Fallback unfurl message posted for job %s", job.job_id)

    async def _process_ask_grok(self, job: XUnfurlJobDto, status_ref: XStatusRef) -> None:
        """Process an 'ask_grok' follow-up question.

        Posts the answer as a threaded reply on the unfurl message.
        """
        logger.info("Processing ask_grok job %s for user %s", job.job_id, job.user_id or "unknown")
        answer = await self._x_repo.ask_about_post(status_ref, job.user_prompt)
        blocks = self._build_ask_grok_reply_blocks(job.user_id, job.user_prompt, answer)

        await self._slack_repo.post_message(
            channel_id=job.channel_id,
            blocks=blocks,
            text=f"Grok's answer: {answer[:100]}",
            thread_ts=job.message_ts,
        )
        logger.info("Ask-grok reply posted for job %s", job.job_id)

    @staticmethod
    def _build_ask_grok_reply_blocks(
        user_id: str, question: str, answer: str
    ) -> list[dict[str, Any]]:
        """Build blocks for a Grok follow-up reply in a thread."""
        blocks: list[dict[str, Any]] = [
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"<@{user_id}> asked:"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"> {question}"},
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✦  *Grok*\n{answer[:3000]}",
                },
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "Powered by Grok  ·  x.ai"},
                ],
            },
        ]
        return blocks


async def _validate_video_thumbnails(snapshot: XPostSnapshot) -> None:
    """HEAD-check video thumbnail URLs; null out any that don't return 200.

    Prevents Slack ``invalid_attachments`` errors caused by dead thumbnail
    URLs from xAI.  Runs all checks concurrently; adds ~100ms overhead.
    """
    all_video = [m for m in snapshot.media if m.type in ("video", "gif")]
    if not all_video:
        return

    missing = [m for m in all_video if not m.thumbnail_url]
    if missing:
        logger.info(
            "Video/gif media missing thumbnail_url from xAI: %d of %d",
            len(missing),
            len(all_video),
        )

    to_check = [m for m in all_video if m.thumbnail_url]
    if not to_check:
        return

    async with httpx.AsyncClient(timeout=_THUMB_VALIDATE_TIMEOUT) as client:
        await asyncio.gather(*[_check_thumbnail(client, m) for m in to_check])


async def _check_thumbnail(client: httpx.AsyncClient, media: XMedia) -> None:
    """HEAD-check a single thumbnail URL; null it out on failure."""
    assert media.thumbnail_url is not None  # caller guarantees this
    try:
        resp = await client.head(media.thumbnail_url, follow_redirects=True)
        if resp.status_code != 200:
            logger.info(
                "Thumbnail HEAD returned %d, clearing: %s",
                resp.status_code,
                media.thumbnail_url,
            )
            media.thumbnail_url = None
        else:
            logger.info("Thumbnail HEAD OK: %s", media.thumbnail_url)
    except Exception:
        logger.info("Thumbnail HEAD failed, clearing: %s", media.thumbnail_url, exc_info=True)
        media.thumbnail_url = None
