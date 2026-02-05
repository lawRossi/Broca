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


class MessageSubType(str, Enum):
    """Subtypes for more specific message categorization"""

    # User message subtypes
    USER_INPUT = "user_input"
    USER_COMMAND = "user_command"
    USER_FILE = "user_file"

    # Agent response subtypes
    AGENT_TEXT = "agent_text"
    AGENT_REASONING = "agent_reasoning"
    AGENT_ACTION = "agent_action"

    # Task subtypes
    TASK_CREATE = "task_create"
    TASK_UPDATE = "task_update"
    TASK_DELETE = "task_delete"

    # Tool subtypes
    TOOL_EXECUTE = "tool_execute"
    TOOL_SUCCESS = "tool_success"
    TOOL_FAILURE = "tool_failure"

    # Error subtypes
    ERROR_CONNECTION = "error_connection"
    ERROR_AUTH = "error_auth"
    ERROR_VALIDATION = "error_validation"
    ERROR_INTERNAL = "error_internal"


class MessageStatus(IntEnum):
    """Message status codes"""

    # Success
    OK = 200
    CREATED = 201
    ACCEPTED = 202

    # Client errors
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    CONFLICT = 409

    # Server errors
    INTERNAL_ERROR = 500
    NOT_IMPLEMENTED = 501
    SERVICE_UNAVAILABLE = 503


@dataclass
class Message:
    """Base message structure for all communications"""

    # Required fields
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    message_type: MessageType = MessageType.USER_MESSAGE
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # Optional fields
    sub_type: Optional[MessageSubType] = None
    status: Optional[MessageStatus] = None
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

        if self.sub_type:
            result["sub_type"] = (
                self.sub_type.value
                if isinstance(self.sub_type, MessageSubType)
                else self.sub_type
            )
        if self.status:
            result["status"] = (
                self.status.value
                if isinstance(self.status, MessageStatus)
                else self.status
            )
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

        sub_type_str = data.get("sub_type")
        sub_type: Optional[MessageSubType] = None
        if sub_type_str:
            try:
                sub_type = MessageSubType(sub_type_str)
            except ValueError:
                sub_type = None

        status_value = data.get("status")
        status: Optional[MessageStatus] = None
        if status_value is not None:
            try:
                status = MessageStatus(status_value)
            except ValueError:
                status = None

        return cls(
            message_id=data.get("message_id", str(uuid.uuid4())),
            message_type=message_type,
            timestamp=data.get("timestamp", datetime.utcnow().isoformat()),
            sub_type=sub_type,
            status=status,
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

    def is_error(self) -> bool:
        """Check if message represents an error"""
        return self.status is not None and self.status.value >= 400

    def is_success(self) -> bool:
        """Check if message represents success"""
        return self.status is not None and self.status.value < 400

    def __str__(self) -> str:
        """String representation for logging"""
        parts = [
            f"Message(id={self.message_id[:8]}...)",
            f"type={self.message_type.value}",
        ]
        if self.sub_type:
            parts.append(f"sub={self.sub_type.value}")
        if self.sender_id:
            parts.append(f"from={self.sender_id}")
        if self.receiver_id:
            parts.append(f"to={self.receiver_id}")
        if self.room:
            parts.append(f"room={self.room}")
        if self.is_error():
            parts.append(f"ERROR: {self.error_message}")
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
            sub_type=MessageSubType.USER_INPUT,
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
            sub_type=MessageSubType.AGENT_TEXT,
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
            sub_type=MessageSubType.ERROR_INTERNAL,
            status=MessageStatus.INTERNAL_ERROR,
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
            sub_type=MessageSubType.TASK_CREATE,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data={
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
            sub_type=MessageSubType.TASK_UPDATE,
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
            sub_type=MessageSubType.TASK_UPDATE,
            sender_id=sender_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data=data,
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
            sub_type=MessageSubType.TOOL_EXECUTE,
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
            sub_type=MessageSubType.TOOL_SUCCESS,
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
