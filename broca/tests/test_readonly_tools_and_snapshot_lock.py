"""Regression tests: read-only tool classification + non-blocking snapshot lock.

Background (bug): ``load_skill`` was not listed in ``READONLY_TOOLS``, so a step
containing only a ``load_skill`` call was treated as a write step.  The
``SnapshotHook`` then captured a full git snapshot of the workspace — and it
acquired the cross-process ``.snapshot.lock`` with a **blocking** ``flock``
executed directly on the event loop.  Whenever another session/sub-agent was
snapshotting the same workspace, the whole runner froze (no heartbeats, no
streaming, and ``asyncio.wait_for`` tool timeouts could not fire).

These tests pin the fixes:

1. read-only tools are classified by ``Tool.is_readonly`` (source of truth),
   with ``ToolManager.READONLY_TOOLS`` kept as a name-based fallback;
2. a ``load_skill``-only step no longer triggers snapshot capture;
3. a busy snapshot lock degrades to "skip this snapshot" instead of blocking;
4. the lock acquisition runs off the event loop (never freezes it).
"""

from __future__ import annotations

import asyncio
import time

import pytest

from broca.components.loop_hook import StepContext
from broca.loop_engine.hooks.snapshot_hook import SnapshotHook
from broca.snapshot.git_manager import FileLock
from broca.tools.executor import DefaultToolExecutor
from broca.tools.tool import Tool
from broca.tools.tool_manager import AutoDiscoverToolManager


# ─── helpers ────────────────────────────────────────────────────────────


class FakeConfig:
    def __init__(self, enable: bool = True, workspace: str = "/tmp/ws"):
        self.enable_snapshot_tracking = enable
        self.workspace = workspace


class FakeToolExecutor:
    """Minimal stand-in exposing only what SnapshotHook needs."""

    def __init__(self, readonly_names: set[str]):
        self._readonly_names = readonly_names

    def is_readonly_tool(self, tool_name: str) -> bool:
        return tool_name in self._readonly_names


class FakeCall:
    """Duck-typed tool call (``function.name`` + ``id``)."""

    def __init__(self, name: str, call_id: str = "call-1"):
        self.id = call_id
        self.function = type("Function", (), {"name": name, "arguments": "{}"})()


def make_step_ctx(tool_names: list[str], has_write_ops: bool = False) -> StepContext:
    return StepContext(
        step_id="step-1",
        turn_id="turn-1",
        agent_id="agent-1",
        session_id="sess-1",
        has_write_ops=has_write_ops,
        tool_calls=[FakeCall(n, f"call-{i}") for i, n in enumerate(tool_names)],
    )


class FakeSnapshotManager:
    """SnapshotManager stand-in with an explicit ``blocking`` signature."""

    def __init__(self, acquire_result: bool = True, acquire_delay: float = 0.0):
        self.acquire_result = acquire_result
        self.acquire_delay = acquire_delay
        self.acquire_calls: list[bool] = []
        self.release_calls = 0
        self.track_calls = 0

    def acquire_lock(self, blocking: bool = True) -> bool:
        self.acquire_calls.append(blocking)
        if self.acquire_delay:
            time.sleep(self.acquire_delay)
        return self.acquire_result

    def release_lock(self) -> None:
        self.release_calls += 1

    async def track(self, workspace: str) -> str:
        self.track_calls += 1
        return f"hash-{self.track_calls}"

    async def calculate_patch(self, from_hash: str, to_hash: str) -> dict:
        return {"files": {"a.py": {}}}

    async def calculate_diff(self, from_hash: str, to_hash: str) -> str:
        return "diff"

    def get_diff_summary(self, diff: str) -> dict:
        return {"total_files": 1, "files_modified": ["a.py"]}


# ─── 1. read-only classification ────────────────────────────────────────


class TestReadonlyClassification:
    def test_load_skill_and_file_mtime_are_readonly(self):
        manager = AutoDiscoverToolManager()
        for name in ("load_skill", "file_mtime"):
            assert name in AutoDiscoverToolManager.READONLY_TOOLS
            assert manager.tools[name].is_readonly is True

    def test_write_tools_are_not_readonly(self):
        manager = AutoDiscoverToolManager()
        for name in ("write_file", "edit_file", "bash", "skill_manage"):
            assert name not in AutoDiscoverToolManager.READONLY_TOOLS
            assert manager.tools[name].is_readonly is False

    def test_tool_is_readonly_defaults_to_false(self):
        """Unknown/new tools must default to "writer" (conservative)."""

        class CustomTool(Tool):
            @property
            def name(self):
                return "custom"

        assert CustomTool().is_readonly is False

    def test_readonly_tools_consistency(self):
        """``Tool.is_readonly`` and ``READONLY_TOOLS`` must not drift apart."""
        manager = AutoDiscoverToolManager()
        mismatched = {
            name: tool.is_readonly
            for name, tool in manager.tools.items()
            if tool.is_readonly != (name in AutoDiscoverToolManager.READONLY_TOOLS)
        }
        assert mismatched == {}, (
            "Tool.is_readonly disagrees with READONLY_TOOLS for: "
            f"{mismatched}"
        )


