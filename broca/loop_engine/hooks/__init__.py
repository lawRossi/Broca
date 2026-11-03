"""Loop engine hooks (Phase 3).

Lifecycle hooks: snapshot / communicator / dead-loop / compression-memory /
context-cleanup, plus the default and sub-agent hook builders.  Phase 3 owns
this package.

Hook order in the default set is fixed::

    snapshot → communicator → dead_loop → compression → context_cleanup
"""

from broca.loop_engine.hooks.context_cleanup_hook import ContextCleanupHook
from broca.loop_engine.hooks.lifecycle_broadcast_hook import LifecycleBroadcastHook
from broca.loop_engine.hooks.compression_hook import CompressionMemoryHook
from broca.loop_engine.hooks.dead_loop_hook import DeadLoopHook
from broca.loop_engine.hooks.factory import (
    SUBAGENT_ROLES,
    build_default_hooks,
    build_hooks_for,
    build_subagent_hooks,
    is_subagent_config,
)
from broca.loop_engine.hooks.snapshot_hook import SnapshotHook

__all__ = [
    "ContextCleanupHook",
    "LifecycleBroadcastHook",
    "CompressionMemoryHook",
    "DeadLoopHook",
    "SnapshotHook",
    "SUBAGENT_ROLES",
    "build_default_hooks",
    "build_hooks_for",
    "build_subagent_hooks",
    "is_subagent_config",
]
