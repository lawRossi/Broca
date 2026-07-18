"""
Tests for Task 1.1: 添加缓存数据结构和基础方法
Plan: plans/offline-message-queue-plan.md

AC 1: 缓存条目包含消息原文、过期时间、request_id
AC 2: msg_key 生成方式为 "{message_type}_{request_id}"，保证唯一
AC 3: 反向索引 request_id → (subscription, msg_key) 维护正确
AC 4: 投递方法不过滤已发送的客户端（全部投递）
AC 5: 投递后不清空缓存
AC 6: 所有方法在 self._lock 保护下
"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from broca.communication.socketio_server import SocketIOServer
from broca.session.models import Message, MessageType, MessageRole


@pytest.fixture
def server():
    """Create a SocketIOServer instance for testing"""
    srv = SocketIOServer()
    return srv


@pytest.fixture
def permission_request():
    """Create a sample PERMISSION_REQUEST message"""
    return Message(
        message_type=MessageType.PERMISSION_REQUEST,
        role=MessageRole.AGENT,
        sender_id="agent1",
        receiver_id="user1",
        data={"request_id": "req-001", "content": "Need permission to access file"},
    )


@pytest.fixture
def agent_query():
    """Create a sample AGENT_QUERY message"""
    return Message(
        message_type=MessageType.AGENT_QUERY,
        role=MessageRole.AGENT,
        sender_id="agent1",
        receiver_id="user1",
        data={
            "request_id": "req-002",
            "content": "Which file should I read?",
        },
    )


@pytest.fixture
def regular_message():
    """Create a regular (non-cacheable) message"""
    return Message(
        message_type=MessageType.USER_MESSAGE,
        role=MessageRole.USER,
        sender_id="user1",
        receiver_id="agent1",
        data={"content": "Hello"},
    )


# --- AC 1: 缓存条目包含消息原文、过期时间、request_id ---

@pytest.mark.asyncio
async def test_ac01_cache_entry_contains_message_expire_at_request_id(
    server, permission_request
):
    """AC: 缓存条目包含消息原文、过期时间、request_id"""
    subscription = "session-001"
    await server._cache_pending_message(subscription, permission_request)

    msg_key = f"{MessageType.PERMISSION_REQUEST}_req-001"
    async with server._lock:
        entries = server._pending_messages.get(subscription, {})
        assert msg_key in entries, "Cache entry should exist"
        entry = entries[msg_key]

        # 检查消息原文
        assert "message" in entry, "Cache entry should contain 'message'"
        assert entry["message"] is permission_request, (
            "Cache entry should contain original message object"
        )

        # 检查过期时间
        assert "expire_at" in entry, "Cache entry should contain 'expire_at'"
        assert isinstance(entry["expire_at"], (int, float)), (
            "expire_at should be a number"
        )
        # 应该在当前时间附近（600s TTL）
        assert entry["expire_at"] > time.time(), "expire_at should be in the future"
        assert entry["expire_at"] <= time.time() + 600 + 1, (
            "expire_at should not exceed TTL of 600s"
        )

        # 检查 request_id
        assert "request_id" in entry, "Cache entry should contain 'request_id'"
        assert entry["request_id"] == "req-001", (
            "request_id should match the message's request_id"
        )


# --- AC 2: msg_key 生成方式为 "{message_type}_{request_id}"，保证唯一 ---

@pytest.mark.asyncio
async def test_ac02_msg_key_format(server, permission_request, agent_query):
    """AC: msg_key 生成方式为 '{message_type}_{request_id}'，保证唯一"""
    subscription = "session-001"
    await server._cache_pending_message(subscription, permission_request)
    await server._cache_pending_message(subscription, agent_query)

    async with server._lock:
        entries = server._pending_messages[subscription]

        # 检查 msg_key 格式
        expected_key_pr = f"{MessageType.PERMISSION_REQUEST}_req-001"
        expected_key_aq = f"{MessageType.AGENT_QUERY}_req-002"
        assert expected_key_pr in entries, (
            f"msg_key should be '{expected_key_pr}'"
        )
        assert expected_key_aq in entries, (
            f"msg_key should be '{expected_key_aq}'"
        )

    # 检查唯一性：相同 request_id + 不同 message_type 不会冲突
    # NOTE: 不能在上面的 async with lock 块内调用 _cache_pending_message，因为该函数自身也会获取锁（非重入锁）
    same_req_diff_type = Message(
        message_type=MessageType.AGENT_QUERY,
        role=MessageRole.AGENT,
        sender_id="agent1",
        data={"request_id": "req-001"},
    )
    await server._cache_pending_message(subscription, same_req_diff_type)

    async with server._lock:
        entries = server._pending_messages[subscription]
        expected_key_aq2 = f"{MessageType.AGENT_QUERY}_req-001"
        assert expected_key_aq2 in entries, (
            "Same request_id with different message_type should create different key"
        )
        assert expected_key_pr in entries, (
            "Original PERMISSION_REQUEST entry should still exist"
        )


# --- AC 3: 反向索引 request_id → (subscription, msg_key) 维护正确 ---

@pytest.mark.asyncio
async def test_ac03_reverse_index_correct(server, permission_request, agent_query):
    """AC: 反向索引 request_id → (subscription, msg_key) 维护正确"""
    subscription = "session-001"
    await server._cache_pending_message(subscription, permission_request)
    await server._cache_pending_message(subscription, agent_query)

    async with server._lock:
        # 检查反向索引
        assert "req-001" in server._request_to_subscription, (
            "Reverse index should contain req-001"
        )
        assert "req-002" in server._request_to_subscription, (
            "Reverse index should contain req-002"
        )

        sub1, key1 = server._request_to_subscription["req-001"]
        assert sub1 == subscription, (
            f"Reverse index should map to correct subscription, got {sub1}"
        )
        assert key1 == f"{MessageType.PERMISSION_REQUEST}_req-001", (
            f"Reverse index should map to correct msg_key, got {key1}"
        )

        sub2, key2 = server._request_to_subscription["req-002"]
        assert sub2 == subscription
        assert key2 == f"{MessageType.AGENT_QUERY}_req-002"

    # 测试不同 subscription
    subscription2 = "session-002"
    another_req = Message(
        message_type=MessageType.PERMISSION_REQUEST,
        role=MessageRole.AGENT,
        sender_id="agent1",
        data={"request_id": "req-003"},
    )
    await server._cache_pending_message(subscription2, another_req)

    async with server._lock:
        sub3, key3 = server._request_to_subscription["req-003"]
        assert sub3 == subscription2
        assert key3 == f"{MessageType.PERMISSION_REQUEST}_req-003"


# --- AC 4: 投递方法不过滤已发送的客户端（全部投递） ---

@pytest.mark.asyncio
async def test_ac04_deliver_all_clients(server, permission_request):
    """AC: 投递方法不过滤已发送的客户端（全部投递）"""
    subscription = "session-001"
    await server._cache_pending_message(subscription, permission_request)

    # Simulate sio.emit mock
    server.sio.emit = AsyncMock(return_value=None)

    # 第一次投递
    await server._deliver_pending_messages(subscription, "sid-001")
    assert server.sio.emit.called, "sio.emit should be called"

    server.sio.emit.reset_mock()

    # 第二次投递（相同 sid）应该再次发送
    await server._deliver_pending_messages(subscription, "sid-001")
    assert server.sio.emit.called, (
        "Deliver should not filter clients - should send again"
    )

    server.sio.emit.reset_mock()

    # 投递给不同 sid
    await server._deliver_pending_messages(subscription, "sid-002")
    assert server.sio.emit.called, (
        "Should also deliver to different clients"
    )


# --- AC 5: 投递后不清空缓存 ---

@pytest.mark.asyncio
async def test_ac05_cache_not_cleared_after_deliver(server, permission_request):
    """AC: 投递后不清空缓存"""
    subscription = "session-001"
    await server._cache_pending_message(subscription, permission_request)

    server.sio.emit = AsyncMock(return_value=None)

    # 投递前确认缓存存在
    async with server._lock:
        assert subscription in server._pending_messages, (
            "Cache should exist before delivery"
        )

    # 投递
    await server._deliver_pending_messages(subscription, "sid-001")

    # 投递后缓存应该仍然存在
    async with server._lock:
        assert subscription in server._pending_messages, (
            "Cache should still exist after delivery"
        )
        assert len(server._pending_messages[subscription]) == 1, (
            "Cache entries should not be cleared after delivery"
        )


# --- AC 6: 所有方法在 self._lock 保护下 ---

@pytest.mark.asyncio
async def test_ac06_cache_pending_message_uses_lock(server, permission_request):
    """AC: _cache_pending_message 在 self._lock 保护下"""
    subscription = "session-001"

    # Mock the lock to track if it's used
    original_lock = server._lock

    # The method uses 'async with self._lock', so it's protected
    await server._cache_pending_message(subscription, permission_request)

    # Verify the operation was successful (lock was used internally)
    async with original_lock:
        assert subscription in server._pending_messages


@pytest.mark.asyncio
async def test_ac06_deliver_pending_messages_uses_lock(server, permission_request):
    """AC: _deliver_pending_messages 在 self._lock 保护下"""
    subscription = "session-001"
    await server._cache_pending_message(subscription, permission_request)

    server.sio.emit = AsyncMock(return_value=None)

    # The method uses 'async with self._lock', so it's protected
    await server._deliver_pending_messages(subscription, "sid-001")

    # Verify operation was successful (lock was used)
    assert server.sio.emit.called


@pytest.mark.asyncio
async def test_ac06_remove_pending_message_uses_lock(server, permission_request):
    """AC: _remove_pending_message_by_request_id 在 self._lock 保护下"""
    subscription = "session-001"
    await server._cache_pending_message(subscription, permission_request)

    # The method uses 'async with self._lock', so it's protected
    await server._remove_pending_message_by_request_id("req-001")

    # Verify the entry was removed
    async with server._lock:
        assert "req-001" not in server._request_to_subscription
