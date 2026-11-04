"""Communicator component interface.

Abstracts the communication layer (SocketIO, WebSocket, CLI, etc.).
The default implementation is ``SocketIOClient``.

Method signatures are aligned with the existing ``SocketIOClient``
implementation to ensure backward compatibility.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

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
        tool_call_id: Optional[str] = None,
        tool_name: str = "",
        arguments: Optional[str] = None,
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
    # High-frequency send methods (MUST be implemented)
    # ------------------------------------------------------------------

    @abstractmethod
    async def send_agent_response(
        self,
        content: str,
        subscription: Optional[str] = None,
        receiver_id: Optional[str] = None,
    ) -> str:
        """Send an agent response message."""
        ...

    @abstractmethod
    async def send_turn_start(
        self,
        turn_id: str,
        turn_description: str,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> str:
        """Broadcast turn start event."""
        ...

    @abstractmethod
    async def send_turn_end(
        self,
        turn_id: str,
        result: Optional[str] = None,
        turn_description: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
        callback: Optional[Callable] = None,
        message_id: Optional[str] = None,
        changed_files: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Broadcast turn end event."""
        ...

    @abstractmethod
    async def send_task_complete(
        self,
        task_id: str,
        result: str,
        receiver_id: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> str:
        """Send task completion notification."""
        ...

    @abstractmethod
    async def send_task_error(
        self,
        task_id: str,
        error_message: str,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> str:
        """Send task error notification."""
        ...

    @abstractmethod
    async def send_permission_request(
        self,
        message: str,
        request_id: Optional[str] = None,
        request_type: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> str:
        """Send a permission request to the user."""
        ...

    @abstractmethod
    async def send_permission_response(
        self,
        granted: bool,
        request_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> str:
        """Send a permission response."""
        ...

    @abstractmethod
    async def send_command(
        self,
        command: str,
        arguments: Optional[Dict[str, Any]] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> str:
        """Send a command message."""
        ...

    # ------------------------------------------------------------------
    # Event system (MUST be implemented)
    # ------------------------------------------------------------------

    @abstractmethod
    def register_event_handler(self, event_name: str, func: Callable) -> None:
        """Register an event handler callback."""
        ...

    # ------------------------------------------------------------------
    # Subscription (MUST be implemented)
    # ------------------------------------------------------------------

    @abstractmethod
    async def subscribe(self, subscription: str) -> str:
        """Subscribe to a channel/topic."""
        ...

    @abstractmethod
    async def unsubscribe(self, subscription: str) -> str:
        """Unsubscribe from a channel/topic."""
        ...

    # ------------------------------------------------------------------
    # Low-frequency methods (optional — default no-op)
    # ------------------------------------------------------------------

    @abstractmethod
    async def send_command_result(
        self,
        command: str,
        result: str,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> str:
        """Send command execution result."""
        ...

    @abstractmethod
    async def send_task_start(
        self,
        task_id: str,
        task_description: str,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> str:
        """Broadcast task start event."""
        ...

    async def send_user_answer(
        self,
        question_id: str,
        answer: str,
        subscription: Optional[str] = None,
    ) -> str:
        """Send user's answer to a question."""
        return ""

    async def send_broadcast(
        self,
        content: str,
        subscription: Optional[str] = None,
    ) -> str:
        """Broadcast a message to all subscribers."""
        return ""

    async def send_agent_system_message(
        self,
        content: str,
        subscription: Optional[str] = None,
    ) -> str:
        """Send an agent system-level message."""
        return ""

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
