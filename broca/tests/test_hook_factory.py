"""Unit tests for the hook factories (Task 3.5).

``build_default_hooks`` → fixed order ``[snapshot, communicator, dead_loop,
compression]``; ``build_subagent_hooks`` → 1~2 hooks, never snapshot/communicator.
Missing dependencies must still produce hooks (no-op semantics), never raise.
"""

from __future__ import annotations

from typing import Any

from broca.loop_engine.hooks import (
    SUBAGENT_ROLES,
    ContextCleanupHook,
    LifecycleBroadcastHook,
    CompressionMemoryHook,
    DeadLoopHook,
    SnapshotHook,
    build_default_hooks,
    build_hooks_for,
    build_subagent_hooks,
    is_subagent_config,
)


class FakeExecConfig:
    def __init__(self, window: Any = 3):
        self.dead_loop_window = window


class FakeConfig:
    def __init__(
        self,
        window: Any = 3,
        enable_compression: bool = True,
        workspace: str = "/tmp/ws",
        role: Any = None,
    ):
        self.execution_config = FakeExecConfig(window)
        self.role = role
        self.enable_context_compression = enable_compression
        self.workspace = workspace
        self.interactive = True


class TestDefaultHooks:
    def test_returns_five_hooks_in_fixed_order(self):
        hooks = build_default_hooks(FakeConfig())

        assert [h.name for h in hooks] == [
            "snapshot",
            "lifecycle_broadcast",
            "dead_loop",
            "compression",
            "context_cleanup",
        ]
        assert isinstance(hooks[0], SnapshotHook)
        assert isinstance(hooks[1], LifecycleBroadcastHook)
        assert isinstance(hooks[2], DeadLoopHook)
        assert isinstance(hooks[3], CompressionMemoryHook)
        assert isinstance(hooks[4], ContextCleanupHook)

    def test_names_are_unique(self):
        hooks = build_default_hooks(FakeConfig())
        assert {h.name for h in hooks} == {
            "snapshot",
            "lifecycle_broadcast",
            "dead_loop",
            "compression",
            "context_cleanup",
        }

    def test_all_dependencies_none_still_creates_five_hooks(self):
        hooks = build_default_hooks(
            FakeConfig(),
            snapshot_manager=None,
            communicator=None,
            context_compressor=None,
            memory_manager=None,
            context=None,
            session_id="",
            compressor_ctx_builder=None,
        )

        assert len(hooks) == 5
        # every hook degrades to a no-op
        assert hooks[0]._enabled is False  # no manager yet (lazy init possible)
        assert hooks[1]._enabled is False  # no communicator
        assert hooks[3]._compression_enabled is False  # no compressor

    def test_dependencies_are_passed_through(self):
        manager = object()
        communicator = object()
        compressor = object()
        memory = object()
        builder = lambda: "cc"

        hooks = build_default_hooks(
            FakeConfig(),
            snapshot_manager=manager,
            communicator=communicator,
            context_compressor=compressor,
            memory_manager=memory,
            context="CTX",
            session_id="sess-1",
            compressor_ctx_builder=builder,
        )

        assert hooks[0]._snapshot_manager is manager
        assert hooks[1]._communicator is communicator
        assert hooks[3]._context_compressor is compressor
        assert hooks[3]._memory_manager is memory
        assert hooks[3]._context == "CTX"
        assert hooks[3]._compressor_ctx_builder is builder
        assert hooks[1]._session_id == "sess-1"

    def test_dead_loop_window_read_from_execution_config(self):
        hooks = build_default_hooks(FakeConfig(window=7))
        assert hooks[2]._window == 7

    def test_invalid_dead_loop_window_falls_back(self):
        for bad in (None, 0, -1, True, "5"):
            hooks = build_default_hooks(FakeConfig(window=bad))
            assert hooks[2]._window == 3

    def test_config_without_execution_config(self):
        class Bare:
            workspace = ""

        hooks = build_default_hooks(Bare())
        assert len(hooks) == 5
        assert hooks[2]._window == 3


class TestSubagentHooks:
    def test_compression_included_when_enabled(self):
        hooks = build_subagent_hooks(FakeConfig(enable_compression=True))

        assert [h.name for h in hooks] == ["dead_loop", "compression"]

    def test_compression_omitted_when_disabled(self):
        hooks = build_subagent_hooks(FakeConfig(enable_compression=False))

        assert [h.name for h in hooks] == ["dead_loop"]

    def test_never_contains_snapshot_or_communicator(self):
        hooks = build_subagent_hooks(FakeConfig(enable_compression=True))

        assert not any(isinstance(h, SnapshotHook) for h in hooks)
        assert not any(isinstance(h, LifecycleBroadcastHook) for h in hooks)

    def test_none_dependencies_do_not_raise(self):
        hooks = build_subagent_hooks(
            FakeConfig(enable_compression=True),
            context_compressor=None,
            memory_manager=None,
            context=None,
            compressor_ctx_builder=None,
        )
        assert len(hooks) == 2
        assert hooks[1]._compression_enabled is False

    def test_window_passed_through(self):
        hooks = build_subagent_hooks(FakeConfig(window=5, enable_compression=False))
        assert hooks[0]._window == 5


class TestBuildHooksFor:
    """Review M1: ``build_subagent_hooks`` used to have no production caller."""

    def test_subagent_roles_get_the_reduced_set(self):
        for role in sorted(SUBAGENT_ROLES):
            hooks = build_hooks_for(FakeConfig(role=role))
            names = [hook.name for hook in hooks]
            assert "snapshot" not in names, role
            assert "lifecycle_broadcast" not in names, role
            assert "dead_loop" in names, role

    def test_main_agent_gets_the_full_set(self):
        hooks = build_hooks_for(FakeConfig(role=None))

        assert [hook.name for hook in hooks] == [
            "snapshot",
            "lifecycle_broadcast",
            "dead_loop",
            "compression",
            "context_cleanup",
        ]

    def test_unknown_role_gets_the_full_set(self):
        hooks = build_hooks_for(FakeConfig(role="coding"))

        assert "snapshot" in [hook.name for hook in hooks]

    def test_is_subagent_config(self):
        assert is_subagent_config(FakeConfig(role="session_memory_manager"))
        assert is_subagent_config(FakeConfig(role="skill_evolution"))
        assert is_subagent_config(FakeConfig(role="persistent_memory_manager"))
        assert not is_subagent_config(FakeConfig(role=None))
        assert not is_subagent_config(FakeConfig(role="coding"))

    def test_missing_role_attribute_is_not_a_subagent(self):
        class Bare:
            pass

        assert not is_subagent_config(Bare())
        assert "snapshot" in [h.name for h in build_hooks_for(Bare())]

    def test_subagent_set_still_gets_compression_when_enabled(self):
        hooks = build_hooks_for(
            FakeConfig(role="skill_evolution", enable_compression=True)
        )

        assert [hook.name for hook in hooks] == ["dead_loop", "compression"]
