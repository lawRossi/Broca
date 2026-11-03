"""Tool execution strategy component interface.

A ``ToolExecutionStrategy`` encapsulates *how* tool calls are executed —
serially or in parallel, with concurrency limits and permission partitioning.
The strategy receives the ``ToolExecutor`` via ``initialize()`` so it never
appears in ``execute()`` arguments.

Note: ``ToolCallContext`` has no ``abort_event`` field, therefore abort is
propagated through the explicit ``should_abort`` callable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Optional

from broca.components.base import BaseComponent

#: Content of the placeholder result a strategy returns for a tool call that
#: was **never executed** because of an abort.  The engine uses it to skip
#: persisting/broadcasting results that never happened (legacy parity: an
#: aborted serial batch wrote no rows for the remaining tool calls).
ABORTED_TOOL_RESULT_CONTENT = "Execution aborted"

if TYPE_CHECKING:
    from broca.components.tool_executor import ToolExecutor
    from broca.tools.tool import ToolCallContext, ToolResult


class ToolExecutionStrategy(BaseComponent, ABC):
    """Strategy interface for executing a batch of tool calls.

    Implementations must return results in the **same order** as the input
    ``tool_calls`` list, regardless of execution concurrency.
    """

    name: str = "tool_strategy"  # non-abstract; every strategy should override

    @abstractmethod
    async def execute(
        self,
        tool_calls: list,
        context: "ToolCallContext",
        tool_mapping: dict,
        *,
        allowed_tools: Optional[list[str]] = None,
        should_abort: Optional[Callable[[], bool]] = None,
    ) -> list["ToolResult"]:
        """Execute ``tool_calls`` and return results in input order.

        Args:
            tool_calls: Tool calls produced by the LLM.
            context: Shared tool call context (7 fields, no abort_event).
            tool_mapping: Mapping of tool names to ``Tool`` instances.
            allowed_tools: Optional whitelist of allowed tool names.
            should_abort: Abort predicate checked between tool executions.
        """
        ...

    @abstractmethod
    async def initialize(self, *, tool_executor: "ToolExecutor", config: Any) -> None:
        """Inject required dependencies.

        Args:
            tool_executor: Executor used to run individual tool calls.
            config: Agent configuration (``max_parallel_tools`` etc.).
        """
        ...

    def reset(self) -> None:
        """Reset internal state.

        Called by the engine on ``reset()`` and at the start of every turn.
        The default implementation is a no-op.
        """
