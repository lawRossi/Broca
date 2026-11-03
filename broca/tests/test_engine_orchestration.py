"""Engine orchestration tests (Phase 4 / Task 4.1a).

These tests instantiate ``broca.loop_engine.engine.DefaultLoopEngine``
**directly**, so they exercise the engine without going through
``Agent.create()`` / the component registry.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.components.llm_strategy import LLMCallResult
from broca.components.loop_engine import ExecutionStatus
from broca.loop_engine.engine import DefaultLoopEngine
from broca.tools.tool import ToolResult, ToolStatus

# ── Fakes ───────────────────────────────────────────────────────────────


class FakeLLMStrategy:
    name = "fake_llm"

    def __init__(self, results):
        self._results = list(results)
        self.calls = []
        self.reset_count = 0
        self.initialized = False

    async def initialize(self, *, llm_client, config):
        self.initialized = True

    def reset(self):
        self.reset_count += 1

    async def call(self, history, tools, *, on_chunk=None, on_error=None, should_abort=None):
        self.calls.append(
            {
                "history": history,
                "tools": tools,
                "on_chunk": on_chunk,
                "on_error": on_error,
                "should_abort": should_abort,
            }
        )
        return self._results.pop(0)


class FakeToolStrategy:
    name = "fake_tool"

    def __init__(self, results=None, on_execute=None):
        self._results = list(results or [])
        self.calls = []
        self.reset_count = 0
        self._on_execute = on_execute

    async def initialize(self, *, tool_executor, config):
        self.initialized = True

    def reset(self):
        self.reset_count += 1

    async def execute(
        self, tool_calls, context, tool_mapping, *, allowed_tools=None, should_abort=None
    ):
        self.calls.append(list(tool_calls))
        if self._on_execute is not None:
            self._on_execute()
        return list(self._results)


class FakeHook:
    name = "fake_hook"

    def __init__(self):
        self.reset_count = 0

    def reset(self):
        self.reset_count += 1


def _tool_call(name="read_file", args="{}", tc_id="call-1"):
    tc = MagicMock()
    tc.id = tc_id
    tc.function.name = name
    tc.function.arguments = args
    return tc


def _message(tool_calls=None, message_id="msg_assistant"):
    msg = MagicMock()
    msg.tool_calls = list(tool_calls or [])
    msg.message_id = message_id
    return msg


def _llm_ok(tool_calls=None, input_tokens=10, output_tokens=5):
    return LLMCallResult(
        message=_message(tool_calls),
        message_id="msg_assistant",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        success=True,
    )


def _config(interactive=False):
    cfg = MagicMock()
    cfg.interactive = interactive
    cfg.provider = "openai"
    cfg.model = "gpt-4o"
    cfg.workspace = "/tmp/ws"
    cfg.execution_config = MagicMock()
    return cfg


def _agent_ref():
    ref = MagicMock()
    ref.agent_id = "agent-1"
    ref.turn_id = None
    ref.last_context_length = None
    ref.on_llm_call_completed = AsyncMock()
    return ref


def _session_manager():
    sm = MagicMock()
    sm.session_id = "session-1"
    sm.start_turn = AsyncMock(return_value="turn-1")
    sm.save_message = AsyncMock(return_value=True)
    sm.save_agent_response = AsyncMock(return_value=True)
    sm.save_tool_call = AsyncMock(return_value=True)
    sm.save_turn_end = AsyncMock(return_value=True)
    sm.message_service.get = AsyncMock(return_value=MagicMock())
    return sm


def _context():
    ctx = MagicMock()
    ctx.history = [{"role": "user", "content": "hi"}]
    ctx.add_message = AsyncMock()
    ctx.format_tool_call_result = MagicMock(return_value={"role": "tool"})
    ctx.truncate_last_assistant_message_with_tool_calls = AsyncMock()
    return ctx


def _tool_executor(readonly=True):
    executor = MagicMock()
    executor.is_readonly_tool = MagicMock(return_value=readonly)
    executor._permission_provider = MagicMock()
    return executor


def _user_message():
    message = MagicMock()
    message.message_id = "msg_user"
    message.sender_id = "user-1"
    message.data = {}
    return message


def _build_engine(llm_results, tool_results=None, *, readonly=True, hooks=None, config=None):
    llm_strategy = FakeLLMStrategy(llm_results)
    tool_strategy = FakeToolStrategy(tool_results)
    engine = DefaultLoopEngine(
        agent_ref=_agent_ref(),
        llm_client=MagicMock(
            parse_message=MagicMock(return_value={"role": "user", "content": "hi"})
        ),
        context=_context(),
        tool_mapping={},
        config=config or _config(),
        communicator=MagicMock(),
        session_manager=_session_manager(),
        tool_executor=_tool_executor(readonly=readonly),
        llm_strategy=llm_strategy,
        tool_strategy=tool_strategy,
        hooks=list(hooks or []),
    )
    return engine, llm_strategy, tool_strategy


# ── Tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_strategy_chain_runs_llm_then_tools():
    """llm_strategy.call → tool_strategy.execute → _process_tool_results."""
    calls = [_tool_call("write_file"), _tool_call("read_file", tc_id="call-2")]
    engine, llm_strategy, tool_strategy = _build_engine(
        [_llm_ok(calls), _llm_ok()],
        tool_results=[
            ToolResult(status=ToolStatus.SUCCESS, content="a"),
            ToolResult(status=ToolStatus.SUCCESS, content="b"),
        ],
    )
    engine.process_tool_call_result = AsyncMock(return_value=True)

    result = await engine.execute(_user_message())

    assert result.status == ExecutionStatus.COMPLETED
    assert len(llm_strategy.calls) == 2
    assert len(tool_strategy.calls) == 1
    assert tool_strategy.calls[0] == calls
    assert engine.process_tool_call_result.await_count == 2


@pytest.mark.asyncio
async def test_llm_call_completed_reported_once_per_successful_call():
    engine, _, _ = _build_engine(
        [_llm_ok([_tool_call()]), _llm_ok()],
        tool_results=[ToolResult(status=ToolStatus.SUCCESS, content="ok")],
    )

    await engine.execute(_user_message())

    assert engine.agent_ref.on_llm_call_completed.await_count == 2
    engine.agent_ref.on_llm_call_completed.assert_awaited_with(10, 5)


@pytest.mark.asyncio
async def test_token_reporting_skipped_on_failed_llm_call():
    engine, _, tool_strategy = _build_engine(
        [LLMCallResult(success=False, error_code="LLM_ERROR")]
    )

    result = await engine.execute(_user_message())

    assert result.status == ExecutionStatus.ERROR
    assert engine.agent_ref.on_llm_call_completed.await_count == 0
    assert tool_strategy.calls == []


@pytest.mark.asyncio
async def test_has_write_ops_default_false_when_no_hook():
    """Engine no longer pre-computes has_write_ops (review 4.2).

    The flag defaults to ``False`` in ``StepContext``; ``SnapshotHook``
    computes it in ``on_step_start``.  Without the hook, it stays ``False``.
    """
    engine, _, _ = _build_engine([_llm_ok([_tool_call("write_file")]), _llm_ok()], readonly=False)
    seen = []

    async def _dispatch(method, ctx):
        if method == "on_step_start":
            seen.append(ctx.has_write_ops)

    engine._dispatch = _dispatch

    await engine.execute(_user_message())

    # No SnapshotHook in the list → flag stays at default False.
    assert all(flag is False for flag in seen) and len(seen) == 2


@pytest.mark.asyncio
async def test_readonly_step_has_no_write_ops():
    """Without SnapshotHook, has_write_ops is always False regardless of tools."""
    engine, _, _ = _build_engine([_llm_ok([_tool_call("read_file")]), _llm_ok()], readonly=True)
    seen = []

    async def _dispatch(method, ctx):
        if method == "on_step_start":
            seen.append(ctx.has_write_ops)

    engine._dispatch = _dispatch

    await engine.execute(_user_message())

    assert all(flag is False for flag in seen) and seen


@pytest.mark.asyncio
async def test_process_tool_call_result_callable_standalone():
    """Kept as a public engine method (``test_image_tool.py`` depends on it)."""
    engine, _, _ = _build_engine([_llm_ok()])
    engine.turn_id = "turn-1"
    engine.step_id = "step-1"

    ok = await engine.process_tool_call_result(
        _tool_call(), ToolResult(status=ToolStatus.SUCCESS, content="ok")
    )

    assert ok is True
    assert engine.session_manager.save_tool_call.await_count == 1
    assert engine.context.add_message.await_count == 1


@pytest.mark.asyncio
async def test_save_turn_end_called_once_on_success():
    engine, _, _ = _build_engine([_llm_ok()])

    await engine.execute(_user_message())

    assert engine.session_manager.save_turn_end.await_count == 1
    kwargs = engine.session_manager.save_turn_end.await_args.kwargs
    assert kwargs["status"] == "completed"
    assert kwargs["turn_id"] == "turn-1"


@pytest.mark.asyncio
async def test_save_turn_end_status_error_on_failure():
    engine, _, _ = _build_engine([LLMCallResult(success=False)])

    await engine.execute(_user_message())

    kwargs = engine.session_manager.save_turn_end.await_args.kwargs
    assert kwargs["status"] == "error"


@pytest.mark.asyncio
async def test_save_turn_end_skipped_when_setup_fails():
    engine, _, _ = _build_engine([_llm_ok()])
    engine.session_manager.start_turn = AsyncMock(return_value=None)

    result = await engine.execute(_user_message())

    assert result.status == ExecutionStatus.ERROR
    assert engine.session_manager.save_turn_end.await_count == 0


@pytest.mark.asyncio
async def test_two_executions_reset_turn_scoped_state():
    """M12: dead-loop signatures and rate-limit counters reset per turn."""
    hook = FakeHook()
    engine, llm_strategy, tool_strategy = _build_engine(
        [_llm_ok(), _llm_ok()], hooks=[hook]
    )

    await engine.execute(_user_message())
    await engine.execute(_user_message())

    assert llm_strategy.reset_count == 2
    assert tool_strategy.reset_count == 2
    assert hook.reset_count == 2


@pytest.mark.asyncio
async def test_empty_message_is_skipped():
    engine, llm_strategy, _ = _build_engine([_llm_ok()])

    result = await engine.execute(None)

    assert result.status == ExecutionStatus.SKIPPED
    assert llm_strategy.calls == []


@pytest.mark.asyncio
async def test_abort_during_tools_stops_the_round():
    llm_strategy = FakeLLMStrategy([_llm_ok([_tool_call()]), _llm_ok()])
    engine = None

    def _abort():
        engine.abort()

    tool_strategy = FakeToolStrategy(
        [ToolResult(status=ToolStatus.SUCCESS, content="ok")], on_execute=_abort
    )
    engine = DefaultLoopEngine(
        agent_ref=_agent_ref(),
        llm_client=MagicMock(
            parse_message=MagicMock(return_value={"role": "user", "content": "hi"})
        ),
        context=_context(),
        tool_mapping={},
        config=_config(),
        communicator=MagicMock(),
        session_manager=_session_manager(),
        tool_executor=_tool_executor(),
        llm_strategy=llm_strategy,
        tool_strategy=tool_strategy,
        hooks=[],
    )

    result = await engine.execute(_user_message())

    assert result.status == ExecutionStatus.ABORTED
    assert len(llm_strategy.calls) == 1


def test_start_turn_does_not_broadcast_turn_start():
    """M13: turn_start broadcasting belongs to LifecycleBroadcastHook only."""
    source = Path(inspect.getfile(DefaultLoopEngine)).read_text()
    assert "send_turn_start" not in source


def test_engine_has_no_inline_policy_logic():
    """Retry loops / semaphores / permission partitioning must live in strategies."""
    source = Path(inspect.getfile(DefaultLoopEngine)).read_text()
    for forbidden in (
        "Semaphore",
        "asyncio.sleep",
        "get_permission",
        "consecutive_rate_limit",
        "dead_loop_window",
        "GitSnapshotManager",
        "ContextCompressor",
        "MemoryManager",
    ):
        assert forbidden not in source, f"{forbidden} must not appear in engine.py"


def test_engine_is_an_orchestrator_not_a_monolith():
    """Guard the *shape*, not the line count.

    The ``engine.py`` ≤320-line AC was withdrawn by the plan owner (plan
    Appendix C, C1) in favour of readability, so asserting a line budget here
    would just be an arbitrary number that keeps getting bumped.  What must
    hold instead: the policy lives in ``strategies/`` + ``hooks/`` (guarded by
    ``test_engine_has_no_inline_policy_logic``), and the engine's method count
    stays well below the legacy monolith's 52.
    """
    source = Path(inspect.getfile(DefaultLoopEngine)).read_text()
    methods = {
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert len(methods) <= 40, f"engine.py grew to {len(methods)} methods"


def test_legacy_engine_module_is_gone():
    """Task 5.1: the 1427-line monolith must not come back."""
    assert importlib.util.find_spec("broca.loop_engine.legacy") is None


def test_engine_imports_no_hook_owned_components():
    """Task 5.1 AC: no ``SnapshotManager`` / ``ContextCompressor`` / ``MemoryManager``.

    They are hook dependencies now; importing them into the engine would
    re-introduce the coupling the refactor removed.
    """
    source = Path(inspect.getfile(DefaultLoopEngine)).read_text()
    import_lines = [
        line
        for line in source.splitlines()
        if line.startswith("import ") or line.startswith("from ")
    ]
    for forbidden in ("SnapshotManager", "ContextCompressor", "MemoryManager"):
        assert not any(forbidden in line for line in import_lines), (
            f"{forbidden} must not be imported by engine.py"
        )


def test_engine_keeps_required_dependency_fields():
    """Round-2 N2: these attributes are read by the engine and asserted by tests."""
    engine, _, _ = _build_engine([_llm_ok()])
    for field in (
        "agent_ref",
        "llm_client",
        "context",
        "communicator",
        "session_manager",
        "config",
        "tool_mapping",
        "tool_executor",
    ):
        assert hasattr(engine, field), f"engine.{field} must be retained"
    for dropped in ("snapshot_manager", "context_compressor", "persistent_memory_manager"):
        assert not hasattr(engine, dropped), f"engine.{dropped} must be dropped"
