"""Loop hook component interface.

``LoopHook`` is the pluggable "extra behaviour" layer of the execution loop.
Each hook receives shared context objects (``TurnContext`` / ``StepContext``)
and may react to lifecycle events.  Hooks are **optional**: every lifecycle
method defaults to a no-op, so a hook only overrides what it needs.

Lifecycle order (owned by the loop engine, single source of truth)::

    _setup_turn → [on_turn_start] → loop:
        llm_strategy.call → _check_write_ops → [on_step_start] → _save_response
        → tool_strategy.execute → _process_tool_results
        → [on_step_end] → [on_post_step]
    → _finalize_turn: [on_turn_end] → save_turn_end → [on_turn_finalized]
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from broca.components.base import BaseComponent

if TYPE_CHECKING:
    from broca.components.loop_engine import ExecutionResult, ExecutionStatus


@dataclass
class TurnContext:
    """Shared state for one turn (one user message → one agent response).

    Created by the engine in ``_setup_turn()`` and passed to every
    turn-scoped hook callback.  Hooks may write to ``data`` to share
    information with later hooks (e.g. ``turn_end_message``).
    """

    turn_id: str
    agent_id: str
    session_id: str
    user_message: dict  # llm_client.parse_message() result
    message_id: str  # message_id of the persisted user message
    sender_id: str = ""
    files: list = field(default_factory=list)  # user message attachments
    from_agent: bool = False
    raw_input: str = ""
    result: "ExecutionResult | None" = None  # filled by the engine at turn end
    data: dict = field(default_factory=dict)  # cross-hook scratch space


@dataclass
class StepContext:
    """Shared state for one step (one LLM call → tool execution → result).

    Created by the engine in ``_execute_step()`` and passed to every
    step-scoped hook callback.
    """

    step_id: str
    turn_id: str
    agent_id: str
    session_id: str
    response: Any = None
    tool_calls: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)
    has_write_ops: bool = False  # filled by the engine before on_step_start
    status: "ExecutionStatus | None" = None  # engine seeds RUNNING; hooks may change
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    step_start_snapshot: str = ""
    step_end_snapshot: str = ""
    step_patch: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)


class LoopHook(BaseComponent, ABC):
    """Pluggable lifecycle hook for the loop engine.

    Subclasses override only the callbacks they care about; all others are
    no-ops.  ``name`` is a plain class attribute (NOT an abstract property) so
    that a subclass which forgets to override it can still be instantiated.
    """

    name: str = "loop_hook"  # non-abstract; every hook should override with a unique name

    async def on_turn_start(self, ctx: TurnContext) -> None:
        """Called right after the turn state was set up (before the first step)."""

    async def on_step_start(self, ctx: StepContext) -> None:
        """Called before the LLM response is persisted and tools run."""

    async def on_step_end(self, ctx: StepContext) -> None:
        """Called after tool results were processed (snapshot patch, dead-loop)."""

    async def on_post_step(self, ctx: StepContext) -> None:
        """Called after ``on_step_end`` (context compression, memory extraction)."""

    async def on_turn_end(self, ctx: TurnContext) -> None:
        """State-computation phase (runs **before** ``save_turn_end``).

        Must not perform outward notifications — use ``on_turn_finalized``.
        """

    async def on_turn_finalized(self, ctx: TurnContext) -> None:
        """Outward-notification phase (runs **after** ``save_turn_end``).

        Broadcast ``turn_end`` / error notifications here.
        """

    def reset(self) -> None:
        """Reset internal hook state.

        Called by the engine on ``reset()`` and at the start of every turn.
        The default implementation is a no-op.
        """
