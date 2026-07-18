"""
Context 单元测试

覆盖：
- Context 初始化
- _build_system_prompt 构建
- add_message 和 history 管理
- build_history_from_session
- format_tool_call_result
- get_latest_assistant_message
- mark_message_as_expired
- message_db_id 映射
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from broca.context import Context
from broca.agent_configs import AgentConfig


@pytest.fixture
def mock_agent_config():
    """创建 mock AgentConfig"""
    config = MagicMock(spec=AgentConfig)
    config.system_prompt_template = "You are a helpful assistant."
    config.role_description = "You are Broca, an AI assistant."
    config.environment = "Linux"
    config.workspace = "/tmp/workspace"
    config.skills = []
    return config


@pytest.fixture
def mock_session_manager():
    """创建 mock SessionManager"""
    sm = MagicMock()
    sm.session_id = "test-session"
    sm.get_messages = AsyncMock(return_value=[])
    return sm


class TestContextInit:
    """测试 Context 初始化"""

    def test_init_with_config(self, mock_agent_config, mock_session_manager):
        """测试使用配置初始化"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        assert ctx.agent_config == mock_agent_config
        assert ctx.session_manager == mock_session_manager
        assert len(ctx.history) == 1  # system prompt
        assert ctx.history[0]["role"] == "system"

    def test_system_prompt_in_history(self, mock_agent_config, mock_session_manager):
        """测试 system prompt 在历史中"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        assert ctx.history[0]["role"] == "system"
        assert "assistant" in ctx.history[0]["content"].lower()

    def test_message_db_ids_init(self, mock_agent_config, mock_session_manager):
        """测试 message_db_ids 初始化"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        assert len(ctx._message_db_ids) == 1
        assert ctx._message_db_ids[0] is None  # system prompt


class TestHistoryManagement:
    """测试历史管理"""

    @pytest.mark.asyncio
    async def test_add_message(self, mock_agent_config, mock_session_manager):
        """测试添加消息"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        initial_len = len(ctx.history)

        await ctx.add_message({"role": "user", "content": "Hello"})
        assert len(ctx.history) == initial_len + 1
        assert ctx.history[-1]["role"] == "user"
        assert ctx.history[-1]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_add_message_with_db_id(self, mock_agent_config, mock_session_manager):
        """测试带数据库 ID 添加消息"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        await ctx.add_message({"role": "user", "content": "Hi"}, db_message_id="msg-1")
        assert ctx.get_message_db_id(1) == "msg-1"

    def test_history_property(self, mock_agent_config, mock_session_manager):
        """测试 history 属性"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        assert ctx.history is ctx._history

    def test_history_setter(self, mock_agent_config, mock_session_manager):
        """测试 history setter"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        new_history = [{"role": "system", "content": "new"}]
        ctx.history = new_history
        assert ctx.history == new_history


class TestMessageDbId:
    """测试消息数据库 ID 管理"""

    def test_get_message_db_id_valid(self, mock_agent_config, mock_session_manager):
        """测试获取有效索引的 message_id"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        ctx._message_db_ids = [None, "msg-1", "msg-2"]
        assert ctx.get_message_db_id(1) == "msg-1"
        assert ctx.get_message_db_id(2) == "msg-2"

    def test_get_message_db_id_invalid(self, mock_agent_config, mock_session_manager):
        """测试获取无效索引的 message_id"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        assert ctx.get_message_db_id(-1) is None
        assert ctx.get_message_db_id(999) is None

    def test_set_message_db_id(self, mock_agent_config, mock_session_manager):
        """测试设置 message_id"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        ctx._message_db_ids = [None, "msg-1"]
        ctx.set_message_db_id(1, "updated-msg")
        assert ctx._message_db_ids[1] == "updated-msg"

    def test_set_message_db_id_invalid(self, mock_agent_config, mock_session_manager):
        """测试设置无效索引"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        ctx._message_db_ids = [None]
        # 不应抛出异常
        ctx.set_message_db_id(999, "msg-999")
        assert len(ctx._message_db_ids) == 1


class TestMarkExpired:
    """测试标记过期"""

    def test_mark_message_as_expired(self, mock_agent_config, mock_session_manager):
        """测试标记消息为过期"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        ctx._message_db_ids = [None, "msg-1"]
        ctx._history = [
            {"role": "system", "content": "sys"},
            {"role": "tool", "content": "result", "meta": {}},
        ]

        db_id = ctx.mark_message_as_expired(1)
        assert db_id == "msg-1"
        assert ctx.history[1]["content"] == Context.STALE_TOOL_RESULT_PLACEHOLDER

    def test_mark_message_as_expired_non_tool(self, mock_agent_config, mock_session_manager):
        """测试标记非 tool 消息"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        ctx._message_db_ids = [None, "msg-1"]
        ctx._history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]

        db_id = ctx.mark_message_as_expired(1)
        assert db_id == "msg-1"
        # user 消息的 content 不会被替换
        assert ctx.history[1]["content"] == "hello"

    def test_mark_message_no_db_id(self, mock_agent_config, mock_session_manager):
        """测试标记无数据库记录的消息"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        ctx._message_db_ids = [None]
        ctx._history = [
            {"role": "system", "content": "sys"},
        ]

        db_id = ctx.mark_message_as_expired(0)
        assert db_id is None


class TestGetLatestAssistantMessage:
    """测试获取最新助手消息"""

    def test_no_messages(self, mock_agent_config, mock_session_manager):
        """测试没有消息"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        # 只有 system prompt
        result = ctx.get_latest_assistant_message()
        assert result is None

    def test_latest_is_assistant(self, mock_agent_config, mock_session_manager):
        """测试最新消息是助手消息"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        ctx._history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        result = ctx.get_latest_assistant_message()
        assert result == "Hi there!"

    def test_latest_is_not_assistant(self, mock_agent_config, mock_session_manager):
        """测试最新消息不是助手消息"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        ctx._history = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "Hi"},
            {"role": "tool", "content": "result"},
        ]
        result = ctx.get_latest_assistant_message()
        assert result is None


