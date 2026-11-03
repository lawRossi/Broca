"""MCPClient ABC — interface for MCP (Model Context Protocol) client.

Manages connections to MCP servers and retrieval of tools from them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class MCPClient(ABC):
    """Abstract base class for MCP protocol client.

    Implementations manage connections to MCP servers and provide
    access to tools exposed by those servers.
    """

    @abstractmethod
    async def connect(self, servers: List[Dict[str, Any]]) -> None:
        """Connect to the given MCP servers.

        Args:
            servers: List of server config dicts with keys like
                     'name', 'command', 'args', 'env', etc.
        """
        ...

    @abstractmethod
    async def get_tools(
        self, server_names: Optional[List[str]] = None
    ) -> List[Any]:
        """Get tools from connected MCP servers.

        Args:
            server_names: If provided, only return tools from these servers.

        Returns:
            List of Tool instances from MCP servers.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect all MCP server connections and release resources."""
        ...
