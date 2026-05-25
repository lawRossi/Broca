import json
from typing import Optional

from broca.commands.base import LocalCommand, CommandContext, CommandResult
from broca.logging_config import get_logger

logger = get_logger(__name__)


class UndoCommand(LocalCommand):
    """Undo the last operation"""

    async def execute(self, args: str, ctx: CommandContext) -> Optional[CommandResult]:
        # Check agent status
        if ctx.agent.status == ctx.agent.STATUS_RUNNING:
            return CommandResult(
                type="error",
                value="Agent is already running, cannot undo",
            )

        session_id = ctx.session_id
        if not session_id:
            return CommandResult(
                type="error",
                value="No active session for undo operation",
            )

        try:
            # Parse arguments as JSON if provided, otherwise use defaults
            target_message_id = None
            level = "step"

            if args:
                try:
                    parsed_args = json.loads(args)
                    if isinstance(parsed_args, dict):
                        target_message_id = parsed_args.get("target_message_id")
                        level = parsed_args.get("level", "step")
                except json.JSONDecodeError:
                    # If not JSON, treat as target_message_id directly
                    target_message_id = args

            # Execute undo
            result = await ctx.agent.revert_service.undo(
                session_id=session_id,
                agent_id=ctx.agent_id,
                target_message_id=target_message_id,
                level=level,
            )

            if result.get("success"):
                # Rebuild context
                await ctx.context.build_history_from_session(ctx.agent_id)

                diff_summary = result.get("diff_summary", {})
                files_changed = diff_summary.get("total_files", 0)

                return CommandResult(
                    type="text",
                    value=f"Undo successful, {files_changed} files changed",
                )
            else:
                return CommandResult(
                    type="error",
                    value=f"Undo failed: {result.get('message', 'Unknown error')}",
                )

        except Exception as e:
            logger.error(f"Error handling undo command: {e}")
            return CommandResult(
                type="error",
                value=f"Error handling undo: {e}",
            )
