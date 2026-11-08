"""GitSnapshotManager — default SnapshotManager implementation.

Composes SnapshotTracker + PatchCalculator + SnapshotRestorer + GitManager
into a single unified interface implementing the SnapshotManager ABC:
  - track / calculate_patch / acquire_lock / release_lock / is_tracked
  - calculate_diff / get_diff_summary / restore / restore_file
  - restore_patches / get_untracked_files

Provides graceful degradation when git is unavailable.
"""

from __future__ import annotations

import shutil
from typing import Any, Dict

from broca.components.snapshot_manager import SnapshotManager
from broca.snapshot.git_manager import GitManager
from broca.snapshot.patch import PatchCalculator
from broca.snapshot.restore import SnapshotRestorer
from broca.snapshot.track import SnapshotTracker
from broca.logging_config import get_logger

logger = get_logger(__name__)


class GitSnapshotManager(SnapshotManager):
    """Snapshot manager backed by git for versioned workspace tracking.

    Composes the existing ``SnapshotTracker``, ``PatchCalculator``, and
    ``GitManager`` classes into a unified ``SnapshotManager`` interface.

    Graceful degradation: when git is unavailable or the workspace is
    not a repository, all methods return safe defaults without raising.
    """

    def __init__(self):
        self._tracker: SnapshotTracker | None = None
        self._patch_calculator: PatchCalculator | None = None
        self._restorer: SnapshotRestorer | None = None
        self._git_manager: GitManager | None = None
        self._available: bool = False

    def initialize(self, workspace: str) -> None:
        """Initialize with the workspace path (synchronous, lightweight).

        Checks git availability and sets up internal trackers.
        """
        if not self._is_git_available():
            logger.debug(
                f"Git not available for workspace {workspace!r}, "
                "snapshot tracking disabled"
            )
            return

        try:
            self._tracker = SnapshotTracker(workspace)
            self._patch_calculator = PatchCalculator(workspace)
            self._restorer = SnapshotRestorer(workspace)
            self._git_manager = GitManager(workspace)
            self._available = True
        except Exception as e:
            logger.warning(
                f"Failed to initialize snapshot tracking for {workspace!r}: {e}"
            )
            self._available = False

    def _is_git_available(self) -> bool:
        """Check if git binary is available on PATH."""
        return shutil.which("git") is not None

    # ------------------------------------------------------------------
    # SnapshotManager ABC implementation
    # ------------------------------------------------------------------

    async def track(self, workspace: str) -> str:
        """Create a snapshot. Returns hash or empty string if unavailable."""
        if not self._available or self._tracker is None:
            return ""
        try:
            return await self._tracker.track()
        except Exception as e:
            logger.warning(f"Snapshot tracking failed: {e}")
            return ""

    async def calculate_patch(
        self, from_hash: str, to_hash: str
    ) -> Dict[str, Any]:
        """Calculate patch between two snapshots."""
        if not self._available or self._patch_calculator is None:
            return {}
        if from_hash == to_hash:
            return {}
        try:
            patch = await self._patch_calculator.calculate_patch(from_hash, to_hash)
            return patch or {}
        except Exception as e:
            logger.warning(f"Patch calculation failed: {e}")
            return {}

    def acquire_lock(self, blocking: bool = True) -> bool:
        """Acquire the git lock for exclusive snapshot access.

        Args:
            blocking: ``True`` waits for the lock (legacy behaviour, blocks the
                calling thread); ``False`` returns ``False`` immediately when
                another writer holds it.

        Returns:
            ``True`` when the lock is held, ``False`` when a non-blocking
            acquire found it busy or the manager is unavailable.
        """
        if not self._available or self._git_manager is None:
            return False
        try:
            return bool(self._git_manager.acquire_lock(blocking=blocking))
        except Exception as e:
            logger.warning(f"Failed to acquire snapshot lock: {e}")
            return False

    def release_lock(self) -> None:
        """Release the git lock."""
        if not self._available or self._git_manager is None:
            return
        try:
            self._git_manager.release_lock()
        except Exception as e:
            logger.warning(f"Failed to release snapshot lock: {e}")

    def is_tracked(self) -> bool:
        """Return True if snapshot tracking is available."""
        return self._available

    # ------------------------------------------------------------------
    # Diff / Restore (ABC extended interface)
    # ------------------------------------------------------------------

    async def calculate_diff(self, from_hash: str, to_hash: str) -> str:
        """Get raw diff content between two snapshots."""
        if not self._available or self._patch_calculator is None:
            return ""
        try:
            return await self._patch_calculator.calculate_diff(from_hash, to_hash)
        except Exception as e:
            logger.warning(f"Diff calculation failed: {e}")
            return ""

    def get_diff_summary(self, diff_content: str) -> Dict[str, Any]:
        """Parse diff content into a summary dict."""
        if not self._available or self._patch_calculator is None:
            return {
                "total_files": 0,
                "total_additions": 0,
                "total_deletions": 0,
                "files_added": [],
                "files_deleted": [],
                "files_modified": [],
            }
        return self._patch_calculator.get_diff_summary(diff_content)

    async def restore(self, tree_hash: str) -> None:
        """Restore workspace to the given snapshot state."""
        if not self._available or self._restorer is None:
            return
        try:
            await self._restorer.restore(tree_hash)
        except Exception as e:
            logger.warning(f"Snapshot restore failed: {e}")

    async def restore_file(self, tree_hash: str, file_path: str) -> None:
        """Restore a single file to the given snapshot state."""
        if not self._available or self._restorer is None:
            return
        try:
            await self._restorer.restore_file(tree_hash, file_path)
        except Exception as e:
            logger.warning(f"File restore failed: {e}")

    async def restore_patches(self, patches: list) -> None:
        """Reverse-apply patches to revert file changes."""
        if not self._available or self._restorer is None:
            return
        try:
            await self._restorer.revert_patches(patches)
        except Exception as e:
            logger.warning(f"Patch revert failed: {e}")

    async def get_untracked_files(self) -> set[str]:
        """Return the set of untracked (but not ignored) files."""
        if not self._available or self._git_manager is None:
            return set()
        try:
            result = await self._git_manager._run_git_command(
                "ls-files", "--others", "--exclude-standard", "-z"
            )
            return set(result.strip().split("\0")) if result.strip() else set()
        except Exception as e:
            logger.warning(f"Failed to get untracked files: {e}")
            return set()
