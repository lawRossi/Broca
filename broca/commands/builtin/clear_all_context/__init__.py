"""
Clear All Context Command

Clears **all agents'** context in the same session by:
1. Marking ALL messages (across all agents) as compressed (is_expired=True, is_truncated=True)
2. Clearing session memory (shared across agents in the session)
3. Rebuilding context for ALL agents via build_history_from_session

Use /clear_context to clear context for a single agent.
"""

from pathlib import Path
from typing import List, Optional

from broca.commands.base import CommandContext, CommandResult, LocalCommand
from broca.logging_config import get_logger

logger = get_logger(__name__)


class ClearAllContextCommand(LocalCommand):
    """Clear ALL agents' context messages, clear session memory, and rebuild ALL agents' contexts"""

    async def execute(self, args: str, ctx: CommandContext) -> Optional[CommandResult]:
        if ctx.agent.status == ctx.agent.STATUS_RUNNING:
            return CommandResult(
                type="error",
                value="Agent is currently running, cannot clear all context",
            )

        try:
            agent = ctx.agent
            session_manager = agent.session_manager
            session_id = session_manager.session_id
            if not session_id:
                return CommandResult(
                    type="error",
                    value="No active session to clear all context",
                )

            # ================================================================
            # 1. Mark ALL messages in the session (all agents) as compressed
            # ================================================================
            all_messages = (
                await session_manager.message_service.get_messages_by_session(
                    session_id, ignore_reverted=False
                )
            )
            all_ids = [m.message_id for m in all_messages if m.message_id]
            if all_ids:
                await session_manager.batch_update_messages(
                    all_ids, is_expired=True, is_truncated=True
                )

            logger.info(
                f"Marked {len(all_ids)} messages as compressed for session "
                f"{session_id} (all agents)"
            )

            # ================================================================
            # 2. Clear session memory (shared across agents in the session)
            # ================================================================
            cleared_session_memory = False
            if agent.session_memory_manager is not None:
                try:
                    agent.session_memory_manager.reset()

                    from broca.session_memory.memory_prompts import (
                        DEFAULT_MEMORY_TEMPLATE,
                    )

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
            # 3. Rebuild context for ALL agents in the session
            # ================================================================
            rebuilt_agents: List[str] = []
            try:
                from broca.agent_manager import AgentFactory

                factory = AgentFactory()
                session_agents_map = factory._session_agents.get(session_id, {})
                all_agents = list(session_agents_map.values())

                for a in all_agents:
                    try:
                        await a.context.build_history_from_session(
                            a.agent_id, rebuild_system_prompt=True
                        )
                        rebuilt_agents.append(a.agent_id)
                        logger.info(
                            f"Context rebuilt for agent {a.agent_id} after clear_all_context"
                        )
                    except Exception as e:
                        logger.error(
                            "Failed to rebuild context for agent %s: %s",
                            a.agent_id,
                            e,
                        )
            except Exception as e:
                # Fallback: rebuild only the current agent's context
                logger.error(
                    "Could not get all agents from AgentFactory (%s), "
                    "rebuilding only current agent's context",
                    e,
                )

            # ================================================================
            # 4. Send frontend notification with clear agent identification
            # ================================================================
            try:
                await agent.communicator.send_agent_system_message(
                    content="🧹 Context cleared for all agents",
                    subscription=agent.session_id,
                )
            except Exception as e:
                logger.warning(
                    "Failed to send frontend notification for clear_all_context: %s",
                    e,
                )

            # ================================================================
            # 5. Build result
            # ================================================================
            parts = [
                "Context cleared for all agents",
                f"Marked {len(all_ids)} messages as compressed",
            ]
            if cleared_session_memory:
                parts.append("Session memory cleared")
            parts.append(f"Context rebuilt for {len(rebuilt_agents)} agent(s)")

            return CommandResult(
                type="text",
                value="; ".join(parts),
            )

        except Exception as e:
            logger.error(f"Error executing clear_all_context command: {e}")
            return CommandResult(
                type="error",
                value=f"Failed to clear all context: {e}",
            )
