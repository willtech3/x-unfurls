"""Orchestration service for X unfurl generation."""

from typing import Any

from shared.domain.dtos import XUnfurlJobDto
from shared.domain.repositories.slack_repository import SlackUnfurlRepository
from xunfurls.application.presenters.x_unfurl_blocks import XUnfurlBlocksBuilder
from xunfurls.domain.entities import XStatusRef
from xunfurls.domain.repositories.x_repository import FetchMode, XRepository


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

        snapshot = await self._x_repo.fetch_post_snapshot(status_ref, mode)
        blocks = self._blocks_builder.build_unfurl_blocks(snapshot, job.canonical_url)

        await self._slack_repo.post_message(
            channel_id=job.channel_id,
            blocks=blocks,
            text=f"X post by @{snapshot.author_handle}",
        )

    async def _process_ask_grok(self, job: XUnfurlJobDto, status_ref: XStatusRef) -> None:
        """Process an 'ask_grok' follow-up question.

        Posts the answer as a threaded reply on the unfurl message.
        """
        answer = await self._x_repo.ask_about_post(status_ref, job.user_prompt)
        blocks = self._build_ask_grok_reply_blocks(job.user_id, job.user_prompt, answer)

        await self._slack_repo.post_message(
            channel_id=job.channel_id,
            blocks=blocks,
            text=f"Grok's answer: {answer[:100]}",
            thread_ts=job.message_ts,
        )

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
