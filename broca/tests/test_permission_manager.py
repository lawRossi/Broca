"""
PermissionManager 单元测试

覆盖：
- PermissionManager 初始化
- set_state 方法
- 权限请求/响应流程
- 超时处理
- pending 请求管理
- reset 方法
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.permission_manager import PermissionManager
from broca.session.models import Message, MessageRole, MessageType


class MockCommunicator:
    """模拟的通信器"""

    def __init__(self):
        self.last_permission_request = None

    async def send_permission_request(self, message, request_id, request_type, subscription):
        self.last_permission_request = {
            "message": message,
            "request_id": request_id,
            "request_type": request_type,
            "subscription": subscription,
        }


class MockSessionManager:
    """模拟的会话管理器"""

    def __init__(self):
        self.saved_messages = []

    async def save_message(self, role, content, message_type, turn_id, agent_id, data=None):
        self.saved_messages.append({
            "role": role,
            "content": content,
            "message_type": message_type,
            "turn_id": turn_id,
            "agent_id": agent_id,
            "data": data,
        })


@pytest.fixture
def permission_manager():
    """创建 PermissionManager 实例"""
    communicator = MockCommunicator()
    session_manager = MockSessionManager()
    return PermissionManager(
        communicator=communicator,
        session_manager=session_manager,
    )


class TestPermissionManager:
    """测试 PermissionManager"""

    def test_init(self, permission_manager):
        """测试初始化"""
        assert permission_manager.communicator is not None
        assert permission_manager.session_manager is not None
        assert permission_manager.get_pending_requests_count() == 0
        assert permission_manager.turn_id is None
        assert permission_manager.agent_id is None
        assert permission_manager.session_id is None

    def test_set_state(self, permission_manager):
        """测试设置状态"""
        permission_manager.set_state(
            turn_id="turn-1",
            agent_id="agent-1",
            session_id="session-1",
        )
        assert permission_manager.turn_id == "turn-1"
        assert permission_manager.agent_id == "agent-1"
        assert permission_manager.session_id == "session-1"

    def test_set_state_partial(self, permission_manager):
        """测试部分设置状态"""
        permission_manager.set_state(agent_id="agent-1")
        assert permission_manager.agent_id == "agent-1"
        assert permission_manager.turn_id is None
        assert permission_manager.session_id is None

    @pytest.mark.asyncio
    async def test_request_permission_timeout(self, permission_manager):
        """测试权限请求超时"""
        # 不模拟响应，请求会超时
        with patch("asyncio.wait_for", AsyncMock(side_effect=__import__("asyncio").TimeoutError)):
            granted = await permission_manager.request_permission("Can I proceed?")
            assert granted is False

    @pytest.mark.asyncio
    async def test_request_tool_permission_timeout(self, permission_manager):
        """测试工具权限请求超时"""
        with patch("asyncio.wait_for", AsyncMock(side_effect=__import__("asyncio").TimeoutError)):
            granted, session_action = await permission_manager.request_tool_permission(
                "Can I run bash?"
            )
            assert granted is False
            assert session_action is None

    def test_get_pending_requests_count(self, permission_manager):
        """测试获取待处理请求数量"""
        assert permission_manager.get_pending_requests_count() == 0

    @pytest.mark.asyncio
    async def test_clear_pending_requests(self, permission_manager):
        """测试清除待处理请求"""
        # 手动添加一个 pending 请求
        async with permission_manager._permission_lock:
            permission_manager._permission_requests["test_id"] = {"event": MagicMock()}

        assert permission_manager.get_pending_requests_count() == 1
        await permission_manager.clear_pending_requests()
        assert permission_manager.get_pending_requests_count() == 0

    @pytest.mark.asyncio
    async def test_reset(self, permission_manager):
        """测试重置"""
        permission_manager.set_state(
            turn_id="turn-1",
            agent_id="agent-1",
            session_id="session-1",
        )
        async with permission_manager._permission_lock:
            permission_manager._permission_requests["test_id"] = {"event": MagicMock()}

        await permission_manager.reset()

        assert permission_manager.get_pending_requests_count() == 0
        assert permission_manager.turn_id is None
        assert permission_manager.agent_id is None
        assert permission_manager.session_id is None

    @pytest.mark.asyncio
    async def test_handle_permission_response_unknown(self, permission_manager):
        """测试处理未知的权限响应"""
        msg = MagicMock(spec=Message)
        msg.data = {"granted": True, "request_id": "nonexistent"}

        # 不应抛出异常
        await permission_manager.handle_permission_response(msg)

    @pytest.mark.asyncio
    async def test_handle_permission_response_with_session_action(self, permission_manager):
        """测试处理带会话操作的权限响应"""
        from asyncio import Event

        # 注册一个权限请求
        async with permission_manager._permission_lock:
            permission_manager._permission_requests["test_id"] = {
                "event": Event(),
                "granted": None,
                "session_action": None,
            }

        # 处理响应
        msg = MagicMock(spec=Message)
        msg.data = {
            "granted": True,
            "request_id": "test_id",
            "session_action": "allow",
        }

        await permission_manager.handle_permission_response(msg)

        async with permission_manager._permission_lock:
            request = permission_manager._permission_requests["test_id"]
            assert request["granted"] is True
            assert request["session_action"] == "allow"

    @pytest.mark.asyncio
    async def test_logging_on_permission_request(self, permission_manager):
        """测试权限请求日志"""
        permission_manager.set_state(
            turn_id="turn-1",
            agent_id="agent-1",
            session_id="session-1",
        )

        with patch("asyncio.wait_for", AsyncMock(side_effect=__import__("asyncio").TimeoutError)):
            await permission_manager.request_permission("Can I proceed?")

        # 验证日志消息被保存
        assert len(permission_manager.session_manager.saved_messages) >= 1
        log_entry = permission_manager.session_manager.saved_messages[0]
        assert log_entry["role"] == MessageRole.AGENT
        assert log_entry["message_type"] == MessageType.PERMISSION_REQUEST
        assert log_entry["turn_id"] == "turn-1"
        assert log_entry["agent_id"] == "agent-1"

    @pytest.mark.asyncio
    async def test_permission_request_failure_returns_false(self, permission_manager):
        """测试权限请求失败返回 False"""
        # 模拟通信器抛出异常
        permission_manager.communicator.send_permission_request = AsyncMock(
            side_effect=RuntimeError("Connection failed")
        )

        granted = await permission_manager.request_permission("Can I proceed?")
        assert granted is False
