"""
TUI Data Models

Contains data structures for the TUI application:
- ChatMessage: Chat message data structure
- MessageBuffer: Thread-safe message buffer
- StatusIndicator: Connection status indicator
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from broca.session.models import MessageRole
from broca.session.models import MessageType as SessionMessageType


@dataclass
class ChatMessage:
    """Chat message data structure for TUI display"""

    # TUI-specific message type for display styling
    class DisplayType(Enum):
        """Message types for TUI display styling"""

        USER = "user"
        ASSISTANT = "assistant"
        SYSTEM = "system"
        ERROR = "error"
        TOOL = "tool"
        TOOL_CALL = "tool_call"
        PERMISSION = "permission"

    content: str
    display_type: DisplayType
    timestamp: datetime = field(default_factory=datetime.now)
    message_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Optional session model fields for compatibility
    role: Optional[MessageRole] = None
    message_type: Optional[SessionMessageType] = None
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    agent_id: Optional[str] = None
    sequence_number: Optional[int] = None

    @classmethod
    def from_session_message(
        cls, message: Any, display_type: Optional[DisplayType] = None
    ) -> "ChatMessage" or None:
        """Create a ChatMessage from a session message model"""
        if message.role not in [
            MessageRole.USER,
            MessageRole.ASSISTANT,
            MessageRole.SYSTEM,
        ]:
            return None
        content = message.content
        if not content:
            return None
        try:
            json_content = json.loads(content)
            content = json_content["content"]
            if not content:
                return None
        except json.JSONDecodeError:
            pass
        # Determine display type from role and message type
        if display_type is None:
            if hasattr(message, "role"):
                if message.role == MessageRole.USER:
                    display_type = cls.DisplayType.USER
                elif message.role == MessageRole.ASSISTANT:
                    display_type = cls.DisplayType.ASSISTANT
                elif message.role == MessageRole.SYSTEM:
                    if (
                        hasattr(message, "message_type")
                        and message.message_type == SessionMessageType.ERROR
                    ):
                        display_type = cls.DisplayType.ERROR
                    else:
                        display_type = cls.DisplayType.SYSTEM
                elif message.role == MessageRole.TOOL:
                    display_type = cls.DisplayType.TOOL
                else:
                    display_type = cls.DisplayType.SYSTEM
            else:
                display_type = cls.DisplayType.SYSTEM

        return cls(
            content=content,
            display_type=display_type,
            timestamp=message.timestamp
            if hasattr(message, "timestamp")
            else datetime.now(),
            message_id=message.message_id if hasattr(message, "message_id") else None,
            role=getattr(message, "role", None),
            message_type=getattr(message, "message_type", None),
            session_id=getattr(message, "session_id", None),
            turn_id=getattr(message, "turn_id", None),
            agent_id=getattr(message, "agent_id", None),
            sequence_number=getattr(message, "sequence_number", None),
            metadata={},
        )


class MessageBuffer:
    """
    Thread-safe message buffer for storing chat messages

    支持两种类型的消息:
    1. ChatMessage 对象 (TUI 显示消息)
    2. Session 消息对象 (通过 add_session_message 方法)
    """

    def __init__(self, max_size: int = 1000):
        self._messages: List[ChatMessage] = []
        self._max_size = max_size
        self._lock = asyncio.Lock()

    async def add_message(self, message: ChatMessage):
        """Add a ChatMessage to the buffer"""
        async with self._lock:
            if len(self._messages) >= self._max_size:
                self._messages.pop(0)
            self._messages.append(message)

    async def add_session_message(
        self, message: Any, display_type: Optional[ChatMessage.DisplayType] = None
    ):
        """
        Add a session message to the buffer

        Args:
            message: A session message object (e.g., Broca.session.models.Message)
            display_type: Optional display type override
        """
        chat_message = ChatMessage.from_session_message(message, display_type)
        if chat_message:
            await self.add_message(chat_message)

    async def get_messages(self) -> List[ChatMessage]:
        """Get all messages from the buffer"""
        async with self._lock:
            return self._messages.copy()

    async def clear(self):
        """Clear all messages from the buffer"""
        async with self._lock:
            self._messages.clear()

    def __len__(self):
        return len(self._messages)


class StatusIndicator:
    """Connection status indicator"""

    def __init__(self):
        # Server connection status
        self.connected = False
        self.connecting = False
        self.session_id: Optional[str] = None
        self.server_url: Optional[str] = None

        # Agent connection status
        self.agent_connected = False
        self.agent_connecting = False
        self.agent_running = False
        self.agent_id: Optional[str] = None

    def set_connecting(self):
        """Set server connection to connecting"""
        self.connecting = True
        self.connected = False

    def set_connected(self, session_id: str, server_url: str):
        """Set server connection to connected"""
        self.connecting = False
        self.connected = True
        self.session_id = session_id
        self.server_url = server_url

    def set_disconnected(self):
        """Set server connection to disconnected"""
        self.connecting = False
        self.connected = False
        self.session_id = None

    def set_agent_connecting(self):
        """Set agent connection to connecting"""
        self.agent_connecting = True
        self.agent_connected = False

    def set_agent_connected(self, agent_id: str):
        """Set agent connection to connected"""
        self.agent_connecting = False
        self.agent_connected = True
        self.agent_running = False
        self.agent_id = agent_id

    def set_agent_disconnected(self):
        """Set agent connection to disconnected"""
        self.agent_connecting = False
        self.agent_connected = False
        self.agent_running = False
        self.agent_id = None

    def set_agent_running(self):
        """Set agent to running state (thinking)"""
        self.agent_running = True

    def set_agent_idle(self):
        """Set agent to idle state (finished thinking)"""
        self.agent_running = False

    def get_status_text(self) -> str:
        """Get server connection status text"""
        if self.connecting:
            return "Connecting..."
        elif self.connected:
            return f"Connected [{self.session_id}]"
        else:
            return "Disconnected"

    def get_status_color(self) -> str:
        """Get server connection status color"""
        if self.connecting:
            return "yellow"
        elif self.connected:
            return "green"
        else:
            return "red"

    def get_agent_status_text(self) -> str:
        """Get agent connection status text"""
        if self.agent_connecting:
            return "Agent Connecting..."
        elif self.agent_connected and self.agent_running:
            return "Agent Running"
        elif self.agent_connected:
            return "Agent Connected"
        else:
            return "Agent Disconnected"

    def get_agent_status_color(self) -> str:
        """Get agent connection status color"""
        if self.agent_connecting:
            return "yellow"
        elif self.agent_connected and self.agent_running:
            return "cyan"
        elif self.agent_connected:
            return "green"
        else:
            return "red"
