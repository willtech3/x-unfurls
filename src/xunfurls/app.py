"""Application factory for creating service instances."""

from xunfurls.application.presenters.x_unfurl_blocks import XUnfurlBlocksBuilder
from xunfurls.application.services.x_unfurl_service import XUnfurlService
from xunfurls.infrastructure.gcp.slack_client import SlackHttpClient
from xunfurls.infrastructure.gcp.xai_client import XAIClient


def create_unfurl_service() -> XUnfurlService:
    """Create and configure the X unfurl service.

    Returns:
        Configured XUnfurlService instance
    """
    # Create infrastructure dependencies
    x_repo = XAIClient()
    slack_repo = SlackHttpClient()
    blocks_builder = XUnfurlBlocksBuilder()

    # Create and return service
    return XUnfurlService(x_repo=x_repo, slack_repo=slack_repo, blocks_builder=blocks_builder)
