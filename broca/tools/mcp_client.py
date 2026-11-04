"""StdMCPClient — default MCPClient implementation.

Wraps the existing ``connect_mcp_servers()`` function and
``AsyncExitStack`` for connection management.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from broca.components.mcp_client import MCPClient
from broca.tools.mcp import connect_mcp_servers
from broca.tools.tool import Tool
from broca.logging_config import get_logger

logger = get_logger(__name__)


class StdMCPClient(MCPClient):
    """Standard MCP client using the built-in ``connect_mcp_servers``.

    Manages an ``AsyncExitStack`` for MCP server connections.
    """

    def __init__(self):
        self._stack = AsyncExitStack()
        self._connected = False
        self._tools_by_server: Dict[str, List[Tool]] = {}

    async def connect(self, servers: List[Dict[str, Any]]) -> None:
        """Connect to MCP servers (idempotent)."""
        if self._connected:
            return
        self._connected = True
        tools = await connect_mcp_servers(servers, self._stack)
        self._tools_by_server = {}
        for tool in tools:
            server = getattr(tool, "server_name", "unknown")
            if server not in self._tools_by_server:
                self._tools_by_server[server] = []
            self._tools_by_server[server].append(tool)

    async def get_tools(
        self, server_names: Optional[List[str]] = None
    ) -> List[Tool]:
        """Get tools from connected MCP servers."""
        if not self._connected:
            return []
        if server_names is None:
            return [t for tools in self._tools_by_server.values() for t in tools]
        return [
            t
            for name in server_names
            for t in self._tools_by_server.get(name, [])
        ]

    async def disconnect(self) -> None:
        """Disconnect all MCP servers and release resources."""
        if not self._connected:
            return
        self._connected = False
        self._tools_by_server.clear()
        await self._stack.aclose()
