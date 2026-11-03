"""Scheduler ABC — interface for job scheduling and execution."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class SchedulerABC(ABC):
    """Abstract base class for job scheduling.

    Implementations wrap a scheduling backend (e.g. APScheduler) and
    provide a uniform API for job lifecycle management.
    """

    @abstractmethod
    async def start(self) -> None:
        """Start the scheduler."""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Shut down the scheduler gracefully."""
        ...

    @abstractmethod
    async def add_job(
        self,
        session_id: str,
        name: str,
        job_type: Any,
        trigger_type: str,
        trigger_config: Dict[str, Any],
        content: str,
        agent_id: Optional[str] = None,
        notify: bool = False,
    ) -> str:
        """Add a new job. Returns the job ID."""
        ...

    @abstractmethod
    async def remove_job(self, job_id: str) -> bool:
        """Remove a job. Returns True if removed."""
        ...

    @abstractmethod
    async def pause_job(self, job_id: str) -> bool:
        """Pause a running job."""
        ...

    @abstractmethod
    async def resume_job(self, job_id: str) -> bool:
        """Resume a paused job."""
        ...

    @abstractmethod
    async def list_jobs(self, session_id: str) -> List[Dict[str, Any]]:
        """List all jobs for a session."""
        ...

    @abstractmethod
    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a job by ID. Returns None if not found."""
        ...

    @abstractmethod
    async def execute_job_now(self, job_id: str) -> bool:
        """Trigger immediate execution of a job."""
        ...

    @abstractmethod
    async def cancel_job_execution(self, job_id: str) -> bool:
        """Cancel an in-progress job execution."""
        ...

    @abstractmethod
    async def cleanup(self) -> None:
        """Cleanup resources (remove finished one-time jobs, etc.)."""
        ...
