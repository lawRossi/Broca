"""
Tool Permission Manager Module

Manages tool permissions based on configuration files and session-level overrides.

Permission values:
    - "allow": Execute directly without asking the user (default)
    - "ask": Ask the user before each execution
    - "forbidden": Do not execute, return an error

Config file loading order (stop at first found):
    1. {workspace}/.broca/tool_permission_config.json (project-specific, highest priority)
    2. ~/.broca/configs/tool_permission_config.json (global default)
    3. Neither exists → all tools default to "allow"
"""

import json
from pathlib import Path
from typing import Dict, Optional

from broca.logging_config import get_logger
from broca.errors import ValidationError

logger = get_logger(__name__)

VALID_PERMISSIONS = {"allow", "ask", "forbidden"}


class ToolPermissionManager:
    """
    Manages tool permissions with support for:
    - Config file loading (stop at first found: workspace > global)
    - Session-level permission overrides
    - Default fallback to "allow"
    """

    def __init__(self, workspace: Optional[str] = None):
        self._default_permissions: Dict[str, str] = {}
        self._session_overrides: Dict[str, str] = {}

        self._load_config(workspace)

    def _load_config(self, workspace: Optional[str] = None):
        """
        Load tool permission configuration from disk.

        Loading order (stop at first found):
        1. {workspace}/.broca/tool_permission_config.json
        2. ~/.broca/configs/tool_permission_config.json
        3. Neither exists → all tools default to "allow"
        """
        self._default_permissions = {}

        # 1. Workspace config first (highest priority)
        if workspace:
            workspace_config = Path(workspace) / ".broca" / "tool_permission_config.json"
            if workspace_config.exists():
                self._parse_config_file(workspace_config)
                logger.info(f"Loaded tool permissions from workspace config: {workspace_config}")
                return

        # 2. Global config as fallback
        global_config = Path.home() / ".broca" / "configs" / "tool_permission_config.json"
        if global_config.exists():
            self._parse_config_file(global_config)
            logger.info(f"Loaded tool permissions from global config: {global_config}")
            return

        # 3. No config found, all tools default to "allow"
        logger.info("No tool permission config found, all tools default to 'allow'")

    def _parse_config_file(self, config_path: Path):
        """Parse a single config file and load permissions."""
        try:
            with open(config_path, "r") as f:
                data = json.load(f)

            tools = data.get("tools", {})
            for tool_name, permission in tools.items():
                permission_str = str(permission).lower().strip()
                if permission_str in VALID_PERMISSIONS:
                    self._default_permissions[tool_name] = permission_str
                else:
                    logger.warning(
                        f"Invalid permission '{permission}' for tool '{tool_name}' "
                        f"in {config_path}. Valid values: {', '.join(VALID_PERMISSIONS)}"
                    )
        except Exception as e:
            logger.error(f"Failed to load tool permission config from {config_path}: {e}")

    def get_permission(self, tool_name: str) -> str:
        """
        Get the effective permission for a tool.

        Priority (high to low):
        1. Session-level override (set by user for current session)
        2. Configured default permission (from config file)
        3. System default ("allow")

        Args:
            tool_name: Name of the tool to check

        Returns:
            One of "allow", "ask", "forbidden"
        """
        # 1. Session override first
        if tool_name in self._session_overrides:
            return self._session_overrides[tool_name]

        # 2. Configured permission
        return self._default_permissions.get(tool_name, "allow")

    def set_session_override(self, tool_name: str, permission: str):
        """
        Set a session-level permission override.

        This affects only the current session and is cleared when
        clear_session_overrides() or reset() is called.

        Args:
            tool_name: Name of the tool
            permission: One of "allow", "forbidden"
        """
        if permission not in {"allow", "forbidden"}:
            raise ValidationError(
                f"Session override must be 'allow' or 'forbidden', got '{permission}'"
            )
        self._session_overrides[tool_name] = permission
        logger.info(f"Session override set: {tool_name} -> {permission}")

    def remove_session_override(self, tool_name: str):
        """Remove a session-level permission override for a specific tool."""
        self._session_overrides.pop(tool_name, None)

    def clear_session_overrides(self):
        """Clear all session-level permission overrides."""
        self._session_overrides.clear()
        logger.debug("All session-level permission overrides cleared")

    def get_all_permissions(self) -> Dict[str, str]:
        """
        Get all effective permissions (includes session overrides).

        Returns:
            Dict mapping tool names to their effective permissions
        """
        result = dict(self._default_permissions)
        result.update(self._session_overrides)
        return result

    def get_configured_permissions(self) -> Dict[str, str]:
        """Get the configured default permissions (without session overrides)."""
        return dict(self._default_permissions)

    def get_session_overrides(self) -> Dict[str, str]:
        """Get current session-level permission overrides."""
        return dict(self._session_overrides)
