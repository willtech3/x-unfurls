"""Orchestration service for X unfurl generation."""

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
        # Determine fetch mode based on action
        mode = FetchMode.RICH
        if job.action == "summarize":
            mode = FetchMode.SUMMARY_ONLY

        # Create status reference
        status_ref = XStatusRef(
            original_url=job.original_url,
            canonical_url=job.canonical_url,
            status_id=job.status_id,
        )

        # Fetch post data via xAI
        snapshot = await self._x_repo.fetch_post_snapshot(status_ref, mode)

        # Build Slack blocks deterministically
        blocks = self._blocks_builder.build_unfurl_blocks(snapshot, job.canonical_url)

        # Attach unfurl to original message
        await self._slack_repo.unfurl_links(
            channel_id=job.channel_id,
            message_ts=job.message_ts,
            unfurls={job.canonical_url: {"blocks": blocks}},
        )
