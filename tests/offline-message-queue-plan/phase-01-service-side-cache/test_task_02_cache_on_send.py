"""
Tests for Task 1.2: 发送时缓存 PERMISSION_REQUEST / AGENT_QUERY
Plan: plans/offline-message-queue-plan.md

AC 1: PERMISSION_REQUEST 和 AGENT_QUERY 发送后立即缓存
AC 2: 其他消息类型不缓存
AC 3: 缓存在发送完成后进行，不影响正常发送流程
"""
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


@pytest.fixture
def agent_query():
    return Message(
        message_type=MessageType.AGENT_QUERY,
        role=MessageRole.AGENT,
        sender_id="agent1",
        receiver_id="user1",
        data={"request_id": "req-002", "content": "Which file?"},
    )


@pytest.fixture
def regular_message():
    return Message(
        message_type=MessageType.USER_MESSAGE,
        role=MessageRole.USER,
        sender_id="user1",
        receiver_id="agent1",
        data={"content": "Hello"},
    )


# --- AC 1: PERMISSION_REQUEST 和 AGENT_QUERY 发送后立即缓存 ---

@pytest.mark.asyncio
async def test_ac01_permission_request_cached_on_send(server, permission_request):
    """AC: PERMISSION_REQUEST 发送后立即缓存"""
    subscription = "session-001"

    # Set up subscription to simulate sending
    await server._cache_pending_message(subscription, permission_request)

    # Verify cache
    async with server._lock:
        msg_key = f"{MessageType.PERMISSION_REQUEST}_req-001"
        assert subscription in server._pending_messages
        assert msg_key in server._pending_messages[subscription]
        assert "req-001" in server._request_to_subscription


@pytest.mark.asyncio
async def test_ac01_agent_query_cached_on_send(server, agent_query):
    """AC: AGENT_QUERY 发送后立即缓存"""
    subscription = "session-001"

    await server._cache_pending_message(subscription, agent_query)

    async with server._lock:
        msg_key = f"{MessageType.AGENT_QUERY}_req-002"
        assert subscription in server._pending_messages
        assert msg_key in server._pending_messages[subscription]
        assert "req-002" in server._request_to_subscription


# --- AC 2: 其他消息类型不缓存 ---

@pytest.mark.asyncio
async def test_ac02_regular_message_not_cached(server, regular_message):
    """AC: 其他消息类型不缓存"""
    subscription = "session-001"

    # For non-cacheable messages, _maybe_cache_pending_message should not cache
    await server._maybe_cache_pending_message(subscription, regular_message)

    async with server._lock:
        # Should not have any cache entry
        if subscription in server._pending_messages:
            assert len(server._pending_messages[subscription]) == 0, (
                "Regular messages should not be cached"
            )


@pytest.mark.asyncio
async def test_ac02_other_message_types_not_cached(server):
    """AC: 多种非缓存消息类型均不缓存"""
    subscription = "session-001"
    other_types = [
        MessageType.USER_MESSAGE,
        MessageType.BROADCAST,
        MessageType.ERROR,
        MessageType.CONNECT,
        MessageType.SUBSCRIBE,
        MessageType.UNSUBSCRIBE,
    ]

    for i, msg_type in enumerate(other_types):
        msg = Message(
            message_type=msg_type,
            role=MessageRole.USER,
            sender_id="user1",
            data={"request_id": f"req-{i}", "content": "test"},
        )
        await server._maybe_cache_pending_message(subscription, msg)

    async with server._lock:
        if subscription in server._pending_messages:
            assert len(server._pending_messages[subscription]) == 0, (
                "No non-PERMISSION_REQUEST/AGENT_QUERY messages should be cached"
            )


# --- AC 3: 缓存在发送完成后进行，不影响正常发送流程 ---

@pytest.mark.asyncio
async def test_ac03_cache_after_send_no_subscribers(server, permission_request):
    """AC: 无订阅者时缓存但不影响发送结果"""
    subscription = "session-001"
    # No subscribers for this subscription

    result = await server._send_to_subscription(subscription, permission_request)

    # Should return proper result even with no subscribers
    assert result == {"total": 0, "sent": 0, "failed": 0}, (
        "Should return correct stats when no subscribers"
    )

    # But message should still be cached
    async with server._lock:
        msg_key = f"{MessageType.PERMISSION_REQUEST}_req-001"
        assert subscription in server._pending_messages
        assert msg_key in server._pending_messages[subscription]


@pytest.mark.asyncio
async def test_ac03_cache_after_send_with_subscribers(server, permission_request):
    """AC: 有订阅者时先发送后缓存"""
    subscription = "session-001"

    # Simulate a subscriber
    server.subscriptions[subscription] = {"client-001"}
    server.client_sids["client-001"] = "sid-001"
    server.clients["sid-001"] = MagicMock()
    server.clients["sid-001"].client_id = "client-001"

    server.sio.emit = AsyncMock(return_value=None)

    result = await server._send_to_subscription(subscription, permission_request)

    # Should have sent successfully
    assert result["sent"] == 1, "Should have sent to 1 client"
    assert result["failed"] == 0, "Should have 0 failures"

    # sio.emit should have been called
    assert server.sio.emit.called, "sio.emit should be called"

    # Message should also be cached
    async with server._lock:
        msg_key = f"{MessageType.PERMISSION_REQUEST}_req-001"
        assert subscription in server._pending_messages
        assert msg_key in server._pending_messages[subscription]


@pytest.mark.asyncio
async def test_ac03_cache_does_not_prevent_send(server, permission_request):
    """AC: 缓存不影响正常发送流程"""
    subscription = "session-001"

    # Simulate a subscriber
    server.subscriptions[subscription] = {"client-001"}
    server.client_sids["client-001"] = "sid-001"
    server.clients["sid-001"] = MagicMock()
    server.clients["sid-001"].client_id = "client-001"

    server.sio.emit = AsyncMock(return_value=None)

    # Call _send_to_subscription which internally calls _maybe_cache_pending_message
    result = await server._send_to_subscription(subscription, permission_request)

    # Normal send should complete successfully
    assert result["sent"] == 1
    assert server.sio.emit.called
    # The emit should have been called with proper args
    call_args = server.sio.emit.call_args
    assert call_args[0][0] == "message", "Should emit 'message' event"
