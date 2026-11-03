"""Unit tests for ``SnapshotHook`` (Task 3.1).

Covers the migration of the legacy engine's snapshot tracking:
``_initialize_snapshot_tracking`` / ``_acquire_step_lock`` / ``_release_step_lock`` /
``_capture_step_start_snapshot`` / ``_compute_step_end_patch`` /
``_compute_turn_level_diff`` / ``_clear_turn_snapshots``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.components.loop_engine import ExecutionResult, ExecutionStatus
from broca.components.loop_hook import StepContext, TurnContext
from broca.loop_engine.hooks.snapshot_hook import SnapshotHook


class FakeConfig:
    def __init__(self, enable: bool = True, workspace: str = "/tmp/ws"):
        self.enable_snapshot_tracking = enable
        self.workspace = workspace


def make_manager(patch: dict | None = None) -> MagicMock:
    manager = MagicMock()
    manager.acquire_lock = MagicMock()
    manager.release_lock = MagicMock()
    manager.track = AsyncMock(side_effect=["hash-1", "hash-2", "hash-3", "hash-4"])
    manager.calculate_patch = AsyncMock(return_value=patch or {"files": {"a.py": {}}})
    manager.calculate_diff = AsyncMock(return_value="diff")
    manager.get_diff_summary = MagicMock(
        return_value={
            "total_files": 1,
            "files_added": [],
            "files_deleted": [],
            "files_modified": ["a.py"],
        }
    )
    return manager


def make_turn_ctx(result: ExecutionResult | None = None) -> TurnContext:
    return TurnContext(
        turn_id="turn-1",
        agent_id="agent-1",
        session_id="sess-1",
        user_message={"content": "hi"},
        message_id="msg-1",
        result=result,
    )


def make_step_ctx(has_write_ops: bool = True) -> StepContext:
    return StepContext(
        step_id="step-1",
        turn_id="turn-1",
        agent_id="agent-1",
        session_id="sess-1",
        has_write_ops=has_write_ops,
    )


class TestGating:
    @pytest.mark.asyncio
    async def test_disabled_by_config_is_noop(self):
        manager = make_manager()
        hook = SnapshotHook(manager, "/tmp/ws", FakeConfig(enable=False))
        turn_ctx = make_turn_ctx(ExecutionResult(ExecutionStatus.COMPLETED))
        step_ctx = make_step_ctx()

        await hook.on_turn_start(turn_ctx)
        await hook.on_step_start(step_ctx)
        await hook.on_step_end(step_ctx)
        await hook.on_turn_end(turn_ctx)

        assert manager.track.await_count == 0
        assert manager.acquire_lock.call_count == 0
        assert manager.release_lock.call_count == 0
        assert manager.calculate_patch.await_count == 0
        assert manager.calculate_diff.await_count == 0
        assert turn_ctx.result.data["changed_files"] is None
        assert step_ctx.step_start_snapshot == ""
        assert step_ctx.step_patch == {}

    @pytest.mark.asyncio
    async def test_missing_manager_without_workspace_is_noop(self):
        # snapshot_manager=None and no workspace → lazy init impossible → no-op
        hook = SnapshotHook(None, "", FakeConfig(enable=True, workspace=""))
        turn_ctx = make_turn_ctx(ExecutionResult(ExecutionStatus.COMPLETED))
        step_ctx = make_step_ctx()

        await hook.on_turn_start(turn_ctx)
        await hook.on_step_start(step_ctx)
        await hook.on_step_end(step_ctx)
        await hook.on_turn_end(turn_ctx)

        assert hook._snapshot_manager is None
        assert step_ctx.step_start_snapshot == ""
        assert turn_ctx.result.data["changed_files"] is None

    @pytest.mark.asyncio
    async def test_lazy_init_failure_does_not_raise(self, monkeypatch):
        class BoomManager:
            def __init__(self):
                raise RuntimeError("git unavailable")

        monkeypatch.setattr(
            "broca.snapshot.manager.GitSnapshotManager", BoomManager, raising=True
        )
        hook = SnapshotHook(None, "/tmp/ws", FakeConfig(enable=True))
        turn_ctx = make_turn_ctx(ExecutionResult(ExecutionStatus.COMPLETED))

        await hook.on_turn_start(turn_ctx)  # must not raise
        assert hook._snapshot_manager is None

    @pytest.mark.asyncio
    async def test_no_write_ops_skips_step_hooks(self):
        manager = make_manager()
        hook = SnapshotHook(manager, "/tmp/ws", FakeConfig())
        turn_ctx = make_turn_ctx(ExecutionResult(ExecutionStatus.COMPLETED))
        step_ctx = make_step_ctx(has_write_ops=False)

        await hook.on_turn_start(turn_ctx)
        await hook.on_step_start(step_ctx)
        await hook.on_step_end(step_ctx)

        assert manager.track.await_count == 0
        assert manager.acquire_lock.call_count == 0
        assert step_ctx.step_start_snapshot == ""
        assert step_ctx.step_patch == {}


class TestStepSnapshots:
    @pytest.mark.asyncio
    async def test_step_start_and_end_call_sequence(self):
        manager = make_manager()
        hook = SnapshotHook(manager, "/tmp/ws", FakeConfig())
        turn_ctx = make_turn_ctx(ExecutionResult(ExecutionStatus.COMPLETED))
        step_ctx = make_step_ctx()

        await hook.on_turn_start(turn_ctx)
        await hook.on_step_start(step_ctx)

        assert step_ctx.step_start_snapshot == "hash-1"
        assert manager.acquire_lock.call_count == 1
        assert manager.track.await_args_list[0].args == ("/tmp/ws",)

        await hook.on_step_end(step_ctx)

        assert step_ctx.step_end_snapshot == "hash-2"
        assert step_ctx.step_patch["files"] == {"a.py": {}}
        assert step_ctx.step_patch["summary"]["total_files"] == 1
        assert manager.release_lock.call_count == 1

    @pytest.mark.asyncio
    async def test_lock_released_when_patch_computation_raises(self):
        manager = make_manager()
        manager.calculate_patch = AsyncMock(side_effect=RuntimeError("boom"))
        hook = SnapshotHook(manager, "/tmp/ws", FakeConfig())
        turn_ctx = make_turn_ctx(ExecutionResult(ExecutionStatus.COMPLETED))
        step_ctx = make_step_ctx()

        await hook.on_turn_start(turn_ctx)
        await hook.on_step_start(step_ctx)
        await hook.on_step_end(step_ctx)  # must not raise

        assert manager.release_lock.call_count == 1
        assert hook._lock_held is False
        assert step_ctx.step_patch == {}

    @pytest.mark.asyncio
    async def test_empty_patch_drops_patch_but_keeps_hash(self):
        manager = make_manager(patch={"files": {}})
        hook = SnapshotHook(manager, "/tmp/ws", FakeConfig())
        turn_ctx = make_turn_ctx(ExecutionResult(ExecutionStatus.COMPLETED))
        step_ctx = make_step_ctx()

        await hook.on_turn_start(turn_ctx)
        await hook.on_step_start(step_ctx)
        await hook.on_step_end(step_ctx)

        assert step_ctx.step_end_snapshot == "hash-2"
        assert step_ctx.step_patch == {}
        # No real change → turn-level last hash stays unset
        assert hook._turn_last_hash is None


class TestTurnDiff:
    @pytest.mark.asyncio
    async def test_turn_end_writes_changed_files(self):
        manager = make_manager()
        hook = SnapshotHook(manager, "/tmp/ws", FakeConfig())
        turn_ctx = make_turn_ctx(ExecutionResult(ExecutionStatus.COMPLETED))
        step_ctx = make_step_ctx()

        await hook.on_turn_start(turn_ctx)
        await hook.on_step_start(step_ctx)
        await hook.on_step_end(step_ctx)
        await hook.on_turn_end(turn_ctx)

        changed = turn_ctx.result.data["changed_files"]
        assert changed["total_modified"] == 1
        assert changed["files_modified"] == ["a.py"]
        assert changed["first_snapshot_hash"] == "hash-1"
        assert changed["last_snapshot_hash"] == "hash-2"

    @pytest.mark.asyncio
    async def test_turn_end_writes_none_without_changes(self):
        manager = make_manager()
        hook = SnapshotHook(manager, "/tmp/ws", FakeConfig())
        turn_ctx = make_turn_ctx(ExecutionResult(ExecutionStatus.COMPLETED))

        await hook.on_turn_start(turn_ctx)
        await hook.on_turn_end(turn_ctx)

        assert turn_ctx.result.data["changed_files"] is None
        assert manager.calculate_diff.await_count == 0

    @pytest.mark.asyncio
    async def test_abnormal_turn_end_captures_final_snapshot(self):
        manager = make_manager()
        hook = SnapshotHook(manager, "/tmp/ws", FakeConfig())
        turn_ctx = make_turn_ctx(ExecutionResult(ExecutionStatus.ERROR))
        step_ctx = make_step_ctx()

        await hook.on_turn_start(turn_ctx)
        await hook.on_step_start(step_ctx)  # start hash only, no step end
        await hook.on_turn_end(turn_ctx)

        # track called twice: step start + compensating turn-end snapshot
        assert manager.track.await_count == 2
        assert turn_ctx.result.data["changed_files"]["last_snapshot_hash"] == "hash-2"

    @pytest.mark.asyncio
    async def test_turn_end_without_result_uses_ctx_data(self):
        manager = make_manager()
        hook = SnapshotHook(manager, "/tmp/ws", FakeConfig())
        turn_ctx = make_turn_ctx(result=None)

        await hook.on_turn_start(turn_ctx)
        await hook.on_turn_end(turn_ctx)

        assert turn_ctx.data["changed_files"] is None


class TestReset:
    @pytest.mark.asyncio
    async def test_reset_clears_state_between_turns(self):
        manager = make_manager()
        hook = SnapshotHook(manager, "/tmp/ws", FakeConfig())

        turn_ctx_1 = make_turn_ctx(ExecutionResult(ExecutionStatus.COMPLETED))
        await hook.on_turn_start(turn_ctx_1)
        await hook.on_step_start(make_step_ctx())
        assert hook._turn_first_hash == "hash-1"

        hook.reset()
        assert hook._turn_first_hash is None
        assert hook._turn_last_hash is None
        assert hook._step_start_hash is None
        assert hook._lock_held is False

        # Second turn must start from a fresh first-hash (hash-2 now).
        turn_ctx_2 = make_turn_ctx(ExecutionResult(ExecutionStatus.COMPLETED))
        await hook.on_turn_start(turn_ctx_2)
        await hook.on_step_start(make_step_ctx())
        assert hook._turn_first_hash == "hash-2"

    @pytest.mark.asyncio
    async def test_reset_releases_held_lock(self):
        manager = make_manager()
        hook = SnapshotHook(manager, "/tmp/ws", FakeConfig())

        await hook.on_turn_start(make_turn_ctx(ExecutionResult(ExecutionStatus.COMPLETED)))
        await hook.on_step_start(make_step_ctx())
        assert hook._lock_held is True

        hook.reset()
        assert manager.release_lock.call_count == 1
        assert hook._lock_held is False


class TestHookContract:
    def test_name_is_unique_and_instantiable(self):
        hook = SnapshotHook(None, "", FakeConfig())
        assert hook.name == "snapshot"
        assert hook._enabled is False
