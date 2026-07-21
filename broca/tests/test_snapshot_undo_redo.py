"""
Tests for snapshot tracking and undo/redo operations.

Verifies:
1. _discover_changed_files detects staged changes (index vs HEAD diff)
2. _filter_files correctly handles ghost files (in HEAD but not in index/disk)
3. _track_snapshot handles index-vs-HEAD diff when no files can be staged
4. Full undo/redo chain with file creation, modification, deletion
5. Orphan file cleanup during redo
6. Multi-file change scenarios
7. Diff calculation correctness after undo operations
8. Incremental track() consistency
9. Concurrent undo (undo Round 2+3 together)
"""

import os
import tempfile
from pathlib import Path

import pytest


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def workspace():
    """Create a temporary workspace with initialized git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Initialize git repo
        os.system(f"cd {tmpdir} && git init -q && git config user.email test@test.com && git config user.name test")
        yield tmpdir


@pytest.fixture
def tracker(workspace):
    """Create a SnapshotTracker instance."""
    from broca.snapshot.track import SnapshotTracker
    return SnapshotTracker(workspace)


@pytest.fixture
def restorer(workspace):
    """Create a SnapshotRestorer instance."""
    from broca.snapshot.restore import SnapshotRestorer
    return SnapshotRestorer(workspace)


@pytest.fixture
def calculator(workspace):
    """Create a PatchCalculator instance."""
    from broca.snapshot.patch import PatchCalculator
    return PatchCalculator(workspace)


def _write(workspace, path, content):
    """Write content to a file in the workspace."""
    Path(workspace, path).write_text(content)


def _unlink(workspace, path):
    """Delete a file from the workspace."""
    os.unlink(Path(workspace, path))


def _exists(workspace, path):
    """Check if a file exists."""
    return Path(workspace, path).exists()


def _read(workspace, path):
    """Read a file."""
    return Path(workspace, path).read_text()


async def _tree_files_via_gitmanager(git_manager, tree_hash):
    """Get the set of files in a git tree using the git manager."""
    result = await git_manager._run_git_command("ls-tree", "-r", "--name-only", tree_hash)
    return set(result.strip().split()) if result.strip() else set()


# ============================================================
# Test 1: _discover_changed_files detects staged changes
# ============================================================

@pytest.mark.asyncio
async def test_discover_changed_files_detects_staged_changes(workspace, tracker, restorer):
    """
    Verifies that _discover_changed_files detects files modified by
    git checkout (index vs HEAD diff), which is the core fix for
    the undo/redo snapshot_hash bug.
    """
    # Setup: create file_a and track
    _write(workspace, "file_a.txt", "content a")
    snap1 = await tracker.track()

    # Create file_b and track
    _write(workspace, "file_b.txt", "content b")
    await tracker.track()

    # Simulate revert_patches: restore file_a state (only file_a)
    await restorer.restore(snap1)

    # Note: after restore(), file_b.txt still exists on disk (restore doesn't
    # clean orphan files). So _discover_changed_files detects it from BOTH
    # diff-index --cached (in HEAD but not in index) AND ls-files --others
    # (on disk but not tracked). This is the pre-orphan-cleanup state.
    changed = await tracker._discover_changed_files()
    assert "file_b.txt" in changed, (
        f"file_b.txt should be detected (HEAD has it, index doesn't). Got: {changed}"
    )

    # _filter_files: file_b exists on disk → passes through (not a ghost yet)
    filtered = await tracker._filter_files(changed)
    assert "file_b.txt" in filtered, (
        f"file_b.txt should pass filter (exists on disk). Got: {filtered}"
    )

    # Now simulate orphan cleanup (as done in redo())
    result = await tracker.git_manager._run_git_command(
        "ls-files", "--others", "--exclude-standard", "-z"
    )
    for f in result.strip().split("\0"):
        if f and (Path(workspace) / f).exists():
            (Path(workspace) / f).unlink()

    # After cleanup: file_b truly is a ghost (in HEAD, not on disk, not in index)
    changed2 = await tracker._discover_changed_files()
    assert "file_b.txt" in changed2, (
        f"file_b.txt should still be detected after cleanup. Got: {changed2}"
    )

    # Now _filter_files should skip file_b (not on disk, not in index)
    filtered2 = await tracker._filter_files(changed2)
    assert "file_b.txt" not in filtered2, (
        f"file_b.txt should be filtered out (ghost file). Got: {filtered2}"
    )


# ============================================================
# Test 2: filter_files skips ghost files
# ============================================================

@pytest.mark.asyncio
async def test_filter_files_skips_ghost_files(workspace):
    """
    Verifies _filter_files correctly handles all file categories:
    - Normal files: exist on disk → pass through
    - Ghost files: in HEAD but not in index/disk → skipped
    - Index-only files: in index but not on disk → pass through
    """
    from broca.snapshot.track import SnapshotTracker

    tracker = SnapshotTracker(workspace)

    # Create normal file
    _write(workspace, "normal.txt", "hello")

    # Create a file that's in the index but not on disk
    _write(workspace, "index_only.txt", "temp")
    await tracker.track()  # Now it's tracked
    _unlink(workspace, "index_only.txt")  # Delete from disk but still in index

    # Test filtering
    test_files = ["normal.txt", "index_only.txt", "ghost.txt"]

    # normal.txt: exists on disk → should pass
    # index_only.txt: not on disk, but in index (from track()) → should pass
    # ghost.txt: not on disk, not in index → should be filtered

    filtered = await tracker._filter_files(test_files)

    assert "normal.txt" in filtered, "normal.txt should pass (exists on disk)"
    assert "index_only.txt" in filtered, "index_only.txt should pass (in index)"
    assert "ghost.txt" not in filtered, "ghost.txt should be filtered (not on disk, not in index)"


# ============================================================
# Test 3: track() handles index diff with ghost files
# ============================================================

@pytest.mark.asyncio
async def test_track_captures_index_diff_with_ghost_files(workspace, tracker, restorer):
    """
    Verifies that track() correctly captures the actual workspace state
    when the index differs from HEAD but all detected files are ghost files
    (filtered out by _filter_files).
    """
    # Setup: create file_a, track
    _write(workspace, "file_a.txt", "a")
    snap1 = await tracker.track()

    # Create file_b, track (HEAD now has both)
    _write(workspace, "file_b.txt", "b")
    snap2 = await tracker.track()
    tree2 = await _tree_files_via_gitmanager(tracker.git_manager, snap2)
    assert "file_b.txt" in tree2

    # Restore to snap1 (only file_a in index/workspace)
    await restorer.restore(snap1)
    # Note: file_b.txt still exists on disk after restore() because
    # checkout-index doesn't delete orphan files. In the redo flow,
    # orphan cleanup is done separately.
    assert _exists(workspace, "file_b.txt"), "file_b still on disk (orphan, not cleaned by restore)"

    # After orphan cleanup (simulating redo() behavior)
    result = await tracker.git_manager._run_git_command(
        "ls-files", "--others", "--exclude-standard", "-z"
    )
    for f in result.strip().split("\0"):
        if f and (Path(workspace) / f).exists():
            (Path(workspace) / f).unlink()
    assert not _exists(workspace, "file_b.txt"), "file_b should be deleted after orphan cleanup"

    # HEAD still has file_b, but index/workspace don't
    head_tree = await _tree_files_via_gitmanager(tracker.git_manager, "HEAD")
    assert "file_b.txt" in head_tree, "HEAD should still have file_b"

    # track() should detect the index diff and create a new tree without file_b
    snap3 = await tracker.track()
    tree3 = await _tree_files_via_gitmanager(tracker.git_manager, snap3)

    assert "file_b.txt" not in tree3, (
        f"file_b should NOT be in the new snapshot. Got: {tree3}"
    )
    assert "file_a.txt" in tree3, f"file_a should be in the snapshot. Got: {tree3}"

    # After track(), HEAD should be updated to match
    head_tree_after = await _tree_files_via_gitmanager(tracker.git_manager, "HEAD")
    assert head_tree_after == tree3, "HEAD should be updated to match new snapshot"


# ============================================================
# Test 4: Undo/redo simple - restore file after deletion
# ============================================================

@pytest.mark.asyncio
async def test_undo_redo_simple(workspace, tracker, restorer, calculator):
    """
    Simple undo/redo: create file → delete file → undo → redo.
    Verifies file state is correct at each step.
    """
    # Round 1: create file_a
    _write(workspace, "file_a.txt", "a")
    await tracker.track()

    # Round 2: create file_b
    _write(workspace, "file_b.txt", "b")
    snap2_before = await tracker.track()

    # Round 3: delete file_b
    _unlink(workspace, "file_b.txt")
    snap3 = await tracker.track()
    assert not _exists(workspace, "file_b.txt")

    # Build patch for deletion
    diff = await calculator.calculate_diff(snap2_before, snap3)
    summary = calculator.get_diff_summary(diff)
    patch = {"snapshot_hash": snap2_before, "files": summary.get("files_deleted", [])}
    assert "file_b.txt" in patch["files"]

    # === Undo deletion ===
    before_undo = await tracker.track()
    await restorer.revert_patches([patch])

    assert _exists(workspace, "file_b.txt"), "file_b should be restored after undo"
    assert _read(workspace, "file_b.txt") == "b", "file_b content should match"

    # The snapshot before undo should not have file_b (for redo)
    assert "file_b.txt" not in await _tree_files_via_gitmanager(tracker.git_manager, before_undo), (
        "before_undo snapshot should not have file_b"
    )

    # === Redo ===
    await restorer.restore(before_undo)
    # Orphan cleanup
    result = await tracker.git_manager._run_git_command(
        "ls-files", "--others", "--exclude-standard", "-z"
    )
    for f in result.strip().split("\0"):
        if f and (Path(workspace) / f).exists():
            (Path(workspace) / f).unlink()

    assert not _exists(workspace, "file_b.txt"), "file_b should be deleted after redo"
    assert _exists(workspace, "file_a.txt"), "file_a should still exist"


# ============================================================
# Test 5: Undo/redo chain with file modification
# ============================================================

@pytest.mark.asyncio
async def test_undo_redo_modification_chain(workspace, tracker, restorer, calculator):
    """
    Full chain: create file_a → modify file_b → delete file_b.
    Undo Round 3 → Redo → Undo Round 2+3.
    This is the exact scenario that had the _stage_files ghost file bug.
    """
    # Round 1: create file_a
    _write(workspace, "file_a.txt", "a")
    await tracker.track()

    # Round 2: create and modify file_b
    _write(workspace, "file_b.txt", "b v1")
    snap_r2_before = await tracker.track()

    _write(workspace, "file_b.txt", "b v2 modified")
    snap_r2_after = await tracker.track()

    # Build patch2 (modification)
    diff2 = await calculator.calculate_diff(snap_r2_before, snap_r2_after)
    s2 = calculator.get_diff_summary(diff2)
    patch2 = {
        "snapshot_hash": snap_r2_before,
        "files": s2.get("files_modified", []) + s2.get("files_added", []),
    }
    assert "file_b.txt" in patch2["files"]

    # Round 3: delete file_b
    _unlink(workspace, "file_b.txt")
    snap_r3 = await tracker.track()

    diff3 = await calculator.calculate_diff(snap_r2_after, snap_r3)
    s3 = calculator.get_diff_summary(diff3)
    patch3 = {"snapshot_hash": snap_r2_after, "files": s3.get("files_deleted", [])}
    assert "file_b.txt" in patch3["files"]

    # === Step 1: Undo Round 3 (delete → restore) ===
    snap_before_undo3 = await tracker.track()
    await restorer.revert_patches([patch3])
    assert _exists(workspace, "file_b.txt"), "file_b should be restored"
    assert _read(workspace, "file_b.txt") == "b v2 modified", "content should be v2"

    snap_after_undo3 = await tracker.track()
    assert "file_b.txt" in await _tree_files_via_gitmanager(tracker.git_manager, snap_after_undo3), "snapshot should have file_b"

    # === Step 2: Redo Round 3 (restore deletion) ===
    await restorer.restore(snap_before_undo3)
    # Orphan cleanup
    for f in ["file_b.txt"]:
        result = await tracker.git_manager._run_git_command(
            "ls-files", "--others", "--exclude-standard", "-z"
        )
        if f in result.strip().split("\0"):
            (Path(workspace) / f).unlink()

    assert not _exists(workspace, "file_b.txt"), "file_b should be deleted after redo"

    # === Step 3: Undo Round 2+3 (the _stage_files bug scenario) ===
    snap_before = await tracker.track()

    # This was the failing call before the fix
    await restorer.revert_patches([patch2, patch3])

    assert _exists(workspace, "file_b.txt"), "file_b should be restored after undo2+3"
    assert _read(workspace, "file_b.txt") == "b v1", "content should be v1 (before modification)"

    # track() must not error (this is the _stage_files test)
    snap_after = await tracker.track()
    assert "file_b.txt" in await _tree_files_via_gitmanager(tracker.git_manager, snap_after), "snapshot should have file_b"

    # === Step 4: Verify redo of Step 3's undo works ===
    await restorer.restore(snap_before)
    for f in ["file_b.txt"]:
        result = await tracker.git_manager._run_git_command(
            "ls-files", "--others", "--exclude-standard", "-z"
        )
        if f in result.strip().split("\0") and (Path(workspace) / f).exists():
            (Path(workspace) / f).unlink()

    snap_redo = await tracker.track()
    assert "file_b.txt" not in await _tree_files_via_gitmanager(tracker.git_manager, snap_redo), (
        "file_b should be gone after redo"
    )


# ============================================================
# Test 6: Multi-file undo/redo
# ============================================================

@pytest.mark.asyncio
async def test_undo_redo_multi_file(workspace, tracker, restorer, calculator):
    """
    Complex multi-file scenario: create multiple files, modify some,
    delete some, then undo all changes together.
    """
    # Initial state
    _write(workspace, "base.txt", "base")
    await tracker.track()

    # Make multiple changes
    _write(workspace, "new.txt", "new file")
    _write(workspace, "base.txt", "base modified")
    _write(workspace, "extra.txt", "extra")
    snap_before = await tracker.track()

    # More changes
    _unlink(workspace, "new.txt")
    _write(workspace, "extra.txt", "extra modified")
    _write(workspace, "another.txt", "another")
    snap_after = await tracker.track()

    # Build patch for all changes
    diff = await calculator.calculate_diff(snap_before, snap_after)
    s = calculator.get_diff_summary(diff)
    patch = {
        "snapshot_hash": snap_before,
        "files": s.get("files_added", []) + s.get("files_modified", []) + s.get("files_deleted", []),
    }

    # Verify patch covers all changed files between snap_before and snap_after
    # Changes: new.txt deleted, extra.txt modified, another.txt added
    # base.txt was modified before snap_before, not between snap_before and snap_after
    assert "new.txt" in s.get("files_deleted", []), f"new.txt should be deleted. Got: {s}"
    assert "extra.txt" in s.get("files_modified", []), f"extra.txt should be modified. Got: {s}"
    assert "another.txt" in s.get("files_added", []), f"another.txt should be added. Got: {s}"

    # Undo all changes (revert to snap_before state)
    await restorer.revert_patches([patch])

    # snap_before state: base.txt="base modified", new.txt="new file", extra.txt="extra"
    assert _read(workspace, "base.txt") == "base modified", (
        f"base.txt should be 'base modified' (snap_before state). Got: {_read(workspace, 'base.txt')}"
    )
    assert _read(workspace, "new.txt") == "new file", "new.txt should be restored"
    assert _read(workspace, "extra.txt") == "extra", "extra.txt should be reverted to 'extra'"
    assert not _exists(workspace, "another.txt"), "another.txt should be gone (was created after snap_before)"

    snap_undo = await tracker.track()
    tree = await _tree_files_via_gitmanager(tracker.git_manager, snap_undo)
    assert "base.txt" in tree, "base.txt should be in tree"
    assert "new.txt" in tree, "new.txt should be in tree (was in snap_before)"
    assert "extra.txt" in tree, "extra.txt should be in tree"
    assert "another.txt" not in tree, "another.txt should not be in tree"


# ============================================================
# Test 7: Diff calculation after undo
# ============================================================

@pytest.mark.asyncio
async def test_diff_calculation_after_undo(workspace, tracker, restorer, calculator):
    """
    Verifies that diff calculation between before-undo and after-undo
    snapshots produces correct file change summary.
    """
    _write(workspace, "f1.txt", "v1")
    await tracker.track()

    _write(workspace, "f1.txt", "v2")
    _write(workspace, "f2.txt", "new")
    snap2 = await tracker.track()

    _unlink(workspace, "f1.txt")
    _write(workspace, "f2.txt", "v2 updated")
    snap3 = await tracker.track()

    # Build patch for Round 3 (delete f1, modify f2)
    diff3 = await calculator.calculate_diff(snap2, snap3)
    s3 = calculator.get_diff_summary(diff3)
    patch3 = {"snapshot_hash": snap2, "files": s3.get("files_deleted", []) + s3.get("files_modified", [])}

    # Undo Round 3
    before_undo = await tracker.track()
    await restorer.revert_patches([patch3])

    # Calculate diff for the undo operation
    diff_undo = await calculator.calculate_diff(before_undo, await tracker.track())
    s_undo = calculator.get_diff_summary(diff_undo)

    assert s_undo.get("total_files", 0) > 0, "undo should produce file changes"
    assert "f1.txt" in s_undo.get("files_added", []), "f1 should be restored (added back)"
    assert "f2.txt" in s_undo.get("files_modified", []), "f2 should be restored (modified back)"


# ============================================================
# Test 8: Incremental track() consistency
# ============================================================

@pytest.mark.asyncio
async def test_track_incremental_consistency(workspace, tracker):
    """
    Verifies that consecutive track() calls correctly capture state
    at each step, and that each snapshot contains all previous files.
    """
    all_files = set()
    for i in range(10):
        fname = f"seq_{i}.txt"
        _write(workspace, fname, f"content {i}")
        snap = await tracker.track()

        all_files.add(fname)
        tree = await _tree_files_via_gitmanager(tracker.git_manager, snap)

        # Each snapshot should contain ALL files created so far
        for j in range(i + 1):
            expected = f"seq_{j}.txt"
            assert expected in tree, (
                f"After step {i}, snapshot should contain {expected}. Got: {tree}"
            )

    # Verify final state
    final = await tracker.track()
    final_tree = await _tree_files_via_gitmanager(tracker.git_manager, final)
    assert final_tree == all_files, f"Final tree should have all files. Got: {final_tree}"


# ============================================================
# Test 9: track() returns correct tree with no changes
# ============================================================

@pytest.mark.asyncio
async def test_track_no_changes_returns_same_hash(workspace, tracker):
    """
    Verifies that calling track() when nothing has changed
    returns the same tree hash as the previous call.
    """
    _write(workspace, "stable.txt", "stable")
    snap1 = await tracker.track()

    # No changes, track() should return same hash
    snap2 = await tracker.track()
    assert snap1 == snap2, "track() should return same hash when nothing changed"

    # Modify and track again
    _write(workspace, "stable.txt", "modified")
    snap3 = await tracker.track()
    assert snap1 != snap3, "track() should return different hash after change"

    # No changes again
    snap4 = await tracker.track()
    assert snap3 == snap4, "track() should return same hash when nothing changed (after modification)"


# ============================================================
# Test 10: Batch file operations consistency
# ============================================================

@pytest.mark.asyncio
async def test_batch_file_operations(workspace, tracker, restorer, calculator):
    """
    Creates 5 files simultaneously, tracks, then deletes 3,
    tracks, then undoes the deletion. Verifies all intermediate
    snapshots are consistent.
    """
    # Create 5 files
    for i in range(5):
        _write(workspace, f"batch_{i}.txt", f"content {i}")
    snap_create = await tracker.track()
    assert len(await _tree_files_via_gitmanager(tracker.git_manager, snap_create)) == 5

    # Delete 3 files
    for i in [1, 2, 4]:
        _unlink(workspace, f"batch_{i}.txt")
    snap_delete = await tracker.track()
    tree_del = await _tree_files_via_gitmanager(tracker.git_manager, snap_delete)
    assert "batch_1.txt" not in tree_del
    assert "batch_3.txt" in tree_del

    # Build patch for deletion
    diff = await calculator.calculate_diff(snap_create, snap_delete)
    s = calculator.get_diff_summary(diff)
    patch = {"snapshot_hash": snap_create, "files": s.get("files_deleted", [])}

    # Undo deletion
    await restorer.revert_patches([patch])
    for i in [1, 2, 4]:
        assert _exists(workspace, f"batch_{i}.txt"), f"batch_{i}.txt should be restored"

    snap_undo = await tracker.track()
    assert len(await _tree_files_via_gitmanager(tracker.git_manager, snap_undo)) == 5, "all 5 files should be back"


# ============================================================
# Test 11: revert_patches with files not in target tree
# ============================================================

@pytest.mark.asyncio
async def test_revert_patches_created_file(workspace, tracker, restorer, calculator):
    """
    When reverting a patch that CREATED a file, the snapshot_hash
    points to a tree without that file. Verifies that restore_file
    handles this gracefully by deleting the file from disk.
    """
    _write(workspace, "existing.txt", "existing")
    snap_before = await tracker.track()

    # Create new file
    _write(workspace, "created.txt", "new file")
    snap_after = await tracker.track()

    # Build patch for creation
    diff = await calculator.calculate_diff(snap_before, snap_after)
    s = calculator.get_diff_summary(diff)
    patch = {"snapshot_hash": snap_before, "files": s.get("files_added", [])}
    assert "created.txt" in patch["files"]

    # Undo creation - should delete the file
    assert _exists(workspace, "created.txt"), "file should exist before undo"
    await restorer.revert_patches([patch])
    assert not _exists(workspace, "created.txt"), "file should be deleted after undo"
    assert _exists(workspace, "existing.txt"), "existing file should remain"


# ============================================================
# Test 12: Ghost file tracking across multiple operations
# ============================================================

@pytest.mark.asyncio
async def test_ghost_file_across_multiple_ops(workspace, tracker, restorer):
    """
    Creates a scenario where ghost files appear across multiple
    restore+orphan-cleanup cycles.
    """
    # Round 1: file_a
    _write(workspace, "a.txt", "a")
    snap1 = await tracker.track()

    # Round 2: file_a, file_b
    _write(workspace, "b.txt", "b")
    await tracker.track()

    # Round 3: file_a, file_b, file_c
    _write(workspace, "c.txt", "c")
    await tracker.track()

    # Restore to snap1 (only a.txt). This creates ghost files b.txt and c.txt
    await restorer.restore(snap1)
    # Orphan cleanup (as in redo())
    result = await tracker.git_manager._run_git_command("ls-files", "--others", "--exclude-standard", "-z")
    for f in result.strip().split("\0"):
        if f and (Path(workspace) / f).exists():
            (Path(workspace) / f).unlink()
    assert not _exists(workspace, "b.txt")
    assert not _exists(workspace, "c.txt")

    # track() should update HEAD to only a.txt
    snap = await tracker.track()
    tree = await _tree_files_via_gitmanager(tracker.git_manager, snap)
    assert tree == {"a.txt"}, f"Should only have a.txt. Got: {tree}"
    assert await _tree_files_via_gitmanager(tracker.git_manager, "HEAD") == tree, "HEAD should match snapshot"

    # Now add b.txt again and track
    _write(workspace, "b.txt", "b again")
    await tracker.track()

    # Restore to snap (only a.txt) - b.txt becomes ghost
    await restorer.restore(snap)
    # Orphan cleanup
    result = await tracker.git_manager._run_git_command("ls-files", "--others", "--exclude-standard", "-z")
    for f in result.strip().split("\0"):
        if f and (Path(workspace) / f).exists():
            (Path(workspace) / f).unlink()
    assert not _exists(workspace, "b.txt")

    # track() should still produce correct tree
    snap_final = await tracker.track()
    tree_final = await _tree_files_via_gitmanager(tracker.git_manager, snap_final)
    assert tree_final == {"a.txt"}, (
        "Final tree should only have a.txt"
    )


# ============================================================
# Test 13: Undo redo with file content verification
# ============================================================

@pytest.mark.asyncio
async def test_undo_redo_content_verification(workspace, tracker, restorer, calculator):
    """
    Verifies that file CONTENTS are correctly preserved across
    undo/redo operations, not just file existence.
    """
    # Create files with specific content
    _write(workspace, "data.txt", "original")
    _write(workspace, "log.txt", "log v1")
    snap1 = await tracker.track()

    # Modify both files
    _write(workspace, "data.txt", "modified")
    _write(workspace, "log.txt", "log v2")
    snap2 = await tracker.track()

    # Delete one file
    _unlink(workspace, "log.txt")
    snap3 = await tracker.track()

    # Build patches
    diff2 = await calculator.calculate_diff(snap1, snap2)
    s2 = calculator.get_diff_summary(diff2)
    patch2 = {"snapshot_hash": snap1, "files": s2.get("files_modified", []) + s2.get("files_added", [])}

    diff3 = await calculator.calculate_diff(snap2, snap3)
    s3 = calculator.get_diff_summary(diff3)
    patch3 = {"snapshot_hash": snap2, "files": s3.get("files_deleted", [])}

    # Undo deletion (Round 3 undo)
    before_undo3 = await tracker.track()
    await restorer.revert_patches([patch3])
    assert _read(workspace, "data.txt") == "modified", "data.txt should be 'modified' after undo3"
    assert _read(workspace, "log.txt") == "log v2", "log.txt should be 'log v2' after undo3"

    # Undo modification (Round 2 undo)
    before_undo2 = await tracker.track()
    await restorer.revert_patches([patch2])
    assert _read(workspace, "data.txt") == "original", "data.txt should be 'original' after undo2"
    assert _read(workspace, "log.txt") == "log v1", "log.txt should be 'log v1' after undo2"

    # Redo modification (redo Round 2 undo) → should restore to state after undo3
    await restorer.restore(before_undo2)
    for f in ["log.txt"]:
        r = await tracker.git_manager._run_git_command("ls-files", "--others", "--exclude-standard", "-z")
        if f in r.strip().split("\0") and (Path(workspace) / f).exists():
            (Path(workspace) / f).unlink()

    assert _read(workspace, "data.txt") == "modified", "data.txt should be 'modified' after redo"
    assert _read(workspace, "log.txt") == "log v2", "log.txt should be 'log v2' after redo"

    # Redo deletion (redo Round 3 undo) → should delete log.txt
    await restorer.restore(before_undo3)
    for f in ["log.txt"]:
        r = await tracker.git_manager._run_git_command("ls-files", "--others", "--exclude-standard", "-z")
        if f in r.strip().split("\0") and (Path(workspace) / f).exists():
            (Path(workspace) / f).unlink()

    assert _read(workspace, "data.txt") == "modified", "data.txt should still be 'modified'"
    assert not _exists(workspace, "log.txt"), "log.txt should be deleted"


# ============================================================
# Test 14: restore() without subsequent track()
# ============================================================

@pytest.mark.asyncio
async def test_restore_without_track(workspace, tracker, restorer):
    """
    Verifies that calling restore() and then immediately checking
    the workspace state is correct, even without calling track().
    This tests the read-tree + checkout-index combination.
    """
    _write(workspace, "f1.txt", "v1")
    _write(workspace, "f2.txt", "v2")
    snap1 = await tracker.track()

    _write(workspace, "f1.txt", "modified")
    _unlink(workspace, "f2.txt")
    _write(workspace, "f3.txt", "new")
    snap2 = await tracker.track()

    # Helper: orphan cleanup (as in redo())
    async def _cleanup_orphans():
        r = await tracker.git_manager._run_git_command("ls-files", "--others", "--exclude-standard", "-z")
        for f in r.strip().split("\0"):
            if f and (Path(workspace) / f).exists():
                (Path(workspace) / f).unlink()

    # Restore to snap1
    await restorer.restore(snap1)
    # Note: f3.txt still exists on disk after restore (checkout-index doesn't
    # delete orphans). This is expected; cleanup is done separately.
    await _cleanup_orphans()
    assert _read(workspace, "f1.txt") == "v1", "f1 should be restored"
    assert _exists(workspace, "f2.txt"), "f2 should be restored"
    assert _read(workspace, "f2.txt") == "v2", "f2 content should be restored"
    assert not _exists(workspace, "f3.txt"), "f3 should be gone after cleanup"

    # Restore to snap2
    await restorer.restore(snap2)
    await _cleanup_orphans()
    assert _read(workspace, "f1.txt") == "modified", "f1 should be modified"
    assert not _exists(workspace, "f2.txt"), "f2 should be gone"
    assert _exists(workspace, "f3.txt"), "f3 should exist"
    assert _read(workspace, "f3.txt") == "new", "f3 content correct"
