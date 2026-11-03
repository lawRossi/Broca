"""Context cleanup hook — state-driven context hygiene at turn end.

Migrated from ``DefaultLoopEngine._finalize_turn()`` (review 4.1): when a turn
ends in the ``ABORTED`` state, the trailing assistant tool-call message is
removed from the conversation history so the next turn starts from a clean
context.

The engine no longer knows *what* to clean up; it simply dispatches
``on_turn_end`` and the hook decides based on ``ctx.result.status``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from broca.components.loop_engine import ExecutionStatus
from broca.components.loop_hook import LoopHook, TurnContext
from broca.logging_config import get_logger

if TYPE_CHECKING:
    from broca.context import Context

logger = get_logger(__name__)


class ContextCleanupHook(LoopHook):
    """Clean up conversation context based on the turn's terminal status."""

    name = "context_cleanup"

    def __init__(self, context: Optional["Context"] = None):
        self._context = context

    async def on_turn_end(self, ctx: TurnContext) -> None:
        if self._context is None or ctx.result is None:
            return
        if ctx.result.status == ExecutionStatus.ABORTED:
            try:
                await self._context.truncate_last_assistant_message_with_tool_calls(
                    turn_id=ctx.turn_id, agent_id=ctx.agent_id
                )
            except Exception as e:
                logger.warning(f"Context cleanup on aborted turn failed: {e}")
