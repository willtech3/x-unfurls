"""Circuit breaker decorator for XRepository.

Prevents hammering a failed external API by tracking consecutive failures
and short-circuiting requests when the failure threshold is exceeded.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Requests immediately fail with CircuitOpenError
- HALF_OPEN: After recovery timeout, one probe request is allowed through
"""

import time

from xunfurls.domain.entities import XPostSnapshot, XStatusRef
from xunfurls.domain.repositories.x_repository import FetchMode, XRepository


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

    async def fetch_post_snapshot(self, status_ref: XStatusRef, mode: FetchMode) -> XPostSnapshot:
        """Fetch with circuit breaker protection."""
        if self._is_open:
            if time.monotonic() - self._last_failure_time < self._recovery_timeout:
                raise CircuitOpenError(
                    f"Circuit breaker open, {self._failure_count} consecutive failures"
                )
            # Recovery timeout elapsed — try one probe request (half-open)
            self._is_open = False

        try:
            result = await self._inner.fetch_post_snapshot(status_ref, mode)
            self._failure_count = 0  # Reset on success
            return result
        except Exception:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self._failure_threshold:
                self._is_open = True
            raise
