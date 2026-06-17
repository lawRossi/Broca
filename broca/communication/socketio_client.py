"""
Socket.io Client Module

This module provides a Socket.io client for multi-endpoint communication.
Supports browser, command-line, VSCode plugin, and browser plugin clients.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from socketio import AsyncClient

from broca.logging_config import get_logger
from broca.session.models import Message, MessageProtocol, MessageRole, MessageType

logger = get_logger(__name__)


@dataclass
class ConnectionInfo:
    """Connection information"""

    server_url: str
    client_id: str
    client_type: str
    user_id: Optional[str] = None
    connected: bool = False
    subscriptions: List[str] = field(default_factory=list)


class SocketIOClient:
    """
    Socket.io client for multi-endpoint communication.

    Features:
    - Connect to Socket.io server
    - Send and receive messages
    - Subscribe to channels
    - Handle events
    - Automatic reconnection
    """

    def __init__(
        self,
        server_url: str = "http://localhost:6868",
        client_type: str = "cli",
        client_id: Optional[str] = None,
        user_id: Optional[str] = None,
        auto_reconnect: bool = True,
        reconnect_delay: float = 1.0,
        max_reconnect_attempts: int = 5,
    ):
        """
        Initialize Socket.io client

        Args:
            server_url: Socket.io server URL
            client_type: Client type (browser, cli, vscode, browser_plugin)
            client_id: Client identifier
            user_id: User identifier
            auto_reconnect: Enable automatic reconnection
            reconnect_delay: Delay between reconnection attempts
            max_reconnect_attempts: Maximum reconnection attempts
        """
        self.server_url = server_url
        self.client_type = client_type
        self.client_id = client_id or f"{client_type}_{id(self)}"
        self.user_id = user_id
        self.auto_reconnect = auto_reconnect
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts

        # Initialize Socket.io client
        self.sio = AsyncClient(logger=False, engineio_logger=False)

        # Connection info
        self.connection_info = ConnectionInfo(
            server_url=server_url,
            client_id=self.client_id,
            client_type=client_type,
            user_id=user_id,
        )

        # Event handlers
        self.event_handlers: Dict[str, List[Callable]] = {}

        # Message callbacks
        self.message_callbacks: Dict[str, Callable] = {}

        # Connection event for waiting on connection
        self._connect_event = asyncio.Event()

        # Setup event handlers
        self._setup_event_handlers()

        # Reconnection state
        self._reconnect_task: Optional[asyncio.Task] = None
        self._should_reconnect = False

    def _setup_event_handlers(self):
        """Setup Socket.io event handlers"""

        @self.sio.event
        async def connect():
            """Handle connection to server"""
            logger.debug(f"Connected to server at {self.server_url}")
            self.connection_info.connected = True

            # Signal that connection is complete
            self._connect_event.set()

            # Send connection info
            headers = {
                "X-Client-Type": self.client_type,
                "X-Client-ID": self.client_id,
            }
            if self.user_id:
                headers["X-User-ID"] = self.user_id

            # Trigger connect event
            await self._trigger_event("connect")

            # Send connection message
            connect_msg = MessageProtocol.create_user_message(
                content="Connected to server", sender_id=self.client_id
            )
            connect_msg.message_type = MessageType.CONNECT

            await self.send_message(connect_msg)

            logger.debug(f"Client {self.client_id} connected successfully")

        @self.sio.event
        async def disconnect():
            """Handle disconnection from server"""
            logger.debug(f"Disconnected from server at {self.server_url}")
            self.connection_info.connected = False

            # Clear the connect event
            self._connect_event.clear()

            # Trigger disconnect event
            await self._trigger_event("disconnect")

            # Start reconnection if enabled
            if self.auto_reconnect and self._should_reconnect:
                self._reconnect_task = asyncio.create_task(self._reconnect())

        @self.sio.event
        async def message(data):
            """Handle incoming messages"""
            try:
                # Parse message
                message_data = json.loads(data) if isinstance(data, str) else data
                message = MessageProtocol.from_dict(message_data)

                # Log message
                logger.debug(f"Received message: {message}")

                # Handle message based on type
                await self._handle_message(message)

                # Trigger message event
                await self._trigger_event("message", message)

                # Call message callback if exists
                if message.message_id in self.message_callbacks:
                    callback = self.message_callbacks[message.message_id]
                    await callback(message)
                    del self.message_callbacks[message.message_id]

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse message: {e}")
            except Exception as e:
                logger.error(f"Error processing message: {e}")

        @self.sio.event
        async def error(data):
            """Handle error messages"""
            logger.error(f"Server error: {data}")
            await self._trigger_event("error", data)

    async def _handle_message(self, message: Message):
        """Handle incoming message"""
        if message.message_type == MessageType.USER_MESSAGE:
            await self._handle_user_message(message)
        elif message.message_type == MessageType.AGENT_RESPONSE:
            await self._handle_agent_response(message)
        elif message.message_type == MessageType.TASK_START:
            await self._handle_task_start(message)
        elif message.message_type == MessageType.TASK_COMPLETE:
            await self._handle_task_complete(message)
        elif message.message_type == MessageType.TURN_START:
            await self._handle_turn_start(message)
        elif message.message_type == MessageType.TURN_END:
            await self._handle_turn_end(message)
        elif message.message_type == MessageType.TOOL_CALL:
            await self._handle_tool_call(message)
        elif message.message_type == MessageType.COMMAND:
            await self._handle_command(message)
        elif message.message_type == MessageType.COMMAND_RESULT:
            await self._handle_command_result(message)
        elif message.message_type == MessageType.PERMISSION_REQUEST:
            await self._handle_permission_request(message)
        elif message.message_type == MessageType.PERMISSION_RESPONSE:
            await self._handle_permission_response(message)
        elif message.message_type == MessageType.AGENT_QUERY:
            await self._handle_agent_query(message)
        elif message.message_type == MessageType.USER_ANSWER:
            await self._handle_user_answer(message)
        elif message.message_type == MessageType.ERROR:
            await self._handle_error(message)
        elif message.message_type == MessageType.SUBSCRIBE:
            await self._handle_subscribe(message)
        elif message.message_type == MessageType.UNSUBSCRIBE:
            await self._handle_unsubscribe(message)
        elif message.message_type == MessageType.BROADCAST:
            await self._handle_broadcast(message)

    async def _handle_user_message(self, message: Message):
        """Handle user message"""
        await self._trigger_event("user_message", message)

    async def _handle_agent_response(self, message: Message):
        """Handle agent response"""
        await self._trigger_event("agent_response", message)

    async def _handle_task_start(self, message: Message):
        """Handle task start"""
        await self._trigger_event("task_start", message)

    async def _handle_task_complete(self, message: Message):
        """Handle task complete"""
        await self._trigger_event("task_complete", message)

    async def _handle_turn_start(self, message: Message):
        """Handle turn start"""
        await self._trigger_event("turn_start", message)

    async def _handle_turn_end(self, message: Message):
        """Handle turn end"""
        await self._trigger_event("turn_end", message)

    async def _handle_tool_call(self, message: Message):
        """Handle tool call"""
        await self._trigger_event("tool_call", message)

    async def _handle_command(self, message: Message):
        """Handle command"""
        await self._trigger_event("command", message)

    async def _handle_command_result(self, message: Message):
        """Handle command result"""
        await self._trigger_event("command_result", message)

    async def _handle_error(self, message: Message):
        """Handle error message"""
        logger.error(f"Error from server: {message.data.get('error_message')}")
        await self._trigger_event("error", message)

    async def _handle_subscribe(self, message: Message):
        """Handle subscribe acknowledgment"""
        if (
            message.subscription
            and message.subscription not in self.connection_info.subscriptions
        ):
            self.connection_info.subscriptions.append(message.subscription)
        await self._trigger_event("subscribe", message)

    async def _handle_unsubscribe(self, message: Message):
        """Handle unsubscribe acknowledgment"""
        if (
            message.subscription
            and message.subscription in self.connection_info.subscriptions
        ):
            self.connection_info.subscriptions.remove(message.subscription)
        await self._trigger_event("unsubscribe", message)

    async def _handle_broadcast(self, message: Message):
        """Handle broadcast message"""
        await self._trigger_event("broadcast", message)

    async def _handle_permission_request(self, message: Message):
        """Handle permission request"""
        await self._trigger_event("permission_request", message)

    async def _handle_permission_response(self, message: Message):
        """Handle permission response"""
        await self._trigger_event("permission_response", message)

    async def _handle_agent_query(self, message: Message):
        """Handle agent query"""
        await self._trigger_event("agent_query", message)

    async def _handle_user_answer(self, message: Message):
        """Handle user answer"""
        await self._trigger_event("user_answer", message)

    async def _trigger_event(self, event_name: str, *args):
        """Trigger event handlers"""
        if event_name in self.event_handlers:
            for handler in self.event_handlers[event_name]:
                try:
                    await handler(*args)
                except Exception as e:
                    logger.error(f"Error in event handler {event_name}: {e}")

    async def connect(self, timeout: float = 10.0) -> bool:
        """Connect to server

        Args:
            timeout: Maximum time to wait for connection to be established
        """
        if self.connection_info.connected:
            logger.warning("Already connected to server")
            return True

        self._should_reconnect = True

        # Clear the connect event before connecting
        self._connect_event.clear()

        try:
            # Add headers for connection
            headers = {
                "X-Client-Type": self.client_type,
                "X-Client-ID": self.client_id,
            }
            if self.user_id:
                headers["X-User-ID"] = self.user_id

            # Connect to server
            await self.sio.connect(
                self.server_url, headers=headers, transports=["websocket", "polling"]
            )

            # Wait for the connect event to be triggered
            try:
                await asyncio.wait_for(self._connect_event.wait(), timeout=timeout)
                return True
            except asyncio.TimeoutError:
                logger.error(f"Connection timeout after {timeout}s")
                await self.sio.disconnect()
                raise RuntimeError(f"Connection timeout after {timeout}s")
                return False

            logger.debug(f"Connected to server at {self.server_url}")

        except Exception as e:
            logger.error(f"Failed to connect to server: {e}")
            if self.auto_reconnect:
                self._reconnect_task = asyncio.create_task(self._reconnect())
            return False

    async def disconnect(self):
        """Disconnect from server"""
        self._should_reconnect = False

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        if self.connection_info.connected:
            await self.sio.disconnect()
            logger.debug(f"Disconnected from server at {self.server_url}")

    async def _reconnect(self):
        """Attempt to reconnect to server"""
        attempt = 0

        while attempt < self.max_reconnect_attempts and self._should_reconnect:
            attempt += 1
            logger.debug(
                f"Reconnection attempt {attempt}/{self.max_reconnect_attempts}"
            )

            try:
                await asyncio.sleep(self.reconnect_delay * attempt)
                await self.connect()
                logger.debug("Reconnected successfully")
                return
            except Exception as e:
                logger.error(f"Reconnection attempt {attempt} failed: {e}")

        logger.error("Max reconnection attempts reached")

    async def send_message(
        self,
        message: Message,
        callback: Optional[Callable] = None,
        retry_on_disconnect: bool = True,
    ) -> str:
        """
        Send message to server with automatic reconnection support

        Args:
            message: Message to send
            callback: Optional callback for response
            retry_on_disconnect: Whether to attempt reconnection if disconnected

        Returns:
            Message ID
        """
        # Check connection and attempt reconnection if needed
        if not self.connection_info.connected:
            if retry_on_disconnect and self.auto_reconnect:
                logger.info("Not connected to server, attempting to reconnect...")
                try:
                    await self.connect()
                except Exception as e:
                    logger.error(f"Failed to reconnect: {e}")
                    raise RuntimeError(
                        "Not connected to server and reconnection failed"
                    )
            else:
                logger.error("Not connected to server")
                raise RuntimeError("Not connected to server")

        # Set sender ID if not set
        if not message.sender_id:
            message.sender_id = self.client_id

        # Register callback if provided
        if callback:
            self.message_callbacks[message.message_id] = callback

        # Send message with retry logic
        max_retries = 2
        for attempt in range(max_retries):
            try:
                await self.sio.emit("message", MessageProtocol.to_dict(message))
                logger.debug(f"Sent message: {message}")
                return message.message_id
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Failed to send message (attempt {attempt + 1}), retrying: {e}"
                    )
                    # Check if we're still connected
                    if not self.connection_info.connected and retry_on_disconnect:
                        try:
                            await self.connect()
                        except Exception as reconnect_error:
                            logger.error(f"Reconnection failed: {reconnect_error}")
                else:
                    logger.error(
                        f"Failed to send message after {max_retries} attempts: {e}"
                    )
                    raise
        return ""

    async def send_user_message(
        self,
        content: str,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> str:
        """Send user message"""
        message = MessageProtocol.create_user_message(
            content=content,
            sender_id=self.client_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
        )
        return await self.send_message(message, callback)

    async def send_agent_response(
        self,
        content: str,
        reasoning_content: Optional[str] = None,
        index: int = 0,
        turn_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        callback: Optional[Callable] = None,
        **kwargs,
    ) -> str:
        """Send agent response"""
        kwargs["sender_id"] = self.client_id
        if turn_id is not None:
            kwargs["turn_id"] = turn_id
        if agent_id is not None:
            kwargs["agent_id"] = agent_id
        message = MessageProtocol.create_agent_response(
            content=content, reasoning_content=reasoning_content, index=index, **kwargs
        )
        return await self.send_message(message, callback)

    async def send_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_call_id: str,
        result: Optional[str] = None,
        status: Optional[bool] = None,
        turn_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
        callback: Optional[Callable] = None,
        message_id: Optional[str] = None,
    ) -> str:
        """Send tool call"""
        message = MessageProtocol.create_tool_call(
            tool_name=tool_name,
            arguments=arguments,
            tool_call_id=tool_call_id,
            result=result,
            status=status,
            sender_id=self.client_id,
            turn_id=turn_id,
            agent_id=agent_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            message_id=message_id,
        )
        return await self.send_message(message, callback)

    async def send_turn_start(
        self,
        turn_id: str,
        turn_description: str,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> str:
        """Send turn start message"""
        message = MessageProtocol.create_turn_start(
            turn_id=turn_id,
            turn_description=turn_description,
            sender_id=self.client_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
        )
        return await self.send_message(message, callback)

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
        """Send turn end message"""
        message = MessageProtocol.create_turn_end(
            turn_id=turn_id,
            result=result,
            turn_description=turn_description,
            changed_files=changed_files,
            sender_id=self.client_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            message_id=message_id,
        )
        return await self.send_message(message, callback)

    async def send_command(
        self,
        command: str,
        arguments: Optional[Dict[str, Any]] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> str:
        """Send command"""
        message = MessageProtocol.create_command(
            command=command,
            arguments=arguments,
            sender_id=self.client_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
        )
        return await self.send_message(message, callback)

    async def send_command_result(
        self,
        command: str,
        result: str,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> str:
        """Send command result"""
        message = Message(
            message_type=MessageType.COMMAND_RESULT,
            role=MessageRole.SYSTEM,
            sender_id=self.client_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data={
                "command": command,
                "result": result,
            },
        )
        return await self.send_message(message, callback)

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
        """Send permission request"""
        msg = MessageProtocol.create_permission_request(
            message=message,
            request_id=request_id,
            request_type=request_type,
            sender_id=self.client_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
        )
        return await self.send_message(msg, callback)

    async def send_permission_response(
        self,
        granted: bool,
        request_id: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> str:
        """Send permission response"""
        msg = MessageProtocol.create_permission_response(
            granted=granted,
            request_id=request_id,
            sender_id=self.client_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
        )
        return await self.send_message(msg, callback)

    async def send_user_answer(
        self,
        answer: str,
        request_id: str,
        receiver_id: str,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ):
        msg = MessageProtocol.create_user_answer(
            answer=answer,
            request_id=request_id,
            sender_id=self.client_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
        )
        return await self.send_message(msg)

    async def send_error(
        self,
        error_message: str,
        error_code: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> str:
        """Send error message"""
        msg = MessageProtocol.create_error_message(
            content=error_message,
            error_code=error_code,
            sender_id=self.client_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
        )
        return await self.send_message(msg, callback)

    async def send_task_start(
        self,
        task_id: str,
        task_description: str,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> str:
        """Send task start message"""
        message = MessageProtocol.create_task_start(
            task_id=task_id,
            task_description=task_description,
            sender_id=self.client_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
        )

        return await self.send_message(message)

    async def send_task_complete(
        self,
        task_id: str,
        result: Optional[str] = None,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> str:
        """Send task complete message"""
        data = {"task_id": task_id}
        if result:
            data["result"] = result

        message = Message(
            message_type=MessageType.TASK_COMPLETE,
            role=MessageRole.AGENT,
            sender_id=self.client_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
            data=data,
        )
        return await self.send_message(message)

    async def send_task_error(
        self,
        task_id: str,
        error_message: str,
        receiver_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> str:
        """Send task error message"""
        message = MessageProtocol.create_task_error(
            task_id=task_id,
            error_message=error_message,
            sender_id=self.client_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription,
        )

        return await self.send_message(message)

    async def send_agent_system_message(self, content: str, subscription: str) -> str:
        """Send system message"""
        message = MessageProtocol.create_agent_system_message(
            content=content, subscription=subscription
        )
        return await self.send_message(message)

    async def subscribe(
        self, subscription: str, callback: Optional[Callable] = None
    ) -> str:
        """
        Subscribe to a channel

        Args:
            subscription: Subscription name
            callback: Optional callback for subscription acknowledgment

        Returns:
            Message ID
        """
        if not self.connection_info.connected:
            raise RuntimeError("Not connected to server")

        message = MessageProtocol.create_subscribe(
            subscription=subscription, sender_id=self.client_id
        )

        if callback:
            self.message_callbacks[message.message_id] = callback

        try:
            await self.sio.emit("subscribe", {"subscription": subscription})
            logger.debug(f"Subscribed to {subscription}")
            return message.message_id
        except Exception as e:
            logger.error(f"Failed to subscribe: {e}")
            raise

    async def unsubscribe(
        self, subscription: str, callback: Optional[Callable] = None
    ) -> str:
        """
        Unsubscribe from a channel

        Args:
            subscription: Subscription name
            callback: Optional callback for unsubscription acknowledgment

        Returns:
            Message ID
        """
        if not self.connection_info.connected:
            raise RuntimeError("Not connected to server")

        message = MessageProtocol.create_unsubscribe(
            subscription=subscription, sender_id=self.client_id
        )

        if callback:
            self.message_callbacks[message.message_id] = callback

        try:
            await self.sio.emit("unsubscribe", {"subscription": subscription})
            logger.debug(f"Unsubscribed from {subscription}")
            return message.message_id
        except Exception as e:
            logger.error(f"Failed to unsubscribe: {e}")
            raise

    async def broadcast(
        self,
        content: str,
        subscription: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> str:
        """Broadcast message"""
        message = MessageProtocol.create_broadcast(
            content=content, subscription=subscription, sender_id=self.client_id
        )
        return await self.send_message(message, callback)

    def register_event_handler(self, event_name: str, func: Callable):
        if event_name not in self.event_handlers:
            self.event_handlers[event_name] = []
        if func not in self.event_handlers[event_name]:
            self.event_handlers[event_name].append(func)

    def on(self, event_name: str):
        """Decorator to register event handlers"""

        def decorator(func):
            self.register_event_handler(event_name, func)
            return func

        return decorator

    def on_message(self, func: Callable):
        """Decorator to register message handler"""
        return self.on("message")(func)

    def on_connect(self, func: Callable):
        """Decorator to register connect handler"""
        return self.on("connect")(func)

    def on_disconnect(self, func: Callable):
        """Decorator to register disconnect handler"""
        return self.on("disconnect")(func)

    def on_error(self, func: Callable):
        """Decorator to register error handler"""
        return self.on("error")(func)

    def on_user_message(self, func: Callable):
        """Decorator to register user message handler"""
        return self.on("user_message")(func)

    def on_agent_response(self, func: Callable):
        """Decorator to register agent response handler"""
        return self.on("agent_response")(func)

    def on_task_start(self, func: Callable):
        """Decorator to register task start handler"""
        return self.on("task_start")(func)

    def on_task_progress(self, func: Callable):
        """Decorator to register task progress handler"""
        return self.on("task_progress")(func)

    def on_task_complete(self, func: Callable):
        """Decorator to register task complete handler"""
        return self.on("task_complete")(func)

    def on_turn_start(self, func: Callable):
        """Decorator to register turn start handler"""
        return self.on("turn_start")(func)

    def on_turn_end(self, func: Callable):
        """Decorator to register turn end handler"""
        return self.on("turn_end")(func)

    def on_tool_call(self, func: Callable):
        """Decorator to register tool call handler"""
        return self.on("tool_call")(func)

    def on_tool_result(self, func: Callable):
        """Decorator to register tool result handler"""
        return self.on("tool_result")(func)

    def on_command(self, func: Callable):
        """Decorator to register command handler"""
        return self.on("command")(func)

    def on_command_result(self, func: Callable):
        """Decorator to register command result handler"""
        return self.on("command_result")(func)

    def on_permission_request(self, func: Callable):
        """Decorator to register permission request handler"""
        return self.on("permission_request")(func)

    def on_permission_response(self, func: Callable):
        """Decorator to register permission response handler"""
        return self.on("permission_response")(func)

    def on_subscribe(self, func: Callable):
        """Decorator to register subscribe handler"""
        return self.on("subscribe")(func)

    def on_unsubscribe(self, func: Callable):
        """Decorator to register unsubscribe handler"""
        return self.on("unsubscribe")(func)

    def on_broadcast(self, func: Callable):
        """Decorator to register broadcast handler"""
        return self.on("broadcast")(func)

    def is_connected(self) -> bool:
        """Check if connected to server"""
        return self.connection_info.connected

    def get_connection_info(self) -> ConnectionInfo:
        """Get connection information"""
        return self.connection_info

    def get_subscriptions(self) -> List[str]:
        """Get list of subscriptions"""
        return self.connection_info.subscriptions.copy()
