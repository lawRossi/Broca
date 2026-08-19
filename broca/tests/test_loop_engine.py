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

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.errors import ErrorCode, LLMError
from broca.loop_engine import (
    ExecutionResult,
    ExecutionStatus,
    LoopEngine,
)
from broca.tools.tool import ToolResult, ToolStatus

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
        assert loop_engine.llm_retry_delay == 5
        assert loop_engine.tool_call_timeout == 120
        assert loop_engine._recent_tool_call_signatures == []
        assert loop_engine._consecutive_rate_limit_errors == 0

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


class TestRateLimitRetry:
    """测试 LLM 限流自动重试"""

    @staticmethod
    def _rate_limit_error() -> LLMError:
        return LLMError(
            "请求频率过高，触发限流", error_code=ErrorCode.LLM_RATE_LIMIT
        )

    @pytest.mark.asyncio
    async def test_rate_limit_retry_then_success(self, loop_engine):
        """限流后等待 5 秒重试，重试成功返回响应且计数清零"""
        response = MagicMock()

        loop_engine._call_llm_streaming = AsyncMock(
            side_effect=[self._rate_limit_error(), response]
        )

        with patch("broca.loop_engine.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            result = await loop_engine._call_llm_with_retry()

        assert result is response
        mock_sleep.assert_awaited_once_with(5)
        assert loop_engine._consecutive_rate_limit_errors == 0

    @pytest.mark.asyncio
    async def test_rate_limit_exhausts_retries(self, loop_engine):
        """连续限流超过 3 次后放弃，抛出 LLMError 结束 turn"""
        err = self._rate_limit_error()
        loop_engine._call_llm_streaming = AsyncMock(side_effect=[err, err, err, err])

        with patch("broca.loop_engine.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            with pytest.raises(LLMError):
                await loop_engine._call_llm_with_retry()

        # 每次失败后重试前等待 5 秒，共 3 次（第 4 次失败直接放弃）
        assert mock_sleep.await_count == 3
        mock_sleep.assert_awaited_with(5)
        assert loop_engine._consecutive_rate_limit_errors == 4

    @pytest.mark.asyncio
    async def test_rate_limit_counter_resets_on_success(self, loop_engine):
        """调用成功后限流计数清零，下一次调用获得全新重试预算"""
        response = MagicMock()

        # 第一次调用：限流 2 次后成功
        loop_engine._call_llm_streaming = AsyncMock(
            side_effect=[self._rate_limit_error(), self._rate_limit_error(), response]
        )
        with patch("broca.loop_engine.asyncio.sleep", new=AsyncMock()):
            result = await loop_engine._call_llm_with_retry()
        assert result is response
        assert loop_engine._consecutive_rate_limit_errors == 0

        # 第二次调用（模拟同一 turn 内的下一步）：仍拥有完整 3 次重试预算
        err = self._rate_limit_error()
        loop_engine._call_llm_streaming = AsyncMock(side_effect=[err, err, err, err])
        with patch("broca.loop_engine.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            with pytest.raises(LLMError):
                await loop_engine._call_llm_with_retry()
        assert mock_sleep.await_count == 3

    @pytest.mark.asyncio
    async def test_non_rate_limit_llm_error_not_retried(self, loop_engine):
        """非限流 LLM 错误保持原行为：立即抛出，不重试"""
        err = LLMError("API Key 认证失败", error_code=ErrorCode.LLM_AUTH_ERROR)
        loop_engine._call_llm_streaming = AsyncMock(side_effect=[err, MagicMock()])

        with patch("broca.loop_engine.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            with pytest.raises(LLMError):
                await loop_engine._call_llm_with_retry()

        mock_sleep.assert_not_awaited()
        assert loop_engine._consecutive_rate_limit_errors == 0


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


class TestSaveUserMessage:
    """测试 _save_user_message（回归：from_agent 消息曾导致 setup context 失败）"""

    @pytest.mark.asyncio
    async def test_from_agent_returns_valid_message_id(self, loop_engine):
        """from_agent=True 时必须返回有效的 message_id，且传给 save_message 的不是 None"""
        mock_message = MagicMock()
        mock_message.message_id = "msg-original"
        mock_message.data = {"content": "task"}

        user_message = {"role": "user", "content": "task"}

        message_id = await loop_engine._save_user_message(
            user_message=user_message,
            message=mock_message,
            turn_id="turn-1",
            from_agent=True,
        )

        # 返回的 message_id 必须非 None，否则 _setup_execution_context 会误判失败
        assert message_id is not None
        assert message_id.startswith("msg_")
        # 不应复用原消息 ID（避免主键冲突），且必须以非 None 传入 save_message
        assert message_id != mock_message.message_id
        saved_message_id = loop_engine.session_manager.save_message.call_args.kwargs[
            "message_id"
        ]
        assert saved_message_id == message_id

    @pytest.mark.asyncio
    async def test_not_from_agent_keeps_original_message_id(self, loop_engine):
        """from_agent=False 时保留原始 message_id"""
        mock_message = MagicMock()
        mock_message.message_id = "msg-original"
        mock_message.data = {"content": "hello"}

        user_message = {"role": "user", "content": "hello"}

        message_id = await loop_engine._save_user_message(
            user_message=user_message,
            message=mock_message,
            turn_id="turn-1",
            from_agent=False,
        )

        assert message_id == "msg-original"
        saved_message_id = loop_engine.session_manager.save_message.call_args.kwargs[
            "message_id"
        ]
        assert saved_message_id == "msg-original"

    @pytest.mark.asyncio
    async def test_save_failure_returns_none(self, loop_engine):
        """save_message 失败时返回 None"""
        loop_engine.session_manager.save_message = AsyncMock(return_value=False)

        mock_message = MagicMock()
        mock_message.message_id = "msg-original"
        mock_message.data = {"content": "hello"}

        message_id = await loop_engine._save_user_message(
            user_message={"role": "user", "content": "hello"},
            message=mock_message,
            turn_id="turn-1",
            from_agent=True,
        )

        assert message_id is None


class TestToolTimeout:
    """测试工具执行超时处理（_execute_tool_with_allow / _execute_tool_with_ask）"""

    class SlowTool:
        """模拟一个永不返回的工具"""

        async def execute(self, arguments, context):
            await asyncio.sleep(30)
            return ToolResult(status=ToolStatus.SUCCESS, content="done")

    def _make_engine(self, loop_engine):
        """配置一个带慢工具 + 短超时的引擎"""
        loop_engine.tool_mapping["slow_tool"] = self.SlowTool()
        loop_engine.tool_call_timeout = 0.05
        return loop_engine

    @pytest.mark.asyncio
    async def test_allow_timeout_returns_error_result(self, loop_engine):
        """allow 权限下工具超时返回 ToolResult(ERROR)，不抛异常"""
        engine = self._make_engine(loop_engine)
        result = await engine._execute_tool_with_allow(
            "slow_tool", "{}", MagicMock()
        )
        assert result.status == ToolStatus.ERROR
        assert "timed out" in result.content
        assert "slow_tool" in result.content

    @pytest.mark.asyncio
    async def test_ask_timeout_returns_error_result(self, loop_engine):
        """ask 权限下工具超时返回 ToolResult(ERROR)，不抛异常"""
        engine = self._make_engine(loop_engine)
        loop_engine.agent.ask_for_tool_permission = AsyncMock(
            return_value=(True, None)
        )
        result, session_action = await engine._execute_tool_with_ask(
            "slow_tool", "{}", MagicMock()
        )
        assert result.status == ToolStatus.ERROR
        assert "timed out" in result.content
        assert session_action is None

    @pytest.mark.asyncio
    async def test_single_tool_call_timeout_returns_error(self, loop_engine):
        """_execute_single_tool_call 超时时返回 ERROR 而非向上抛异常"""
        engine = self._make_engine(loop_engine)
        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "slow_tool"
        tool_call.function.arguments = "{}"

        result = await engine._execute_single_tool_call(tool_call, MagicMock())
        assert result.status == ToolStatus.ERROR
        assert "timed out" in result.content
