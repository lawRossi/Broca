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
    async def send_command(
        self, session_id: str, msg_type: Any, payload: dict, **kwargs: Any
    ) -> Any:
        """Send a command to a running session runner."""
        ...

    @abstractmethod
    def on(
        self, event: str, handler: Callable[..., Any]
    ) -> None:
        """Register an event handler."""
        ...
