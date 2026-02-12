import inspect
import json
import logging
from typing import Optional, Dict, Any, List, Callable, Set
from dataclasses import dataclass, field
from socketio import AsyncServer

from .message_types import (
    Message, MessageType, MessageStatus, MessageProtocol
)


logger = logging.getLogger(__name__)


@dataclass
class ClientInfo:
    """Information about a connected client"""
    client_id: str
    client_type: str  # browser, cli, vscode, browser_plugin
    user_id: Optional[str] = None
    subscriptions: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)


class SocketIOServer:
    """
    Socket.io server for multi-endpoint communication.

    Features:
    - Message broadcasting
    - Message subscription
    - 1-to-1 communication
    - Room-based communication
    - Client management
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8000,
                 cors_allowed_origins: str = "*"):
        self.host = host
        self.port = port
        self.cors_allowed_origins = cors_allowed_origins

        self.sio = AsyncServer(
            async_mode="asgi",
            cors_allowed_origins=cors_allowed_origins,
            logger=False,
            engineio_logger=False
        )

        self.clients: Dict[str, ClientInfo] = {}
        self.client_sids: Dict[str, str] = {}
        self.subscriptions: Dict[str, Set[str]] = {}
        self.event_handlers: Dict[str, List[Callable]] = {}

        self._setup_event_handlers()
        logger.info(f"Socket.io server initialized on {host}:{port}")

    def _setup_event_handlers(self):
        """Setup Socket.io event handlers"""

        @self.sio.event
        async def connect(sid, environ):
            client_type = environ.get("HTTP_X_CLIENT_TYPE", "unknown")
            user_id = environ.get("HTTP_X_USER_ID")
            client_id = environ.get("HTTP_X_CLIENT_ID", sid)

            client_info = ClientInfo(
                client_id=client_id,
                client_type=client_type,
                user_id=user_id
            )

            self.clients[sid] = client_info
            self.client_sids[client_id] = sid

            connect_msg = MessageProtocol.create_user_message(
                content="Connected to server",
                sender_id="server",
                receiver_id=client_id
            )
            connect_msg.message_type = MessageType.CONNECT
            connect_msg.status = MessageStatus.OK
            await self.sio.emit("message", connect_msg.to_dict(), room=sid)
            await self._trigger_event("connect", client_info)
            logger.info(f"Client {client_id} ({client_type}) connected successfully")

        @self.sio.event
        async def disconnect(sid):
            if sid not in self.clients:
                return

            client_info = self.clients[sid]
            client_id = client_info.client_id

            for subscription in client_info.subscriptions:
                self.subscriptions.get(subscription, set()).discard(client_id)

            del self.clients[sid]
            self.client_sids.pop(client_id, None)

            await self._trigger_event("disconnect", client_info)
            logger.info(f"Client {client_id} disconnected successfully")

        @self.sio.event
        async def message(sid, data):
            try:
                message = Message.from_json(data) if isinstance(data, str) else Message.from_dict(data)

                is_valid, error_msg = MessageProtocol.validate_message(message)
                if not is_valid:
                    await self._send_error(sid, "VALIDATION_ERROR", error_msg, message.sender_id)
                    return

                await self._process_message(sid, message)
            except json.JSONDecodeError as e:
                await self._send_error(sid, "PARSE_ERROR", f"Failed to parse message: {e}")
            except Exception as e:
                await self._send_error(sid, "PROCESS_ERROR", f"Error processing message: {e}")

        @self.sio.event
        async def subscribe(sid, data):
            await self._handle_subscription(sid, data, subscribe=True)

        @self.sio.event
        async def unsubscribe(sid, data):
            await self._handle_subscription(sid, data, subscribe=False)

    async def _handle_subscription(self, sid: str, data: Any, subscribe: bool):
        """Handle subscription/unsubscription requests"""
        try:
            parsed_data = json.loads(data) if isinstance(data, str) else data
            subscription = parsed_data.get("subscription")

            if not subscription:
                await self._send_error(sid, "MISSING_SUBSCRIPTION", "Subscription name is required")
                return

            if sid not in self.clients:
                await self._send_error(sid, "CLIENT_NOT_FOUND", "Client not found")
                return

            client_info = self.clients[sid]
            client_id = client_info.client_id

            if subscribe:
                client_info.subscriptions.add(subscription)
                self.subscriptions.setdefault(subscription, set()).add(client_id)
                content = f"Subscribed to {subscription}"
                msg_type = MessageType.SUBSCRIBE
                logger.info(f"Client {client_id} subscribed to {subscription}")
            else:
                client_info.subscriptions.discard(subscription)
                if subscription in self.subscriptions:
                    self.subscriptions[subscription].discard(client_id)
                    if not self.subscriptions[subscription]:
                        del self.subscriptions[subscription]
                content = f"Unsubscribed from {subscription}"
                msg_type = MessageType.UNSUBSCRIBE
                logger.info(f"Client {client_id} unsubscribed from {subscription}")

            ack_msg = MessageProtocol.create_user_message(
                content=content,
                sender_id="server",
                receiver_id=client_id
            )
            ack_msg.message_type = msg_type
            ack_msg.status = MessageStatus.OK
            ack_msg.subscription = subscription
            await self.sio.emit("message", ack_msg.to_dict(), room=sid)

        except Exception as e:
            error_code = f"{'SUBSCRIBE' if subscribe else 'UNSUBSCRIBE'}_ERROR"
            await self._send_error(sid, error_code, f"Error processing: {e}")

    async def _send_error(self, sid: str, error_code: str, error_message: str,
                         receiver_id: Optional[str] = None):
        """Send error message to client"""
        error_response = MessageProtocol.create_error_message(
            error_code=error_code,
            error_message=error_message,
            sender_id="server",
            receiver_id=receiver_id
        )
        await self.sio.emit("message", error_response.to_dict(), room=sid)

    async def _process_message(self, sid: str, message: Message):
        """Process incoming message"""
        client_info = self.clients.get(sid)
        if not client_info:
            return

        logger.debug(f"Processing message from {client_info.client_id}: {message}")

        # Route message based on target
        if message.receiver_id:
            await self._send_to_client(message.receiver_id, message)
        elif message.room:
            await self._send_to_room(message.room, message)
        elif message.subscription:
            await self._send_to_subscription(message.subscription, message)
        else:
            await self._broadcast(message)

        # Trigger appropriate event
        event_name = message.message_type.value if hasattr(message.message_type, 'value') else "message"
        await self._trigger_event(event_name, client_info, message)

    async def _send_to_client(self, client_id: str, message: Message):
        """Send message to specific client"""
        if client_id not in self.client_sids:
            logger.warning(f"Client {client_id} not found")
            return

        sid = self.client_sids[client_id]
        await self.sio.emit("message", message.to_dict(), room=sid)
        logger.debug(f"Sent message to client {client_id}")

    async def _send_to_room(self, room: str, message: Message):
        """Send message to room"""
        await self.sio.emit("message", message.to_dict(), room=room)
        logger.info(f"Sent message to room {room}")

    async def _send_to_subscription(self, subscription: str, message: Message):
        """Send message to subscription"""
        if subscription not in self.subscriptions:
            logger.warning(f"Subscription {subscription} not found")
            return

        for client_id in self.subscriptions[subscription]:
            if client_id in self.client_sids:
                await self.sio.emit("message", message.to_dict(), room=self.client_sids[client_id])

        logger.debug(f"Sent message to subscription {subscription}")

    async def _broadcast(self, message: Message):
        """Broadcast message to all clients"""
        await self.sio.emit("message", message.to_dict())
        logger.debug("Broadcasted message to all clients")

    async def _trigger_event(self, event_name: str, client_info: ClientInfo,
                            message: Optional[Message] = None):
        """Trigger event handlers"""
        if event_name not in self.event_handlers:
            return

        for handler in self.event_handlers[event_name]:
            try:                
                sig = inspect.signature(handler)
                param_count = len(sig.parameters)
                
                if message and param_count >= 2:
                    await handler(client_info, message)
                elif param_count >= 1:
                    await handler(client_info)
                else:
                    # Handler expects no arguments, just call it
                    await handler()
            except Exception as e:
                logger.error(f"Error in event handler {event_name}: {e}")

    def on(self, event_name: str):
        """Decorator to register event handlers"""
        def decorator(func):
            self.event_handlers.setdefault(event_name, []).append(func)
            return func
        return decorator

    async def send_message(self, message: Message, client_id: Optional[str] = None,
                          room: Optional[str] = None, subscription: Optional[str] = None):
        """Send message from server"""
        if client_id:
            await self._send_to_client(client_id, message)
        elif room:
            await self._send_to_room(room, message)
        elif subscription:
            await self._send_to_subscription(subscription, message)
        else:
            await self._broadcast(message)

    async def broadcast(self, content: str, subscription: Optional[str] = None,
                       sender_id: str = "server"):
        """Broadcast message from server"""
        message = MessageProtocol.create_broadcast(
            content=content,
            subscription=subscription,
            sender_id=sender_id
        )
        await self.send_message(message, subscription=subscription)

    async def send_to_client(self, client_id: str, content: str,
                            sender_id: str = "server"):
        """Send message to specific client from server"""
        message = MessageProtocol.create_user_message(
            content=content,
            sender_id=sender_id,
            receiver_id=client_id
        )
        await self.send_message(message, client_id=client_id)

    def get_clients(self) -> List[Dict[str, Any]]:
        """Get list of connected clients"""
        return [
            {
                "client_id": info.client_id,
                "client_type": info.client_type,
                "user_id": info.user_id,
                "subscriptions": list(info.subscriptions),
                "metadata": info.metadata,
            }
            for info in self.clients.values()
        ]

    def get_subscriptions(self) -> Dict[str, List[str]]:
        """Get list of subscriptions and their clients"""
        return {
            sub: list(clients)
            for sub, clients in self.subscriptions.items()
        }

    async def start(self):
        """Start the server"""
        import uvicorn
        from socketio import ASGIApp

        logger.info(f"Starting Socket.io server on {self.host}:{self.port}")

        app = ASGIApp(self.sio)
        config = uvicorn.Config(app, host=self.host, port=self.port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

    async def stop(self):
        """Stop the server"""
        logger.info("Stopping Socket.io server")
        await self.sio.shutdown()
        logger.info("Socket.io server stopped")
