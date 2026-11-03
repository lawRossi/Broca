"""
Compact Command

Manually triggers context compression for the current agent:
- Attempt session memory truncation (if session memory is available and aligned)

Unlike the automatic compression (which waits for token thresholds), /compact forces
compression regardless of current token count. This is useful when:
- The user feels the context is becoming too large
- Before switching to a different task to keep context focused
"""

from typing import Optional

from broca.commands.base import CommandContext, CommandResult, LocalCommand
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
            # Perform forced context compression via shared compressor
            # ================================================================
            compressor = getattr(agent, "context_compressor", None)
            if compressor is None:
                # Fallback: get from registry (non-interactive scenario)
                from broca.components import ContextCompressor
                from broca.components.registry import ComponentRegistry

                registry = ComponentRegistry.get_instance()
                compressor = registry.get(ContextCompressor, scope_key=agent.agent_id)
                await compressor.initialize(
                    agent_ref=agent,
                    session_manager=execution_engine.session_manager,
                    config=agent.config,
                )

            from broca.components.compressor_context_factory import build_compressor_context

            cc_ctx = build_compressor_context(
                agent_ref=agent,
                config=agent.config,
                communicator=agent.communicator,
                session_manager=execution_engine.session_manager,
                agent_id=agent.agent_id,
                session_id=execution_engine.session_id,
            )
            stats = await compressor.check_and_compress(
                context=context,
                compressor_context=cc_ctx,
                force=True,
            )

            # ================================================================
            # Build result message
            # ================================================================
            parts = [f"Context compression completed for agent: **{agent_name}**"]

            if stats.truncated_count > 0:
                parts.append(
                    f"✅ Session memory truncation completed, "
                    f"**{stats.truncated_count}** message(s) truncated"
                )
            else:
                parts.append(
                    "ℹ️ Session memory truncation not applicable "
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
                f"Compact command: truncated={stats.truncated_count} "
                f"for agent {agent.agent_id}"
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
