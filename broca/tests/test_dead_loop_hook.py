"""Unit tests for ``DeadLoopHook`` (Task 3.4).

Covers the migration of ``_detect_dead_loop`` / ``_extract_tool_call_signatures`` /
``_normalize_arguments``.

Semantics under test: the flattened signature list's **last ``window``
elements** must all be identical — a step with two tool calls contributes two
signatures, so ``window`` counts signatures, not steps.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from broca.components.loop_engine import ExecutionStatus
from broca.components.loop_hook import StepContext
from broca.loop_engine.hooks.dead_loop_hook import DeadLoopHook


def make_tool_call(name: str, arguments: str):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))


def make_step_ctx(tool_calls: list | None = None) -> StepContext:
    return StepContext(
        step_id="step-1",
        turn_id="turn-1",
        agent_id="agent-1",
        session_id="sess-1",
        tool_calls=tool_calls or [],
        status=ExecutionStatus.RUNNING,
    )


class TestDetection:
    @pytest.mark.asyncio
    async def test_three_identical_calls_trigger_dead_loop(self):
        hook = DeadLoopHook(window=3)
        call = make_tool_call("read_file", '{"path": "a.py"}')

        for _ in range(2):
            ctx = make_step_ctx([call])
            await hook.on_step_end(ctx)
            assert ctx.status == ExecutionStatus.RUNNING

        ctx = make_step_ctx([call])
        await hook.on_step_end(ctx)
        assert ctx.status == ExecutionStatus.DEAD_LOOP

    @pytest.mark.asyncio
    async def test_two_identical_calls_do_not_trigger(self):
        hook = DeadLoopHook(window=3)
        call = make_tool_call("read_file", '{"path": "a.py"}')

        for _ in range(2):
            ctx = make_step_ctx([call])
            await hook.on_step_end(ctx)
            assert ctx.status == ExecutionStatus.RUNNING

    @pytest.mark.asyncio
    async def test_window_counts_signatures_not_steps(self):
        # window=3 with 2 calls per step: 2 steps → 4 signatures → triggers
        hook = DeadLoopHook(window=3)
        calls = [
            make_tool_call("read_file", '{"path": "a.py"}'),
            make_tool_call("read_file", '{"path": "a.py"}'),
        ]

        ctx1 = make_step_ctx(calls)
        await hook.on_step_end(ctx1)
        assert ctx1.status == ExecutionStatus.RUNNING  # only 2 signatures so far

        ctx2 = make_step_ctx(calls)
        await hook.on_step_end(ctx2)
        assert ctx2.status == ExecutionStatus.DEAD_LOOP

    @pytest.mark.asyncio
    async def test_different_calls_do_not_trigger(self):
        hook = DeadLoopHook(window=3)
        calls = [
            make_tool_call("read_file", '{"path": "a.py"}'),
            make_tool_call("read_file", '{"path": "b.py"}'),
            make_tool_call("read_file", '{"path": "c.py"}'),
        ]

        ctx = make_step_ctx(calls)
        await hook.on_step_end(ctx)
        assert ctx.status == ExecutionStatus.RUNNING

    @pytest.mark.asyncio
    async def test_no_tool_calls_never_triggers(self):
        hook = DeadLoopHook(window=3)
        for _ in range(5):
            ctx = make_step_ctx([])
            await hook.on_step_end(ctx)
            assert ctx.status == ExecutionStatus.RUNNING
        assert hook._signatures == []


class TestReset:
    @pytest.mark.asyncio
    async def test_reset_restarts_counting(self):
        hook = DeadLoopHook(window=3)
        call = make_tool_call("read_file", '{"path": "a.py"}')

        for _ in range(2):
            await hook.on_step_end(make_step_ctx([call]))

        hook.reset()
        assert hook._signatures == []

        # After reset two more identical calls must not trigger
        ctx = make_step_ctx([call])
        await hook.on_step_end(ctx)
        assert ctx.status == ExecutionStatus.RUNNING
        ctx = make_step_ctx([call])
        await hook.on_step_end(ctx)
        assert ctx.status == ExecutionStatus.RUNNING

        ctx = make_step_ctx([call])
        await hook.on_step_end(ctx)
        assert ctx.status == ExecutionStatus.DEAD_LOOP


class TestNormalization:
    def test_key_order_is_normalized(self):
        a = DeadLoopHook._normalize_arguments('{"a": 1, "b": 2}')
        b = DeadLoopHook._normalize_arguments('{"b": 2, "a": 1}')
        assert a == b == '{"a": 1, "b": 2}'

    def test_empty_and_none_arguments(self):
        assert DeadLoopHook._normalize_arguments("") == ""
        assert DeadLoopHook._normalize_arguments(None) == ""
        assert DeadLoopHook._normalize_arguments("   ") == ""

    def test_invalid_json_returned_stripped(self):
        assert DeadLoopHook._normalize_arguments("  not json  ") == "not json"

    def test_list_arguments_kept_in_order(self):
        assert DeadLoopHook._normalize_arguments("[2, 1]") == "[2, 1]"

    def test_signature_format(self):
        calls = [make_tool_call("read_file", '{"b": 2, "a": 1}')]
        assert DeadLoopHook._extract_tool_call_signatures(calls) == [
            'read_file({"a": 1, "b": 2})'
        ]


class TestHookContract:
    def test_name_is_unique(self):
        assert DeadLoopHook.name == "dead_loop"

    def test_default_window(self):
        assert DeadLoopHook()._window == 3

    def test_invalid_window_falls_back(self):
        assert DeadLoopHook(window=0)._window == 3
        assert DeadLoopHook(window=None)._window == 3
        assert DeadLoopHook(window=True)._window == 3
