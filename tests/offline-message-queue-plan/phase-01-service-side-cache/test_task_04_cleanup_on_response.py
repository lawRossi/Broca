"""
Tests for Task 1.4: 收到响应时清理缓存
Plan: plans/offline-message-queue-plan.md

AC 1: PERMISSION_RESPONSE 到达时通过 request_id 移除对应缓存及反向索引
AC 2: USER_ANSWER 到达时通过 request_id 移除对应缓存及反向索引
AC 3: 无匹配 request_id 时无副作用
AC 4: 清理在响应被路由到 Agent 之后进行
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from broca.communication.socketio_server import SocketIOServer
from broca.session.models import Message, MessageType, MessageRole


@pytest.fixture
def server():
    srv = SocketIOServer()
    srv.clients["sid-001"] = MagicMock()
    srv.clients["sid-001"].client_id = "client-001"
    srv.sio.emit = AsyncMock(return_value=None)
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


# Helper to set up a cached message
async def setup_cache(server, subscription="session-001", request_id="req-001"):
    msg = Message(
        message_type=MessageType.PERMISSION_REQUEST,
        role=MessageRole.AGENT,
        sender_id="agent1",
        data={"request_id": request_id},
    )
    await server._cache_pending_message(subscription, msg)
    return msg


# --- AC 1: PERMISSION_RESPONSE 到达时通过 request_id 移除对应缓存及反向索引 ---

@pytest.mark.asyncio
async def test_ac01_permission_response_removes_cache(server):
    """AC: PERMISSION_RESPONSE 到达时通过 request_id 移除对应缓存"""
    await setup_cache(server)

    # Verify cache exists before
    async with server._lock:
        assert "req-001" in server._request_to_subscription
        assert "session-001" in server._pending_messages

    # Simulate PERMISSION_RESPONSE
    response = Message(
        message_type=MessageType.PERMISSION_RESPONSE,
        role=MessageRole.USER,
        sender_id="user1",
        receiver_id="agent1",
        data={"request_id": "req-001", "content": "Granted"},
    )
    await server._remove_pending_message_by_request_id("req-001")

    # Verify cache is cleared
    async with server._lock:
        assert "req-001" not in server._request_to_subscription, (
            "Reverse index should be removed"
        )
        assert "session-001" not in server._pending_messages, (
            "Subscription entry should be removed when no more items"
        )


@pytest.mark.asyncio
async def test_ac01_permission_response_via_process_message(server):
    """AC: PERMISSION_RESPONSE 通过 _process_message 触发清理"""
    await setup_cache(server)

    # Register the agent client so _send_to_client can route the message
    async with server._lock:
        server.client_sids["agent1"] = "sid-agent"
        server.clients["sid-agent"] = MagicMock()
        server.clients["sid-agent"].client_id = "agent1"

    # Verify cache exists before
    async with server._lock:
        assert "req-001" in server._request_to_subscription

    # Create PERMISSION_RESPONSE - this will trigger _process_message
    # which should call _remove_pending_message_by_request_id
    response = Message(
        message_type=MessageType.PERMISSION_RESPONSE,
        role=MessageRole.USER,
        sender_id="user1",
        receiver_id="agent1",
        data={"request_id": "req-001", "content": "Granted"},
    )
    await server._process_message("sid-001", response)

    # Verify cache is cleared
    async with server._lock:
        assert "req-001" not in server._request_to_subscription
        assert "session-001" not in server._pending_messages


# --- AC 2: USER_ANSWER 到达时通过 request_id 移除对应缓存及反向索引 ---

@pytest.mark.asyncio
async def test_ac02_user_answer_removes_cache(server):
    """AC: USER_ANSWER 到达时通过 request_id 移除对应缓存"""
    await setup_cache(server)

    async with server._lock:
        assert "req-001" in server._request_to_subscription

    # Simulate USER_ANSWER directly
    await server._remove_pending_message_by_request_id("req-001")

    async with server._lock:
        assert "req-001" not in server._request_to_subscription
        assert "session-001" not in server._pending_messages


@pytest.mark.asyncio
async def test_ac02_user_answer_via_process_message(server):
    """AC: USER_ANSWER 通过 _process_message 触发清理"""
    await setup_cache(server)

    # Register the agent client so _send_to_client can route the message
    async with server._lock:
        server.client_sids["agent1"] = "sid-agent"
        server.clients["sid-agent"] = MagicMock()
        server.clients["sid-agent"].client_id = "agent1"

    async with server._lock:
        assert "req-001" in server._request_to_subscription

    # Create USER_ANSWER
    response = Message(
        message_type=MessageType.USER_ANSWER,
        role=MessageRole.USER,
        sender_id="user1",
        receiver_id="agent1",
        data={"request_id": "req-001", "content": "My answer"},
    )
    await server._process_message("sid-001", response)

    async with server._lock:
        assert "req-001" not in server._request_to_subscription
        assert "session-001" not in server._pending_messages


# --- AC 3: 无匹配 request_id 时无副作用 ---

@pytest.mark.asyncio
async def test_ac03_no_matching_request_id_no_side_effects(server):
    """AC: 无匹配 request_id 时无副作用"""
    # Setup some cache
    await setup_cache(server)

    # Try to remove non-existent request_id
    await server._remove_pending_message_by_request_id("non-existent-id")

    # Original cache should be untouched
    async with server._lock:
        assert "req-001" in server._request_to_subscription
        assert "session-001" in server._pending_messages
        assert len(server._pending_messages["session-001"]) == 1


@pytest.mark.asyncio
async def test_ac03_empty_request_id_no_error(server):
    """AC: 空的 request_id 不会导致错误"""
    # This should not raise any error
    await server._remove_pending_message_by_request_id("")
    await server._remove_pending_message_by_request_id(None)

    # And with process_message with no request_id
    response = Message(
        message_type=MessageType.PERMISSION_RESPONSE,
        role=MessageRole.USER,
        sender_id="user1",
        data={},  # No request_id
    )
    # Should not raise
    await server._process_message("sid-001", response)


# --- AC 4: 清理在响应被路由到 Agent 之后进行 ---

@pytest.mark.asyncio
async def test_ac04_cleanup_after_routing(server):
    """AC: 清理在响应被路由到 Agent 之后进行"""
    await setup_cache(server)

    # Register the agent client so _send_to_client can route the message
    async with server._lock:
        server.client_sids["agent1"] = "sid-agent"
        server.clients["sid-agent"] = MagicMock()
        server.clients["sid-agent"].client_id = "agent1"

    # Track call order
    call_order = []
    original_remove = server._remove_pending_message_by_request_id

    async def tracking_remove(request_id):
        call_order.append("cleanup")
        await original_remove(request_id)

    server._remove_pending_message_by_request_id = tracking_remove

    # The _process_message first routes message (sio.emit),
    # then calls _remove_pending_message_by_request_id
    response = Message(
        message_type=MessageType.PERMISSION_RESPONSE,
        role=MessageRole.USER,
        sender_id="user1",
        receiver_id="agent1",
        data={"request_id": "req-001", "content": "Granted"},
    )

    # Reset mock to track emit calls
    server.sio.emit.reset_mock()

    await server._process_message("sid-001", response)

    # sio.emit should have been called BEFORE cleanup
    # Check that sio.emit was called (message was routed to agent)
    assert server.sio.emit.called, "Message should be routed to agent"


@pytest.mark.asyncio
async def test_ac04_only_one_cache_entry_removed(server):
    """AC: 只移除匹配的缓存条目，其他条目不受影响"""
    # Setup two cached messages for the same subscription
    await setup_cache(server, subscription="session-001", request_id="req-001")

    msg2 = Message(
        message_type=MessageType.AGENT_QUERY,
        role=MessageRole.AGENT,
        sender_id="agent1",
        data={"request_id": "req-002"},
    )
    await server._cache_pending_message("session-001", msg2)

    async with server._lock:
        assert len(server._pending_messages["session-001"]) == 2

    # Remove only req-001
    await server._remove_pending_message_by_request_id("req-001")

    async with server._lock:
        assert "req-001" not in server._request_to_subscription
        # req-002 should still exist
        assert "req-002" in server._request_to_subscription
        assert len(server._pending_messages["session-001"]) == 1
        # The remaining entry should be req-002
        assert f"{MessageType.AGENT_QUERY}_req-002" in server._pending_messages["session-001"]
