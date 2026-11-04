"""SessionRunner ABC — interface for session runner process management.

Manages IPC-based session runner processes: start, stop, command
dispatch, and event subscription.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional


class SessionRunner(ABC):
    """Abstract base class for session runner management.

    Implementations manage IPC-based runner subprocesses that handle
    session lifecycle and command dispatch.
    """

    @abstractmethod
    async def start_session(
        self, session_id: str, **kwargs: Any
    ) -> Optional[Any]:
        """Start a session runner. Returns runner info or None."""
        ...

    @abstractmethod
    async def stop_session(
        self, session_id: str, timeout: float = 5.0
    ) -> bool:
        """Stop a session runner. Returns True if successfully stopped."""
        ...

    @abstractmethod
    async def request_stop(self, session_id: str) -> dict:
        """Request a graceful stop without waiting for the process to exit.

        Returns a dict like ``{"session_id", "status", "message"}``.
        """
        ...

    @abstractmethod
    async def send_command(
        self, session_id: str, msg_type: Any, payload: dict, **kwargs: Any
    ) -> Any:
        """Send a command to a running session runner."""
        ...

    @abstractmethod
    async def restart_session(self, session_id: str) -> Any:
        """Restart a session runner. Returns the new runner info."""
        ...

    @abstractmethod
    def get_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Return the runner status dict for a session, or None if absent."""
        ...

    @abstractmethod
    def list_sessions(self) -> list[Dict[str, Any]]:
        """Return status dicts for all runners."""
        ...

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Return aggregate runner statistics."""
        ...

    @abstractmethod
    def on(
        self, event: str, handler: Callable[..., Any]
    ) -> None:
        """Register an event handler."""
        ...

    @abstractmethod
    async def start_heartbeat_monitor(self) -> None:
        """Start the background heartbeat/health monitor."""
        ...

    @abstractmethod
    async def stop_heartbeat_monitor(self) -> None:
        """Stop the background heartbeat/health monitor."""
        ...

    @abstractmethod
    async def restore_active_sessions(self) -> int:
        """Reclaim runner records left over from a previous process.

        Returns the number of records inspected.
        """
        ...

    @abstractmethod
    async def shutdown_all(self) -> int:
        """Stop every runner. Returns the number successfully stopped."""
        ...
