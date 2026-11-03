"""
LoopEngine 单元测试+集成测试

覆盖：
- ExecutionStatus 枚举
- ExecutionResult 类
- LoopEngine 初始化（策略/Hook 注入）
- execute 主流程
- 用户消息持久化
- abort/reset 功能

注意：私有方法级用例已迁至
``test_llm_strategy.py``（限流/空响应重试）、``test_tool_strategy.py``（并行/串行工具执行）、
``test_dead_loop_hook.py``（死循环检测）、``test_engine_orchestration.py`` /
``test_engine_dispatch.py``（编排与 Hook dispatch）。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.loop_engine import (
    DefaultLoopEngine,
    ExecutionResult,
    ExecutionStatus,
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
    # 提供真实的 execution 配置，模拟 AgentManager 注入的全局配置
    from broca.configs import ExecutionConfig

    agent.config.execution_config = ExecutionConfig()
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
def mock_tool_executor():
    """创建 mock ToolExecutor（Phase 2）"""
    from unittest.mock import MagicMock

    from broca.configs import ExecutionConfig
    from broca.tests.mock_components import MockToolExecutor

    executor = MockToolExecutor()
    config = MagicMock()
    config.interactive = False
    config.execution_config = ExecutionConfig()
    await_init = executor.initialize(
        tool_mapping={},
        permission_provider=MagicMock(),
        config=config,
        communicator=MagicMock(),
    )
    import asyncio
    loop = asyncio.new_event_loop()
    loop.run_until_complete(await_init)
    loop.close()
    return executor


@pytest.fixture
def loop_engine(mock_agent, mock_llm_client, mock_context, mock_session_manager, mock_tool_executor):
    """创建 LoopEngine 实例（含 ToolExecutor）"""
    engine = DefaultLoopEngine(
        agent_ref=mock_agent,
        llm_client=mock_llm_client,
        context=mock_context,
        tool_mapping={},
        config=mock_agent.config,
        communicator=MagicMock(),
        session_manager=mock_session_manager,
        tool_executor=mock_tool_executor,
    )
    return engine


class TestLoopEngineInit:
    """测试 LoopEngine 初始化"""

    def test_init(self, loop_engine):
        """初始化：依赖 + 策略/Hook 注入（重试参数已迁至策略）"""
        from broca.loop_engine.strategies.parallel_tool import ParallelToolStrategy
        from broca.loop_engine.strategies.retry_llm import RetryLLMStrategy

        assert loop_engine.agent_id == "test-agent"
        assert loop_engine.session_id == "test-session"
        assert loop_engine.abort_event.is_set() is False
        assert isinstance(loop_engine._llm_strategy, RetryLLMStrategy)
        assert isinstance(loop_engine._tool_strategy, ParallelToolStrategy)
        assert loop_engine._hooks == []
        # 重试/限流状态归策略所有，engine 不再持有
        assert not hasattr(loop_engine, "_consecutive_rate_limit_errors")
        assert not hasattr(loop_engine, "_recent_tool_call_signatures")

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


class TestEngineReset:
    """reset() 语义（死循环检测本身已迁至 test_dead_loop_hook.py）"""

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
        """测试上下文设置失败（_setup_turn 抛出 SessionError）"""
        from broca.errors import SessionError

        loop_engine._setup_turn = AsyncMock(
            side_effect=SessionError("创建 Turn 失败 (session_id=None)")
        )

        mock_message = MagicMock()
        mock_message.data = {"content": "Hello"}

        result = await loop_engine.execute(message=mock_message)
        assert result.status == ExecutionStatus.ERROR
        assert "创建 Turn 失败" in (result.message or "")


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


# ============================================================================
# 并行工具执行测试
# ============================================================================


