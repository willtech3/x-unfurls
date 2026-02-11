"""Circuit breaker decorator for XRepository.

Prevents hammering a failed external API by tracking consecutive failures
and short-circuiting requests when the failure threshold is exceeded.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Requests immediately fail with CircuitOpenError
- HALF_OPEN: After recovery timeout, one probe request is allowed through
"""

import logging
import time

from xunfurls.domain.entities import XPostSnapshot, XStatusRef
from xunfurls.domain.repositories.x_repository import FetchMode, XRepository

logger = logging.getLogger(__name__)


class CircuitOpenError(RuntimeError):
    """Raised when the circuit breaker is open and requests are blocked."""


class CircuitBreakerXRepository:
    """Decorator that adds circuit breaker protection to an XRepository."""

    def __init__(
        self,
        inner: XRepository,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 60.0,
    ) -> None:
        self._inner = inner
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout_seconds
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._is_open = False

    def _check_breaker(self) -> None:
        """Check circuit state; raise if open and not yet recovered."""
        if self._is_open:
            if time.monotonic() - self._last_failure_time < self._recovery_timeout:
                raise CircuitOpenError(
                    f"Circuit breaker open, {self._failure_count} consecutive failures"
                )
            logger.info("Circuit breaker entering half-open state, allowing probe request")
            self._is_open = False

    def _record_success(self) -> None:
        if self._failure_count > 0:
            logger.info("Circuit breaker reset after successful request")
        self._failure_count = 0

    def _record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._failure_threshold:
            if not self._is_open:
                logger.warning(
                    "Circuit breaker opened after %d consecutive failures",
                    self._failure_count,
                )
            self._is_open = True

    async def fetch_post_snapshot(self, status_ref: XStatusRef, mode: FetchMode) -> XPostSnapshot:
        """Fetch with circuit breaker protection."""
        self._check_breaker()
        try:
            result = await self._inner.fetch_post_snapshot(status_ref, mode)
            self._record_success()
            return result
        except Exception:
            self._record_failure()
            raise

    async def ask_about_post(self, status_ref: XStatusRef, question: str) -> str:
        """Ask with circuit breaker protection."""
        self._check_breaker()
        try:
            result = await self._inner.ask_about_post(status_ref, question)
            self._record_success()
            return result
        except Exception:
            self._record_failure()
            raise