class TestFormatToolCallResult:
    """测试格式化工具调用结果"""

    def test_format_tool_call_result(self, mock_agent_config, mock_session_manager):
        """测试格式化工具调用结果"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )

        mock_message = MagicMock()
        mock_message.data = {
            "content": '{"role": "tool", "content": "result"}',
            "tool_name": "read_file",
            "arguments": {"path": "/tmp/test"},
            "status": "success",
        }
        mock_message.is_expired = False

        result = ctx.format_tool_call_result(mock_message)
        assert result["role"] == "tool"
        assert result["content"] == "result"
        assert result["meta"]["tool_name"] == "read_file"
        assert result["meta"]["arguments"]["path"] == "/tmp/test"
        assert result["meta"]["status"] == "success"

    def test_format_expired_tool_result(self, mock_agent_config, mock_session_manager):
        """测试格式化过期的工具调用结果"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )

        mock_message = MagicMock()
        mock_message.data = {
            "content": '{"role": "tool", "content": "old result"}',
            "tool_name": "read_file",
            "arguments": {},
            "status": "success",
        }
        mock_message.is_expired = True

        result = ctx.format_tool_call_result(mock_message)
        assert result["content"] == Context.STALE_TOOL_RESULT_PLACEHOLDER

    def test_format_with_string_arguments(self, mock_agent_config, mock_session_manager):
        """测试参数为字符串时的解析"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )

        mock_message = MagicMock()
        mock_message.data = {
            "content": '{"role": "tool", "content": "result"}',
            "tool_name": "read_file",
            "arguments": '{"path": "/tmp/test"}',  # 字符串而非 dict
            "status": "success",
        }
        mock_message.is_expired = False

        result = ctx.format_tool_call_result(mock_message)
        assert result["meta"]["arguments"]["path"] == "/tmp/test"


class TestBuildHistoryFromSession:
    """测试从会话构建历史"""

    @pytest.mark.asyncio
    async def test_empty_session(self, mock_agent_config, mock_session_manager):
        """测试空会话"""
        mock_session_manager.get_messages = AsyncMock(return_value=[])
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )

        await ctx.build_history_from_session("agent-1")
        assert len(ctx.history) == 1  # 只有 system prompt

    @pytest.mark.asyncio
    async def test_with_messages(self, mock_agent_config, mock_session_manager):
        """测试有消息时"""
        from broca.session.models import MessageType

        mock_msg = MagicMock()
        mock_msg.message_type = MessageType.USER_MESSAGE
        mock_msg.data = {"content": '{"role": "user", "content": "hello"}'}
        mock_msg.is_truncated = False
        mock_msg.message_id = "msg-1"

        mock_session_manager.get_messages = AsyncMock(return_value=[mock_msg])
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )

        await ctx.build_history_from_session("agent-1")
        assert len(ctx.history) >= 2

    @pytest.mark.asyncio
    async def test_skips_truncated_messages(self, mock_agent_config, mock_session_manager):
        """测试跳过已被截断的消息"""
        mock_msg = MagicMock()
        mock_msg.message_type = "USER_MESSAGE"
        mock_msg.data = {"content": '{"role": "user", "content": "hello"}'}
        mock_msg.is_truncated = True  # 标记为已截断

        mock_session_manager.get_messages = AsyncMock(return_value=[mock_msg])
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )

        await ctx.build_history_from_session("agent-1")
        # 截断的消息应该被跳过
        assert len(ctx.history) == 1  # 只有 system prompt

    @pytest.mark.asyncio
    async def test_rebuild_system_prompt(self, mock_agent_config, mock_session_manager):
        """测试重建 system prompt"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        original_prompt = ctx.system_prompt

        # 修改 config 后重建
        mock_agent_config.role_description = "Updated role"
        await ctx.build_history_from_session("agent-1", rebuild_system_prompt=True)
        # system prompt 应该已更新
        assert ctx.history[0]["role"] == "system"


class TestLoadBootstrapFiles:
    """测试加载引导文件"""

    # 直接测试 _load_bootstrap_files 的逻辑：当文件不存在时应返回空
    def test_no_bootstrap_files(self, mock_agent_config, mock_session_manager):
        """测试没有引导文件"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        # workspace 中的 bootstrap 文件不存在
        result = ctx._load_bootstrap_files("/tmp/nonexistent_workspace_xyz")
        # 没有文件时返回空字符串
        assert result == "" or result is None

    def test_format_skills(self, mock_agent_config, mock_session_manager):
        """测试技能格式化"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        skills = {
            "read_file": {"description": "Read file content"},
            "write_file": {"description": "Write file content"},
        }
        result = ctx._format_skills(skills)
        assert "read_file: Read file content" in result
        assert "write_file: Write file content" in result

    def test_format_skills_empty(self, mock_agent_config, mock_session_manager):
        """测试空技能格式化"""
        ctx = Context(
            agent_config=mock_agent_config,
            session_manager=mock_session_manager,
        )
        result = ctx._format_skills({})
        assert result == ""
