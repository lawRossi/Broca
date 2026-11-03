"""ToolManager ABC — interface for tool discovery and registration.

Manages discovery, loading, and retrieval of tools (builtin, custom, MCP).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional


class ToolManager(ABC):
    """Abstract base class for tool management.

    Implementations discover and manage tool registrations: builtin
    tools, custom workspace tools, and MCP server tools.
    """

    # Read-only tool names (class-level constant, not abstract)
    READONLY_TOOLS: frozenset

    @abstractmethod
    async def init(self, workspace: Optional[str] = None) -> None:
        """Initialize the tool manager (idempotent).

        Scans builtin tools, loads custom tools, and connects MCP servers.
        Must be safe to call multiple times without duplicating connections.
        """
        ...

    @abstractmethod
    def get_tools(
        self, tool_names: Optional[List[str]] = None
    ) -> List[Any]:
        """Get registered tools by name (or all if None)."""
        ...

    @abstractmethod
    async def get_mcp_tools(
        self, server_names: Optional[List[str]] = None
    ) -> List[Any]:
        """Get tools from MCP servers by server name."""
        ...

    @abstractmethod
    async def load_custom_tools(
        self, workspace: Optional[str] = None
    ) -> None:
        """Load custom tools from the workspace."""
        ...
