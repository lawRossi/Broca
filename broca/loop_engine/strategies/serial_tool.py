"""Serial tool execution strategy.

Always executes tool calls one by one, in input order.  Also provides the
shared ``run_serially`` helper used by ``ParallelToolStrategy`` when the batch
degrades to serial (``tool_execution_mode == "serial"`` or a single call).

The strategy only *executes*: broadcasting, DB persistence and context updates
stay in the engine (``process_tool_call_result``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

from broca.components.tool_strategy import (
    ABORTED_TOOL_RESULT_CONTENT,
    ToolExecutionStrategy,
)
from broca.logging_config import get_logger
from broca.tools.tool import ToolResult, ToolStatus

if TYPE_CHECKING:
    from broca.components.tool_executor import ToolExecutor
    from broca.tools.tool import ToolCallContext

logger = get_logger(__name__)

ShouldAbort = Callable[[], bool]

def aborted_result() -> ToolResult:
    """The result used for tool calls skipped because of an abort."""
    return ToolResult(status=ToolStatus.ERROR, content=ABORTED_TOOL_RESULT_CONTENT)


async def run_serially(
    tool_executor: "ToolExecutor",
    tool_calls: list,
    context: "ToolCallContext",
    tool_mapping: dict,
    *,
    allowed_tools: Optional[list[str]] = None,
    should_abort: Optional[ShouldAbort] = None,
) -> list["ToolResult"]:
    """Execute every tool call sequentially, preserving input order."""
    results: list[ToolResult] = []
    for tool_call in tool_calls:
        if should_abort is not None and should_abort():
            logger.info("Agent execution aborted during tool call processing")
            results.append(aborted_result())
            continue
        outcome = await tool_executor.execute_tool(
            tool_call.function.name,
            tool_call.function.arguments,
            tool_call.id,
            context,
            tool_mapping.get(tool_call.function.name),
            allowed_tools=allowed_tools,
        )
        results.append(outcome.result)
    return results


class SerialToolStrategy(ToolExecutionStrategy):
    """Execute tool calls one by one (no concurrency)."""

    name = "serial_tool"

    def __init__(self) -> None:
        self._tool_executor: Optional["ToolExecutor"] = None

    async def initialize(self, *, tool_executor: "ToolExecutor", config: Any) -> None:
        self._tool_executor = tool_executor

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
        return await run_serially(
            self._tool_executor,
            tool_calls,
            context,
            tool_mapping,
            allowed_tools=allowed_tools,
            should_abort=should_abort,
        )
