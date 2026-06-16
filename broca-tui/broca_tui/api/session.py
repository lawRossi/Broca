"""
Session API client.

Provides methods for Session CRUD, Runner control, and message history.
"""

from typing import Any, Dict, List, Optional

from broca_tui.api.client import APIClient


class SessionAPI:
    """Session API client."""

    def __init__(self, client: Optional[APIClient] = None):
        """Initialize session API.

        Args:
            client: APIClient instance. Creates a new one if not provided.
        """
        self._client = client or APIClient()

    async def list_sessions(
        self,
        skip: int = 0,
        limit: int = 10,
        keyword: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get list of sessions.

        Returns:
            Dict with 'sessions' list and 'total' count.
        """
        params: Dict[str, Any] = {"skip": skip, "limit": limit}
        if keyword:
            params["keyword"] = keyword
        return await self._client.get("/session/sessions", params=params)

    async def get_session(self, session_id: str) -> Dict[str, Any]:
        """Get session details."""
        return await self._client.get(f"/session/{session_id}")

    async def create_session(
        self,
        description: Optional[str] = None,
        workspace: Optional[str] = None,
        category: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new session.

        Args:
            description: Optional session name/description
            workspace: Optional workspace path. If None, backend creates a temp dir.
            category: Session category ('normal' or 'agent-orchestration')
            provider: Optional LLM provider (e.g. 'openrouter', 'deepseek').
                      If None, backend uses default.
            model: Optional LLM model (e.g. 'stepfun', 'nemotron').
                   If None, backend uses default.

        Returns:
            Dict with session_id, workspace, agent_id, etc.
        """
        data: Dict[str, Any] = {}
        if description:
            data["description"] = description
        if workspace:
            data["workspace"] = workspace
        if category:
            data["category"] = category
        if provider:
            data["provider"] = provider
        if model:
            data["model"] = model
        return await self._client.post("/session/sessions", data=data)

    async def update_session(
        self, session_id: str, description: Optional[str] = None
    ) -> None:
        """Update session info."""
        data: Dict[str, Any] = {}
        if description is not None:
            data["description"] = description
        await self._client.put(f"/session/{session_id}", data=data)

    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        await self._client.delete(f"/session/{session_id}")

    async def get_session_agents(self, session_id: str) -> List[Dict[str, Any]]:
        """Get agents for a session."""
        return await self._client.get(f"/session/{session_id}/agents")

    async def get_session_messages(
        self,
        session_id: str,
        skip: int = 0,
        limit: int = 50,
        execution_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get message history for a session.

        Args:
            session_id: Session ID
            skip: Number of messages to skip
            limit: Max messages to return
            execution_id: Optional execution ID filter

        Returns:
            Dict with 'messages' list and 'total' count.
        """
        params: Dict[str, Any] = {"skip": skip, "limit": limit}
        if execution_id:
            params["execution_id"] = execution_id
        return await self._client.get(
            f"/session/{session_id}/messages", params=params
        )

    async def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """Get session statistics."""
        return await self._client.get(f"/session/{session_id}/stats")

    async def get_agent_config(self, session_id: str, agent_id: str) -> Dict[str, Any]:
        """Get agent configuration.

        Args:
            session_id: Session ID
            agent_id: Agent ID

        Returns:
            Dict with config_content, config_name, etc.
        """
        return await self._client.get(f"/session/{session_id}/agents/{agent_id}/config")

    async def update_agent_config(self, session_id: str, agent_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Update agent configuration.

        Args:
            session_id: Session ID
            agent_id: Agent ID
            config: Dict with provider, model, config_content (JSON string), etc.

        Returns:
            Dict with config_id, config_name, etc.
        """
        return await self._client.put(f"/session/{session_id}/agents/{agent_id}/config", data=config)

    async def get_session_turns(
        self,
        session_id: str,
        skip: int = 0,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """获取会话的 turn 摘要列表（简洁模式使用）。

        Args:
            session_id: Session ID
            skip: Number of turns to skip
            limit: Max turns to return

        Returns:
            Dict with 'turns' list and 'total' count.
        """
        params: Dict[str, Any] = {"skip": skip, "limit": limit}
        return await self._client.get(
            f"/session/{session_id}/turns", params=params
        )

    # ==================== Runner Management ====================

    async def get_runner_status(self, session_id: str) -> Dict[str, Any]:
        """Get Runner process status."""
        return await self._client.get(f"/session/{session_id}/runner/status")

    async def restart_runner(self, session_id: str) -> Dict[str, Any]:
        """Restart Runner process."""
        return await self._client.post(f"/session/{session_id}/runner/restart")

    async def stop_runner(self, session_id: str) -> None:
        """Stop Runner process."""
        await self._client.post(f"/session/{session_id}/runner/stop")

    # ==================== Config API ====================

    async def get_llm_providers(self) -> List[Dict[str, str]]:
        """Get available LLM providers."""
        return await self._client.get("/config/llm/providers")

    async def get_llm_models(self, provider: str) -> List[Dict[str, str]]:
        """Get available models for a provider."""
        return await self._client.get(f"/config/llm/models/{provider}")

    async def get_commands(self) -> List[Dict[str, str]]:
        """Get available commands from API.

        Returns:
            List of command dicts with 'name', 'description', 'type' keys.
            Each command: {"name": str, "description": str, "type": str}
        """
        try:
            response = await self._client.get("/commands")
            if isinstance(response, dict) and "commands" in response:
                return response["commands"]
            return []
        except Exception:
            return []

    async def close(self):
        """Close the underlying HTTP client."""
        await self._client.close()
