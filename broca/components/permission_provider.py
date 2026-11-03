"""PermissionProvider component interface.

Merges the responsibilities of ``PermissionManager`` (interactive permission
requests via communicator) and ``ToolPermissionManager`` (config-based tool
permission levels + session overrides).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Optional

from broca.components.base import BaseComponent

if TYPE_CHECKING:
    from broca.components.communicator import Communicator
    from broca.session.session_manager import SessionManager


class PermissionProvider(BaseComponent, ABC):
    """Permission provider interface.

    Combines:
    - Interactive permission requests (``request_permission``,
      ``request_tool_permission``) — from ``PermissionManager``.
    - Tool permission levels (``get_permission``, ``set_session_override``,
      etc.) — from ``ToolPermissionManager``.
    """

    # ------------------------------------------------------------------
    # Interactive permission requests (from PermissionManager)
    # ------------------------------------------------------------------

    @abstractmethod
    async def request_permission(self, message: str) -> bool:
        """Ask for user permission via communication channel (general flow).

        Frontend shows Allow/Deny buttons (request_type="general").

        Args:
            message: Permission request message.

        Returns:
            True if permission is granted, False otherwise.
        """
        ...

    @abstractmethod
    async def request_tool_permission(
        self, tool_name: str, arguments: str | None = None
    ) -> tuple[bool, Optional[str]]:
        """Ask for user permission for tool execution (tool permission flow).

        Frontend shows 4 options: Allow Once / Session Allow / Deny Once /
        Session Deny.

        Args:
            tool_name: Name of the tool requesting permission.
            arguments: Tool arguments (JSON string). Truncated if >500 chars.

        Returns:
            Tuple of ``(granted, session_action)``:
            - ``granted``: True if permission is granted.
            - ``session_action``: ``None`` (once only), ``"allow"`` (session
              allow), or ``"forbid"`` (session forbid).
        """
        ...

    # ------------------------------------------------------------------
    # Tool permission levels (from ToolPermissionManager)
    # ------------------------------------------------------------------

    @abstractmethod
    def get_permission(self, tool_name: str) -> str:
        """Get the effective permission for a tool.

        Priority: session override → configured default → system default
        ("allow").

        Args:
            tool_name: Name of the tool.

        Returns:
            One of ``"allow"``, ``"ask"``, ``"forbidden"``.
        """
        ...

    @abstractmethod
    def set_session_override(self, tool_name: str, permission: str) -> None:
        """Set a session-level permission override.

        Args:
            tool_name: Name of the tool.
            permission: One of ``"allow"``, ``"forbidden"``.
        """
        ...

    @abstractmethod
    def clear_session_overrides(self) -> None:
        """Clear all session-level permission overrides."""
        ...

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def initialize(
        self,
        communicator: "Communicator",
        session_manager: "SessionManager",
        config: Any,
    ) -> None:
        """Inject runtime dependencies.

        Args:
            communicator: For sending permission request/response messages.
            session_manager: For logging permission events.
            config: Agent configuration (workspace, permission_request_timeout,
                etc.).
        """
        ...
