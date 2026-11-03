"""LoopEngine component interface.

The execution engine that drives the agent's main loop:
LLM calls → tool execution → result processing → context compression.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Optional

from broca.components.base import BaseComponent

if TYPE_CHECKING:
    from broca.components.communicator import Communicator
    from broca.components.llm_client import LLMClient
    from broca.components.llm_strategy import LLMStrategy
    from broca.components.loop_hook import LoopHook
    from broca.components.permission_provider import PermissionProvider
    from broca.components.protocols import AgentReference
    from broca.components.tool_executor import ToolExecutor
    from broca.components.tool_strategy import ToolExecutionStrategy
    from broca.context import Context
    from broca.session.session_manager import SessionManager
    from broca.tools.tool import Tool


class ExecutionStatus(str, Enum):
    """Agent execution status enumeration."""

    RUNNING = "running"
    PENDING = "pending"
    COMPLETED = "completed"
    ERROR = "error"
    ABORTED = "aborted"
    SKIPPED = "skipped"
    LIMIT_EXCEEDED = "limit_exceeded"
    DEAD_LOOP = "dead_loop"


@dataclass
class ExecutionResult:
    """Result of agent execution."""

    status: ExecutionStatus
    message: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "status": self.status,
            "message": self.message,
            "data": self.data,
            "error": self.error,
        }

    def __str__(self) -> str:
        return f"ExecutionResult(status={self.status}, message={self.message})"


class LoopEngine(BaseComponent, ABC):
    """Execution engine interface.

    Drives the core agent loop: LLM calls, tool execution, result
    processing, and context compression.

    This is a **per-agent** component — it holds ``abort_event``,
    ``turn_id``, and other mutable execution state.
    """

    @abstractmethod
    async def execute(
        self,
        message: Optional[Any],
        max_steps: Optional[int] = None,
        from_agent: Optional[bool] = False,
        *,
        allowed_tools: Optional[list[str]] = None,
        namespace: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute the agent loop with the given message.

        Args:
            message: The message to process (``Message`` instance or None).
            max_steps: Maximum number of execution steps.
            from_agent: Whether the message came from another agent.
            allowed_tools: Optional list of tool names that are allowed to be
                called.  Tools not in this list are skipped with an error.
            namespace: Optional execution namespace (e.g. for sub-agents).

        Returns:
            ``ExecutionResult`` with status and any result/error info.
        """
        ...

    @abstractmethod
    def abort(self) -> None:
        """Abort the current execution."""
        ...

    @abstractmethod
    def reset(self) -> None:
        """Reset execution state (clears abort, turn_id, session overrides)."""
        ...

    @abstractmethod
    async def initialize(
        self,
        agent_ref: "AgentReference",
        llm_client: "LLMClient",
        context: "Context",
        tool_executor: "ToolExecutor",
        communicator: "Communicator",
        session_manager: "SessionManager",
        config: Any,
        tool_mapping: dict[str, "Tool"],
        permission_provider: "PermissionProvider",
        # ── Optional pluggability (all defaulted: existing callers unaffected) ──
        llm_strategy: "LLMStrategy | None" = None,
        tool_strategy: "ToolExecutionStrategy | None" = None,
        hooks: list["LoopHook"] | None = None,
    ) -> None:
        """Inject all runtime dependencies.

        Args:
            agent_ref: Narrow reference to the agent (``AgentReference``
                protocol).  Must support ``turn_id`` read/write and
                ``last_context_length``.
            llm_client: LLM client for API calls.
            context: Context for message history management.
            tool_executor: Tool executor for executing tool calls.
            communicator: Communication interface.
            session_manager: Session manager for persistence.
            config: Agent configuration.
            tool_mapping: Mapping of tool names to ``Tool`` instances.
            permission_provider: Permission provider (also used by
                ``reset()`` for clearing session overrides).
            llm_strategy: Optional LLM strategy override.  ``None`` → the
                implementation falls back to its built-in default.
            tool_strategy: Optional tool execution strategy override.
                ``None`` → built-in default.
            hooks: Optional lifecycle hooks.  ``None`` → built-in default set.

        Note:
            ``context_compressor`` and ``memory_manager`` are **not** engine
            dependencies — they belong to ``CompressionMemoryHook`` and are
            wired by the hook factory.  They were removed from this signature
            in the review fix (2.1).
        """
        ...

    def add_hook(self, hook: "LoopHook") -> None:
        """Register a lifecycle hook (may be called after ``initialize``).

        Default implementation appends to an internal ``_hooks`` list.
        """
        hooks = getattr(self, "_hooks", None)
        if hooks is None:
            self._hooks = []
            hooks = self._hooks
        hooks.append(hook)
