"""SessionManager ABC — interface for session and message persistence.

Manages session lifecycle, message storage, turn tracking, and
context truncation markers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class SessionManager(ABC):
    """Abstract base class for session/message persistence.

    Implementations handle storage of conversation messages, session
    metadata, and turn boundaries.
    """

    # -- Session lifecycle ------------------------------------------------

    @abstractmethod
    async def create_session(
        self, **kwargs: Any
    ) -> str:
        """Create a new session. Returns the session ID."""
        ...

    # -- Message CRUD -----------------------------------------------------

    @abstractmethod
    async def save_message(
        self,
        role: str,
        content: str | None,
        **kwargs: Any,
    ) -> bool:
        """Persist a message to the session. Returns True on success."""
        ...

    @abstractmethod
    async def get_messages(
        self, agent_id: str | None = None, **kwargs: Any
    ) -> list:
        """Retrieve messages from the session."""
        ...

    # -- Turn management ---------------------------------------------------

    @abstractmethod
    async def start_turn(
        self, **kwargs: Any
    ) -> str:
        """Start a new turn. Returns the turn ID."""
        ...

    # -- Context compression support ---------------------------------------

    @abstractmethod
    async def mark_messages_before_as_truncated(
        self, agent_id: str, keep_from_message_id: str
    ) -> int:
        """Mark all messages before the given message as truncated
        (for context compression). Returns count of marked messages."""
        ...

    # -- Properties --------------------------------------------------------

    session_id: str
    """The current session ID (set after create_session)."""
