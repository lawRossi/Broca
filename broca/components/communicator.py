"""Communicator component interface.

Abstracts the communication layer (SocketIO, WebSocket, CLI, etc.).
The default implementation is ``SocketIOClient``.

Method signatures are aligned with the existing ``SocketIOClient``
implementation to ensure backward compatibility.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Optional

from broca.components.base import BaseComponent

if TYPE_CHECKING:
    from broca.communication.socketio_client import Message


class Communicator(BaseComponent, ABC):
    """Communication interface for agents.

    Abstracts SocketIO-based communication.  Holds a persistent connection,
    so it is **per-agent** scoped and requires ``shutdown()``.
    """

    agent_id: str
    """Unique identifier for this agent's connection."""

    @abstractmethod
    async def connect(self, timeout: float = 10.0) -> bool:
        """Establish the communication connection.

        Args:
            timeout: Connection timeout in seconds.

        Returns:
            True if connected successfully.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the communication connection."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Check whether the connection is active."""
        ...

    # ------------------------------------------------------------------
    # Message sending (signatures aligned with SocketIOClient)
    # ------------------------------------------------------------------

    @abstractmethod
    async def send_message(
        self,
        message: "Message",
        callback: Optional[Callable] = None,
        retry_on_disconnect: bool = True,
    ) -> str:
        """Send a message to the server.

        Args:
            message: ``Message`` object to send.
            callback: Optional callback for response.
            retry_on_disconnect: Whether to reconnect if disconnected.

        Returns:
            Message ID.
        """
        ...

    @abstractmethod
    async def send_user_message(
        self,
        content: str,
        subscription: Optional[str] = None,
        receiver_id: Optional[str] = None,
    ) -> str:
        """Send a user-facing message.

        Args:
            content: Message content.
            subscription: Target subscription (session_id).
            receiver_id: Optional target user.

        Returns:
            Message ID.
        """
        ...

    @abstractmethod
    async def send_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: str,
        turn_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> str:
        """Broadcast a tool call event.

        Args:
            tool_call_id: Unique ID for this tool call.
            tool_name: Name of the tool.
            arguments: JSON string of tool arguments.
            turn_id: Current turn ID.
            agent_id: Agent making the call.
            subscription: Target subscription.

        Returns:
            Message ID.
        """
        ...

    @abstractmethod
    async def send_error(
        self,
        error_info: dict,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> str:
        """Send a structured error message to the frontend.

        Args:
            error_info: Structured error dict from ``BrocaError.to_dict()``.
            receiver_id: Optional target receiver.
            room: Optional room.
            subscription: Target subscription.
            callback: Optional callback.

        Returns:
            Message ID.
        """
        ...

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def initialize(
        self,
        agent_id: str,
        session_id: Optional[str] = None,
        config: Any = None,
    ) -> None:
        """Initialize the communicator connection.

        Args:
            agent_id: Unique agent identifier (also used as client_id).
            session_id: Optional session subscription.
            config: Configuration (server_url, client_type, etc.).
        """
        ...
