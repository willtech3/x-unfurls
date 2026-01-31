"""Protocol definitions for job queue repositories."""

from typing import Protocol, runtime_checkable

from shared.domain.dtos import XUnfurlJobDto


@runtime_checkable
class JobQueueProducer(Protocol):
    """Interface for queue producers."""

    async def enqueue_job(self, job: XUnfurlJobDto) -> str:
        """Enqueue a job and return the message ID."""
        ...
