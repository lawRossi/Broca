"""Snapshot hook — step/turn snapshot capture, patch computation, turn diff.

Migrated from ``DefaultLoopEngine`` (``_initialize_snapshot_tracking``,
``_acquire_step_lock``, ``_release_step_lock``, ``_capture_step_start_snapshot``,
``_compute_step_end_patch``, ``_compute_turn_level_diff``,
``_clear_turn_snapshots``).

The hook only touches the snapshot manager: persisting ``step_start`` /
``step_end`` messages and broadcasting them stay in the engine and in
``LifecycleBroadcastHook`` respectively.

Gating: ``config.enable_snapshot_tracking`` is the master switch.  When no
snapshot manager was injected, the hook lazily creates a ``GitSnapshotManager``
on the first turn (legacy ``_initialize_snapshot_tracking`` behaviour, which
requires a non-empty workspace).  If lazy initialisation is impossible the hook
degrades to a complete no-op.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import TYPE_CHECKING, Any, Optional

from broca.components.loop_hook import LoopHook, StepContext, TurnContext
from broca.logging_config import get_logger

if TYPE_CHECKING:
    from broca.components.snapshot_manager import SnapshotManager

logger = get_logger(__name__)

#: Upper bound (seconds) for acquiring the snapshot lock off the event loop.
#: Keeps a wedged/legacy manager from stalling a step indefinitely.
DEFAULT_LOCK_TIMEOUT = 5.0


class SnapshotHook(LoopHook):
    """Capture step-level snapshots/patches and the turn-level file diff."""

    name = "snapshot"

    def __init__(
        self,
        snapshot_manager: Optional["SnapshotManager"] = None,
        workspace: str = "",
        config: Any = None,
        tool_executor: Optional[Any] = None,
    ):
        self._snapshot_manager = snapshot_manager
        self._config = config
        self._workspace = workspace or getattr(config, "workspace", "") or ""
        self._config_enabled = bool(
            getattr(config, "enable_snapshot_tracking", True)
        )
        self._tool_executor = tool_executor
        self._turn_first_hash: Optional[str] = None
        self._turn_last_hash: Optional[str] = None
        self._step_start_hash: Optional[str] = None
        self._turn_modified_files: set[str] = set()
        self._lock_held = False
        self._lock_timeout = DEFAULT_LOCK_TIMEOUT

    # ------------------------------------------------------------------
    # Gating
    # ------------------------------------------------------------------

    @property
    def _enabled(self) -> bool:
        """True only when tracking is switched on *and* a manager exists."""
        return self._config_enabled and self._snapshot_manager is not None

    def _ensure_manager(self) -> None:
        """Lazily create a snapshot manager (legacy ``_initialize_snapshot_tracking``)."""
        if not self._config_enabled or self._snapshot_manager is not None:
            return
        if not self._workspace:
            return
        try:
            from broca.snapshot.manager import GitSnapshotManager

            manager = GitSnapshotManager()
            manager.initialize(self._workspace)
            self._snapshot_manager = manager
        except Exception as e:
            logger.error(f"Snapshot tracking unavailable, disabling: {e}")
            self._snapshot_manager = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def on_turn_start(self, ctx: TurnContext) -> None:
        self._ensure_manager()
        self._clear_turn_state()
        self._lock_held = False

    async def on_step_start(self, ctx: StepContext) -> None:
        if not self._enabled:
            return
        # Compute write-ops flag (review 4.2: moved from the engine — only
        # SnapshotHook reads it, and the knowledge of "what is a write op"
        # belongs to the tool layer, not the orchestrator).
        if not ctx.has_write_ops:
            ctx.has_write_ops = self._check_write_ops(ctx.tool_calls)
        if not ctx.has_write_ops:
            return
        try:
            if not await self._acquire_lock():
                # Another process is snapshotting this workspace right now.
                # Degrade gracefully: skip the snapshot for this step instead
                # of stalling the event loop on a blocking ``flock``.
                return
            snapshot_hash = await self._snapshot_manager.track(self._workspace)
            self._step_start_hash = snapshot_hash
            ctx.step_start_snapshot = snapshot_hash
            # First snapshot of this turn feeds the turn-level diff.
            if self._turn_first_hash is None:
                self._turn_first_hash = snapshot_hash
        except Exception as e:
            logger.error(f"Error capturing step start snapshot: {e}")

    async def on_step_end(self, ctx: StepContext) -> None:
        if not self._enabled:
            return
        try:
            if not ctx.has_write_ops or not self._step_start_hash:
                return
            end_hash, patch = await self._compute_step_end_patch()
            ctx.step_end_snapshot = end_hash
            ctx.step_patch = patch
            # Accumulate files modified by this session for turn-level diff.
            self._accumulate_modified_files(patch.get("files"))
        except Exception as e:
            logger.error(f"Error capturing step end snapshot: {e}")
        finally:
            # The lock must be released even when patch computation blew up.
            self._release_lock()

    async def on_turn_end(self, ctx: TurnContext) -> None:
        changed_files = await self._compute_turn_level_diff()
        self._clear_turn_state()
        if ctx.result is not None:
            ctx.result.data["changed_files"] = changed_files
        else:  # defensive: the engine always sets ``result`` before dispatch
            ctx.data["changed_files"] = changed_files

    def reset(self) -> None:
        self._release_lock()
        self._clear_turn_state()

    # ------------------------------------------------------------------
    # Lock handling
    # ------------------------------------------------------------------

    async def _acquire_lock(self) -> bool:
        """Acquire the snapshot lock **without blocking the event loop**.

        ``SnapshotManager.acquire_lock`` is a synchronous ``flock``. Calling it
        inline freezes the runner's event loop (heartbeats, streamed output and
        tool timeouts all live on that loop) whenever another session/sub-agent
        process holds ``.snapshot.lock`` for the same workspace.

        So: try a **non-blocking** acquire inside a worker thread. If the lock
        is busy we skip snapshot capture for this step — losing one undo point
        is far cheaper than a frozen session.

        Returns:
            ``True`` when the lock is held by this hook, ``False`` otherwise.
        """
        if self._snapshot_manager is None:
            return False
        future = asyncio.ensure_future(
            asyncio.to_thread(self._try_acquire_nonblocking)
        )
        try:
            acquired = await asyncio.wait_for(
                asyncio.shield(future), timeout=self._lock_timeout
            )
        except asyncio.TimeoutError:
            # The worker thread keeps running: make sure a late acquire is
            # released instead of leaking the cross-process lock forever.
            future.add_done_callback(self._release_late_acquire)
            logger.warning(
                "Snapshot lock acquisition timed out after %.1fs, skipping "
                "snapshot for this step",
                self._lock_timeout,
            )
            return False
        except Exception as e:
            logger.warning(f"Failed to acquire snapshot lock: {e}")
            return False
        if not acquired:
            logger.info(
                "Snapshot lock busy (another writer is snapshotting this "
                "workspace), skipping snapshot for this step"
            )
            return False
        self._lock_held = True
        return True

    def _release_late_acquire(self, future: "asyncio.Future[bool]") -> None:
        """Release a lock that was acquired after ``_acquire_lock`` gave up."""
        if self._snapshot_manager is None:
            return
        try:
            if future.result():
                self._snapshot_manager.release_lock()
                logger.warning(
                    "Snapshot lock acquired after timeout — released it to "
                    "avoid leaking the lock"
                )
        except Exception as e:  # cancelled / raised in the worker thread
            logger.debug(f"Late snapshot lock acquire failed: {e}")

    def _try_acquire_nonblocking(self) -> bool:
        """Worker-thread half of :meth:`_acquire_lock` (never blocks the loop)."""
        acquire = self._snapshot_manager.acquire_lock
        try:
            params = inspect.signature(acquire).parameters
        except (TypeError, ValueError):  # builtins / C callables
            params = {}
        if "blocking" in params:
            return acquire(blocking=False) is not False
        # Legacy manager without the ``blocking`` kwarg: nothing we can do but
        # call it (still off the event loop) — bounded by ``_lock_timeout``.
        acquire()
        return True

    def _release_lock(self) -> None:
        if self._lock_held and self._snapshot_manager is not None:
            self._snapshot_manager.release_lock()
        self._lock_held = False

    # ------------------------------------------------------------------
    # Step-level snapshots
    # ------------------------------------------------------------------

    async def _compute_step_end_patch(self) -> tuple[str, dict]:
        """Track the end snapshot and compute the step patch."""
        if not (self._enabled and self._step_start_hash):
            return ("", {})

        try:
            end_hash = await self._snapshot_manager.track(self._workspace)
            patch = await self._snapshot_manager.calculate_patch(
                self._step_start_hash, end_hash
            )
            if not patch.get("files"):
                return (end_hash, {})

            try:
                diff_content = await self._snapshot_manager.calculate_diff(
                    self._step_start_hash, end_hash
                )
                patch["summary"] = self._snapshot_manager.get_diff_summary(
                    diff_content
                )
            except Exception as e:
                logger.warning(f"Error calculating diff summary: {e}")
                patch["summary"] = {}

            self._turn_last_hash = end_hash
            return (end_hash, patch)
        except Exception as e:
            logger.error(f"Error capturing snapshot/patch at step end: {e}")
            return ("", {})

    # ------------------------------------------------------------------
    # Turn-level diff
    # ------------------------------------------------------------------

    async def _compute_turn_level_diff(self) -> Optional[dict]:
        """Full-turn file diff (``None`` when nothing changed)."""
        if not self._enabled:
            return None

        # A turn that ended abnormally may have a start snapshot but no end
        # snapshot: capture the current state so the diff is still reported.
        if self._turn_first_hash and not self._turn_last_hash:
            try:
                self._turn_last_hash = await self._snapshot_manager.track(
                    self._workspace
                )
            except Exception as e:
                logger.warning(
                    f"Error capturing final snapshot for abnormal turn end: {e}"
                )

        if not (
            self._turn_first_hash
            and self._turn_last_hash
            and self._turn_first_hash != self._turn_last_hash
        ):
            return None

        try:
            diff_content = await self._snapshot_manager.calculate_diff(
                self._turn_first_hash,
                self._turn_last_hash,
                file_paths=sorted(self._turn_modified_files)
                if self._turn_modified_files
                else None,
            )
            diff_summary = self._snapshot_manager.get_diff_summary(diff_content)
            if diff_summary.get("total_files", 0) == 0:
                return None
            return {
                "total_added": len(diff_summary.get("files_added", [])),
                "total_deleted": len(diff_summary.get("files_deleted", [])),
                "total_modified": len(diff_summary.get("files_modified", [])),
                "files_added": diff_summary.get("files_added", []),
                "files_deleted": diff_summary.get("files_deleted", []),
                "files_modified": diff_summary.get("files_modified", []),
                "first_snapshot_hash": self._turn_first_hash,
                "last_snapshot_hash": self._turn_last_hash,
            }
        except Exception as e:
            logger.warning(f"Error calculating turn-level diff: {e}")
            return None

    def _accumulate_modified_files(self, files: Any) -> None:
        """Extract file paths from a patch's ``files`` field.

        Handles the three shapes seen in production and tests:
        - ``list[str]``          (real PatchCalculator)
        - ``list[dict]``          (some test mocks: ``[{"path": "a.py"}]``)
        - ``dict``               (some test mocks: ``{"a.py": {…}}``)
        """
        if files is None:
            return
        if isinstance(files, list):
            for f in files:
                if isinstance(f, str):
                    self._turn_modified_files.add(f)
                elif isinstance(f, dict) and "path" in f:
                    self._turn_modified_files.add(f["path"])
        elif isinstance(files, dict):
            self._turn_modified_files.update(files.keys())

    def _check_write_ops(self, tool_calls: list) -> bool:
        """True when the step contains at least one non-read-only tool call."""
        if not tool_calls or self._tool_executor is None:
            return False
        return any(
            not self._tool_executor.is_readonly_tool(tc.function.name)
            for tc in tool_calls
        )

    def _clear_turn_state(self) -> None:
        """Drop all per-turn hashes (legacy ``_clear_turn_snapshots``)."""
        self._turn_first_hash = None
        self._turn_last_hash = None
        self._step_start_hash = None
        self._turn_modified_files.clear()
