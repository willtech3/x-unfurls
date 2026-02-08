"""Tests for XUnfurlService: parallel thumbnail fetching and merge logic."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from xunfurls.application.presenters.x_unfurl_blocks import XUnfurlBlocksBuilder
from xunfurls.application.services.x_unfurl_service import XUnfurlService, _apply_video_thumbnails
from xunfurls.domain.entities import XMedia, XPostSnapshot

from .conftest import FakeSlackUnfurlRepository, FakeXRepository

# ---------------------------------------------------------------------------
# Fake thumbnail client
# ---------------------------------------------------------------------------


@dataclass
class FakeThumbnailClient:
    """Fake that records calls and returns pre-configured thumbnails."""

    thumbnails: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    should_raise: Exception | None = None

    async def fetch_video_thumbnails(self, canonical_url: str) -> list[str]:
        self.calls.append(canonical_url)
        if self.should_raise is not None:
            raise self.should_raise
        return self.thumbnails


# ---------------------------------------------------------------------------
# _apply_video_thumbnails unit tests
# ---------------------------------------------------------------------------


class TestApplyVideoThumbnails:
    def test_overwrites_video_thumbnail(
        self, make_post_snapshot: Callable[..., XPostSnapshot]
    ) -> None:
        video = XMedia(type="video", url="vid.mp4", thumbnail_url="https://old-thumb.jpg")
        snapshot = make_post_snapshot(media=[video])

        _apply_video_thumbnails(snapshot, ["https://new-thumb.jpg"])

        assert snapshot.media[0].thumbnail_url == "https://new-thumb.jpg"

    def test_skips_image_media(self, make_post_snapshot: Callable[..., XPostSnapshot]) -> None:
        image = XMedia(type="image", url="img.jpg")
        video = XMedia(type="video", url="vid.mp4", thumbnail_url="https://old.jpg")
        snapshot = make_post_snapshot(media=[image, video])

        _apply_video_thumbnails(snapshot, ["https://new.jpg"])

        assert snapshot.media[0].thumbnail_url is None  # image unchanged
        assert snapshot.media[1].thumbnail_url == "https://new.jpg"

    def test_handles_gif_type(self, make_post_snapshot: Callable[..., XPostSnapshot]) -> None:
        gif = XMedia(type="gif", url="anim.mp4", thumbnail_url="https://old-gif.jpg")
        snapshot = make_post_snapshot(media=[gif])

        _apply_video_thumbnails(snapshot, ["https://new-gif.jpg"])

        assert snapshot.media[0].thumbnail_url == "https://new-gif.jpg"

    def test_empty_thumbnails_no_change(
        self, make_post_snapshot: Callable[..., XPostSnapshot]
    ) -> None:
        video = XMedia(type="video", url="vid.mp4", thumbnail_url="https://original.jpg")
        snapshot = make_post_snapshot(media=[video])

        _apply_video_thumbnails(snapshot, [])

        assert snapshot.media[0].thumbnail_url == "https://original.jpg"

    def test_fewer_thumbnails_than_videos(
        self, make_post_snapshot: Callable[..., XPostSnapshot]
    ) -> None:
        v1 = XMedia(type="video", url="v1.mp4", thumbnail_url="https://old1.jpg")
        v2 = XMedia(type="video", url="v2.mp4", thumbnail_url="https://old2.jpg")
        snapshot = make_post_snapshot(media=[v1, v2])

        _apply_video_thumbnails(snapshot, ["https://new1.jpg"])

        assert snapshot.media[0].thumbnail_url == "https://new1.jpg"
        assert snapshot.media[1].thumbnail_url == "https://old2.jpg"

    def test_more_thumbnails_than_videos(
        self, make_post_snapshot: Callable[..., XPostSnapshot]
    ) -> None:
        video = XMedia(type="video", url="vid.mp4", thumbnail_url="https://old.jpg")
        snapshot = make_post_snapshot(media=[video])

        _apply_video_thumbnails(snapshot, ["https://new1.jpg", "https://extra.jpg"])

        assert snapshot.media[0].thumbnail_url == "https://new1.jpg"

    def test_no_media(self, make_post_snapshot: Callable[..., XPostSnapshot]) -> None:
        snapshot = make_post_snapshot(media=[])
        _apply_video_thumbnails(snapshot, ["https://orphan.jpg"])
        assert snapshot.media == []


# ---------------------------------------------------------------------------
# XUnfurlService parallel flow tests
# ---------------------------------------------------------------------------


class TestServiceParallelThumbnails:
    async def test_thumbnail_client_called_with_canonical_url(
        self,
        fake_x_repo: FakeXRepository,
        fake_slack: FakeSlackUnfurlRepository,
        make_post_snapshot: Callable[..., XPostSnapshot],
        make_job_dto: Callable,
    ) -> None:
        video = XMedia(type="video", url="vid.mp4", thumbnail_url="https://xai-thumb.jpg")
        snapshot = make_post_snapshot(media=[video])
        fake_x_repo.default_snapshot = snapshot

        thumb_client = FakeThumbnailClient(thumbnails=["https://fxtw-thumb.jpg"])
        service = XUnfurlService(
            x_repo=fake_x_repo,
            slack_repo=fake_slack,
            blocks_builder=XUnfurlBlocksBuilder(),
            thumbnail_client=thumb_client,
        )

        job = make_job_dto(canonical_url="https://x.com/user/status/42")
        await service.process_unfurl_job(job)

        assert thumb_client.calls == ["https://x.com/user/status/42"]
        # Thumbnail should be overwritten
        assert snapshot.media[0].thumbnail_url == "https://fxtw-thumb.jpg"

    async def test_thumbnail_client_failure_falls_back_to_xai(
        self,
        fake_x_repo: FakeXRepository,
        fake_slack: FakeSlackUnfurlRepository,
        make_post_snapshot: Callable[..., XPostSnapshot],
        make_job_dto: Callable,
    ) -> None:
        video = XMedia(type="video", url="vid.mp4", thumbnail_url="https://xai-thumb.jpg")
        snapshot = make_post_snapshot(media=[video])
        fake_x_repo.default_snapshot = snapshot

        thumb_client = FakeThumbnailClient(thumbnails=[])  # FxTwitter returned nothing
        service = XUnfurlService(
            x_repo=fake_x_repo,
            slack_repo=fake_slack,
            blocks_builder=XUnfurlBlocksBuilder(),
            thumbnail_client=thumb_client,
        )

        job = make_job_dto()
        await service.process_unfurl_job(job)

        # Original xAI thumbnail preserved
        assert snapshot.media[0].thumbnail_url == "https://xai-thumb.jpg"

    async def test_no_thumbnail_client_works_normally(
        self,
        fake_x_repo: FakeXRepository,
        fake_slack: FakeSlackUnfurlRepository,
        make_post_snapshot: Callable[..., XPostSnapshot],
        make_job_dto: Callable,
    ) -> None:
        snapshot = make_post_snapshot()
        fake_x_repo.default_snapshot = snapshot

        service = XUnfurlService(
            x_repo=fake_x_repo,
            slack_repo=fake_slack,
            blocks_builder=XUnfurlBlocksBuilder(),
            # no thumbnail_client
        )

        job = make_job_dto()
        await service.process_unfurl_job(job)

        # Should complete without error
        assert len(fake_slack.post_message_calls) == 1

    async def test_summarize_action_still_uses_thumbnails(
        self,
        fake_x_repo: FakeXRepository,
        fake_slack: FakeSlackUnfurlRepository,
        make_post_snapshot: Callable[..., XPostSnapshot],
        make_job_dto: Callable,
    ) -> None:
        video = XMedia(type="video", url="vid.mp4", thumbnail_url="https://xai.jpg")
        snapshot = make_post_snapshot(media=[video])
        fake_x_repo.default_snapshot = snapshot

        thumb_client = FakeThumbnailClient(thumbnails=["https://fxtw.jpg"])
        service = XUnfurlService(
            x_repo=fake_x_repo,
            slack_repo=fake_slack,
            blocks_builder=XUnfurlBlocksBuilder(),
            thumbnail_client=thumb_client,
        )

        job = make_job_dto(action="summarize")
        await service.process_unfurl_job(job)

        assert snapshot.media[0].thumbnail_url == "https://fxtw.jpg"

    async def test_ask_grok_action_does_not_use_thumbnails(
        self,
        fake_x_repo: FakeXRepository,
        fake_slack: FakeSlackUnfurlRepository,
        make_post_snapshot: Callable[..., XPostSnapshot],
        make_job_dto: Callable,
    ) -> None:
        thumb_client = FakeThumbnailClient(thumbnails=["https://fxtw.jpg"])
        service = XUnfurlService(
            x_repo=fake_x_repo,
            slack_repo=fake_slack,
            blocks_builder=XUnfurlBlocksBuilder(),
            thumbnail_client=thumb_client,
        )

        job = make_job_dto(action="ask_grok", user_prompt="What is this?", user_id="U001")
        await service.process_unfurl_job(job)

        # Thumbnail client should NOT be called for ask_grok
        assert thumb_client.calls == []
