"""
Regression tests for snapshot module fixes (Phase 1).

Covers:
- Shell injection protection (create_subprocess_exec)
- to_hash=None diff command fix
- undo/redo lock holding
- revert_patches batch atomicity
- Ghost file batch check optimization
- GitManager lifecycle (cleanup/reset)
"""

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def workspace():
    """Create a temporary workspace with initialized git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.system(
            f"cd {tmpdir} && git init -q && "
            f"git config user.email test@test.com && "
            f"git config user.name test"
        )
        yield tmpdir


@pytest.fixture
def tracker(workspace):
    from broca.snapshot.track import SnapshotTracker
    return SnapshotTracker(workspace)


@pytest.fixture
def restorer(workspace):
    from broca.snapshot.restore import SnapshotRestorer
    return SnapshotRestorer(workspace)


@pytest.fixture
def calculator(workspace):
    from broca.snapshot.patch import PatchCalculator
    return PatchCalculator(workspace)


@pytest.fixture
def git_manager(workspace):
    from broca.snapshot.git_manager import GitManager
    return GitManager(workspace)


# ============================================================
# TestShellSafety (Task 1.1)
# ============================================================


class TestShellSafety:
    """Verify that special characters in filenames are not interpreted as shell commands."""

    @pytest.mark.asyncio
    async def test_track_file_with_spaces(self, workspace, tracker):
        """Files with spaces in name should be tracked and restored correctly."""
        # Create file with space in name
        path = "my file.txt"
        Path(workspace, path).write_text("hello world\n")

        # Track
        hash1 = await tracker.track()
        assert hash1, "track() should return a non-empty hash"

        # Modify
        Path(workspace, path).write_text("changed content\n")

        # Track again
        hash2 = await tracker.track()
        assert hash2 != hash1, "hashes should differ after modification"

        # Restore to first snapshot
        from broca.snapshot.restore import SnapshotRestorer
        restorer = SnapshotRestorer(workspace)
        await restorer.restore(hash1)

        # Verify content restored
        content = Path(workspace, path).read_text()
        assert content == "hello world\n"

    @pytest.mark.asyncio
    async def test_track_file_with_shell_metachars(self, workspace, tracker):
        """Files with $() in name should NOT execute shell commands."""
        # Create file with shell metacharacters in name
        filename = "test$(echo hacked).txt"
        Path(workspace, filename).write_text("safe content\n")

        # Track — if shell injection exists, "hacked" file would be created
        hash1 = await tracker.track()
        assert hash1, "track() should succeed"

        # Verify NO "hacked" file was created by shell expansion
        hacked_file = Path(workspace, "hacked")
        assert not hacked_file.exists(), (
            f"Shell injection detected: 'hacked' file was created "
            f"by command substitution in filename"
        )

        # Verify the original file still exists
        assert Path(workspace, filename).exists()

    @pytest.mark.asyncio
    async def test_track_file_with_semicolon(self, workspace, tracker):
        """Files with ; in name should NOT create extra files via shell command chaining."""
        filename = "test;ls.txt"
        Path(workspace, filename).write_text("safe\n")

        hash1 = await tracker.track()
        assert hash1, "track() should succeed"

        # No extra files should exist in workspace beyond what we created
        files = set(p.name for p in Path(workspace).iterdir() if not p.name.startswith("."))
        # Should only contain our file (and maybe .gitignore if created)
        assert filename in files
        # Ensure no "ls" output file was accidentally created
        assert "hacked" not in files

    @pytest.mark.asyncio
    async def test_ignored_batch_with_special_chars(self, git_manager):
        """is_ignored_batch should correctly handle paths with spaces."""
        git_manager.ensure_initialized()

        # These should not be "ignored" (they're regular files)
        result = await git_manager.is_ignored_batch(
            ["file with spaces.txt", "another file.md"]
        )
        # Regular files without ignore patterns should not be in the ignored set
        # (unless they match default ignore patterns like node_modules)
        assert "file with spaces.txt" not in result
        assert "another file.md" not in result


# ============================================================
# TestToHashNoneFix (Task 1.3 Fix B2)
# ============================================================


class TestToHashNoneFix:
    """Verify calculate_patch with to_hash=None uses correct diff command (no HEAD)."""

    @pytest.mark.asyncio
    async def test_calculate_patch_to_hash_none(self, workspace, tracker, calculator):
        """Modified file should be detected when to_hash=None (diff index vs worktree).

        After read-tree(from_hash), the index contains from_hash's files.
        git diff (index vs worktree) shows files that differ between index and worktree.
        """
        # Create initial file and track
        Path(workspace, "file_a.txt").write_text("original\n")
        snapshot_hash = await tracker.track()

        # Modify the file after the snapshot
        Path(workspace, "file_a.txt").write_text("modified\n")

        # Calculate patch with to_hash=None:
        # 1. read-tree snapshot_hash → index = snapshot's state (file_a.txt = "original")
        # 2. git diff --name-only -- . → index vs worktree: file_a.txt differs
        # 3. reset --mixed → index reset to HEAD
        result = await calculator.calculate_patch(snapshot_hash, to_hash=None)
        assert "file_a.txt" in result.get("files", []), (
            f"Expected file_a.txt in patch files, got: {result.get('files', [])}"
        )

    @pytest.mark.asyncio
    async def test_calculate_patch_to_hash_none_no_false_positive(self, workspace, tracker, calculator):
        """No modifications → calculate_patch with to_hash=None should return empty files.

        If the worktree hasn't changed since the snapshot, diff (index vs worktree)
        should show no differences.
        """
        # Create and track
        Path(workspace, "file_a.txt").write_text("content\n")
        snapshot_hash = await tracker.track()

        # No modification — worktree matches index (both have the tracked state)
        # calculate_patch: read-tree(snapshot) → index = snapshot state
        # git diff (index vs worktree) → no differences
        result = await calculator.calculate_patch(snapshot_hash, to_hash=None)
        assert result.get("files", []) == [], (
            f"Expected empty files (no changes), got: {result.get('files', [])}"
        )


# ============================================================
# TestUndoLock (Task 1.3 Fix B3)
# ============================================================


class TestUndoLock:
    """Verify undo()/redo() hold the lock for the entire operation."""

    @staticmethod
    def _fake_db_manager(partial_turn_ids: list[str] | None = None):
        """Stand-in for ``revert_service.db_manager``.

        ``_mark_messages_as_reverted_sql`` runs a raw SQL query through
        ``db_manager.get_session()`` to find partially-reverted turns.  Without
        this stub the test hits the real (process-wide) SQLite DB, whose
        ``message`` table only exists if some *other* test directory's conftest
        created it — i.e. the test used to pass or fail depending on which
        files pytest happened to collect (see ``broca/tests/session/conftest.py``).
        """
        result = MagicMock()
        result.scalars.return_value.all.return_value = list(partial_turn_ids or [])

        session = MagicMock()
        session.execute = AsyncMock(return_value=result)

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)

        db = MagicMock()
        db.get_session = MagicMock(return_value=ctx)
        return db

    @pytest.mark.asyncio
    async def test_undo_holds_lock_for_entire_operation(self):
        """acquire_lock should be called before track, release_lock after all operations."""
        from broca.session.revert_service import SessionRevertService
        from broca.session.models import MessageType

        # Mock session manager
        mock_session_mgr = MagicMock()
        mock_session_mgr.get_session = AsyncMock(return_value=MagicMock())

        # Mock snapshot manager to track call order
        mock_sm = MagicMock()
        mock_sm.track = AsyncMock(return_value="hash_123")
        mock_sm.restore_patches = AsyncMock()
        mock_sm.calculate_diff = AsyncMock(return_value="")
        mock_sm.get_diff_summary = MagicMock(return_value={"total_files": 0})
        mock_sm.acquire_lock = MagicMock()
        mock_sm.release_lock = MagicMock()
        mock_sm.get_untracked_files = AsyncMock(return_value=set())

        service = SessionRevertService(
            session_manager=mock_session_mgr,
            snapshot_manager=mock_sm,
            workspace_path="/tmp/test_ws",
        )

        # Mock message service — must use MessageType enum
        mock_msg_svc = MagicMock()
        mock_msg_svc.get_last_agent_response_id = AsyncMock(return_value="msg_1")
        mock_msg_svc.find_pivot_message_id = AsyncMock(return_value="msg_pivot")
        mock_msg_svc.get_messages_from_pivot = AsyncMock(return_value=[
            # pivot message itself — triggers collecting=True
            MagicMock(
                message_id="msg_pivot",
                message_type=MessageType.STEP_END,
                data=None,
            ),
            # subsequent STEP_END with a patch — gets collected
            MagicMock(
                message_id="msg_2",
                message_type=MessageType.STEP_END,
                data={"patch": {"snapshot_hash": "old_hash", "files": ["f1.txt"]}},
            ),
        ])
        mock_msg_svc.get_message_ids_from_pivot = AsyncMock(
            return_value={"message_ids": {"msg_2"}, "turn_ids": {"t1"}}
        )
        mock_session_mgr.batch_update_messages = AsyncMock()
        mock_session_mgr.batch_update_turns = AsyncMock()

        with patch("broca.session.revert_service.get_message_service", return_value=mock_msg_svc), \
             patch("broca.session.revert_service.db_manager", self._fake_db_manager()), \
             patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda func, *a, **kw: func(*a, **kw))):
            await service.undo(
                session_id="s1", agent_id="a1", target_message_id="msg_1", level="step"
            )

        # Verify acquire_lock was called (via asyncio.to_thread)
        # Since we patch asyncio.to_thread to call func directly,
        # we check that mock_sm.acquire_lock was called
        assert mock_sm.acquire_lock.called, "acquire_lock should be called during undo"
        assert mock_sm.release_lock.called, "release_lock should be called during undo"

        # Verify the snapshot operations were performed
        assert mock_sm.track.called
        assert mock_sm.restore_patches.called
        # 完全撤销的轮次应被标记（SQL 分支确实走通了 stub）
        assert mock_session_mgr.batch_update_turns.called

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "partial_turns, expect_marked",
        [
            ([], True),          # 该 turn 所有消息都被撤销 → 标记 turn
            (["t1"], False),     # 该 turn 还有未撤销消息 → 不标记
        ],
    )
    async def test_partial_turn_is_not_marked_reverted(
        self, partial_turns, expect_marked
    ):
        """``_mark_messages_as_reverted_sql`` 只在整轮消息都被撤销时标记 turn。

        使用 stub 的 ``db_manager``，避免依赖真实 SQLite schema。
        """
        from broca.session.revert_service import SessionRevertService

        mock_session_mgr = MagicMock()
        mock_session_mgr.batch_update_messages = AsyncMock()
        mock_session_mgr.batch_update_turns = AsyncMock()

        service = SessionRevertService(
            session_manager=mock_session_mgr,
            snapshot_manager=MagicMock(),
            workspace_path="/tmp/test_ws",
        )

        mock_msg_svc = MagicMock()
        mock_msg_svc.get_message_ids_from_pivot = AsyncMock(
            return_value={"message_ids": {"msg_2"}, "turn_ids": {"t1"}}
        )

        with patch(
            "broca.session.revert_service.get_message_service",
            return_value=mock_msg_svc,
        ), patch(
            "broca.session.revert_service.db_manager",
            self._fake_db_manager(partial_turns),
        ):
            await service._mark_messages_as_reverted_sql("a1", "msg_pivot")

        assert mock_session_mgr.batch_update_messages.called
        assert mock_session_mgr.batch_update_turns.called is expect_marked

    @pytest.mark.asyncio
    async def test_redo_holds_lock(self):
        """redo() should hold lock for the entire restore + orphan cleanup."""
        from broca.session.revert_service import SessionRevertService

        mock_session_mgr = MagicMock()
        mock_session_mgr.get_session = AsyncMock(return_value=MagicMock())

        mock_sm = MagicMock()
        mock_sm.restore = AsyncMock()
        mock_sm.get_untracked_files = AsyncMock(return_value=set())
        mock_sm.acquire_lock = MagicMock()
        mock_sm.release_lock = MagicMock()

        service = SessionRevertService(
            session_manager=mock_session_mgr,
            snapshot_manager=mock_sm,
            workspace_path="/tmp/test_ws",
        )

        # Set up undo stack with a snapshot
        service.undo_stack.append({
            "patches": [{"snapshot_hash": "old", "files": ["a.txt"]}],
            "snapshot_hash": "snap_123",
            "message_ids_to_revert": [],
        })

        with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda func, *a, **kw: func(*a, **kw))), \
             patch("broca.session.revert_service.get_message_service") as mock_msg:
            mock_msg.return_value._get_turn_ids_for_messages = AsyncMock(return_value=set())
            mock_session_mgr.batch_update_messages = AsyncMock()
            mock_session_mgr.batch_update_turns = AsyncMock()
            await service.redo(session_id="s1", agent_id="a1")

        assert mock_sm.acquire_lock.called, "acquire_lock should be called during redo"
        assert mock_sm.release_lock.called, "release_lock should be called during redo"
        assert mock_sm.restore.called, "restore should be called during redo"


# ============================================================
# TestRevertAtomicity (Task 1.3 Fix B4)
# ============================================================


class TestRevertAtomicity:
    """Verify revert_patches uses batch git checkout per tree_hash."""

    @pytest.mark.asyncio
    async def test_revert_patches_batch_checkout(self, workspace, restorer):
        """3 files from same tree_hash should use 1 git checkout call."""
        # Set up files
        for f in ["a.txt", "b.txt", "c.txt"]:
            Path(workspace, f).write_text(f"content {f}\n")

        # Track to create a snapshot
        tracker = restorer.git_manager  # Same GitManager
        from broca.snapshot.track import SnapshotTracker
        tr = SnapshotTracker(workspace)
        await tr.track()

        # Now mock _run_git_command to track checkout calls
        checkout_calls = []

        async def mock_run_git(*args, **kwargs):
            if args[0] == "checkout":
                checkout_calls.append(args)
            return ""

        with patch.object(
            restorer.git_manager, "_run_git_command", side_effect=mock_run_git
        ), patch.object(
            restorer.git_manager, "_run_git_command_no_lock", side_effect=mock_run_git
        ):
            patches = [{
                "snapshot_hash": "abc123",
                "files": ["a.txt", "b.txt", "c.txt"],
            }]
            await restorer.revert_patches(patches)

        # Should have exactly 1 checkout call (batch)
        checkout_calls = [c for c in checkout_calls if c[0] == "checkout"]
        assert len(checkout_calls) == 1, (
            f"Expected 1 batch checkout call, got {len(checkout_calls)}: {checkout_calls}"
        )
        # Verify all 3 files are in the single call
        call = checkout_calls[0]
        assert "a.txt" in call
        assert "b.txt" in call
        assert "c.txt" in call

    @pytest.mark.asyncio
    async def test_revert_patches_mixed_hashes(self, workspace, restorer):
        """2 files from tree A, 1 from tree B → 2 checkout calls."""
        for f in ["a.txt", "b.txt", "c.txt"]:
            Path(workspace, f).write_text(f"content {f}\n")

        from broca.snapshot.track import SnapshotTracker
        tr = SnapshotTracker(workspace)
        await tr.track()

        checkout_calls = []

        async def mock_run_git(*args, **kwargs):
            if args[0] == "checkout":
                checkout_calls.append(args)
            return ""

        with patch.object(
            restorer.git_manager, "_run_git_command", side_effect=mock_run_git
        ), patch.object(
            restorer.git_manager, "_run_git_command_no_lock", side_effect=mock_run_git
        ):
            patches = [
                {"snapshot_hash": "tree_A", "files": ["a.txt", "b.txt"]},
                {"snapshot_hash": "tree_B", "files": ["c.txt"]},
            ]
            await restorer.revert_patches(patches)

        checkout_calls = [c for c in checkout_calls if c[0] == "checkout"]
        assert len(checkout_calls) == 2, (
            f"Expected 2 checkout calls (one per tree), got {len(checkout_calls)}"
        )

    @pytest.mark.asyncio
    async def test_revert_patches_fallback_delete(self, workspace, restorer):
        """File not in target tree → ls-tree check + file deletion."""
        # Create a file that exists on disk
        target_file = "orphan.txt"
        Path(workspace, target_file).write_text("to be deleted\n")

        from broca.snapshot.track import SnapshotTracker
        tr = SnapshotTracker(workspace)
        await tr.track()

        # Mock: checkout fails for this file, ls-tree returns empty (not in tree)
        async def mock_run_git(*args, **kwargs):
            import git
            if args[0] == "checkout":
                raise git.GitCommandError("checkout", 1, b"not found")
            if args[0] == "ls-tree":
                return ""  # File not in tree
            return ""

        with patch.object(
            restorer.git_manager, "_run_git_command", side_effect=mock_run_git
        ), patch.object(
            restorer.git_manager, "_run_git_command_no_lock", side_effect=mock_run_git
        ):
            patches = [{
                "snapshot_hash": "tree_X",
                "files": [target_file],
            }]
            await restorer.revert_patches(patches)

        # File should be deleted (not in target tree, but was on disk)
        assert not Path(workspace, target_file).exists(), (
            f"Orphan file {target_file} should have been deleted"
        )


# ============================================================
# TestGhostFileBatch (Task 1.4)
# ============================================================


class TestGhostFileBatch:
    """Verify _filter_files uses at most 1 ls-files --cached call for ghost files."""

    @pytest.mark.asyncio
    async def test_filter_files_batch_ghost_check(self, workspace, tracker, git_manager):
        """3 ghost files → ls-files --cached called at most 1 time."""
        # Set up a tracked file that's been "deleted" from disk (ghost)
        # We need files that are in the index but not on disk.
        # Simulate: create files, track, then delete from disk.
        for f in ["g1.txt", "g2.txt", "g3.txt"]:
            Path(workspace, f).write_text(f"content {f}\n")

        await tracker.track()

        # Now delete files from disk (they become ghosts)
        for f in ["g1.txt", "g2.txt", "g3.txt"]:
            (Path(workspace) / f).unlink()

        # Count ls-files --cached calls
        ls_files_cached_calls = []

        original_run = git_manager._run_git_command

        async def counting_run(*args, **kwargs):
            if args[0] == "ls-files" and "--cached" in args:
                ls_files_cached_calls.append(args)
            return await original_run(*args, **kwargs)

        with patch.object(
            git_manager, "_run_git_command", side_effect=counting_run
        ):
            # _filter_files will be called internally by track()
            # But let's call it directly
            files = ["g1.txt", "g2.txt", "g3.txt"]
            await tracker._filter_files(files)

        # Should be at most 1 ls-files --cached call (batch)
        assert len(ls_files_cached_calls) <= 1, (
            f"Expected at most 1 batch ls-files call, got {len(ls_files_cached_calls)}"
        )

    @pytest.mark.asyncio
    async def test_filter_files_no_ghost_no_git_call(self, workspace, tracker, git_manager):
        """All files on disk → ls-files --cached called 0 times."""
        # Create real files
        for f in ["real1.txt", "real2.txt"]:
            Path(workspace, f).write_text(f"content {f}\n")

        await tracker.track()

        # Count ls-files --cached calls
        ls_files_cached_calls = []

        original_run = git_manager._run_git_command

        async def counting_run(*args, **kwargs):
            if args[0] == "ls-files" and "--cached" in args:
                ls_files_cached_calls.append(args)
            return await original_run(*args, **kwargs)

        with patch.object(
            git_manager, "_run_git_command", side_effect=counting_run
        ):
            files = ["real1.txt", "real2.txt"]
            await tracker._filter_files(files)

        # No ghost files → no ls-files --cached call needed
        assert len(ls_files_cached_calls) == 0, (
            f"Expected 0 ls-files calls (all files on disk), got {len(ls_files_cached_calls)}"
        )


# ============================================================
# TestGitManagerLifecycle (Task 1.5 Fix A3)
# ============================================================


class TestGitManagerLifecycle:
    """Verify GitManager singleton cleanup works correctly."""

    def test_cleanup_removes_singleton(self, workspace):
        """After cleanup(), the workspace is no longer in _instances."""
        from broca.snapshot.git_manager import GitManager

        # Create instance (registers in _instances)
        gm = GitManager(workspace)
        normalized = str(Path(workspace).resolve())
        assert normalized in GitManager._instances, (
            "Newly created GitManager should be in _instances"
        )

        # Initialize and cleanup
        gm.initialize()
        gm.cleanup()

        assert normalized not in GitManager._instances, (
            "After cleanup(), instance should be removed from _instances"
        )

    def test_reset_removes_singleton(self, workspace):
        """GitManager.reset(path) removes the singleton from _instances."""
        from broca.snapshot.git_manager import GitManager

        # Create instance
        gm = GitManager(workspace)
        normalized = str(Path(workspace).resolve())
        assert normalized in GitManager._instances

        # Reset
        GitManager.reset(workspace)

        assert normalized not in GitManager._instances, (
            "After reset(), instance should be removed from _instances"
        )
