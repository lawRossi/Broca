"""Hook factories — the single entry point for building hook sets.

Two sets are defined:

* :func:`build_default_hooks` — main agent: snapshot → communicator → dead-loop
  → compression (order is fixed; snapshot must precede communicator because
  ``LifecycleBroadcastHook`` broadcasts the patch ``SnapshotHook`` computed).
* :func:`build_subagent_hooks` — sub agents: no snapshot, no communicator.

**``None`` semantics**: a missing dependency does *not* drop the hook — the
hook is still created and degrades to a no-op (each hook owns its own
``_enabled`` gate).  Only ``build_subagent_hooks`` conditionally omits the
compression hook, because that set is defined by configuration, not by a
missing dependency.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from broca.components.loop_hook import LoopHook
from broca.loop_engine.hooks.context_cleanup_hook import ContextCleanupHook
from broca.loop_engine.hooks.lifecycle_broadcast_hook import LifecycleBroadcastHook
from broca.loop_engine.hooks.compression_hook import CompressionMemoryHook
from broca.loop_engine.hooks.dead_loop_hook import (
    DEFAULT_DEAD_LOOP_WINDOW,
    DeadLoopHook,
)
from broca.loop_engine.hooks.snapshot_hook import SnapshotHook

#: ``AgentConfig.role`` values used by the internal sub agents (session-memory
#: extraction / skill evolution / persistent-memory extraction).  They run in
#: the background on the user's workspace, so they must neither take file
#: snapshots nor broadcast to the front end.
SUBAGENT_ROLES = frozenset(
    {"session_memory_manager", "skill_evolution", "persistent_memory_manager"}
)


def _resolve_dead_loop_window(config: Any) -> int:
    """``config.execution_config.dead_loop_window`` with a safe fallback."""
    exec_cfg = getattr(config, "execution_config", None)
    window = getattr(exec_cfg, "dead_loop_window", DEFAULT_DEAD_LOOP_WINDOW)
    if isinstance(window, int) and not isinstance(window, bool) and window > 0:
        return window
    return DEFAULT_DEAD_LOOP_WINDOW


def build_default_hooks(
    config: Any,
    *,
    snapshot_manager: Optional[Any] = None,
    communicator: Optional[Any] = None,
    context_compressor: Optional[Any] = None,
    memory_manager: Optional[Any] = None,
    context: Optional[Any] = None,
    session_id: str = "",
    compressor_ctx_builder: Optional[Callable[[], Any]] = None,
    tool_executor: Optional[Any] = None,
) -> list[LoopHook]:
    """Full hook set for the main agent.

    Order is fixed: ``snapshot → communicator → dead_loop → compression →
    context_cleanup``.  (DeadLoop only acts in ``on_step_end`` and
    Compression only in ``on_post_step``, so their relative order is
    irrelevant; snapshot must come first because
    ``LifecycleBroadcastHook`` reads the patch it writes.)
    """
    return [
        SnapshotHook(
            snapshot_manager,
            getattr(config, "workspace", "") or "",
            config,
            tool_executor=tool_executor,
        ),
        LifecycleBroadcastHook(communicator, config, session_id),
        DeadLoopHook(window=_resolve_dead_loop_window(config)),
        CompressionMemoryHook(
            context_compressor,
            memory_manager,
            config,
            context,
            compressor_ctx_builder,
        ),
        ContextCleanupHook(context),
    ]


def build_subagent_hooks(
    config: Any,
    *,
    context_compressor: Optional[Any] = None,
    memory_manager: Optional[Any] = None,
    context: Optional[Any] = None,
    compressor_ctx_builder: Optional[Callable[[], Any]] = None,
) -> list[LoopHook]:
    """Reduced hook set for sub agents: no snapshot, no communicator."""
    hooks: list[LoopHook] = [DeadLoopHook(window=_resolve_dead_loop_window(config))]
    if getattr(config, "enable_context_compression", False):
        hooks.append(
            CompressionMemoryHook(
                context_compressor,
                memory_manager,
                config,
                context,
                compressor_ctx_builder,
            )
        )
    return hooks


def is_subagent_config(config: Any) -> bool:
    """True when ``config`` describes one of the internal sub agents."""
    return getattr(config, "role", None) in SUBAGENT_ROLES


def build_hooks_for(
    config: Any,
    *,
    snapshot_manager: Optional[Any] = None,
    communicator: Optional[Any] = None,
    context_compressor: Optional[Any] = None,
    memory_manager: Optional[Any] = None,
    context: Optional[Any] = None,
    session_id: str = "",
    compressor_ctx_builder: Optional[Callable[[], Any]] = None,
    tool_executor: Optional[Any] = None,
) -> list[LoopHook]:
    """Pick the hook set that matches the agent's role.

    Main agents get :func:`build_default_hooks`; internal sub agents (see
    :data:`SUBAGENT_ROLES`) get :func:`build_subagent_hooks`, i.e. no snapshot
    and no communicator hook.  This is the single wiring point used by
    ``Agent.create()`` (review M1 — the reduced factory used to have no
    production caller at all).
    """
    if is_subagent_config(config):
        return build_subagent_hooks(
            config,
            context_compressor=context_compressor,
            memory_manager=memory_manager,
            context=context,
            compressor_ctx_builder=compressor_ctx_builder,
        )
    return build_default_hooks(
        config,
        snapshot_manager=snapshot_manager,
        communicator=communicator,
        context_compressor=context_compressor,
        memory_manager=memory_manager,
        context=context,
        session_id=session_id,
        compressor_ctx_builder=compressor_ctx_builder,
        tool_executor=tool_executor,
    )
