"""Application factory for creating service instances."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from xunfurls.application.middleware.caching import CachingXRepository
from xunfurls.application.middleware.circuit_breaker import CircuitBreakerXRepository
from xunfurls.application.presenters.x_unfurl_blocks import XUnfurlBlocksBuilder
from xunfurls.application.services.x_unfurl_service import XUnfurlService
from xunfurls.infrastructure.gcp.slack_client import SlackHttpClient
from xunfurls.infrastructure.gcp.xai_client import XAIClient

logger = logging.getLogger(__name__)


@asynccontextmanager
async def create_managed_unfurl_service() -> AsyncIterator[XUnfurlService]:
    """Create service with proper lifecycle management.

    Composes the XRepository with caching and circuit breaker middleware:
        XAIClient -> CircuitBreaker -> Cache -> XUnfurlService

    Yields the configured XUnfurlService and ensures HTTP clients are
    closed on exit.

    Yields:
        Configured XUnfurlService instance
    """
    xai_client = XAIClient()
    slack_client = SlackHttpClient()
    blocks_builder = XUnfurlBlocksBuilder()

    # Compose middleware: circuit breaker wraps xAI, cache wraps that
    breaker = CircuitBreakerXRepository(
        xai_client, failure_threshold=5, recovery_timeout_seconds=60.0
    )
    cached = CachingXRepository(breaker, ttl_seconds=3600, max_size=100)

    try:
        service = XUnfurlService(
            x_repo=cached, slack_repo=slack_client, blocks_builder=blocks_builder
        )
        yield service
    finally:
        await xai_client.close()
        logger.info("XAI client closed")
        await slack_client.close()
        logger.info("Slack client closed")
