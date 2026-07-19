"""
Crew Execution API client.

Provides methods for submitting, listing, monitoring, and aborting crew executions.
"""

from typing import Any, Dict, Optional

from broca_tui.api.client import APIClient


class CrewAPI:
    """Crew execution API client."""

    def __init__(self, client: Optional[APIClient] = None):
        """Initialize crew API.

        Args:
            client: APIClient instance. Creates a new one if not provided.
        """
        self._client = client or APIClient()

    async def list_executions(
        self,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List crew executions.

        Args:
            session_id: Optional session ID filter
            status: Optional status filter (pending, running, completed, failed, aborted)

        Returns:
            Dict with 'executions' list and 'total' count.
        """
        params: Dict[str, Any] = {}
        if session_id:
            params["session_id"] = session_id
        if status:
            params["status"] = status
        return await self._client.get("/crews", params=params)

    async def get_execution_detail(self, execution_id: str) -> Dict[str, Any]:
        """Get execution detail by ID."""
        return await self._client.get(f"/crews/{execution_id}")

    async def submit_execution(
        self,
        session_id: str,
        yaml_path: Optional[str] = None,
        yaml_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submit a new crew execution.

        Args:
            session_id: Session ID
            yaml_path: Path to the YAML config file
            yaml_content: Inline YAML content (alternative to yaml_path)

        Returns:
            Created CrewExecution dict.
        """
        data: Dict[str, Any] = {"session_id": session_id}
        if yaml_path:
            data["yaml_path"] = yaml_path
        if yaml_content:
            data["yaml_content"] = yaml_content
        return await self._client.post("/crews", data=data)

    async def abort_execution(self, execution_id: str) -> Dict[str, Any]:
        """Abort a running execution."""
        return await self._client.post(f"/crews/{execution_id}/abort")

    async def delete_execution(self, execution_id: str) -> Dict[str, Any]:
        """Delete an execution record."""
        return await self._client.delete(f"/crews/{execution_id}")

    async def validate_config(
        self,
        yaml_path: Optional[str] = None,
        yaml_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate a crew configuration.

        Returns:
            Dict with 'valid' bool and 'errors' list.
        """
        data: Dict[str, Any] = {}
        if yaml_path:
            data["yaml_path"] = yaml_path
        if yaml_content:
            data["yaml_content"] = yaml_content
        return await self._client.post("/crews/validate", data=data)

    # ==================== Workspace Config Files ====================

    async def list_config_files(self, workspace: str) -> Dict[str, Any]:
        """List crew config files in a workspace.

        Args:
            workspace: Workspace path

        Returns:
            Dict with 'configs' list and 'total' count.
        """
        return await self._client.get(
            "/crews/configs", params={"workspace": workspace}
        )

    async def get_config_detail(
        self, filename: str, workspace: str
    ) -> Dict[str, Any]:
        """Get detail of a config file."""
        import urllib.parse

        encoded_name = urllib.parse.quote(filename, safe="")
        return await self._client.get(
            f"/crews/configs/{encoded_name}", params={"workspace": workspace}
        )

    async def save_config(
        self, filename: str, workspace: str, content: str
    ) -> Dict[str, Any]:
        """Save/update a config file."""
        import urllib.parse

        encoded_name = urllib.parse.quote(filename, safe="")
        return await self._client.put(
            f"/crews/configs/{encoded_name}",
            data={"workspace": workspace, "filename": filename, "content": content},
        )

    async def close(self):
        """Close the underlying HTTP client."""
        await self._client.close()
