"""SnapshotManager ABC — interface for workspace snapshot tracking.

Provides version-controlled snapshots of workspace state for undo/redo
functionality. Composes file tracking, patch calculation, and locking.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class SnapshotManager(ABC):
    """Abstract base class for workspace snapshot management.

    Implementations track file changes in a workspace, calculate
    patches between snapshots, and provide concurrency locking.
    """

    # -- Tracking -------------------------------------------------------

    @abstractmethod
    async def track(self, workspace: str) -> str:
        """Create a snapshot of the current workspace state.

        Returns the snapshot hash, or empty string if tracking is not
        available (e.g., git not installed, workspace not a repo).
        """
        ...

    # -- Patch calculation ------------------------------------------------

    @abstractmethod
    async def calculate_patch(
        self, from_hash: str, to_hash: str
    ) -> Dict[str, Any]:
        """Calculate the patch (diff) between two snapshots.

        Returns a dict with patch details. Returns empty dict if no
        changes detected.
        """
        ...

    # -- Locking ----------------------------------------------------------

    @abstractmethod
    def acquire_lock(self, blocking: bool = True) -> bool:
        """Acquire the snapshot lock.

        Args:
            blocking: when ``True`` (default, legacy behaviour) wait until the
                lock is available; when ``False`` return immediately with
                ``False`` if another writer holds it.

        Returns:
            ``True`` if the lock is now held, ``False`` if a non-blocking
            acquire found it busy.

        Callers on an asyncio event loop MUST NOT call this with
        ``blocking=True`` directly — the underlying ``flock`` would freeze the
        whole loop (heartbeats, streaming, tool timeouts).
        """
        ...

    @abstractmethod
    def release_lock(self) -> None:
        """Release the snapshot lock."""
        ...

    # -- Status -----------------------------------------------------------

    @abstractmethod
    def is_tracked(self) -> bool:
        """Return True if snapshot tracking is available (git exists,
        workspace is a repo, etc.)."""
        ...

    # -- Diff / Restore (extended interface) ------------------------------
    # These methods are NOT @abstractmethod — they provide safe default
    # implementations so existing plugin subclasses remain instantiable.

    async def calculate_diff(self, from_hash: str, to_hash: str) -> str:
        """Get raw diff content between two snapshots.

        Returns empty string if unavailable.
        """
        return ""

    def get_diff_summary(self, diff_content: str) -> Dict[str, Any]:
        """Parse diff content into a summary dict.

        Returns an empty summary if unavailable.
        """
        return {
            "total_files": 0,
            "total_additions": 0,
            "total_deletions": 0,
            "files_added": [],
            "files_deleted": [],
            "files_modified": [],
        }

    async def restore(self, tree_hash: str) -> None:
        """Restore workspace to the given snapshot state.

        No-op if restore is not supported.
        """
        pass

    async def restore_file(self, tree_hash: str, file_path: str) -> None:
        """Restore a single file to the given snapshot state.

        No-op if restore is not supported.
        """
        pass

    async def restore_patches(self, patches: list) -> None:
        """Reverse-apply a list of patches to revert file changes.

        No-op if restore is not supported.
        """
        pass

    async def get_untracked_files(self) -> set[str]:
        """Return the set of untracked (but not ignored) files.

        Returns empty set if unavailable.
        """
        return set()
