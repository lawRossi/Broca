"""ProcessManager ABC — interface for background process management.

Manages lifecycle of background processes (start, stop, status, cleanup).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ProcessManager(ABC):
    """Abstract base class for process management.

    Implementations manage background process lifecycle: starting,
    monitoring, stopping, and cleaning up processes.
    """

    @abstractmethod
    async def start_process(
        self, command: str, **kwargs: Any
    ) -> Optional[str]:
        """Start a background process. Returns the process ID or None."""
        ...

    @abstractmethod
    def get_status(self, process_id: str) -> Optional[Any]:
        """Get the current status of a process. Returns ProcessInfo or None."""
        ...

    @abstractmethod
    async def stop_process(
        self, process_id: str, force: bool = False
    ) -> bool:
        """Stop a running process. Returns True if successfully stopped.

        Must not raise for already-exited PIDs.
        """
        ...

    @abstractmethod
    def list_processes(self) -> List[Any]:
        """List all managed processes. Returns list of ProcessInfo."""
        ...

    @abstractmethod
    async def cleanup(self) -> None:
        """Stop all running processes and clean up resources."""
        ...
