import asyncio
import inspect
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from socketio import AsyncServer

from broca.logging_config import get_logger
from broca.session.models import Message, MessageProtocol, MessageRole, MessageType

logger = get_logger(__name__)


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

    def __init__(
        self, host: str = "0.0.0.0", port: int = 8000, cors_allowed_origins: str = "*"
    ):
        self.host = host
        self.port = port
        self.cors_allowed_origins = cors_allowed_origins

        self.sio = AsyncServer(
            async_mode="aiohttp",
            cors_allowed_origins=cors_allowed_origins,
            logger=False,
            engineio_logger=False,
        )

        self.clients: Dict[str, ClientInfo] = {}
        self.client_sids: Dict[str, str] = {}
        self.subscriptions: Dict[str, Set[str]] = {}
        self.event_handlers: Dict[str, List[Callable]] = {}

        # 添加锁保护共享状态访问
        self._lock = asyncio.Lock()

        # 待处理消息缓存：subscription → {msg_key: {message, expire_at, request_id}}
        # 用于缓存 PERMISSION_REQUEST / AGENT_QUERY，供后续订阅的客户端接收
        self._pending_messages: Dict[str, Dict[str, dict]] = {}
        # 反向索引：request_id → (subscription, msg_key)，O(1) 定位清理
        self._request_to_subscription: Dict[str, Tuple[str, str]] = {}

        # 保存 runner 引用以便正确清理
        self._runner = None

        self._setup_event_handlers()
        logger.info(f"Socket.io server initialized on {host}:{port}")

    async def _cache_pending_message(self, subscription: str, message: Message):
        """缓存待处理的消息（PERMISSION_REQUEST / AGENT_QUERY）

        消息缓存后，后续订阅该频道的客户端会收到此消息。
        缓存条目有 TTL（600s），收到对应响应或过期后清理。

        Args:
            subscription: 订阅频道名称（通常是 session_id）
            message: 待缓存的消息
        """
        request_id = (message.data or {}).get("request_id")
        if not request_id:
            return

        msg_key = f"{message.message_type}_{request_id}"
        expire_at = time.time() + 600  # TTL 600s

        async with self._lock:
            entry = {
                "message": message,
                "expire_at": expire_at,
                "request_id": request_id,
            }
            self._pending_messages.setdefault(subscription, {})[msg_key] = entry
            self._request_to_subscription[request_id] = (subscription, msg_key)
            logger.info(
                f"Cached {message.message_type} [{request_id}] for {subscription}"
            )

    async def _deliver_pending_messages(self, subscription: str, sid: str):
        """投递指定频道的所有未过期缓存消息给指定客户端

        遍历该频道的缓存条目，跳过已过期的，未过期的通过正常 message 事件发送。
        投递后不清空缓存，保持供后续订阅的客户端使用。

        Args:
            subscription: 订阅频道名称
            sid: 目标客户端的 Socket.IO session ID
        """
        async with self._lock:
            entries = self._pending_messages.get(subscription, {})
            if not entries:
                return

            now = time.time()
            delivered = 0
            for msg_key, entry in list(entries.items()):
                if now > entry["expire_at"]:
                    continue
                try:
                    await self.sio.emit(
                        "message",
                        MessageProtocol.to_dict(entry["message"]),
                        room=sid,
                    )
                    delivered += 1
                except Exception as e:
                    logger.error(
                        f"Failed to deliver pending message {msg_key}: {e}"
                    )

        if delivered > 0:
            logger.info(
                f"Delivered {delivered} pending messages for subscription "
                f"{subscription}"
            )

    async def _remove_pending_message_by_request_id(self, request_id: str):
        """通过 request_id 移除缓存的待处理消息

        在收到 PERMISSION_RESPONSE 或 USER_ANSWER 时调用。

        Args:
            request_id: 要移除的请求 ID
        """
        async with self._lock:
            if request_id not in self._request_to_subscription:
                return

            subscription, msg_key = self._request_to_subscription.pop(request_id)
            sub_entries = self._pending_messages.get(subscription)
            if sub_entries:
                sub_entries.pop(msg_key, None)
                if not sub_entries:
                    del self._pending_messages[subscription]

            logger.debug(
                f"Removed pending message [{request_id}] from {subscription}"
            )

    def _setup_event_handlers(self):
        """Setup Socket.io event handlers"""

        @self.sio.event
        async def connect(sid, environ, auth_data=None):
            if not auth_data:
                client_type = environ.get("HTTP_X_CLIENT_TYPE", "unknown")
                user_id = environ.get("HTTP_X_USER_ID")
                client_id = environ.get("HTTP_X_CLIENT_ID", sid)
            else:
                client_type = auth_data.get("client_type", "unknown")
                user_id = auth_data.get("user_id")
                client_id = auth_data.get("client_id", sid)
            client_info = ClientInfo(
                client_id=client_id, client_type=client_type, user_id=user_id
            )

            # 使用锁保护共享状态
            async with self._lock:
                self.clients[sid] = client_info
                self.client_sids[client_id] = sid

            connect_msg = Message(
                message_type=MessageType.CONNECT,
                role=MessageRole.SYSTEM,
                sender_id="server",
                receiver_id=client_id,
                data={"content": "Connected to server"},
            )
            await self.sio.emit(
                "message", MessageProtocol.to_dict(connect_msg), room=sid
            )
            await self._trigger_event("connect", client_info)
            logger.debug(f"Client {client_id} ({client_type}) connected successfully")

        @self.sio.event
        async def disconnect(sid):
            client_info = None
            client_id = None

            # 使用锁保护共享状态读取和修改
            async with self._lock:
                if sid not in self.clients:
                    return

                client_info = self.clients[sid]
                client_id = client_info.client_id

                # 清理订阅
                for subscription in client_info.subscriptions:
                    if subscription in self.subscriptions:
                        self.subscriptions[subscription].discard(client_id)
                        # 如果订阅为空，删除该订阅
                        if not self.subscriptions[subscription]:
                            del self.subscriptions[subscription]

                # 清理客户端
                del self.clients[sid]
                self.client_sids.pop(client_id, None)

            if client_info:
                await self._trigger_event("disconnect", client_info)
                logger.debug(f"Client {client_id} disconnected successfully")

        @self.sio.event
        async def message(sid, data):
            try:
                message_data = json.loads(data) if isinstance(data, str) else data
                message = MessageProtocol.from_dict(message_data)

                if not message.message_type:
                    error_msg = "Message type is required"
                    await self._send_error(
                        sid, "VALIDATION_ERROR", error_msg, message.sender_id
                    )
                    return

                await self._process_message(sid, message)
            except json.JSONDecodeError as e:
                await self._send_error(
                    sid, "PARSE_ERROR", f"Failed to parse message: {e}"
                )
            except Exception as e:
                import traceback

                logger.error(traceback.format_exc())
                await self._send_error(
                    sid, "PROCESS_ERROR", f"Error processing message: {e}"
                )

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
                await self._send_error(
                    sid, "MISSING_SUBSCRIPTION", "Subscription name is required"
                )
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
                logger.debug(f"Client {client_id} subscribed to {subscription}")
            else:
                client_info.subscriptions.discard(subscription)
                if subscription in self.subscriptions:
                    self.subscriptions[subscription].discard(client_id)
                    if not self.subscriptions[subscription]:
                        del self.subscriptions[subscription]
                content = f"Unsubscribed from {subscription}"
                msg_type = MessageType.UNSUBSCRIBE
                logger.debug(f"Client {client_id} unsubscribed from {subscription}")

            ack_msg = Message(
                message_type=msg_type,
                role=MessageRole.SYSTEM,
                sender_id="server",
                receiver_id=client_id,
                subscription=subscription,
                data={"content": content},
            )
            await self.sio.emit("message", MessageProtocol.to_dict(ack_msg), room=sid)

            # 订阅成功后，投递该频道的所有未过期缓存消息
            if subscribe:
                await self._deliver_pending_messages(subscription, sid)

        except Exception as e:
            error_code = f"{'SUBSCRIBE' if subscribe else 'UNSUBSCRIBE'}_ERROR"
            await self._send_error(sid, error_code, f"Error processing: {e}")

    async def _send_error(
        self,
        sid: str,
        error_code: str,
        error_message: str,
        receiver_id: Optional[str] = None,
    ):
        """Send error message to client"""
        error_response = Message(
            message_type=MessageType.ERROR,
            role=MessageRole.SYSTEM,
            sender_id="server",
            receiver_id=receiver_id,
            error_code=error_code,
            data={"error_message": error_message},
        )
        await self.sio.emit(
            "message", MessageProtocol.to_dict(error_response), room=sid
        )

    async def _process_message(self, sid: str, message: Message):
        """Process incoming message"""
        client_info = self.clients.get(sid)
        if not client_info:
            logger.warning(f"Received message from unknown SID: {sid}")
            return

        logger.debug(f"Processing message from {client_info.client_id}: {message}")

        # Route message based on target
        result = None
        if message.receiver_id:
            result = await self._send_to_client(message.receiver_id, message)
        elif message.room:
            result = await self._send_to_room(message.room, message)
        elif message.subscription:
            result = await self._send_to_subscription(message.subscription, message)
        else:
            result = await self._broadcast(message)

        # 收到 PERMISSION_RESPONSE 或 USER_ANSWER 时，清理缓存中的对应待处理请求
        if message.message_type in (
            MessageType.PERMISSION_RESPONSE,
            MessageType.USER_ANSWER,
        ):
            request_id = (message.data or {}).get("request_id")
            if request_id:
                await self._remove_pending_message_by_request_id(request_id)

        # 记录发送状态
        if result:
            if isinstance(result, dict):
                if result.get("failed", 0) > 0:
                    logger.warning(f"Message delivery incomplete: {result}")
                else:
                    logger.debug(f"Message delivered successfully: {result}")
            elif isinstance(result, bool):
                if not result:
                    logger.warning("Message failed to deliver to target")

        # Trigger appropriate event
        event_name = (
            message.message_type if message.message_type is not None else "message"
        )
        await self._trigger_event(event_name, client_info, message)

    async def _send_to_client(self, client_id: str, message: Message) -> bool:
        """Send message to specific client

        Returns:
            bool: True if message was sent successfully, False otherwise
        """
        sid = None
        async with self._lock:
            if client_id not in self.client_sids:
                logger.warning(f"Client {client_id} not found, cannot send message")
                return False
            sid = self.client_sids[client_id]

        try:
            await self.sio.emit("message", MessageProtocol.to_dict(message), room=sid)
            logger.debug(f"Sent message to client {client_id} (sid: {sid})")
            return True
        except Exception as e:
            logger.error(f"Failed to send message to client {client_id}: {e}")
            return False

    async def _send_to_room(self, room: str, message: Message) -> bool:
        """Send message to room

        Returns:
            bool: True if message was sent successfully, False otherwise
        """
        try:
            await self.sio.emit("message", MessageProtocol.to_dict(message), room=room)
            logger.debug(f"Sent message to room {room}")
            return True
        except Exception as e:
            logger.error(f"Failed to send message to room {room}: {e}")
            return False

    async def _send_to_subscription(
        self, subscription: str, message: Message
    ) -> Dict[str, int]:
        """Send message to subscription

        Returns:
            Dict with 'total', 'sent', 'failed' counts
        """
        if subscription not in self.subscriptions:
            logger.debug(f"Subscription {subscription} not found")
            # 无订阅者时仍需缓存，供后续订阅的客户端接收
            await self._maybe_cache_pending_message(subscription, message)
            return {"total": 0, "sent": 0, "failed": 0}

        # 收集所有有效的 SID
        sids = []
        async with self._lock:
            for client_id in self.subscriptions[subscription]:
                if client_id in self.client_sids:
                    sids.append(self.client_sids[client_id])

        total_clients = len(sids)
        if not sids:
            logger.debug(f"Subscription {subscription} has no connected clients")
            # 无在线客户端时仍需缓存，供后续订阅的客户端接收
            await self._maybe_cache_pending_message(subscription, message)
            return {"total": 0, "sent": 0, "failed": 0}

        try:
            await self.sio.emit(
                "message",
                MessageProtocol.to_dict(message),
                room=sids,
            )
            logger.debug(
                f"Sent message to subscription {subscription} ({total_clients} clients)"
            )
            # 发送后同时缓存，供后续订阅的客户端接收
            await self._maybe_cache_pending_message(subscription, message)
            return {"total": total_clients, "sent": total_clients, "failed": 0}
        except Exception as e:
            logger.error(f"Failed to send message to subscription {subscription}: {e}")
            # 发送失败时也缓存，供后续订阅的客户端接收
            await self._maybe_cache_pending_message(subscription, message)
            return {"total": total_clients, "sent": 0, "failed": total_clients}

    async def _maybe_cache_pending_message(self, subscription: str, message: Message):
        """如果是 PERMISSION_REQUEST 或 AGENT_QUERY，则缓存消息

        抽取为辅助方法，避免在 _send_to_subscription 的多个返回点重复判断逻辑。
        """
        if message.message_type in (
            MessageType.PERMISSION_REQUEST,
            MessageType.AGENT_QUERY,
        ):
            await self._cache_pending_message(subscription, message)

    async def _broadcast(self, message: Message) -> Dict[str, int]:
        """Broadcast message to all clients

        Returns:
            Dict with 'total', 'sent', 'failed' counts
        """
        try:
            await self.sio.emit("message", MessageProtocol.to_dict(message))
            # 广播无法知道确切数量，但可以记录已发送
            async with self._lock:
                total_clients = len(self.clients)
            logger.debug(
                f"Broadcasted message to all clients ({total_clients} connected)"
            )
            return {"total": total_clients, "sent": total_clients, "failed": 0}
        except Exception as e:
            logger.error(f"Failed to broadcast message: {e}")
            return {"total": 0, "sent": 0, "failed": 0}

    async def _trigger_event(
        self,
        event_name: str,
        client_info: ClientInfo,
        message: Optional[Message] = None,
    ):
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

    async def send_message(
        self,
        message: Message,
        client_id: Optional[str] = None,
        room: Optional[str] = None,
        subscription: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send message from server

        Returns:
            Dict with send status, e.g.:
            - For client_id: {"success": bool}
            - For room/subscription/broadcast: {"total": int, "sent": int, "failed": int}
        """
        if client_id:
            success = await self._send_to_client(client_id, message)
            return {"success": success}
        elif room:
            success = await self._send_to_room(room, message)
            return {"success": success}
        elif subscription:
            stats = await self._send_to_subscription(subscription, message)
            return stats
        else:
            stats = await self._broadcast(message)
            return stats

    async def broadcast(
        self,
        content: str,
        subscription: Optional[str] = None,
        sender_id: str = "server",
    ) -> Dict[str, Any]:
        """Broadcast message from server

        Returns:
            Dict with send status (total, sent, failed counts)
        """
        message = Message(
            message_type=MessageType.BROADCAST,
            role=MessageRole.SYSTEM,
            sender_id=sender_id,
            subscription=subscription,
            data={"content": content},
        )
        return await self.send_message(message, subscription=subscription)

    async def send_to_client(
        self, client_id: str, content: str, sender_id: str = "server"
    ) -> Dict[str, Any]:
        """Send message to specific client from server

        Returns:
            Dict with send status, e.g. {"success": bool}
        """
        message = Message(
            message_type=MessageType.USER_MESSAGE,
            role=MessageRole.USER,
            sender_id=sender_id,
            receiver_id=client_id,
            data={"content": content},
        )
        return await self.send_message(message, client_id=client_id)

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
        return {sub: list(clients) for sub, clients in self.subscriptions.items()}

    async def start(self):
        """Start the server"""
        from aiohttp import web

        logger.info(f"Starting Socket.io server on {self.host}:{self.port}")

        app = web.Application()
        self.sio.attach(app)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()

    async def stop(self):
        """Stop the server"""
        logger.info("Stopping Socket.io server")
        await self.sio.shutdown()

        # 清理 runner 资源
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

        logger.info("Socket.io server stopped")

    def is_client_connected(self, client_id: str) -> bool:
        return client_id in self.client_sids
