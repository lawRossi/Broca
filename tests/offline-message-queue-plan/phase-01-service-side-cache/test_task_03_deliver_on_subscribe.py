"""
Tests for Task 1.3: 订阅时投递缓存消息
Plan: plans/offline-message-queue-plan.md

AC 1: 订阅成功后自动投递该频道的所有未过期缓存消息
AC 2: 投递在 subscribe ack 之后
AC 3: 无缓存或全部过期时，订阅行为不变
"""
import time
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from broca.communication.socketio_server import SocketIOServer
from broca.session.models import Message, MessageType, MessageRole


@pytest.fixture
def server():
    srv = SocketIOServer()
    return srv


@pytest.fixture
def permission_request():
    return Message(
        message_type=MessageType.PERMISSION_REQUEST,
        role=MessageRole.AGENT,
        sender_id="agent1",
        receiver_id="user1",
        data={"request_id": "req-001", "content": "Need permission"},
    )


# --- AC 1: 订阅成功后自动投递该频道的所有未过期缓存消息 ---

@pytest.mark.asyncio
async def test_ac01_deliver_on_subscribe(server, permission_request):
    """AC: 订阅成功后自动投递该频道的所有未过期缓存消息"""
    subscription = "session-001"

    # Pre-cache a message
    await server._cache_pending_message(subscription, permission_request)

    # Simulate client subscription
    sid = "sid-001"
    server.clients[sid] = MagicMock()
    server.clients[sid].client_id = "client-001"
    server.clients[sid].subscriptions = set()

    server.sio.emit = AsyncMock(return_value=None)

    # Call _handle_subscription with subscribe=True
    data = json.dumps({"subscription": subscription})
    await server._handle_subscription(sid, data, subscribe=True)

    # Verify that sio.emit was called at least once for the ack
    assert server.sio.emit.called, "sio.emit should be called for ack and delivery"
    # Should have been called at least twice (once for ack, once for delivery)
    assert server.sio.emit.call_count >= 2, (
        "Should have called sio.emit for both ack and delivery"
    )


@pytest.mark.asyncio
async def test_ac01_deliver_multiple_cached_messages(server):
    """AC: 订阅时投递多个缓存消息"""
    subscription = "session-001"

    # Cache multiple messages
    for i in range(3):
        msg = Message(
            message_type=MessageType.PERMISSION_REQUEST,
            role=MessageRole.AGENT,
            sender_id="agent1",
            data={"request_id": f"req-00{i}", "content": f"Request {i}"},
        )
        await server._cache_pending_message(subscription, msg)

    sid = "sid-001"
    server.clients[sid] = MagicMock()
    server.clients[sid].client_id = "client-001"
    server.clients[sid].subscriptions = set()
    server.sio.emit = AsyncMock(return_value=None)

    data = json.dumps({"subscription": subscription})
    await server._handle_subscription(sid, data, subscribe=True)

    # Should have called sio.emit for each cached message (3) + ack (1)
    # but _deliver_pending_messages sends them all, so call_count should be at least 4
    assert server.sio.emit.call_count >= 4, (
        f"Should deliver all 3 cached messages + ack, got {server.sio.emit.call_count}"
    )


# --- AC 2: 投递在 subscribe ack 之后 ---

@pytest.mark.asyncio
async def test_ac02_deliver_after_ack(server, permission_request):
    """AC: 投递在 subscribe ack 之后"""
    subscription = "session-001"
    await server._cache_pending_message(subscription, permission_request)

    sid = "sid-001"
    server.clients[sid] = MagicMock()
    server.clients[sid].client_id = "client-001"
    server.clients[sid].subscriptions = set()

    call_order = []
    server.sio.emit = AsyncMock(side_effect=lambda event, data, room=None: call_order.append(event))

    data = json.dumps({"subscription": subscription})
    await server._handle_subscription(sid, data, subscribe=True)

    # First emit should be the SUBSCRIBE ack message
    assert call_order[0] == "message", "First emit should be a 'message' event (ack)"


# --- AC 3: 无缓存或全部过期时，订阅行为不变 ---

@pytest.mark.asyncio
async def test_ac03_no_cache_subscribe_still_works(server):
    """AC: 无缓存时订阅行为不变"""
    subscription = "session-001"
    sid = "sid-001"

    server.clients[sid] = MagicMock()
    server.clients[sid].client_id = "client-001"
    server.clients[sid].subscriptions = set()
    server.sio.emit = AsyncMock(return_value=None)

    data = json.dumps({"subscription": subscription})
    await server._handle_subscription(sid, data, subscribe=True)

    # Should still emit ack message
    assert server.sio.emit.called, "Ack should still be sent even without cache"
    assert sid in server.clients
    assert subscription in server.clients[sid].subscriptions, (
        "Client should be subscribed"
    )


@pytest.mark.asyncio
async def test_ac03_expired_cache_subscribe_still_works(server, permission_request):
    """AC: 缓存全部过期时订阅行为不变"""
    subscription = "session-001"

    # Manually add an expired cache entry
    msg_key = f"{MessageType.PERMISSION_REQUEST}_req-001"
    async with server._lock:
        server._pending_messages[subscription] = {
            msg_key: {
                "message": permission_request,
                "expire_at": time.time() - 1,  # Already expired
                "request_id": "req-001",
            }
        }
        server._request_to_subscription["req-001"] = (subscription, msg_key)

    sid = "sid-001"
    server.clients[sid] = MagicMock()
    server.clients[sid].client_id = "client-001"
    server.clients[sid].subscriptions = set()
    server.sio.emit = AsyncMock(return_value=None)

    data = json.dumps({"subscription": subscription})
    await server._handle_subscription(sid, data, subscribe=True)

    # Should still subscribe successfully (ack message)
    assert server.sio.emit.called
    assert subscription in server.clients[sid].subscriptions, (
        "Client should be subscribed even with expired cache"
    )
    # The expired message should NOT have been delivered
    # Only the ack should have been sent
    assert server.sio.emit.call_count == 1, (
        "Expired messages should not be delivered"
    )
