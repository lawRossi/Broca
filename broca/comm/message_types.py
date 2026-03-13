"""
Message Types and Protocol Definitions

This module defines the message types and protocol for multi-endpoint communication.
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from typing import Any, Dict, Optional


class MessageType(str, Enum):
    """Main message types for communication"""

    # System messages
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    PING = "ping"
    PONG = "pong"
    ERROR = "error"

    # User interaction messages
    USER_MESSAGE = "user_message"
    AGENT_RESPONSE = "agent_response"
    AGENT_THINKING = "agent_thinking"
    AGENT_ERROR = "agent_error"

    # Task management
    TASK_START = "task_start"
    TASK_PROGRESS = "task_progress"
    TASK_COMPLETE = "task_complete"
    TASK_FAILED = "task_failed"

    # Turn management
    TURN_START = "turn_start"
    TURN_END = "turn_end"

    # Tool execution
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # Subscription and broadcasting
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    BROADCAST = "broadcast"

    # Command messages
    COMMAND = "command"
    COMMAND_RESULT = "command_result"

    # Permission messages
    PERMISSION_REQUEST = "permission_request"
    PERMISSION_RESPONSE = "permission_response"


@dataclass
class Message:
    """Base message structure for all communications"""

    # Required fields
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    message_type: MessageType = MessageType.USER_MESSAGE
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # Optional fields
    sender_id: Optional[str] = None
    receiver_id: Optional[str] = None
    room: Optional[str] = None
    subscription: Optional[str] = None

    # Payload
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Error information
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary"""
        result: Dict[str, Any] = {
            "message_id": self.message_id,
            "message_type": self.message_type.value
            if isinstance(self.message_type, MessageType)
            else self.message_type,
            "timestamp": self.timestamp,
        }

        if self.sender_id:
            result["sender_id"] = self.sender_id
        if self.receiver_id:
            result["receiver_id"] = self.receiver_id
        if self.room:
            result["room"] = self.room
        if self.subscription:
            result["subscription"] = self.subscription
        if self.data:
            result["data"] = self.data
        if self.metadata:
            result["metadata"] = self.metadata
        if self.error_code:
            result["error_code"] = self.error_code
        if self.error_message:
            result["error_message"] = self.error_message

        return result

    def to_json(self) -> str:
        """Convert message to JSON string"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """Create message from dictionary"""
        message_type_str = data.get("message_type", MessageType.USER_MESSAGE)
        message_type: MessageType
        if isinstance(message_type_str, str):
            try:
                message_type = MessageType(message_type_str)
            except ValueError:
                message_type = MessageType.USER_MESSAGE
        else:
            message_type = message_type_str

        return cls(
            message_id=data.get("message_id", str(uuid.uuid4())),
            message_type=message_type,
            timestamp=data.get("timestamp", datetime.utcnow().isoformat()),
            sender_id=data.get("sender_id"),
            receiver_id=data.get("receiver_id"),
            room=data.get("room"),
            subscription=data.get("subscription"),
            data=data.get("data", {}),
            metadata=data.get("metadata", {}),
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "Message":
        """Create message from JSON string"""
        data = json.loads(json_str)
        return cls.from_dict(data)

    def __str__(self) -> str:
        """String representation for logging"""
        parts = [
            f"Message(id={self.message_id[:8]}...)",
            f"type={self.message_type.value}",
        ]
        if self.sender_id:
            parts.append(f"from={self.sender_id}")
        if self.receiver_id:
            parts.append(f"to={self.receiver_id}")
        if self.room:
            parts.append(f"room={self.room}")
        return " ".join(parts)


class MessageProtocol:
    """Protocol handler for message validation and processing"""

    @staticmethod
    def validate_message(message: Message) -> tuple[bool, Optional[str]]:
        """
        Validate a message structure

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not message.message_type:
            return False, "Message type is required"

        if not isinstance(message.message_type, MessageType):
            return False, f"Invalid message type: {message.message_type}"

        # Validate message type specific rules
        if message.message_type == MessageType.USER_MESSAGE:
            if not message.data.get("content"):
                return False, "User message requires content"

        if message.message_type == MessageType.AGENT_RESPONSE:
            if not message.data.get("content") and not message.data.get(
                "reasoning_content"
            ):
                return False, "Agent response requires content or reasoning_content"

        if message.message_type == MessageType.TOOL_CALL:
            if not message.data.get("tool_name"):
                return False, "Tool call requires tool_name"

        if message.message_type == MessageType.ERROR:
            if not message.error_code:
                return False, "Error message requires error_code"

        return True, None

    @staticmethod
    def create_user_message(
        content: str,
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> Message:
        """Create a user message"""
        return Message(
            message_type=MessageType.USER_MESSAGE,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data={"content": content},
        )

    @staticmethod
    def create_agent_response(
        content: str,
        reasoning_content: Optional[str] = None,
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> Message:
        """Create an agent response message"""
        data: Dict[str, Any] = {"content": content}
        if reasoning_content:
            data["reasoning_content"] = reasoning_content

        return Message(
            message_type=MessageType.AGENT_RESPONSE,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data=data,
        )

    @staticmethod
    def create_error_message(
        error_code: str,
        error_message: str,
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> Message:
        """Create an error message"""
        return Message(
            message_type=MessageType.ERROR,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            error_code=error_code,
            error_message=error_message,
        )

    @staticmethod
    def create_task_start(
        task_id: str,
        task_description: str,
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> Message:
        """Create a task start message"""
        return Message(
            message_type=MessageType.TASK_START,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data={
                "assigner": sender_id,
                "task_id": task_id,
                "task_description": task_description,
            },
        )

    @staticmethod
    def create_task_progress(
        task_id: str,
        progress: float,
        message: Optional[str] = None,
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> Message:
        """Create a task progress message"""
        data: Dict[str, Any] = {
            "task_id": task_id,
            "progress": progress,
        }
        if message:
            data["message"] = message

        return Message(
            message_type=MessageType.TASK_PROGRESS,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data=data,
        )

    @staticmethod
    def create_task_complete(
        task_id: str,
        result: Optional[str] = None,
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> Message:
        """Create a task complete message"""
        data: Dict[str, Any] = {"task_id": task_id}
        if result:
            data["result"] = result

        return Message(
            message_type=MessageType.TASK_COMPLETE,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data=data,
        )

    @staticmethod
    def create_task_error(
        task_id: str,
        error_message: str,
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> Message:
        """Create a task error message"""
        return Message(
            message_type=MessageType.TASK_FAILED,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            error_code=task_id,
            error_message=error_message,
        )

    @staticmethod
    def create_turn_start(
        turn_id: str,
        turn_description: str,
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> Message:
        """Create a turn start message"""
        return Message(
            message_type=MessageType.TURN_START,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data={
                "turn_id": turn_id,
                "turn_description": turn_description,
            },
        )

    @staticmethod
    def create_turn_end(
        turn_id: str,
        result: Optional[str] = None,
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> Message:
        """Create a turn end message"""
        data: Dict[str, Any] = {"turn_id": turn_id}
        if result:
            data["result"] = result

        return Message(
            message_type=MessageType.TURN_END,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data=data,
        )

    @staticmethod
    def create_tool_call(
        tool_name: str,
        arguments: Dict[str, Any],
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> Message:
        """Create a tool call message"""
        return Message(
            message_type=MessageType.TOOL_CALL,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data={
                "tool_name": tool_name,
                "arguments": arguments,
            },
        )

    @staticmethod
    def create_tool_result(
        tool_name: str,
        result: Any,
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> Message:
        """Create a tool result message"""
        return Message(
            message_type=MessageType.TOOL_RESULT,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data={
                "tool_name": tool_name,
                "result": result,
            },
        )

    @staticmethod
    def create_subscribe(
        subscription: str,
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
    ) -> Message:
        """Create a subscribe message"""
        return Message(
            message_type=MessageType.SUBSCRIBE,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
        )

    @staticmethod
    def create_unsubscribe(
        subscription: str,
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
    ) -> Message:
        """Create an unsubscribe message"""
        return Message(
            message_type=MessageType.UNSUBSCRIBE,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
        )

    @staticmethod
    def create_broadcast(
        content: str,
        subscription: Optional[str] = None,
        sender_id: Optional[str] = None,
        room: Optional[str] = None,
    ) -> Message:
        """Create a broadcast message"""
        return Message(
            message_type=MessageType.BROADCAST,
            sender_id=sender_id,
            room=room,
            subscription=subscription,
            data={"content": content},
        )

    @staticmethod
    def create_command(
        command: str,
        arguments: Optional[Dict[str, Any]] = None,
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> Message:
        """Create a command message"""
        data: Dict[str, Any] = {"command": command}
        if arguments:
            data["arguments"] = arguments

        return Message(
            message_type=MessageType.COMMAND,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data=data,
        )

    @staticmethod
    def create_command_result(
        command: str,
        result: Any,
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> Message:
        """Create a command result message"""
        return Message(
            message_type=MessageType.COMMAND_RESULT,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data={
                "command": command,
                "result": result,
            },
        )

    @staticmethod
    def create_permission_request(
        message: str,
        request_id: Optional[str] = None,
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> Message:
        """Create a permission request message"""
        data: Dict[str, Any] = {"message": message}
        if request_id:
            data["request_id"] = request_id

        return Message(
            message_type=MessageType.PERMISSION_REQUEST,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data=data,
        )

    @staticmethod
    def create_permission_response(
        granted: bool,
        request_id: Optional[str] = None,
        sender_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> Message:
        """Create a permission response message"""
        data: Dict[str, Any] = {"granted": granted}
        if request_id:
            data["request_id"] = request_id

        return Message(
            message_type=MessageType.PERMISSION_RESPONSE,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data=data,
        )
