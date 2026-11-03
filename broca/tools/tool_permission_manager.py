"""Tool Permission Manager Module (backward-compatible alias).

The original ``ToolPermissionManager`` class has been merged into
``DefaultPermissionProvider`` (``broca.permission_provider``) in Phase 4.2.

This module is kept as a thin compat layer for any remaining imports.
New code should use ``DefaultPermissionProvider`` directly.
"""

from broca.permission_provider import DefaultPermissionProvider

# Backward-compatible alias
ToolPermissionManager = DefaultPermissionProvider

__all__ = ["ToolPermissionManager", "DefaultPermissionProvider"]
