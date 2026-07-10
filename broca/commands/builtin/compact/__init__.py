"""
Compact Command

Manually triggers context compression for the current agent:
1. Strategy A: Clean up stale tool call results (expired tool results)
2. Strategy B: Attempt session memory truncation (if session memory is available and aligned)

Unlike the automatic compression (which waits for token thresholds), /compact forces
compression regardless of current token count. This is useful when:
- The user feels the context is becoming too large
- After a long conversation where many tool results are no longer relevant
- Before switching to a different task to keep context focused
"""

from typing import Optional

from broca.commands.base import LocalCommand, CommandContext, CommandResult
from broca.context_compressor import ContextCompressor
from broca.logging_config import get_logger

logger = get_logger(__name__)


class CompactCommand(LocalCommand):
    """Manually trigger context compression for the current agent"""

    async def execute(self, args: str, ctx: CommandContext) -> Optional[CommandResult]:
        # Check agent status
        if ctx.agent.status == ctx.agent.STATUS_RUNNING:
            return CommandResult(
                type="error",
                value="Agent is currently running, cannot compact context",
            )

        try:
            agent = ctx.agent
            context = ctx.context
            agent_name = agent.config.name or agent.agent_id

            # Get the execution engine from the agent
            execution_engine = getattr(agent, "execution_engine", None)
            if execution_engine is None:
                return CommandResult(
                    type="error",
                    value="Could not find execution engine for agent. "
                    "Compression requires access to the database session manager.",
                )

            # ================================================================
            # Perform forced context compression
            # ================================================================
            compressor = ContextCompressor()
            stats = await compressor.check_and_compress(
                context=context,
                execution_engine=execution_engine,
                agent=agent,
                force=True,
            )

            # ================================================================
            # Build result message
            # ================================================================
            parts = [f"Context compression completed for agent: **{agent_name}**"]

            if stats.expired_count > 0:
                parts.append(
                    f"✅ Strategy A: Marked **{stats.expired_count}** stale "
                    "tool result(s) as expired"
                )
            else:
                parts.append("ℹ️ Strategy A: No stale tool results to clean up")

            if stats.truncated_count > 0:
                parts.append(
                    f"✅ Strategy B: Session memory truncation completed, "
                    f"**{stats.truncated_count}** message(s) truncated"
                )
            else:
                parts.append(
                    "ℹ️ Strategy B: Session memory truncation not applicable "
                    "(session memory unavailable, empty, or index misaligned)"
                )

            result_text = "\n".join(parts)

            # ================================================================
            # Send frontend notification
            # ================================================================
            try:
                await agent.communicator.send_agent_system_message(
                    content=result_text,
                    subscription=agent.session_id,
                )
            except Exception as e:
                logger.warning(
                    "Failed to send frontend notification for compact: %s", e
                )

            logger.info(
                f"Compact command: expired={stats.expired_count}, "
                f"truncated={stats.truncated_count} for agent {agent.agent_id}"
            )

            return CommandResult(
                type="text",
                value=result_text,
            )

        except Exception as e:
            logger.error(f"Error executing compact command: {e}")
            return CommandResult(
                type="error",
                value=f"Failed to compact context: {e}",
            )
