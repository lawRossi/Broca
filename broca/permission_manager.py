"""Permission Manager Module (backward-compatible alias).

The original ``PermissionManager`` class has been merged into
``DefaultPermissionProvider`` (``broca.permission_provider``) in Phase 4.2.

This module is kept as a thin compat layer for any remaining imports.
New code should use ``DefaultPermissionProvider`` directly.
"""

from broca.permission_provider import DefaultPermissionProvider

# Backward-compatible alias
PermissionManager = DefaultPermissionProvider

__all__ = ["PermissionManager", "DefaultPermissionProvider"]
