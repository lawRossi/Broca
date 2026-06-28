"""
Clear History Command

Clears all agent messages by:
1. Marking all agent messages as reverted=True in database
2. If it's the main agent (has session_memory_manager), also clears session memory
3. Rebuilds context from scratch via build_history_from_session
"""

from pathlib import Path
from typing import Optional

from broca.commands.base import LocalCommand, CommandContext, CommandResult
from broca.logging_config import get_logger

logger = get_logger(__name__)


class ClearHistoryCommand(LocalCommand):
    """Mark all agent messages as reverted, clear session memory, and rebuild context"""

    async def execute(self, args: str, ctx: CommandContext) -> Optional[CommandResult]:
        if ctx.agent.status == ctx.agent.STATUS_RUNNING:
            return CommandResult(
                type="error",
                value="Agent is currently running, cannot clear history",
            )

        try:
            agent = ctx.agent
            context = ctx.context
            session_manager = agent.session_manager

            # ================================================================
            # 1. Mark all agent messages and turns as reverted in database
            # ================================================================
            messages = await session_manager.get_messages(agent_id=agent.agent_id)
            msg_ids = [m.message_id for m in messages if m.message_id]
            if msg_ids:
                await session_manager.batch_update_messages(msg_ids, reverted=True)

            turns = await session_manager.turn_service.get_batch(
                filters={"agent_id": agent.agent_id}
            )
            turn_ids = [t.turn_id for t in turns if t.turn_id]
            if turn_ids:
                await session_manager.batch_update_turns(turn_ids, reverted=True)

            logger.info(
                f"Marked {len(msg_ids)} messages and {len(turn_ids)} turns "
                f"as reverted for agent {agent.agent_id}"
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
            # 3. Rebuild context (skipping reverted messages)
            # ================================================================
            await context.build_history_from_session(
                agent.agent_id, rebuild_system_prompt=True
            )

            logger.info("Context rebuilt after clear_history command")

            parts = [f"Marked {len(msg_ids)} messages and {len(turn_ids)} turns as reverted"]
            if cleared_session_memory:
                parts.append("Session memory cleared")
            parts.append("Context rebuilt")

            return CommandResult(
                type="text",
                value="; ".join(parts),
            )

        except Exception as e:
            logger.error(f"Error executing clear_history command: {e}")
            return CommandResult(
                type="error",
                value=f"Failed to clear history: {e}",
            )
