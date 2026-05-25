from typing import Optional

from broca.commands.base import CommandContext, CommandResult, LocalCommand
from broca.logging_config import get_logger

logger = get_logger(__name__)


class RedoCommand(LocalCommand):
    """Redo the last undone operation"""

    async def execute(self, args: str, ctx: CommandContext) -> Optional[CommandResult]:
        # Check agent status
        if ctx.agent.status == ctx.agent.STATUS_RUNNING:
            return CommandResult(
                type="error",
                value="Agent is already running, cannot redo",
            )

        session_id = ctx.session_id
        if not session_id:
            return CommandResult(
                type="error",
                value="No active session for redo operation",
            )

        try:
            # Execute redo
            result = await ctx.agent.revert_service.redo(
                session_id=session_id, agent_id=ctx.agent_id
            )

            if result.get("success"):
                # Rebuild context
                await ctx.context.build_history_from_session(ctx.agent_id)
                return CommandResult(
                    type="text",
                    value="Redo successful",
                )
            else:
                return CommandResult(
                    type="error",
                    value=f"Redo failed: {result.get('message', 'Unknown error')}",
                )

        except Exception as e:
            logger.error(f"Error handling redo command: {e}")
            return CommandResult(
                type="error",
                value=f"Error handling redo: {e}",
            )
