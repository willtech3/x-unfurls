"""Tests for caching, deduplication, and circuit breaker (ARCH-1, ARCH-2, ARCH-4)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from xunfurls.application.middleware.caching import CachingXRepository
from xunfurls.application.middleware.circuit_breaker import (
    CircuitBreakerXRepository,
    CircuitOpenError,
)
from xunfurls.domain.entities import XMetrics, XPostSnapshot, XStatusRef
from xunfurls.domain.repositories.x_repository import FetchMode


def _make_ref(status_id: str = "123") -> XStatusRef:
    return XStatusRef(
        original_url=f"https://x.com/u/status/{status_id}",
        canonical_url=f"https://x.com/u/status/{status_id}",
        status_id=status_id,
    )


def _make_snap(text: str = "Hello") -> XPostSnapshot:
    return XPostSnapshot(
        author_name="Test",
        author_handle="test",
        author_avatar_url=None,
        verified=False,
        created_at=datetime(2024, 6, 1, tzinfo=UTC),
        text=text,
        media=[],
        metrics=XMetrics(),
        top_replies=[],
        summary=None,
    )


# ---------------------------------------------------------------------------
# ARCH-1: In-memory caching
# ---------------------------------------------------------------------------


class TestCachingXRepository:
    @pytest.fixture
    def inner(self) -> AsyncMock:
        mock = AsyncMock()
        mock.fetch_post_snapshot = AsyncMock(return_value=_make_snap("first"))
        return mock

    @pytest.fixture
    def cached(self, inner: AsyncMock) -> CachingXRepository:
        return CachingXRepository(inner, ttl_seconds=60, max_size=10)

    async def test_first_call_delegates_to_inner(
        self, cached: CachingXRepository, inner: AsyncMock
    ) -> None:
        ref = _make_ref("1")
        result = await cached.fetch_post_snapshot(ref, FetchMode.RICH)
        assert result.text == "first"
        inner.fetch_post_snapshot.assert_called_once()

    async def test_second_call_returns_cached(
        self, cached: CachingXRepository, inner: AsyncMock
    ) -> None:
        ref = _make_ref("1")
        await cached.fetch_post_snapshot(ref, FetchMode.RICH)
        inner.fetch_post_snapshot.return_value = _make_snap("second")
        result = await cached.fetch_post_snapshot(ref, FetchMode.RICH)
        assert result.text == "first"  # cached
        assert inner.fetch_post_snapshot.call_count == 1

    async def test_different_status_ids_not_shared(
        self, cached: CachingXRepository, inner: AsyncMock
    ) -> None:
        inner.fetch_post_snapshot.return_value = _make_snap("one")
        await cached.fetch_post_snapshot(_make_ref("1"), FetchMode.RICH)
        inner.fetch_post_snapshot.return_value = _make_snap("two")
        result = await cached.fetch_post_snapshot(_make_ref("2"), FetchMode.RICH)
        assert result.text == "two"
        assert inner.fetch_post_snapshot.call_count == 2

    async def test_summary_mode_bypasses_cache(
        self, cached: CachingXRepository, inner: AsyncMock
    ) -> None:
        await cached.fetch_post_snapshot(_make_ref("1"), FetchMode.RICH)
        inner.fetch_post_snapshot.return_value = _make_snap("summarized")
        result = await cached.fetch_post_snapshot(_make_ref("1"), FetchMode.SUMMARY_ONLY)
        assert result.text == "summarized"
        assert inner.fetch_post_snapshot.call_count == 2

    async def test_cache_respects_max_size(self, inner: AsyncMock) -> None:
        cached = CachingXRepository(inner, ttl_seconds=60, max_size=2)
        inner.fetch_post_snapshot.return_value = _make_snap("a")
        await cached.fetch_post_snapshot(_make_ref("1"), FetchMode.RICH)
        inner.fetch_post_snapshot.return_value = _make_snap("b")
        await cached.fetch_post_snapshot(_make_ref("2"), FetchMode.RICH)
        inner.fetch_post_snapshot.return_value = _make_snap("c")
        await cached.fetch_post_snapshot(_make_ref("3"), FetchMode.RICH)
        # Oldest entry (status_id=1) should be evicted
        inner.fetch_post_snapshot.return_value = _make_snap("refetched")
        result = await cached.fetch_post_snapshot(_make_ref("1"), FetchMode.RICH)
        assert result.text == "refetched"  # not cached anymore


# ---------------------------------------------------------------------------
# ARCH-4: Circuit breaker
# ---------------------------------------------------------------------------


class TestCircuitBreakerXRepository:
    @pytest.fixture
    def inner(self) -> AsyncMock:
        mock = AsyncMock()
        mock.fetch_post_snapshot = AsyncMock(return_value=_make_snap())
        return mock

    @pytest.fixture
    def breaker(self, inner: AsyncMock) -> CircuitBreakerXRepository:
        return CircuitBreakerXRepository(
            inner, failure_threshold=3, recovery_timeout_seconds=1
        )

    async def test_passes_through_on_success(
        self, breaker: CircuitBreakerXRepository, inner: AsyncMock
    ) -> None:
        result = await breaker.fetch_post_snapshot(_make_ref(), FetchMode.RICH)
        assert result.text == "Hello"
        inner.fetch_post_snapshot.assert_called_once()

    async def test_opens_circuit_after_threshold_failures(
        self, breaker: CircuitBreakerXRepository, inner: AsyncMock
    ) -> None:
        inner.fetch_post_snapshot.side_effect = ConnectionError("timeout")
        for _ in range(3):
            with pytest.raises(ConnectionError):
                await breaker.fetch_post_snapshot(_make_ref(), FetchMode.RICH)
        # Circuit should now be open
        with pytest.raises(CircuitOpenError):
            await breaker.fetch_post_snapshot(_make_ref(), FetchMode.RICH)

    async def test_circuit_resets_after_recovery_timeout(
        self, inner: AsyncMock
    ) -> None:
        breaker = CircuitBreakerXRepository(
            inner, failure_threshold=2, recovery_timeout_seconds=0.1
        )
        inner.fetch_post_snapshot.side_effect = ConnectionError("down")
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await breaker.fetch_post_snapshot(_make_ref(), FetchMode.RICH)
        # Wait for recovery
        await asyncio.sleep(0.15)
        inner.fetch_post_snapshot.side_effect = None
        inner.fetch_post_snapshot.return_value = _make_snap("recovered")
        result = await breaker.fetch_post_snapshot(_make_ref(), FetchMode.RICH)
        assert result.text == "recovered"

    async def test_success_resets_failure_count(
        self, breaker: CircuitBreakerXRepository, inner: AsyncMock
    ) -> None:
        inner.fetch_post_snapshot.side_effect = ConnectionError("fail")
        for _ in range(2):  # 2 failures (threshold is 3)
            with pytest.raises(ConnectionError):
                await breaker.fetch_post_snapshot(_make_ref(), FetchMode.RICH)
        # One success should reset
        inner.fetch_post_snapshot.side_effect = None
        inner.fetch_post_snapshot.return_value = _make_snap()
        await breaker.fetch_post_snapshot(_make_ref(), FetchMode.RICH)
        # Now 2 more failures shouldn't open circuit
        inner.fetch_post_snapshot.side_effect = ConnectionError("fail")
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await breaker.fetch_post_snapshot(_make_ref(), FetchMode.RICH)
        # Still closed (only 2 consecutive failures after reset)
        inner.fetch_post_snapshot.side_effect = None
        inner.fetch_post_snapshot.return_value = _make_snap("ok")
        result = await breaker.fetch_post_snapshot(_make_ref(), FetchMode.RICH)
        assert result.text == "ok"
