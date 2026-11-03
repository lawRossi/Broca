"""AgentFactory component interface.

Factory for creating and restoring ``Agent`` instances.  The default
implementation is ``DefaultAgentFactory`` (renamed from ``AgentFactory``
in Phase 4, with singleton pattern removed).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Optional

from broca.components.base import BaseComponent

if TYPE_CHECKING:
    from broca.agent import Agent
    from broca.agent_configs import AgentConfig
    from broca.session.session_manager import SessionManager


class AgentFactory(BaseComponent, ABC):
    """Factory interface for creating and restoring agents.

    This is a **singleton** component — it manages the global mapping of
    session agents and is stateless with respect to any single agent.
    """

    @abstractmethod
    async def create_agent(
        self,
        agent_config: Any,
        session_manager: "SessionManager",
        workspace: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> "Agent":
        """Create a new ``Agent`` instance.

        Args:
            agent_config: Agent configuration dict (passed to
                ``AgentConfig.from_config()``).
            session_manager: Session manager for persistence.
            workspace: Optional workspace path override.
            provider: Optional LLM provider override.
            model: Optional LLM model override.
            agent_id: Optional explicit agent ID.

        Returns:
            The created ``Agent`` instance.
        """
        ...

    @abstractmethod
    async def restore_agents_from_session(
        self, session_id: str
    ) -> list["Agent"]:
        """Restore all agents from a session.

        Args:
            session_id: The session to restore from.

        Returns:
            List of restored ``Agent`` instances.
        """
        ...
