"""Cross-component Protocol definitions.

These Protocols define the **narrow interfaces** that components use to
communicate with each other, avoiding the need to pass the full ``Agent``
object between components.

**Exception**: ``ToolCallContext.agent`` continues to reference the real
``Agent`` — the ``task`` / ``blackboard`` / ``cron`` / ``bash`` / ``image`` /
``agent_interaction`` tools depend on ``context.agent.name``,
``context.agent.agent_id``, and ``context.agent.config``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from broca.agent_configs import ContextCompactConfig
    from broca.components.communicator import Communicator
    from broca.context import Context
    from broca.session.session_manager import SessionManager


@runtime_checkable
class CompressorContext(Protocol):
    """Narrow interface required by ContextCompressor.

    Replaces direct access to the ``Agent`` object in the compression path.
    """

    agent_id: str
    session_id: str
    communicator: Communicator
    session_manager: SessionManager

    @property
    def compact_config(self) -> ContextCompactConfig: ...

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def workspace(self) -> str | None: ...

    last_context_length: Optional[int]
    """Token count from the last LLM response, used by the compressor's
    token estimation (``context_compressor.py`` line 181 area)."""


@runtime_checkable
class AgentReference(Protocol):
    """Narrow interface required by LoopEngine.

    Replaces direct ``Agent`` reference in the execution loop.
    Note: ``turn_id`` is **read-write** (``loop_engine.py`` writes it via
    ``self.agent_ref.turn_id = ...``).

    ``last_context_length`` is proxied through the adapter for use by
    ``components.compressor_context_factory.build_compressor_context()``.
    """

    agent_id: str
    session_id: str

    @property
    def turn_id(self) -> Optional[str]: ...

    @turn_id.setter
    def turn_id(self, value: Optional[str]) -> None: ...

    last_context_length: Optional[int]

    async def on_llm_call_completed(
        self, input_tokens: int, output_tokens: int
    ) -> None: ...

    async def ask_for_permission(self, message: str) -> bool: ...

    async def ask_for_tool_permission(
        self, tool_name: str, arguments: str
    ) -> tuple[bool, Optional[str]]: ...


@runtime_checkable
class PermissionContext(Protocol):
    """Narrow context passed to PermissionProvider for permission requests."""

    turn_id: Optional[str]
    agent_id: Optional[str]
    session_id: Optional[str]


@runtime_checkable
class ExecutionContext(Protocol):
    """Narrow context for execution-scoped operations (e.g. session memory)."""

    agent_id: str
    session_id: str
    turn_id: Optional[str]
    communicator: Communicator
    session_manager: SessionManager
    context: Context
    config: object
