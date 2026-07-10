"""
Remember Command

Manually triggers persistent memory extraction for the current agent.
Analyzes the recent conversation and saves important information
(user preferences, feedback, project context, external references)
to persistent memory files.

Usage: /remember [hint]
  - hint (optional): specific focus guidance for the extraction agent
  - Example: /remember User prefers dark theme
"""

from typing import Optional

from broca.commands.base import LocalCommand, CommandContext, CommandResult
from broca.logging_config import get_logger

logger = get_logger(__name__)


class RememberCommand(LocalCommand):
    """Manually trigger persistent memory extraction"""

    async def execute(self, args: str, ctx: CommandContext) -> Optional[CommandResult]:
        # Check agent status
        if ctx.agent.status == ctx.agent.STATUS_RUNNING:
            return CommandResult(
                type="error",
                value="Agent is currently running, cannot trigger memory extraction",
            )

        try:
            agent = ctx.agent
            context = ctx.context

            # Get PersistentMemoryManager
            manager = getattr(agent, "persistent_memory_manager", None)
            if manager is None:
                return CommandResult(
                    type="error",
                    value="Persistent memory manager is not available. "
                    "Please enable persistent_memory_config in agent config.",
                )

            # Parse hint from args
            hint = args.strip() or None

            # Trigger extraction (non-blocking via create_task)
            import asyncio

            asyncio.create_task(
                manager.trigger_extraction(context=context, hint=hint)
            )

            msg = "🧠 Persistent memory extraction triggered"
            if hint:
                msg += f" (hint: {hint})"
            msg += "..."

            # Send notification to frontend
            try:
                await agent.communicator.send_agent_system_message(
                    content=msg,
                    subscription=agent.session_id,
                )
            except Exception as e:
                logger.warning(
                    "Failed to send frontend notification for remember: %s", e
                )

            logger.info(
                f"Remember command triggered for agent {agent.agent_id}, hint={hint}"
            )

            return CommandResult(
                type="text",
                value=msg,
            )

        except Exception as e:
            logger.error(f"Error executing remember command: {e}")
            return CommandResult(
                type="error",
                value=f"Failed to trigger memory extraction: {e}",
            )
