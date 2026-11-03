"""End-to-end event-flow tests (Phase 4 / Task 4.4).

Replaces the manual front-end verification with an automated equivalent: the
engine runs with the **real** default hook set and a recording communicator, so
the full WebSocket event stream (``turn_start`` → ``step_start`` → ``step_end``
→ ``turn_end`` + error notifications) is asserted end to end.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.components.loop_engine import ExecutionStatus
from broca.components.compressor_context_factory import build_compressor_context
from broca.loop_engine.engine import DefaultLoopEngine
from broca.loop_engine.hooks.factory import build_default_hooks, build_subagent_hooks
from broca.session import MessageType
from broca.tests.test_engine_orchestration import (
    FakeLLMStrategy,
    FakeToolStrategy,
    _agent_ref,
    _llm_ok,
    _session_manager,
    _tool_call,
    _tool_executor,
    _user_message,
)
from broca.tools.tool import ToolResult, ToolStatus


class RecordingCommunicator:
    """Captures every outward call the hooks/engine make."""

    def __init__(self):
        self.events: list[tuple[str, object]] = []

    async def send_turn_start(self, **kwargs):
        self.events.append(("turn_start", kwargs))

    async def send_turn_end(self, **kwargs):
        self.events.append(("turn_end", kwargs))

    async def send_message(self, message):
        self.events.append(("message", message))

    async def send_tool_call(self, **kwargs):
        self.events.append(("tool_call", kwargs))

    async def send_agent_response(self, **kwargs):
        self.events.append(("agent_response", kwargs))

    async def send_error(self, error_info, subscription=None):
        self.events.append(("error", error_info))

    # helpers
    def names(self):
        return [name for name, _ in self.events]

    def messages_of(self, message_type):
        return [
            payload
            for name, payload in self.events
            if name == "message" and payload.message_type == message_type
        ]


class FakeSnapshotManager:
    """Deterministic stand-in for ``GitSnapshotManager``."""

    def __init__(self):
        self.counter = 0
        self.locks = 0
        self.first_hash = None
        self.last_hash = None

    def acquire_lock(self):
        self.locks += 1

    def release_lock(self):
        self.locks -= 1

    async def track(self, workspace):
        self.counter += 1
        value = f"h{self.counter}"
        if self.first_hash is None:
            self.first_hash = value
        self.last_hash = value
        return value

    async def calculate_patch(self, start, end):
        return {"files": [{"path": "a.py"}], "summary": {}}

    async def calculate_diff(self, start, end):
        return "diff --git a/a.py b/a.py"

    def get_diff_summary(self, diff):
        return {
            "total_files": 1,
            "files_added": [],
            "files_deleted": [],
            "files_modified": ["a.py"],
        }


def _config(interactive=True):
    cfg = MagicMock()
    cfg.interactive = interactive
    cfg.provider = "openai"
    cfg.model = "gpt-4o"
    cfg.workspace = "/tmp/ws"
    cfg.enable_snapshot_tracking = True
    cfg.enable_context_compression = False
    cfg.compact_config = MagicMock()
    cfg.execution_config = MagicMock()
    return cfg


def _build(llm_results, *, tool_results=None, interactive=True, subagent=False):
    config = _config(interactive=interactive)
    communicator = RecordingCommunicator()
    session_manager = _session_manager()
    agent_ref = _agent_ref()
    context = MagicMock()
    context.history = [{"role": "user", "content": "hi"}]
    context.add_message = AsyncMock()
    context.format_tool_call_result = MagicMock(return_value={"role": "tool"})
    context.truncate_last_assistant_message_with_tool_calls = AsyncMock()

    tool_executor = _tool_executor(readonly=False)
    if subagent:
        hooks = build_subagent_hooks(config)
    else:
        hooks = build_default_hooks(
            config,
            snapshot_manager=FakeSnapshotManager(),
            communicator=communicator,
            context_compressor=None,
            memory_manager=None,
            context=context,
            session_id=session_manager.session_id,
            compressor_ctx_builder=lambda: build_compressor_context(
                agent_ref=agent_ref,
                config=config,
                communicator=communicator,
                session_manager=session_manager,
                agent_id=agent_ref.agent_id,
                session_id=session_manager.session_id,
            ),
            tool_executor=tool_executor,
        )

    engine = DefaultLoopEngine(
        agent_ref=agent_ref,
        llm_client=MagicMock(
            parse_message=MagicMock(return_value={"role": "user", "content": "hi"})
        ),
        context=context,
        tool_mapping={},
        config=config,
        communicator=communicator,
        session_manager=session_manager,
        tool_executor=tool_executor,
        llm_strategy=FakeLLMStrategy(llm_results),
        tool_strategy=FakeToolStrategy(
            tool_results or [ToolResult(status=ToolStatus.SUCCESS, content="ok")]
        ),
        hooks=hooks,
    )
    return engine, communicator


@pytest.mark.asyncio
async def test_event_flow_turn_start_once_and_turn_end_with_changed_files():
    engine, comm = _build([_llm_ok([_tool_call("write_file")]), _llm_ok()])

    result = await engine.execute(_user_message())

    assert result.status == ExecutionStatus.COMPLETED
    # turn_start is broadcast exactly once (M13).
    assert comm.names().count("turn_start") == 1
    # user message + one step_start/step_end per step
    assert len(comm.messages_of(MessageType.USER_MESSAGE)) == 1
    assert len(comm.messages_of(MessageType.STEP_START)) == 2
    assert len(comm.messages_of(MessageType.STEP_END)) == 2
    # turn_end is broadcast once, with the turn-level diff
    turn_end = [p for n, p in comm.events if n == "turn_end"]
    assert len(turn_end) == 1
    assert turn_end[0]["result"] == ExecutionStatus.COMPLETED.value
    assert turn_end[0]["changed_files"]["total_modified"] == 1
    # no error notification for a successful turn
    assert "error" not in comm.names()


@pytest.mark.asyncio
async def test_step_end_carries_patch_for_write_steps():
    engine, comm = _build([_llm_ok([_tool_call("write_file")]), _llm_ok()])

    await engine.execute(_user_message())

    patches = [m.data.get("patch") for m in comm.messages_of(MessageType.STEP_END)]
    assert patches[0].get("files"), "write step must carry a patch"
    # ``create_step_end`` omits the key entirely when the patch is empty.
    assert not patches[1], "read-only step carries no patch"


@pytest.mark.asyncio
async def test_snapshot_lock_released_after_turn():
    engine, _ = _build([_llm_ok([_tool_call("write_file")]), _llm_ok()])
    snapshot_hook = engine._hooks[0]

    await engine.execute(_user_message())

    assert snapshot_hook._lock_held is False
    assert snapshot_hook._snapshot_manager.locks == 0


@pytest.mark.asyncio
async def test_failed_turn_broadcasts_turn_end_and_error_notification():
    engine, comm = _build([FakeLLMStrategy_result_failure()])

    result = await engine.execute(_user_message())

    assert result.status == ExecutionStatus.ERROR
    turn_end = [p for n, p in comm.events if n == "turn_end"]
    assert turn_end[0]["result"] == ExecutionStatus.ERROR.value
    errors = [p for n, p in comm.events if n == "error"]
    assert errors and errors[0]["code"] == "EXECUTION_ERROR"


@pytest.mark.asyncio
async def test_rate_limit_error_reaches_front_end_with_specific_code():
    from broca.errors import ErrorCode, LLMError

    class _RateLimitedStrategy(FakeToolStrategy):
        async def execute(self, *args, **kwargs):
            raise LLMError("too many", error_code=ErrorCode.LLM_RATE_LIMIT)

    engine, comm = _build([_llm_ok([_tool_call("write_file")])])
    engine._tool_strategy = _RateLimitedStrategy()

    result = await engine.execute(_user_message())

    assert result.status == ExecutionStatus.ERROR
    codes = [p.get("code") for n, p in comm.events if n == "error"]
    assert ErrorCode.LLM_RATE_LIMIT.value in codes


@pytest.mark.asyncio
async def test_subagent_hooks_emit_no_front_end_events():
    """Sub agents run with ``interactive=False`` and the reduced hook set."""
    engine, comm = _build(
        [_llm_ok([_tool_call("write_file")]), _llm_ok()], subagent=True, interactive=False
    )

    result = await engine.execute(_user_message())

    assert result.status == ExecutionStatus.COMPLETED
    assert comm.events == []


def FakeLLMStrategy_result_failure():
    from broca.components.llm_strategy import LLMCallResult

    return LLMCallResult(success=False, error_code="LLM_ERROR")
