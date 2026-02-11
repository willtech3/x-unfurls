"""Tests for caching and circuit breaker middleware."""

from __future__ import annotations

import time
from collections.abc import Callable
from unittest.mock import patch

import pytest

from xunfurls.application.middleware.caching import CachingXRepository
from xunfurls.application.middleware.circuit_breaker import (
    CircuitBreakerXRepository,
    CircuitOpenError,
)
from xunfurls.domain.entities import XPostSnapshot, XStatusRef
from xunfurls.domain.repositories.x_repository import FetchMode

from .conftest import FakeXRepository

# ---------------------------------------------------------------------------
# Cache tests
# ---------------------------------------------------------------------------


class TestCachingTTLExpiry:
    """Cache entries expire after TTL and trigger a fresh fetch."""

    async def test_expired_entry_triggers_refetch(
        self,
        fake_x_repo: FakeXRepository,
        make_post_snapshot: Callable[..., XPostSnapshot],
        make_status_ref: Callable[..., XStatusRef],
    ) -> None:
        snapshot = make_post_snapshot(text="original")
        fake_x_repo.default_snapshot = snapshot
        cache = CachingXRepository(fake_x_repo, ttl_seconds=1)

        ref = make_status_ref(status_id="1")

        # First fetch — cache miss
        await cache.fetch_post_snapshot(ref, FetchMode.RICH)
        assert len(fake_x_repo.fetch_calls) == 1

        # Second fetch — cache hit, no new call
        await cache.fetch_post_snapshot(ref, FetchMode.RICH)
        assert len(fake_x_repo.fetch_calls) == 1

        # Simulate TTL expiry by patching time.monotonic
        with patch("xunfurls.application.middleware.caching.time") as mock_time:
            mock_time.monotonic.return_value = time.monotonic() + 2
            await cache.fetch_post_snapshot(ref, FetchMode.RICH)

        # Expired entry triggers new fetch
        assert len(fake_x_repo.fetch_calls) == 2

    async def test_summary_mode_bypasses_cache(
        self,
        fake_x_repo: FakeXRepository,
        make_post_snapshot: Callable[..., XPostSnapshot],
        make_status_ref: Callable[..., XStatusRef],
    ) -> None:
        fake_x_repo.default_snapshot = make_post_snapshot()
        cache = CachingXRepository(fake_x_repo)

        ref = make_status_ref(status_id="1")

        await cache.fetch_post_snapshot(ref, FetchMode.SUMMARY_ONLY)
        await cache.fetch_post_snapshot(ref, FetchMode.SUMMARY_ONLY)

        # Both calls should go through (no caching for SUMMARY_ONLY)
        assert len(fake_x_repo.fetch_calls) == 2

    async def test_ask_about_post_passes_through(
        self,
        fake_x_repo: FakeXRepository,
        make_status_ref: Callable[..., XStatusRef],
    ) -> None:
        cache = CachingXRepository(fake_x_repo)
        ref = make_status_ref()

        result = await cache.ask_about_post(ref, "What is this?")

        assert result == fake_x_repo.ask_response
        assert len(fake_x_repo.ask_calls) == 1


# ---------------------------------------------------------------------------
# Circuit breaker tests
# ---------------------------------------------------------------------------


class TestCircuitBreakerAskAboutPost:
    """Circuit breaker protects ask_about_post the same as fetch_post_snapshot."""

    async def test_ask_opens_circuit_on_repeated_failures(
        self,
        make_status_ref: Callable[..., XStatusRef],
    ) -> None:
        failing_repo = FakeXRepository()
        failing_repo.ask_response = "ok"  # won't be used once we override

        cb = CircuitBreakerXRepository(failing_repo, failure_threshold=3)
        ref = make_status_ref()

        # Override ask_about_post to raise
        async def _fail(sr: XStatusRef, q: str) -> str:
            raise RuntimeError("API down")

        failing_repo.ask_about_post = _fail  # type: ignore[assignment]

        # 3 failures should open the circuit
        for _ in range(3):
            with pytest.raises(RuntimeError, match="API down"):
                await cb.ask_about_post(ref, "test")

        # 4th call should be blocked by circuit breaker
        with pytest.raises(CircuitOpenError):
            await cb.ask_about_post(ref, "test")

    async def test_ask_resets_after_success(
        self,
        fake_x_repo: FakeXRepository,
        make_status_ref: Callable[..., XStatusRef],
    ) -> None:
        cb = CircuitBreakerXRepository(fake_x_repo, failure_threshold=3)
        ref = make_status_ref()

        result = await cb.ask_about_post(ref, "What is this post about?")

        assert result == fake_x_repo.ask_response
        assert len(fake_x_repo.ask_calls) == 1
