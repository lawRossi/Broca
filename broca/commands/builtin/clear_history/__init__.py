"""
Clear History Command

Clears **all agents'** history in the same session by:
1. Marking ALL messages and turns (across all agents) as reverted=True in database
2. Clearing session memory (shared across agents in the session)
3. Rebuilding context for ALL agents in the session via build_history_from_session
"""

from pathlib import Path
from typing import List, Optional

from broca.commands.base import LocalCommand, CommandContext, CommandResult
from broca.logging_config import get_logger

logger = get_logger(__name__)


class ClearHistoryCommand(LocalCommand):
    """Mark ALL agents' messages/turns in the session as reverted, clear session memory, and rebuild ALL agents' contexts"""

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
            session_id = session_manager.session_id
            if not session_id:
                return CommandResult(
                    type="error",
                    value="No active session to clear history",
                )

            # ================================================================
            # 1. Mark ALL messages in the session (all agents) as reverted
            # ================================================================
            all_messages = await session_manager.message_service.get_messages_by_session(
                session_id, ignore_reverted=False
            )
            msg_ids = [m.message_id for m in all_messages if m.message_id]
            if msg_ids:
                await session_manager.batch_update_messages(msg_ids, reverted=True)

            # ================================================================
            # 2. Mark ALL turns in the session (all agents) as reverted
            # ================================================================
            all_turns = await session_manager.turn_service.get_batch(
                filters={"session_id": session_id}
            )
            turn_ids = [t.turn_id for t in all_turns if t.turn_id]
            if turn_ids:
                await session_manager.batch_update_turns(turn_ids, reverted=True)

            logger.info(
                f"Marked {len(msg_ids)} messages and {len(turn_ids)} turns "
                f"as reverted for session {session_id} (all agents)"
            )

            # ================================================================
            # 3. Clear session memory (shared across agents in the session)
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
            # 4. Rebuild context for ALL agents in the session
            # ================================================================
            # AgentFactory._session_agents[session_id] maps agent_name -> Agent,
            # covering all agents (main, sub, explorer, custom, etc.) in this session.
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
                            "Context rebuilt for agent %s after clear_history",
                            a.agent_id,
                        )
                    except Exception as e:
                        logger.error(
                            "Failed to rebuild context for agent %s: %s",
                            a.agent_id,
                            e,
                        )
            except Exception as e:
                # Fallback: rebuild only the current agent's context
                logger.warning(
                    "Could not get all agents from AgentFactory (%s), "
                    "rebuilding only current agent's context",
                    e,
                )
                await context.build_history_from_session(
                    agent.agent_id, rebuild_system_prompt=True
                )
                rebuilt_agents.append(agent.agent_id)

            # ================================================================
            # 5. Report result
            # ================================================================
            try:
                agents_in_session = (
                    await session_manager.agent_service.get_agents_by_session(
                        session_id
                    )
                )
                agent_names = [
                    a.name or a.agent_id[:8] for a in agents_in_session
                ]
                agents_info = f" ({', '.join(agent_names)})"
            except Exception:
                agents_info = ""

            parts = [
                f"Marked {len(msg_ids)} messages and {len(turn_ids)} turns as reverted"
                f"{agents_info}"
            ]
            if cleared_session_memory:
                parts.append("Session memory cleared")
            parts.append(
                f"Context rebuilt for {len(rebuilt_agents)} agent(s)"
            )

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
