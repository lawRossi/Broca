"""
Agent state management.

Manages agent list, status, visibility filtering, and selection state.
Each chat page creates its own AgentStore instance.
"""

from typing import Any, Callable, Dict, List, Optional

from broca_tui.api.session import SessionAPI


class AgentStore:
    """Store for agent state."""

    def __init__(self, api: Optional[SessionAPI] = None):
        """Initialize agent store.

        Args:
            api: SessionAPI instance. Creates a new one if not provided.
        """
        self._api = api or SessionAPI()

        # State
        self.agents: List[Dict[str, Any]] = []
        self.current_agent_id: Optional[str] = None
        self.visible_agent_ids: List[str] = []
        self.loading: bool = False
        self._current_session_id: str = ""

        # Session-level visibility persistence (matching Web's _visibleAgentIdsMap)
        self._visible_agent_ids_map: Dict[str, List[str]] = {}

        # Callbacks
        self._on_change: Optional[Callable[[], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._on_visibility_change: Optional[Callable[[], None]] = None

    def on_change(self, callback: Callable[[], None]):
        """Register callback for state changes."""
        self._on_change = callback

    def on_error(self, callback: Callable[[str], None]):
        """Register callback for errors."""
        self._on_error = callback

    def on_visibility_change(self, callback: Callable[[], None]):
        """Register callback for visibility changes."""
        self._on_visibility_change = callback

    def _notify_change(self):
        """Notify UI of state change."""
        if self._on_change:
            self._on_change()

    def _notify_visibility_change(self):
        """Notify UI of visibility state change."""
        if self._on_visibility_change:
            self._on_visibility_change()

    def _notify_error(self, message: str):
        """Notify UI of error."""
        if self._on_error:
            self._on_error(message)

    def set_visible_agent_ids(self, ids: List[str]):
        """Set visible agent IDs and notify both change and visibility listeners.

        Args:
            ids: List of visible agent IDs
        """
        self.visible_agent_ids = ids
        self._save_visibility_state()
        self._notify_change()
        self._notify_visibility_change()

    def _save_visibility_state(self):
        """Save current visibility state for the active session (Web: _visibleAgentIdsMap)."""
        if self._current_session_id:
            self._visible_agent_ids_map[self._current_session_id] = list(self.visible_agent_ids)

    def _restore_visibility_state(self, session_id: str) -> bool:
        """Restore visibility state for a session (Web: _visibleAgentIdsMap).

        Args:
            session_id: Session ID to restore

        Returns:
            True if state was restored, False if no saved state
        """
        if session_id in self._visible_agent_ids_map:
            self.visible_agent_ids = list(self._visible_agent_ids_map[session_id])
            return True
        return False

    async def fetch_agents(self, session_id: str):
        """Fetch agents for a session.

        Args:
            session_id: Session ID
        """
        if self.loading:
            return

        self.loading = True
        self._current_session_id = session_id
        self._notify_change()

        try:
            agents = await self._api.get_session_agents(session_id)
            self.agents = agents

            # Try to restore visibility from saved state first
            if not self._restore_visibility_state(session_id):
                # No saved state: set all agents visible by default
                self.visible_agent_ids = [a.get("agent_id") for a in agents if a.get("agent_id")]

            # Set first agent as current
            if agents and not self.current_agent_id:
                self.current_agent_id = agents[0].get("agent_id")
        except Exception as e:
            self._notify_error(f"加载Agent列表失败: {e}")
        finally:
            self.loading = False
            self._notify_change()

    def update_agent_status(self, agent_id: str, status: str):
        """Update an agent's status.

        Args:
            agent_id: Agent ID
            status: New status (idle, running, disconnected, etc.)
        """
        for agent in self.agents:
            if agent.get("agent_id") == agent_id:
                agent["agent_status"] = status
                self._notify_change()
                return

    def set_current_agent(self, agent_id: str):
        """Set the current target agent."""
        self.current_agent_id = agent_id
        self._notify_change()

    def toggle_agent_visibility(self, agent_id: str):
        """Toggle visibility of an agent.

        Args:
            agent_id: Agent ID to toggle
        """
        if agent_id in self.visible_agent_ids:
            self.visible_agent_ids.remove(agent_id)
        else:
            self.visible_agent_ids.append(agent_id)
        self._notify_change()

    def set_all_visible(self, visible: bool = True):
        """Set all agents visible or invisible."""
        if visible:
            self.visible_agent_ids = [
                a.get("agent_id") for a in self.agents if a.get("agent_id")
            ]
        else:
            self.visible_agent_ids = []
        self._notify_change()

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get agent by ID."""
        for a in self.agents:
            if a.get("agent_id") == agent_id:
                return a
        return None

    def get_agent_name(self, agent_id: str) -> str:
        """Get agent display name."""
        agent = self.get_agent(agent_id)
        return agent.get("name") or agent.get("agent_id", "Unknown") if agent else agent_id

    @property
    def current_agent(self) -> Optional[Dict[str, Any]]:
        """Get current agent."""
        return self.get_agent(self.current_agent_id) if self.current_agent_id else None

    # Regex pattern for @mention matching (supports mid-line positions)
    _MENTION_PATTERN = r"@(\S+)"

    def parse_mention(self, text: str):
        """Parse @mention from text.

        Supports @mention at any position in the text (not just line start).

        Args:
            text: Input text

        Returns:
            Dict with 'targetAgentId' and 'cleanText'.
        """
        import re

        match = re.search(self._MENTION_PATTERN, text)
        if match:
            mention = match.group(1)
            # Remove the @mention from the text (include trailing whitespace)
            clean_text = re.sub(r"@\S+\s*", "", text, count=1).strip()

            # Find agent by name or ID
            for agent in self.agents:
                agent_name = agent.get("name", "")
                agent_id = agent.get("agent_id", "")
                if mention == agent_name or mention == agent_id:
                    return {"targetAgentId": agent_id, "cleanText": clean_text}

        return {"targetAgentId": None, "cleanText": text}

    def clear_cache(self):
        """Clear all cached data."""
        self.agents = []
        self.current_agent_id = None
        self.visible_agent_ids = []
        self._notify_change()

    async def close(self):
        """Close the underlying API client."""
        await self._api.close()
