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
    def acquire_lock(self) -> None:
        """Acquire the snapshot lock (blocking).

        Ensures only one agent at a time is capturing snapshots.
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
