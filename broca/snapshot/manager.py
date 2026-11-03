"""GitSnapshotManager — default SnapshotManager implementation.

Composes SnapshotTracker + PatchCalculator + GitManager into a single
unified interface. Provides graceful degradation when git is unavailable.
"""

from __future__ import annotations

import logging
import shutil
from typing import Any, Dict

from broca.components.snapshot_manager import SnapshotManager
from broca.snapshot.git_manager import GitManager
from broca.snapshot.patch import PatchCalculator
from broca.snapshot.track import SnapshotTracker

logger = logging.getLogger(__name__)


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
        self._git_manager: GitManager | None = None
        self._workspace: str = ""
        self._available: bool = False

    def initialize(self, workspace: str) -> None:
        """Initialize with the workspace path (synchronous, lightweight).

        Checks git availability and sets up internal trackers.
        """
        self._workspace = workspace
        if not self._is_git_available():
            logger.debug(
                f"Git not available for workspace {workspace!r}, "
                "snapshot tracking disabled"
            )
            return

        try:
            self._tracker = SnapshotTracker(workspace)
            self._patch_calculator = PatchCalculator(workspace)
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

    def acquire_lock(self) -> None:
        """Acquire the git lock for exclusive snapshot access."""
        if not self._available or self._git_manager is None:
            return
        try:
            self._git_manager.acquire_lock(blocking=True)
        except Exception as e:
            logger.warning(f"Failed to acquire snapshot lock: {e}")

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
    # Extended API (not in ABC, used directly by LoopEngine)
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
            return {}
        return self._patch_calculator.get_diff_summary(diff_content)
