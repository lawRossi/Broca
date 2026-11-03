"""Unit tests for ``ParallelToolStrategy`` / ``SerialToolStrategy``.

Covers permission partitioning, concurrency bounds, input-order preservation,
abort semantics and exception fallbacks.  The ``ToolExecutor`` is mocked; the
strategies must not touch session/DB/communicator (asserted by the fake).
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import pytest

from broca.components.tool_executor import ToolExecutionOutcome
from broca.loop_engine.strategies.parallel_tool import ParallelToolStrategy
from broca.loop_engine.strategies.serial_tool import SerialToolStrategy
from broca.tools.tool import ToolCallContext, ToolResult, ToolStatus


class FakeFunction:
    def __init__(self, name: str, arguments: str = "{}") -> None:
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str = "{}") -> None:
        self.id = call_id
        self.function = FakeFunction(name, arguments)


class FakeConfig:
    tool_execution_mode: Optional[str] = None
    max_parallel_tools: Optional[int] = None

    class _Exec:
        tool_execution_mode = "parallel"
        max_parallel_tools = 2

    execution_config = _Exec()


class FakeToolExecutor:
    """Records executions and enforces ``get_permission`` partitioning."""

    def __init__(
        self,
        permissions: dict[str, str] | None = None,
        delay: float = 0.0,
        unknown: tuple[str, ...] = (),
    ):
        self._permissions = permissions or {}
        self._delay = delay
        self._unknown = set(unknown)
        self.executed: list[str] = []
        self.concurrent = 0
        self.max_concurrent = 0
        self.raise_for: set[str] = set()

    def get_permission(self, tool_name: str) -> str:
        return self._permissions.get(tool_name, "allow")

    async def execute_tool(
        self,
        tool_name: str,
        arguments: str,
        tool_call_id: str,
        context: Any,
        tool: Any,
        allowed_tools=None,
    ) -> ToolExecutionOutcome:
        if tool_name in self.raise_for:
            raise RuntimeError(f"boom:{tool_name}")
        if tool_name in self._unknown:
            self.executed.append(tool_call_id)
            return ToolExecutionOutcome(
                result=ToolResult(
                    status=ToolStatus.ERROR, content=f"Tool not found: {tool_name}"
                )
            )
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            self.executed.append(tool_call_id)
            return ToolExecutionOutcome(
                result=ToolResult(
                    status=ToolStatus.SUCCESS, content=f"{tool_name}-done"
                )
            )
        finally:
            self.concurrent -= 1


def _calls(*specs: tuple[str, str]) -> list[FakeToolCall]:
    return [FakeToolCall(f"call_{i}", name) for i, (name, _) in enumerate(specs)]


async def _strategy(kind: str, executor: FakeToolExecutor, **config_attrs):
    config = FakeConfig()
    for key, value in config_attrs.items():
        setattr(config, key, value)
    strategy = (
        ParallelToolStrategy() if kind == "parallel" else SerialToolStrategy()
    )
    await strategy.initialize(tool_executor=executor, config=config)
    return strategy


# ---------------------------------------------------------------------------
# ParallelToolStrategy
# ---------------------------------------------------------------------------
class TestParallelToolStrategy:
    @pytest.mark.asyncio
    async def test_concurrency_bounded_by_max_parallel(self):
        executor = FakeToolExecutor(delay=0.01)
        strategy = await _strategy("parallel", executor, max_parallel_tools=2)
        tool_calls = _calls(*[("read_file", "") for _ in range(6)])

        results = await strategy.execute(tool_calls, ToolCallContext(), {})

        assert len(results) == 6
        assert executor.max_concurrent <= 2
        assert all(r.status == ToolStatus.SUCCESS for r in results)

    @pytest.mark.asyncio
    async def test_ask_permission_tools_run_serially_and_in_order(self):
        executor = FakeToolExecutor(permissions={"bash": "ask"})
        strategy = await _strategy("parallel", executor)
        tool_calls = _calls(("read_file", ""), ("bash", ""), ("read_file", ""))

        results = await strategy.execute(
            tool_calls, ToolCallContext(), {"read_file": object(), "bash": object()}
        )

        # Results keep input order regardless of execution scheduling.
        assert [r.content for r in results] == [
            "read_file-done",
            "bash-done",
            "read_file-done",
        ]

    @pytest.mark.asyncio
    async def test_results_order_matches_input_with_varying_delays(self):
        executor = FakeToolExecutor(delay=0.005)
        strategy = await _strategy("parallel", executor, max_parallel_tools=4)
        tool_calls = [FakeToolCall(f"call_{i}", f"tool_{i}") for i in range(5)]

        results = await strategy.execute(tool_calls, ToolCallContext(), {})

        assert [r.content for r in results] == [f"tool_{i}-done" for i in range(5)]

    @pytest.mark.asyncio
    async def test_abort_marks_remaining_tools_as_error(self):
        executor = FakeToolExecutor()
        strategy = await _strategy("parallel", executor)
        tool_calls = _calls(("read_file", ""), ("read_file", ""), ("read_file", ""))

        results = await strategy.execute(
            tool_calls, ToolCallContext(), {}, should_abort=lambda: True
        )

        assert [r.content for r in results] == ["Execution aborted"] * 3
        assert all(r.status == ToolStatus.ERROR for r in results)
        assert executor.executed == []

    @pytest.mark.asyncio
    async def test_exception_fallback_fills_missing_result(self):
        executor = FakeToolExecutor()
        executor.raise_for = {"explode"}
        strategy = await _strategy("parallel", executor)
        tool_calls = _calls(("ok_tool", ""), ("explode", ""))

        results = await strategy.execute(tool_calls, ToolCallContext(), {})

        assert results[0].status == ToolStatus.SUCCESS
        assert results[1].status == ToolStatus.ERROR
        assert results[1].content == "Tool execution failed (task cancelled or error)"

    @pytest.mark.asyncio
    async def test_unknown_tool_is_not_partitioned_as_ask(self):
        executor = FakeToolExecutor(permissions={"unknown": "ask"})
        strategy = await _strategy("parallel", executor)
        tool_calls = _calls(("unknown", ""), ("read_file", ""))

        results = await strategy.execute(tool_calls, ToolCallContext(), {})

        assert len(results) == 2
        assert all(r.status == ToolStatus.SUCCESS for r in results)

    @pytest.mark.asyncio
    async def test_unknown_tool_error_does_not_block_other_tools(self):
        """Migrated from ``test_loop_engine.TestParallelToolExecution``."""
        executor = FakeToolExecutor(unknown=("nonexistent",))
        strategy = await _strategy("parallel", executor)
        tool_calls = _calls(("read_file", ""), ("nonexistent", ""))

        results = await strategy.execute(tool_calls, ToolCallContext(), {})

        assert results[0].status == ToolStatus.SUCCESS
        assert results[1].status == ToolStatus.ERROR
        assert "not found" in results[1].content

    @pytest.mark.asyncio
    async def test_serial_mode_from_config_degrades_to_serial(self):
        executor = FakeToolExecutor()
        strategy = await _strategy("parallel", executor, tool_execution_mode="serial")
        tool_calls = _calls(("a", ""), ("b", ""), ("c", ""))

        await strategy.execute(tool_calls, ToolCallContext(), {})

        assert executor.max_concurrent == 1
        assert executor.executed == ["call_0", "call_1", "call_2"]

    @pytest.mark.asyncio
    async def test_single_call_runs_serially(self):
        executor = FakeToolExecutor()
        strategy = await _strategy("parallel", executor)

        await strategy.execute(_calls(("a", "")), ToolCallContext(), {})

        assert executor.executed == ["call_0"]

    @pytest.mark.asyncio
    async def test_empty_batch_returns_empty_list(self):
        executor = FakeToolExecutor()
        strategy = await _strategy("parallel", executor)
        assert await strategy.execute([], ToolCallContext(), {}) == []

    @pytest.mark.asyncio
    async def test_strategy_does_not_touch_session_or_communicator(self):
        executor = FakeToolExecutor()
        strategy = await _strategy("parallel", executor)
        # No session_manager / communicator is injected — a call to them would
        # raise AttributeError and fail the test.
        assert not hasattr(strategy, "_session_manager")
        assert not hasattr(strategy, "_communicator")
        await strategy.execute(_calls(("a", ""), ("b", "")), ToolCallContext(), {})


# ---------------------------------------------------------------------------
# SerialToolStrategy
# ---------------------------------------------------------------------------
class TestSerialToolStrategy:
    @pytest.mark.asyncio
    async def test_executes_in_order(self):
        executor = FakeToolExecutor(delay=0.001)
        strategy = await _strategy("serial", executor)
        tool_calls = _calls(("a", ""), ("b", ""), ("c", ""))

        results = await strategy.execute(tool_calls, ToolCallContext(), {})

        assert executor.executed == ["call_0", "call_1", "call_2"]
        assert executor.max_concurrent == 1
        assert [r.content for r in results] == ["a-done", "b-done", "c-done"]

    @pytest.mark.asyncio
    async def test_abort_skips_remaining_calls(self):
        executor = FakeToolExecutor()
        strategy = await _strategy("serial", executor)
        tool_calls = _calls(("a", ""), ("b", ""))

        results = await strategy.execute(
            tool_calls, ToolCallContext(), {}, should_abort=lambda: True
        )

        assert [r.status for r in results] == [ToolStatus.ERROR, ToolStatus.ERROR]
        assert [r.content for r in results] == ["Execution aborted"] * 2
        assert executor.executed == []

    @pytest.mark.asyncio
    async def test_allowed_tools_is_forwarded_to_executor(self):
        seen: dict = {}

        class RecordingExecutor(FakeToolExecutor):
            async def execute_tool(
                self, tool_name, arguments, tool_call_id, context, tool, allowed_tools=None
            ):
                seen["allowed_tools"] = allowed_tools
                return await super().execute_tool(
                    tool_name, arguments, tool_call_id, context, tool, allowed_tools
                )

        executor = RecordingExecutor()
        strategy = await _strategy("serial", executor)
        await strategy.execute(
            _calls(("a", "")), ToolCallContext(), {}, allowed_tools=["a"]
        )

        assert seen["allowed_tools"] == ["a"]
