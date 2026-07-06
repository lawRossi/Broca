"""
Clear Context Command

Clears the **current agent's** context by:
1. Marking all agent messages as compressed (is_expired=True, is_truncated=True) in database
2. If it's the main agent (has session_memory_manager), also clears session memory
3. Rebuilds context from scratch via build_history_from_session

Use /clear_all_context to clear context for ALL agents in the session.
"""

from pathlib import Path
from typing import Optional

from broca.commands.base import LocalCommand, CommandContext, CommandResult
from broca.logging_config import get_logger

logger = get_logger(__name__)


class ClearContextCommand(LocalCommand):
    """Clear the current agent's context messages, clear session memory, and rebuild context"""

    async def execute(self, args: str, ctx: CommandContext) -> Optional[CommandResult]:
        # Check agent status
        if ctx.agent.status == ctx.agent.STATUS_RUNNING:
            return CommandResult(
                type="error",
                value="Agent is currently running, cannot clear context",
            )

        try:
            agent = ctx.agent
            context = ctx.context
            session_manager = agent.session_manager
            agent_name = agent.config.name or agent.agent_id

            # ================================================================
            # 1. Mark all agent messages as compressed in database
            # ================================================================
            messages = await session_manager.get_messages(agent_id=agent.agent_id)
            all_ids = [m.message_id for m in messages if m.message_id]

            if all_ids:
                await session_manager.batch_update_messages(
                    all_ids, is_expired=True, is_truncated=True
                )

            logger.info(
                f"Marked {len(all_ids)} messages as compressed for agent {agent.agent_id}"
            )

            # ================================================================
            # 2. Clear session memory (if this is the main agent)
            # ================================================================
            cleared_session_memory = False
            if agent.session_memory_manager is not None:
                try:
                    agent.session_memory_manager.reset()

                    from broca.session_memory.memory_prompts import DEFAULT_MEMORY_TEMPLATE

                    snapshot_path = Path(
                        agent.session_memory_manager.snapshot_memory_path
                    )
                    if snapshot_path.exists():
                        snapshot_path.write_text(
                            DEFAULT_MEMORY_TEMPLATE.strip(), encoding="utf-8"
                        )

                    frozen_path = Path(agent.session_memory_manager.memory_path)
                    if frozen_path.exists():
                        frozen_path.write_text(
                            DEFAULT_MEMORY_TEMPLATE.strip(), encoding="utf-8"
                        )

                    cleared_session_memory = True
                    logger.info("Session memory cleared")
                except Exception as e:
                    logger.error(f"Failed to clear session memory: {e}")

            # ================================================================
            # 3. Rebuild context (skipping truncated messages)
            # ================================================================
            await context.build_history_from_session(
                agent.agent_id, rebuild_system_prompt=True
            )

            logger.info(
                "Context rebuilt for agent %s after clear_context", agent_name
            )

            # ================================================================
            # 4. Send frontend notification with clear agent identification
            # ================================================================
            try:
                await agent.communicator.send_agent_system_message(
                    content=f"🧹 Context cleared for agent: **{agent_name}**",
                    subscription=agent.session_id,
                )
            except Exception as e:
                logger.warning(
                    "Failed to send frontend notification for clear_context: %s", e
                )

            # ================================================================
            # 5. Build result
            # ================================================================
            parts = [
                f"Context cleared for agent: {agent_name}",
                f"Marked {len(all_ids)} messages as compressed",
            ]
            if cleared_session_memory:
                parts.append("Session memory cleared")
            parts.append("Context rebuilt")

            return CommandResult(
                type="text",
                value="; ".join(parts),
            )

        except Exception as e:
            logger.error(f"Error executing clear_context command: {e}")
            return CommandResult(
                type="error",
                value=f"Failed to clear context: {e}",
            )
