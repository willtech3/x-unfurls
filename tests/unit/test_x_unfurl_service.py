"""Tests for XUnfurlService: HEAD thumbnail validation and unfurl flow."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import respx

from xunfurls.application.presenters.x_unfurl_blocks import XUnfurlBlocksBuilder
from xunfurls.application.services.x_unfurl_service import (
    XUnfurlService,
    _validate_video_thumbnails,
)
from xunfurls.domain.entities import XMedia, XPostSnapshot

from .conftest import FakeSlackUnfurlRepository, FakeXRepository

# ---------------------------------------------------------------------------
# _validate_video_thumbnails unit tests
# ---------------------------------------------------------------------------


class TestValidateVideoThumbnails:
    @respx.mock
    async def test_clears_404_thumbnail(
        self, make_post_snapshot: Callable[..., XPostSnapshot]
    ) -> None:
        url = "https://pbs.twimg.com/ext_tw_video_thumb/123/456.jpg"
        respx.head(url).mock(return_value=httpx.Response(404))

        video = XMedia(type="video", url="vid.mp4", thumbnail_url=url)
        snapshot = make_post_snapshot(media=[video])

        await _validate_video_thumbnails(snapshot)

        assert snapshot.media[0].thumbnail_url is None

    @respx.mock
    async def test_keeps_200_thumbnail(
        self, make_post_snapshot: Callable[..., XPostSnapshot]
    ) -> None:
        url = "https://pbs.twimg.com/amplify_video_thumb/123/img/good.jpg"
        respx.head(url).mock(return_value=httpx.Response(200))

        video = XMedia(type="video", url="vid.mp4", thumbnail_url=url)
        snapshot = make_post_snapshot(media=[video])

        await _validate_video_thumbnails(snapshot)

        assert snapshot.media[0].thumbnail_url == url

    @respx.mock
    async def test_clears_on_network_error(
        self, make_post_snapshot: Callable[..., XPostSnapshot]
    ) -> None:
        url = "https://pbs.twimg.com/ext_tw_video_thumb/123/456.jpg"
        respx.head(url).mock(side_effect=httpx.ConnectError("connection refused"))

        video = XMedia(type="video", url="vid.mp4", thumbnail_url=url)
        snapshot = make_post_snapshot(media=[video])

        await _validate_video_thumbnails(snapshot)

        assert snapshot.media[0].thumbnail_url is None

    @respx.mock
    async def test_skips_image_media(
        self, make_post_snapshot: Callable[..., XPostSnapshot]
    ) -> None:
        """Image media should not be HEAD-checked."""
        image = XMedia(type="image", url="https://pbs.twimg.com/media/img.jpg")
        snapshot = make_post_snapshot(media=[image])

        await _validate_video_thumbnails(snapshot)

        # No HEAD requests made, image untouched
        assert snapshot.media[0].url == "https://pbs.twimg.com/media/img.jpg"

    @respx.mock
    async def test_skips_video_without_thumbnail(
        self, make_post_snapshot: Callable[..., XPostSnapshot]
    ) -> None:
        video = XMedia(type="video", url="vid.mp4", thumbnail_url=None)
        snapshot = make_post_snapshot(media=[video])

        await _validate_video_thumbnails(snapshot)

        assert snapshot.media[0].thumbnail_url is None

    @respx.mock
    async def test_validates_multiple_videos(
        self, make_post_snapshot: Callable[..., XPostSnapshot]
    ) -> None:
        good_url = "https://pbs.twimg.com/thumb/good.jpg"
        bad_url = "https://pbs.twimg.com/thumb/bad.jpg"
        respx.head(good_url).mock(return_value=httpx.Response(200))
        respx.head(bad_url).mock(return_value=httpx.Response(404))

        v1 = XMedia(type="video", url="v1.mp4", thumbnail_url=good_url)
        v2 = XMedia(type="video", url="v2.mp4", thumbnail_url=bad_url)
        snapshot = make_post_snapshot(media=[v1, v2])

        await _validate_video_thumbnails(snapshot)

        assert snapshot.media[0].thumbnail_url == good_url
        assert snapshot.media[1].thumbnail_url is None

    @respx.mock
    async def test_validates_gif_thumbnails(
        self, make_post_snapshot: Callable[..., XPostSnapshot]
    ) -> None:
        url = "https://pbs.twimg.com/thumb/gif.jpg"
        respx.head(url).mock(return_value=httpx.Response(404))

        gif = XMedia(type="gif", url="anim.mp4", thumbnail_url=url)
        snapshot = make_post_snapshot(media=[gif])

        await _validate_video_thumbnails(snapshot)

        assert snapshot.media[0].thumbnail_url is None

    async def test_no_media_is_noop(self, make_post_snapshot: Callable[..., XPostSnapshot]) -> None:
        snapshot = make_post_snapshot(media=[])
        await _validate_video_thumbnails(snapshot)
        assert snapshot.media == []


# ---------------------------------------------------------------------------
# XUnfurlService flow tests
# ---------------------------------------------------------------------------


class TestServiceUnfurlFlow:
    async def test_basic_unfurl(
        self,
        fake_x_repo: FakeXRepository,
        fake_slack: FakeSlackUnfurlRepository,
        make_post_snapshot: Callable[..., XPostSnapshot],
        make_job_dto: Callable,
    ) -> None:
        snapshot = make_post_snapshot(media=[])
        fake_x_repo.default_snapshot = snapshot

        service = XUnfurlService(
            x_repo=fake_x_repo,
            slack_repo=fake_slack,
            blocks_builder=XUnfurlBlocksBuilder(),
        )

        job = make_job_dto()
        await service.process_unfurl_job(job)

        assert len(fake_slack.unfurl_calls) == 1
        assert len(fake_slack.post_message_calls) == 0

    async def test_unfurl_failure_falls_back_to_post_message(
        self,
        fake_x_repo: FakeXRepository,
        fake_slack: FakeSlackUnfurlRepository,
        make_post_snapshot: Callable[..., XPostSnapshot],
        make_job_dto: Callable,
    ) -> None:
        fake_x_repo.default_snapshot = make_post_snapshot(media=[])
        fake_slack.unfurl_should_raise = ValueError("cannot_unfurl_url")

        service = XUnfurlService(
            x_repo=fake_x_repo,
            slack_repo=fake_slack,
            blocks_builder=XUnfurlBlocksBuilder(),
        )

        await service.process_unfurl_job(make_job_dto())

        assert len(fake_slack.unfurl_calls) == 1
        assert len(fake_slack.post_message_calls) == 1
        posted = fake_slack.post_message_calls[0]
        assert posted.text.startswith("X post by @")
        assert posted.color == XUnfurlBlocksBuilder.ACCENT_COLOR

    async def test_ask_grok_posts_threaded_reply(
        self,
        fake_x_repo: FakeXRepository,
        fake_slack: FakeSlackUnfurlRepository,
        make_job_dto: Callable,
    ) -> None:
        service = XUnfurlService(
            x_repo=fake_x_repo,
            slack_repo=fake_slack,
            blocks_builder=XUnfurlBlocksBuilder(),
        )

        job = make_job_dto(action="ask_grok", user_prompt="What is this?", user_id="U001")
        await service.process_unfurl_job(job)

        assert len(fake_slack.unfurl_calls) == 0
        assert len(fake_slack.post_message_calls) == 1
        posted = fake_slack.post_message_calls[0]
        assert posted.thread_ts == job.message_ts


# ---------------------------------------------------------------------------
# _build_ask_grok_reply_blocks structure tests
# ---------------------------------------------------------------------------


class TestBuildAskGrokReplyBlocks:
    """Verify structure and sanitization of Ask Grok reply blocks."""

    def test_block_structure(self) -> None:
        blocks = XUnfurlService._build_ask_grok_reply_blocks("U001", "What is this?", "An answer.")

        assert len(blocks) == 5
        assert blocks[0]["type"] == "context"  # "<@U001> asked:"
        assert blocks[1]["type"] == "section"  # quoted question
        assert blocks[2]["type"] == "divider"
        assert blocks[3]["type"] == "section"  # Grok answer
        assert blocks[4]["type"] == "context"  # footer

    def test_answer_contains_grok_prefix(self) -> None:
        blocks = XUnfurlService._build_ask_grok_reply_blocks("U001", "Q?", "The answer.")
        answer_text = blocks[3]["text"]["text"]
        assert answer_text.startswith("✦  *Grok*\n")

    def test_question_is_quoted(self) -> None:
        blocks = XUnfurlService._build_ask_grok_reply_blocks("U001", "Why?", "Because.")
        question_text = blocks[1]["text"]["text"]
        assert question_text.startswith("> ")

    def test_long_answer_truncated_with_ellipsis(self) -> None:
        long_answer = "x" * 4000
        blocks = XUnfurlService._build_ask_grok_reply_blocks("U001", "Q?", long_answer)
        answer_text = blocks[3]["text"]["text"]
        assert answer_text.endswith("...")
        # Grok prefix + truncated answer should be under Slack's 3000 limit + prefix
        assert len(answer_text) < 3100

    def test_sanitizes_mentions_in_answer(self) -> None:
        malicious_answer = "Hey @channel check <@U999> and <!subteam^S123>"
        blocks = XUnfurlService._build_ask_grok_reply_blocks("U001", "Q?", malicious_answer)
        answer_text = blocks[3]["text"]["text"]
        # Broadcast mentions should have zero-width space inserted
        assert "@channel" not in answer_text
        assert "@\u200bchannel" in answer_text
        # Targeted mentions should be broken
        assert "<@U999>" not in answer_text

    def test_sanitizes_mentions_in_question(self) -> None:
        malicious_question = "Tell @everyone about <@U999>"
        blocks = XUnfurlService._build_ask_grok_reply_blocks("U001", malicious_question, "Safe.")
        question_text = blocks[1]["text"]["text"]
        assert "@everyone" not in question_text
        assert "@\u200beveryone" in question_text


# ---------------------------------------------------------------------------
# Thumbnail domain allowlist tests
# ---------------------------------------------------------------------------


class TestThumbnailDomainAllowlist:
    """SSRF mitigation: only allowlisted domains pass thumbnail validation."""

    async def test_non_allowlisted_domain_is_cleared(
        self, make_post_snapshot: Callable[..., XPostSnapshot]
    ) -> None:
        evil_url = "http://169.254.169.254/latest/meta-data/"
        video = XMedia(type="video", url="vid.mp4", thumbnail_url=evil_url)
        snapshot = make_post_snapshot(media=[video])

        await _validate_video_thumbnails(snapshot)

        assert snapshot.media[0].thumbnail_url is None

    @respx.mock
    async def test_allowlisted_domain_proceeds(
        self, make_post_snapshot: Callable[..., XPostSnapshot]
    ) -> None:
        url = "https://pbs.twimg.com/ext_tw_video_thumb/123.jpg"
        respx.head(url).mock(return_value=httpx.Response(200))

        video = XMedia(type="video", url="vid.mp4", thumbnail_url=url)
        snapshot = make_post_snapshot(media=[video])

        await _validate_video_thumbnails(snapshot)

        assert snapshot.media[0].thumbnail_url == url
