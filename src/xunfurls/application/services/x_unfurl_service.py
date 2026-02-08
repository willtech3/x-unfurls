"""Orchestration service for X unfurl generation."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from shared.domain.dtos import XUnfurlJobDto
from shared.domain.repositories.slack_repository import SlackUnfurlRepository
from xunfurls.application.presenters.x_unfurl_blocks import XUnfurlBlocksBuilder
from xunfurls.domain.entities import XPostSnapshot, XStatusRef
from xunfurls.domain.repositories.video_thumbnail_repository import VideoThumbnailRepository
from xunfurls.domain.repositories.x_repository import FetchMode, XRepository

logger = logging.getLogger(__name__)


class XUnfurlService:
    """Orchestrates X unfurl generation."""

    def __init__(
        self,
        x_repo: XRepository,
        slack_repo: SlackUnfurlRepository,
        blocks_builder: XUnfurlBlocksBuilder,
        thumbnail_repo: VideoThumbnailRepository | None = None,
    ) -> None:
        self._x_repo = x_repo
        self._slack_repo = slack_repo
        self._blocks_builder = blocks_builder
        self._thumbnail_repo = thumbnail_repo

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

        if self._thumbnail_repo is not None:
            snapshot, thumbnails = await asyncio.gather(
                self._x_repo.fetch_post_snapshot(status_ref, mode),
                self._fetch_thumbnails_safe(job.canonical_url, job.status_id),
            )
            _apply_video_thumbnails(snapshot, thumbnails)
        else:
            snapshot = await self._x_repo.fetch_post_snapshot(status_ref, mode)

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

    async def _fetch_thumbnails_safe(self, canonical_url: str, status_id: str) -> list[str]:
        """Fetch thumbnails and degrade to empty list on non-critical failures."""
        if self._thumbnail_repo is None:
            return []

        try:
            return await self._thumbnail_repo.fetch_video_thumbnails(canonical_url)
        except Exception:
            logger.warning(
                "Thumbnail enrichment failed for status_id=%s; continuing with source thumbnail",
                status_id,
                exc_info=True,
            )
            return []

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


def _apply_video_thumbnails(snapshot: XPostSnapshot, thumbnails: list[str]) -> None:
    """Overwrite video media thumbnail URLs with FxTwitter results.

    Matches thumbnails to video media items by position. Only overwrites
    if FxTwitter returned a non-empty list.
    """
    if not thumbnails:
        return

    video_indices = [i for i, m in enumerate(snapshot.media) if m.type in ("video", "gif")]
    for idx, thumb_url in zip(video_indices, thumbnails, strict=False):
        logger.debug(
            "Replacing video thumbnail [%d]: %s -> %s",
            idx,
            snapshot.media[idx].thumbnail_url,
            thumb_url,
        )
        snapshot.media[idx].thumbnail_url = thumb_url
