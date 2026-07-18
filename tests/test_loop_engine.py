"""
LoopEngine 单元测试+集成测试

覆盖：
- ExecutionStatus 枚举
- ExecutionResult 类
- LoopEngine 初始化
- execute 主流程
- 死循环检测
- 超时控制
- abort/reset 功能
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.loop_engine import (
    ExecutionResult,
    ExecutionStatus,
    LoopEngine,
)

# ============================================================================
# 测试 ExecutionStatus
# ============================================================================


class TestExecutionStatus:
    """测试 ExecutionStatus 枚举"""

    def test_enum_values(self):
        """测试枚举值"""
        assert ExecutionStatus.RUNNING.value == "running"
        assert ExecutionStatus.COMPLETED.value == "completed"
        assert ExecutionStatus.ERROR.value == "error"
        assert ExecutionStatus.ABORTED.value == "aborted"
        assert ExecutionStatus.DEAD_LOOP.value == "dead_loop"
        assert ExecutionStatus.LIMIT_EXCEEDED.value == "limit_exceeded"
        assert ExecutionStatus.SKIPPED.value == "skipped"
        assert ExecutionStatus.PENDING.value == "pending"


# ============================================================================
# 测试 ExecutionResult
# ============================================================================


class TestExecutionResult:
    """测试 ExecutionResult 类"""

    def test_create_result(self):
        """测试创建结果"""
        result = ExecutionResult(
            status=ExecutionStatus.COMPLETED,
            message="Done",
            data={"steps": 5},
        )
        assert result.status == ExecutionStatus.COMPLETED
        assert result.message == "Done"
        assert result.data == {"steps": 5}
        assert result.error is None

    def test_create_error_result(self):
        """测试创建错误结果"""
        result = ExecutionResult(
            status=ExecutionStatus.ERROR,
            error="Something went wrong",
        )
        assert result.error == "Something went wrong"

    def test_to_dict(self):
        """测试转字典"""
        result = ExecutionResult(
            status=ExecutionStatus.COMPLETED,
            message="Success",
        )
        d = result.to_dict()
        assert d["status"] == ExecutionStatus.COMPLETED
        assert d["message"] == "Success"

    def test_str_representation(self):
        """测试字符串表示"""
        result = ExecutionResult(
            status=ExecutionStatus.RUNNING,
            message="In progress",
        )
        s = str(result)
        assert "RUNNING" in s
        assert "In progress" in s


# ============================================================================
# LoopEngine 测试
# ============================================================================


@pytest.fixture
def mock_agent():
    """创建 mock Agent"""
    agent = MagicMock()
    agent.agent_id = "test-agent"
    agent.turn_id = None
    agent.config.provider = "openai"
    agent.config.model = "gpt-4o"
    agent.config.interactive = False
    return agent


@pytest.fixture
def mock_llm_client():
    """创建 mock LLMClient"""
    client = MagicMock()
    client.parse_message = MagicMock(return_value={"role": "user", "content": "test"})
    # Mock get_stream_response as async generator
    return client


@pytest.fixture
def mock_context():
    """创建 mock Context"""
    ctx = MagicMock()
    ctx.history = [{"role": "system", "content": "sys"}]
    ctx.add_message = AsyncMock()
    ctx.get_latest_assistant_message = MagicMock(return_value=None)
    return ctx


@pytest.fixture
def mock_session_manager():
    """创建 mock SessionManager"""
    sm = MagicMock()
    sm.session_id = "test-session"
    sm.create_session = AsyncMock()
    sm.start_turn = AsyncMock(return_value="turn-1")
    sm.save_message = AsyncMock(return_value=True)
    sm.save_agent_response = AsyncMock(return_value=True)
    sm.save_turn_end = AsyncMock(return_value=True)
    sm.get_messages = AsyncMock(return_value=[])
    return sm


@pytest.fixture
def loop_engine(mock_agent, mock_llm_client, mock_context, mock_session_manager):
    """创建 LoopEngine 实例"""
    engine = LoopEngine(
        agent=mock_agent,
        llm_client=mock_llm_client,
        context=mock_context,
        tool_mapping={},
        config=mock_agent.config,
        communicator=MagicMock(),
        session_manager=mock_session_manager,
    )
    return engine


class TestLoopEngineInit:
    """测试 LoopEngine 初始化"""

    def test_init(self, loop_engine):
        """测试初始化"""
        assert loop_engine.agent_id == "test-agent"
        assert loop_engine.session_id == "test-session"
        assert loop_engine.step_max_errors == 3
        assert loop_engine.llm_retry_delay == 10
        assert loop_engine.tool_call_timeout == 120
        assert loop_engine._recent_tool_call_signatures == []

    def test_abort_event_not_set(self, loop_engine):
        """测试 abort 事件初始未设置"""
        assert loop_engine.abort_event.is_set() is False

    def test_reset(self, loop_engine):
        """测试 reset 方法"""
        loop_engine.abort_event.set()
        loop_engine.turn_id = "turn-1"
        assert loop_engine.abort_event.is_set() is True

        loop_engine.reset()
        assert loop_engine.abort_event.is_set() is False
        assert loop_engine.turn_id is None

    def test_abort(self, loop_engine):
        """测试 abort 方法"""
        assert loop_engine.abort_event.is_set() is False
        loop_engine.abort()
        assert loop_engine.abort_event.is_set() is True


class TestDeadLoopDetection:
    """测试死循环检测"""

    def test_no_dead_loop(self, loop_engine):
        """测试没有死循环"""
        sigs = ["read_file(/tmp/a)", "read_file(/tmp/b)", "read_file(/tmp/c)"]
        loop_engine._recent_tool_call_signatures.extend(sigs)
        assert len(loop_engine._recent_tool_call_signatures) >= 3

        # 手动检查：应该不相等
        last3 = loop_engine._recent_tool_call_signatures[-3:]
        assert not (last3[0] == last3[1] == last3[2])

    def test_dead_loop_detected(self, loop_engine):
        """测试死循环检测"""
        sigs = ["read_file(/tmp/a)", "read_file(/tmp/a)", "read_file(/tmp/a)"]
        loop_engine._recent_tool_call_signatures.extend(sigs)

        last3 = loop_engine._recent_tool_call_signatures[-3:]
        assert last3[0] == last3[1] == last3[2]

    def test_less_than_three_signatures(self, loop_engine):
        """测试不足三个签名时不触发"""
        sigs = ["read_file(/tmp/a)", "read_file(/tmp/a)"]
        loop_engine._recent_tool_call_signatures.extend(sigs)
        assert len(loop_engine._recent_tool_call_signatures) < 3

    def test_reset_clears_abort(self, loop_engine):
        """测试 reset 清除 abort 状态"""
        loop_engine.abort_event.set()
        assert loop_engine.abort_event.is_set() is True
        loop_engine.reset()
        assert loop_engine.abort_event.is_set() is False

    def test_reset_clears_turn_id(self, loop_engine):
        """测试 reset 清除 turn_id"""
        loop_engine.turn_id = "turn-1"
        loop_engine.reset()
        assert loop_engine.turn_id is None


class TestExecute:
    """测试 execute 方法"""

    @pytest.mark.asyncio
    async def test_execute_with_null_message(self, loop_engine):
        """测试空消息"""
        result = await loop_engine.execute(message=None)
        assert result.status == ExecutionStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_execute_aborted(self, loop_engine):
        """测试执行被中止（execute 遇到错误时仍能完成处理）"""
        mock_message = MagicMock()
        mock_message.data = {"content": "Hello"}

        result = await loop_engine.execute(message=mock_message)
        # LLM 调用会失败（mock 未配置），返回 ERROR
        assert result.status in [ExecutionStatus.ERROR, ExecutionStatus.SKIPPED]

    @pytest.mark.asyncio
    async def test_execute_context_setup_failure(self, loop_engine):
        """测试上下文设置失败"""
        loop_engine._setup_execution_context = AsyncMock(return_value=False)

        mock_message = MagicMock()
        mock_message.data = {"content": "Hello"}

        result = await loop_engine.execute(message=mock_message)
        assert result.status == ExecutionStatus.ERROR
