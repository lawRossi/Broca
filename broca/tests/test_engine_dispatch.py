"""Hook dispatch tests (Phase 4 / Task 4.1b).

Covers the six lifecycle call points, hook-failure isolation, DEAD_LOOP
propagation, ``BrocaError`` code preservation and step-message persistence.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.components.loop_engine import ExecutionStatus
from broca.components.loop_hook import LoopHook
from broca.components.tool_strategy import ABORTED_TOOL_RESULT_CONTENT
from broca.errors import ErrorCode, LLMError
from broca.loop_engine.engine import DefaultLoopEngine
from broca.loop_engine.hooks.dead_loop_hook import DeadLoopHook
from broca.session import MessageType
from broca.tests.test_engine_orchestration import (
    FakeLLMStrategy,
    FakeToolStrategy,
    _agent_ref,
    _config,
    _context,
    _llm_ok,
    _session_manager,
    _tool_call,
    _tool_executor,
    _user_message,
)
from broca.tools.tool import ToolResult, ToolStatus


class RecordingHook(LoopHook):
    """Records every lifecycle call (and optionally raises)."""

    name = "recording"

    def __init__(self, raise_on=()):
        self.calls = []
        self.raise_on = set(raise_on)

    def _record(self, method):
        self.calls.append(method)
        if method in self.raise_on:
            raise RuntimeError(f"boom in {method}")

    async def on_turn_start(self, ctx):
        self._record("on_turn_start")

    async def on_step_start(self, ctx):
        self._record("on_step_start")

    async def on_step_end(self, ctx):
        self._record("on_step_end")

    async def on_post_step(self, ctx):
        self._record("on_post_step")

    async def on_turn_end(self, ctx):
        self._record("on_turn_end")

    async def on_turn_finalized(self, ctx):
        self._record("on_turn_finalized")


def _engine(llm_results, tool_results=None, *, hooks=(), interactive=False, readonly=True):
    engine = DefaultLoopEngine(
        agent_ref=_agent_ref(),
        llm_client=MagicMock(
            parse_message=MagicMock(return_value={"role": "user", "content": "hi"})
        ),
        context=_context(),
        tool_mapping={},
        config=_config(interactive=interactive),
        communicator=MagicMock(send_error=AsyncMock()),
        session_manager=_session_manager(),
        tool_executor=_tool_executor(readonly=readonly),
        llm_strategy=FakeLLMStrategy(llm_results),
        tool_strategy=FakeToolStrategy(tool_results),
        hooks=list(hooks),
    )
    return engine


TOOL_OK = [ToolResult(status=ToolStatus.SUCCESS, content="ok")]


@pytest.mark.asyncio
async def test_lifecycle_call_order():
    hook = RecordingHook()
    engine = _engine([_llm_ok([_tool_call()]), _llm_ok()], TOOL_OK, hooks=[hook])

    result = await engine.execute(_user_message())

    assert result.status == ExecutionStatus.COMPLETED
    assert hook.calls == [
        "on_turn_start",
        "on_step_start",
        "on_step_end",
        "on_post_step",
        "on_step_start",
        "on_step_end",
        "on_post_step",
        "on_turn_end",
        "on_turn_finalized",
    ]


@pytest.mark.asyncio
async def test_hook_exception_does_not_break_the_loop():
    hook = RecordingHook(raise_on={"on_turn_start", "on_step_start", "on_step_end"})
    engine = _engine([_llm_ok([_tool_call()]), _llm_ok()], TOOL_OK, hooks=[hook])

    result = await engine.execute(_user_message())

    assert result.status == ExecutionStatus.COMPLETED
    assert "on_turn_finalized" in hook.calls


@pytest.mark.asyncio
async def test_dead_loop_status_propagates_to_result():
    calls = [_tool_call("read_file", args='{"path": "a"}')]
    engine = _engine(
        [_llm_ok(calls), _llm_ok(calls), _llm_ok(calls), _llm_ok(calls)],
        TOOL_OK,
        hooks=[DeadLoopHook(window=2)],
    )

    result = await engine.execute(_user_message())

    assert result.status == ExecutionStatus.DEAD_LOOP


@pytest.mark.asyncio
async def test_broca_error_code_preserved_in_round_error():
    """Round-2 N4: the concrete code (LLM_RATE_LIMIT) must reach the front end."""

    class _RaisingToolStrategy(FakeToolStrategy):
        async def execute(self, tool_calls, context, tool_mapping, **kwargs):
            raise LLMError("rate limited", error_code=ErrorCode.LLM_RATE_LIMIT)

    engine = _engine([_llm_ok([_tool_call()])], interactive=True)
    engine._tool_strategy = _RaisingToolStrategy()

    result = await engine.execute(_user_message())

    assert result.status == ExecutionStatus.ERROR
    payload = engine.communicator.send_error.await_args.args[0]
    assert payload["code"] == ErrorCode.LLM_RATE_LIMIT.value


@pytest.mark.asyncio
async def test_on_step_end_runs_even_when_tools_raise():
    class _ExplodingToolStrategy(FakeToolStrategy):
        async def execute(self, tool_calls, context, tool_mapping, **kwargs):
            raise RuntimeError("tool blew up")

    hook = RecordingHook()
    engine = _engine([_llm_ok([_tool_call()])], hooks=[hook])
    engine._tool_strategy = _ExplodingToolStrategy()

    result = await engine.execute(_user_message())

    assert result.status == ExecutionStatus.ERROR
    assert "on_step_end" in hook.calls


@pytest.mark.asyncio
async def test_step_messages_persisted_when_snapshot_tracking_on():
    engine = _engine([_llm_ok(), _llm_ok()])
    engine.config.enable_snapshot_tracking = True
    engine.config.workspace = "/tmp/ws"

    await engine.execute(_user_message())

    types = [
        c.kwargs["message_type"] for c in engine.session_manager.save_message.await_args_list
    ]
    assert MessageType.STEP_START in types
    assert MessageType.STEP_END in types


@pytest.mark.asyncio
async def test_step_start_not_persisted_without_snapshot_tracking():
    engine = _engine([_llm_ok(), _llm_ok()])
    engine.config.enable_snapshot_tracking = False
    engine.config.workspace = "/tmp/ws"

    await engine.execute(_user_message())

    types = [
        c.kwargs["message_type"] for c in engine.session_manager.save_message.await_args_list
    ]
    assert MessageType.STEP_START not in types
    # STEP_END uses the same gate as STEP_START (review 1.1).
    assert MessageType.STEP_END not in types


@pytest.mark.asyncio
async def test_step_message_failure_does_not_break_execution():
    engine = _engine([_llm_ok(), _llm_ok()])
    engine.config.enable_snapshot_tracking = True
    engine.session_manager.save_message = AsyncMock(side_effect=RuntimeError("db down"))

    result = await engine.execute(_user_message())

    assert result.status == ExecutionStatus.ERROR  # user message save fails first


@pytest.mark.asyncio
async def test_on_turn_end_sees_result_and_on_turn_finalized_sees_message_id():
    seen = {}

    class _Probe(LoopHook):
        name = "probe"

        async def on_turn_end(self, ctx):
            seen["turn_end_status"] = ctx.result.status
            seen["message"] = ctx.data.get("turn_end_message")

        async def on_turn_finalized(self, ctx):
            seen["message_id"] = ctx.data.get("turn_end_message_id")
            seen["saved"] = ctx.result.status

    engine = _engine([_llm_ok()], hooks=[_Probe()])

    await engine.execute(_user_message())

    assert seen["turn_end_status"] == ExecutionStatus.COMPLETED
    assert seen["message"] == "Turn completed successfully"
    assert seen["message_id"].startswith("msg_")
    assert seen["saved"] == ExecutionStatus.COMPLETED


# ── Review M3 / m1 / m2 regressions ─────────────────────────────────────


@pytest.mark.asyncio
async def test_abort_placeholders_are_not_persisted():
    """Review M3: a tool call that never ran must not produce a DB row/event.

    Legacy's serial path returned early on abort, so the remaining tool calls
    left no trace.  The strategy now returns placeholders for them — the engine
    must skip those instead of persisting "Execution aborted" rows.
    """
    engine = _engine([_llm_ok()])
    engine.process_tool_call_result = AsyncMock(return_value=True)
    engine.abort_event.set()

    calls = [_tool_call("read_file", tc_id="c1"), _tool_call("read_file", tc_id="c2")]
    executed = ToolResult(status=ToolStatus.SUCCESS, content="ok")
    skipped = ToolResult(
        status=ToolStatus.ERROR, content=ABORTED_TOOL_RESULT_CONTENT
    )

    await engine._process_tool_results(calls, [executed, skipped])

    assert engine.process_tool_call_result.await_count == 1
    assert engine.process_tool_call_result.await_args.args[0].id == "c1"


@pytest.mark.asyncio
async def test_aborted_content_is_persisted_when_no_abort_is_in_flight():
    """Only the *placeholder* is skipped — a real tool may return that text."""
    engine = _engine([_llm_ok()])
    engine.process_tool_call_result = AsyncMock(return_value=True)

    calls = [_tool_call("read_file", tc_id="c1")]
    result = ToolResult(status=ToolStatus.ERROR, content=ABORTED_TOOL_RESULT_CONTENT)

    await engine._process_tool_results(calls, [result])

    assert engine.process_tool_call_result.await_count == 1


@pytest.mark.asyncio
async def test_missing_tool_results_are_padded_not_truncated():
    """Review m1: ``zip()`` used to silently drop calls with no result."""
    engine = _engine([_llm_ok()])
    engine.process_tool_call_result = AsyncMock(return_value=True)

    calls = [
        _tool_call("read_file", tc_id="c1"),
        _tool_call("read_file", tc_id="c2"),
        _tool_call("read_file", tc_id="c3"),
    ]

    await engine._process_tool_results(calls, [ToolResult(status=ToolStatus.SUCCESS, content="ok")])

    assert engine.process_tool_call_result.await_count == 3
    statuses = [c.args[1].status for c in engine.process_tool_call_result.await_args_list]
    assert statuses == [ToolStatus.SUCCESS, ToolStatus.ERROR, ToolStatus.ERROR]


@pytest.mark.asyncio
async def test_reinitialize_raises_instead_of_silently_ignoring():
    """Review 2.4: a registry-reused instance must fail-fast, not silently drop deps."""
    llm_strategy = FakeLLMStrategy([_llm_ok()])
    engine = _engine([_llm_ok()], hooks=[])
    engine._llm_strategy = llm_strategy

    replacement = FakeLLMStrategy([_llm_ok()])
    with pytest.raises(RuntimeError, match="already-initialized"):
        await engine.initialize(
            agent_ref=_agent_ref(),
            llm_client=MagicMock(),
            context=_context(),
            tool_executor=MagicMock(),
            communicator=MagicMock(),
            session_manager=_session_manager(),
            config=_config(),
            tool_mapping={},
            permission_provider=None,
            llm_strategy=replacement,
        )

    # Original strategy is untouched.
    assert engine._llm_strategy is llm_strategy
