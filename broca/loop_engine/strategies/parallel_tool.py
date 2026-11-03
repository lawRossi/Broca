"""Parallel tool execution strategy (default).

Migrated from the former monolithic engine's ``_process_tool_calls_parallel``
(removed in Phase 5):

- partition tool calls into "parallel-safe" and "serial" (permission ``ask``)
  using ``tool_executor.get_permission()``;
- run parallel-safe calls concurrently, bounded by a semaphore
  (``max_parallel_tools``);
- run ``ask``-permission calls one by one in a separate task;
- return results in the original input order.

The strategy only *executes*: broadcasting, DB persistence and context updates
stay in the engine (``process_tool_call_result``).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Callable, Optional

from broca.components.tool_strategy import ToolExecutionStrategy
from broca.logging_config import get_logger
from broca.loop_engine.strategies.serial_tool import aborted_result, run_serially
from broca.tools.tool import ToolResult, ToolStatus

if TYPE_CHECKING:
    from broca.components.tool_executor import ToolExecutor
    from broca.tools.tool import ToolCallContext

logger = get_logger(__name__)

ShouldAbort = Callable[[], bool]

FAILED_RESULT_CONTENT = "Tool execution failed (task cancelled or error)"


class ParallelToolStrategy(ToolExecutionStrategy):
    """Execute tool calls concurrently, except ``ask``-permission tools.

    Degrades to serial execution when ``tool_execution_mode == "serial"`` or
    when there is at most one tool call (identical to the legacy engine).
    """

    name = "parallel_tool"

    def __init__(self) -> None:
        self._tool_executor: Optional["ToolExecutor"] = None
        self._max_parallel: int = 10
        self._mode: str = "parallel"

    async def initialize(self, *, tool_executor: "ToolExecutor", config: Any) -> None:
        """Inject dependencies and resolve execution parameters.

        Priority: explicit ``AgentConfig`` attribute > ``execution_config`` >
        default (plan Task 2.3).
        """
        self._tool_executor = tool_executor
        exec_cfg = getattr(config, "execution_config", None)

        mode = getattr(config, "tool_execution_mode", None)
        if not (isinstance(mode, str) and mode):
            mode = getattr(exec_cfg, "tool_execution_mode", None)
        self._mode = mode if isinstance(mode, str) and mode else "parallel"

        max_parallel = getattr(config, "max_parallel_tools", None)
        if not (isinstance(max_parallel, int) and max_parallel > 0):
            max_parallel = getattr(exec_cfg, "max_parallel_tools", None)
        self._max_parallel = (
            max_parallel if isinstance(max_parallel, int) and max_parallel > 0 else 10
        )

    async def execute(
        self,
        tool_calls: list,
        context: "ToolCallContext",
        tool_mapping: dict,
        *,
        allowed_tools: Optional[list[str]] = None,
        should_abort: Optional[ShouldAbort] = None,
    ) -> list["ToolResult"]:
        if not tool_calls:
            return []

        if self._mode == "serial" or len(tool_calls) <= 1:
            # ── Serial mode (legacy behaviour) ─────────────────────────────
            return await run_serially(
                self._tool_executor,
                tool_calls,
                context,
                tool_mapping,
                allowed_tools=allowed_tools,
                should_abort=should_abort,
            )

        return await self._execute_parallel(
            tool_calls,
            context,
            tool_mapping,
            allowed_tools=allowed_tools,
            should_abort=should_abort,
        )

    async def _execute_parallel(
        self,
        tool_calls: list,
        context: "ToolCallContext",
        tool_mapping: dict,
        *,
        allowed_tools: Optional[list[str]],
        should_abort: Optional[ShouldAbort],
    ) -> list["ToolResult"]:
        """Run the batch concurrently, returning results in input order."""
        semaphore = asyncio.Semaphore(self._max_parallel)
        results: list[Optional[ToolResult]] = [None] * len(tool_calls)

        def _aborted() -> bool:
            return should_abort is not None and should_abort()

        # ── Partition: tools needing serial execution ──────────────────────
        # Serial if: (a) tool is an interactive-blocking tool (ask_user),
        # (b) permission == "ask", or (c) pre_execute_check indicates
        # the tool needs a dynamic permission prompt (e.g. bash with
        # dangerous commands).  Running these serially prevents the
        # permission/question dialog from being dismissed by concurrent
        # tool results.
        serial_indices: set[int] = set()
        for index, tool_call in enumerate(tool_calls):
            tool_name = tool_call.function.name
            if tool_name not in tool_mapping:
                continue
            # (a) Interactive-blocking tools must be serial
            if tool_name == "ask_user":
                serial_indices.add(index)
                continue
            tool = tool_mapping[tool_name]
            if self._tool_executor.get_permission(tool_name) == "ask":
                serial_indices.add(index)
            else:
                pre_check_fn = getattr(tool, "pre_execute_check", None)
                if pre_check_fn and pre_check_fn(
                    tool_call.function.arguments, context
                ):
                    serial_indices.add(index)
        parallel_indices = [
            i for i in range(len(tool_calls)) if i not in serial_indices
        ]
        serial_list = sorted(serial_indices)

        async def _exec_tool(tool_call: Any) -> ToolResult:
            outcome = await self._tool_executor.execute_tool(
                tool_call.function.name,
                tool_call.function.arguments,
                tool_call.id,
                context,
                tool_mapping.get(tool_call.function.name),
                allowed_tools=allowed_tools,
            )
            return outcome.result

        async def _run_parallel_tool(index: int) -> None:
            if _aborted():
                results[index] = aborted_result()
                return
            async with semaphore:
                if _aborted():
                    results[index] = aborted_result()
                    return
                results[index] = await _exec_tool(tool_calls[index])

        async def _run_serial_tools() -> None:
            for index in serial_list:
                if _aborted():
                    results[index] = aborted_result()
                    continue
                results[index] = await _exec_tool(tool_calls[index])

        tasks = [
            asyncio.create_task(_run_parallel_tool(i)) for i in parallel_indices
        ]
        if serial_list:
            tasks.append(asyncio.create_task(_run_serial_tools()))
        gather_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log exceptions that caused a task to die before it could fill its
        # result slot (OOM, timeout, etc.) — they would otherwise be silently
        # swallowed by ``return_exceptions=True`` (review 1.4).
        for r in gather_results:
            if isinstance(r, BaseException) and not isinstance(
                r, asyncio.CancelledError
            ):
                logger.warning(f"Parallel tool task raised: {r}")

        # ── Fill gaps (cancelled tasks / unexpected errors) ────────────────
        for index in range(len(tool_calls)):
            if results[index] is None:
                results[index] = ToolResult(
                    status=ToolStatus.ERROR, content=FAILED_RESULT_CONTENT
                )
        return results