class TestExecutorReadonlyResolution:
    def _executor(self, mapping: dict) -> DefaultToolExecutor:
        executor = DefaultToolExecutor()
        executor._tool_mapping = mapping
        return executor

    def test_prefers_tool_attribute(self):
        class ReadTool(Tool):
            is_readonly = True

            @property
            def name(self):
                return "not_in_name_set"

        executor = self._executor({"not_in_name_set": ReadTool()})
        assert executor.is_readonly_tool("not_in_name_set") is True

    def test_attribute_false_wins_over_name_set(self):
        class WriterTool(Tool):
            is_readonly = False

            @property
            def name(self):
                return "read_file"  # name says readonly, attribute says no

        executor = self._executor({"read_file": WriterTool()})
        assert executor.is_readonly_tool("read_file") is False

    def test_falls_back_to_name_set_for_unknown_tool(self):
        executor = self._executor({})
        assert executor.is_readonly_tool("grep") is True
        assert executor.is_readonly_tool("load_skill") is True
        assert executor.is_readonly_tool("bash") is False


# ─── 2. load_skill step must not snapshot ───────────────────────────────


class TestLoadSkillStepSkipsSnapshot:
    @pytest.mark.asyncio
    async def test_load_skill_only_step_is_not_a_write_op(self):
        manager = FakeSnapshotManager()
        hook = SnapshotHook(
            manager,
            "/tmp/ws",
            FakeConfig(),
            tool_executor=FakeToolExecutor({"load_skill"}),
        )
        ctx = make_step_ctx(["load_skill"])

        await hook.on_step_start(ctx)

        assert ctx.has_write_ops is False
        assert manager.acquire_calls == []
        assert manager.track_calls == 0
        assert ctx.step_start_snapshot == ""

    @pytest.mark.asyncio
    async def test_write_step_still_snapshots(self):
        manager = FakeSnapshotManager()
        hook = SnapshotHook(
            manager,
            "/tmp/ws",
            FakeConfig(),
            tool_executor=FakeToolExecutor({"load_skill"}),
        )
        ctx = make_step_ctx(["edit_file"])

        await hook.on_step_start(ctx)
        await hook.on_step_end(ctx)

        assert ctx.has_write_ops is True
        assert manager.acquire_calls == [False]  # non-blocking acquire
        assert manager.track_calls >= 1
        assert manager.release_calls == 1


# ─── 3/4. snapshot lock must never block the event loop ─────────────────


class TestSnapshotLockNonBlocking:
    @pytest.mark.asyncio
    async def test_busy_lock_skips_snapshot_instead_of_blocking(self):
        manager = FakeSnapshotManager(acquire_result=False)
        hook = SnapshotHook(
            manager, "/tmp/ws", FakeConfig(), tool_executor=FakeToolExecutor(set())
        )

        started = time.monotonic()
        ctx = make_step_ctx(["edit_file"])
        await hook.on_step_start(ctx)
        elapsed = time.monotonic() - started

        assert elapsed < 1.0
        assert manager.acquire_calls == [False]
        assert manager.track_calls == 0  # degraded: no snapshot this step
        assert hook._lock_held is False
        assert ctx.step_start_snapshot == ""

    @pytest.mark.asyncio
    async def test_no_lock_release_when_acquire_failed(self):
        manager = FakeSnapshotManager(acquire_result=False)
        hook = SnapshotHook(
            manager, "/tmp/ws", FakeConfig(), tool_executor=FakeToolExecutor(set())
        )

        ctx = make_step_ctx(["edit_file"])
        await hook.on_step_start(ctx)
        await hook.on_step_end(ctx)

        assert manager.release_calls == 0

    @pytest.mark.asyncio
    async def test_slow_acquire_does_not_freeze_event_loop(self):
        """A slow (worker-thread) acquire must not stall other tasks."""
        manager = FakeSnapshotManager(acquire_result=True, acquire_delay=0.4)
        hook = SnapshotHook(
            manager, "/tmp/ws", FakeConfig(), tool_executor=FakeToolExecutor(set())
        )

        ticks = 0

        async def ticker():
            nonlocal ticks
            for _ in range(40):
                ticks += 1
                await asyncio.sleep(0.02)

        ticker_task = asyncio.create_task(ticker())
        await asyncio.sleep(0)
        ctx = make_step_ctx(["edit_file"])
        await hook.on_step_start(ctx)
        ticker_task.cancel()

        # ~0.4s of acquire → the loop must have kept running (>5 ticks)
        assert ticks > 5
        assert manager.track_calls == 1
        assert hook._lock_held is True

    @pytest.mark.asyncio
    async def test_acquire_timeout_degrades_gracefully(self):
        manager = FakeSnapshotManager(acquire_result=True, acquire_delay=0.5)
        hook = SnapshotHook(
            manager, "/tmp/ws", FakeConfig(), tool_executor=FakeToolExecutor(set())
        )
        hook._lock_timeout = 0.05

        ctx = make_step_ctx(["edit_file"])
        started = time.monotonic()
        await hook.on_step_start(ctx)
        elapsed = time.monotonic() - started

        assert elapsed < 0.4
        assert manager.track_calls == 0
        assert hook._lock_held is False

        # The worker thread keeps running after the timeout: a late acquire
        # must be released instead of leaking the cross-process lock.
        await asyncio.sleep(0.6)
        assert manager.release_calls == 1


class TestFileLockNonBlocking:
    """Real ``FileLock`` semantics used by the hook."""

    def test_second_acquire_nonblocking_fails_while_held(self, tmp_path):
        lock_path = tmp_path / ".snapshot.lock"
        holder = FileLock(str(lock_path))
        contender = FileLock(str(lock_path))

        assert holder.acquire(True) is True
        assert contender.acquire(False) is False

        holder.release()
        assert contender.acquire(False) is True
        contender.release()

    def test_reentrant_acquire_counts(self, tmp_path):
        lock = FileLock(str(tmp_path / ".snapshot.lock"))
        assert lock.acquire(True) is True
        assert lock.acquire(False) is True  # reentrant, no OS call
        lock.release()
        assert lock.is_held is True  # still one level left
        lock.release()
        assert lock.is_held is False
