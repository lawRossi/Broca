"""ToolExecutor component interface.

Encapsulates the full tool execution pipeline:
broadcast → existence check → allowed_tools whitelist → permission
(forbidden/ask/allow) → timeout (with skip rules) → execute →
exception mapping → session decision.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Sequence

from broca.components.base import BaseComponent

if TYPE_CHECKING:
    from broca.components.communicator import Communicator
    from broca.components.permission_provider import PermissionProvider
    from broca.tools.tool import Tool, ToolResult


@dataclass
class ToolExecutionOutcome:
    """Tool execution result + session-level permission decision **observation**.

    The ``override`` has already been applied internally by the executor.
    Callers must NOT apply it again.

    Attributes:
        result: The tool execution result.
        session_action: ``"allow" | "forbid" | None`` — observation only,
            for logging/reporting.  The actual ``set_session_override()``
            call is made inside the executor.
    """

    result: "ToolResult"
    session_action: Optional[str] = None


class ToolExecutor(BaseComponent, ABC):
    """Tool executor interface — full pipeline from broadcast to session decision."""

    @abstractmethod
    async def execute_tool(
        self,
        tool_name: str,
        arguments: str,
        tool_call_id: str,
        context: Any,
        tool: "Tool",
        allowed_tools: Sequence[str] | None = None,
    ) -> ToolExecutionOutcome:
        """Execute a single tool call.

        Pipeline order (matches real code, see Task 2.1):
        broadcast → existence → whitelist → permission → timeout → execute
        → exception mapping → session decision.

        Args:
            tool_name: Name of the tool to execute.
            arguments: JSON string of tool arguments.
            tool_call_id: Unique ID for this tool call (used for broadcast).
            context: ``ToolCallContext`` instance (must contain
                ``turn_id`` / ``agent_id``, see Task 2.2 extension).
            tool: The ``Tool`` instance.
            allowed_tools: Per-run whitelist (set by ``LoopEngine``, reset
                by ``agent.run()``).  ``None`` means no restriction.
                This is a **per-run** parameter, NOT part of ``initialize()``.

        Returns:
            ``ToolExecutionOutcome`` with result and session_action.
        """
        ...

    @abstractmethod
    def get_permission(self, tool_name: str) -> str:
        """Return ``"allow" | "ask" | "forbidden"`` for a tool.

        LoopEngine uses this for parallel/serial partitioning.
        """
        ...

    @abstractmethod
    def is_readonly_tool(self, tool_name: str) -> bool:
        """Check whether a tool is read-only (used for snapshot decisions)."""
        ...

    @abstractmethod
    async def initialize(
        self,
        tool_mapping: dict[str, "Tool"],
        permission_provider: "PermissionProvider",
        config: Any,
        communicator: "Communicator",
    ) -> None:
        """Inject runtime dependencies.

        The parameter set **must** match the call sites in
        Task 2.4 / Task 6.1 exactly.  ``allowed_tools`` is deliberately
        excluded — it is per-run state managed by ``LoopEngine``.

        Args:
            tool_mapping: Mapping of tool names to ``Tool`` instances.
            permission_provider: Permission provider for permission checks
                and session overrides.
            config: Agent configuration (for ``interactive``, timeouts, etc.).
            communicator: Communicator for tool-call broadcast.
        """
        ...
