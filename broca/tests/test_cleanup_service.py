"""
SessionCleanupService 单元测试

覆盖：
- cleanup_workspace_files: 正常删除、空 workspace、目录不存在
- cleanup_runner_logs: 正常删除、目录不存在
- cleanup_orphaned_jobs: 有 job 删除、无 job 返回 0
- cleanup_snapshots_if_last_session: 最后一个 session 删除 repo、非最后跳过、空 workspace
- cleanup_session_resilience: 单项失败不阻塞其他项
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pathlib import Path


@pytest.fixture
def cleanup_service():
    """创建 SessionCleanupService 实例（重置单例）"""
    from broca.session.cleanup_service import SessionCleanupService

    SessionCleanupService._instance = None
    return SessionCleanupService()


class TestCleanupWorkspaceFiles:
    """测试 cleanup_workspace_files"""

    @pytest.mark.asyncio
    async def test_removes_session_dir(self, tmp_path):
        """正常场景：删除 {workspace}/.broca/{session_id}/ 目录"""
        workspace = str(tmp_path / "workspace")
        session_id = "test-session-001"

        # 创建目录结构
        session_dir = Path(workspace) / ".broca" / session_id
        session_dir.mkdir(parents=True)
        (session_dir / "session-memory.md").write_text("memory content")
        agents_dir = session_dir / "agents"
        agents_dir.mkdir()
        (agents_dir / "assistant.json").write_text("{}")

        assert session_dir.exists()

        from broca.session.cleanup_service import SessionCleanupService
        svc = SessionCleanupService()
        await svc.cleanup_workspace_files(workspace, session_id)

        assert not session_dir.exists()

    @pytest.mark.asyncio
    async def test_skips_when_workspace_is_none(self):
        """workspace 为 None 时直接 return，不抛异常"""
        from broca.session.cleanup_service import SessionCleanupService
        svc = SessionCleanupService()
        # 不应抛异常
        await svc.cleanup_workspace_files(None, "test-session")

    @pytest.mark.asyncio
    async def test_skips_when_workspace_is_empty(self):
        """workspace 为空字符串时直接 return"""
        from broca.session.cleanup_service import SessionCleanupService
        svc = SessionCleanupService()
        await svc.cleanup_workspace_files("", "test-session")

    @pytest.mark.asyncio
    async def test_no_error_when_dir_not_exists(self, tmp_path):
        """目录不存在时不抛异常"""
        workspace = str(tmp_path / "workspace")
        Path(workspace).mkdir(parents=True)

        from broca.session.cleanup_service import SessionCleanupService
        svc = SessionCleanupService()
        # 不存在的 session_id
        await svc.cleanup_workspace_files(workspace, "nonexistent-session")


class TestCleanupRunnerLogs:
    """测试 cleanup_runner_logs"""

    @pytest.mark.asyncio
    async def test_removes_log_dir(self, tmp_path, monkeypatch):
        """正常场景：删除 ~/.broca/logs/runners/{session_id}/ 目录"""
        # 模拟 home 目录
        fake_home = tmp_path / "fake_home"
        log_dir = fake_home / ".broca" / "logs" / "runners" / "test-session-001"
        log_dir.mkdir(parents=True)
        (log_dir / "20260101.log").write_text("log content")

        monkeypatch.setattr(Path, "home", lambda: fake_home)

        from broca.session.cleanup_service import SessionCleanupService
        svc = SessionCleanupService()
        await svc.cleanup_runner_logs("test-session-001")

        assert not log_dir.exists()

    @pytest.mark.asyncio
    async def test_no_error_when_log_dir_not_exists(self, tmp_path, monkeypatch):
        """日志目录不存在时不抛异常"""
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        from broca.session.cleanup_service import SessionCleanupService
        svc = SessionCleanupService()
        await svc.cleanup_runner_logs("nonexistent-session")


class TestCleanupOrphanedJobs:
    """测试 cleanup_orphaned_jobs"""

    @pytest.mark.asyncio
    async def test_deletes_related_jobs(self):
        """有关联 job 时删除并返回数量"""
        with patch("broca.session.database.db_manager") as mock_db_mgr:
            mock_session = AsyncMock()
            mock_db_mgr.get_session = MagicMock(return_value=_async_context_manager(mock_session))

            # mock 查询结果
            mock_job1 = MagicMock()
            mock_job1.status = "active"
            mock_job1.job_id = "job-1"
            mock_job2 = MagicMock()
            mock_job2.status = "active"
            mock_job2.job_id = "job-2"

            mock_result = MagicMock()
            mock_result.all = MagicMock(return_value=[mock_job1, mock_job2])
            mock_session.exec = AsyncMock(return_value=mock_result)
            mock_session.delete = AsyncMock()
            mock_session.commit = AsyncMock()
            mock_session.add = MagicMock()

            from broca.session.cleanup_service import SessionCleanupService
            svc = SessionCleanupService()
            count = await svc.cleanup_orphaned_jobs("test-session")

            assert count == 2
            assert mock_session.delete.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_jobs(self):
        """无关联 job 时返回 0"""
        with patch("broca.session.database.db_manager") as mock_db_mgr:
            mock_session = AsyncMock()
            mock_db_mgr.get_session = MagicMock(return_value=_async_context_manager(mock_session))

            mock_result = MagicMock()
            mock_result.all = MagicMock(return_value=[])
            mock_session.exec = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()

            from broca.session.cleanup_service import SessionCleanupService
            svc = SessionCleanupService()
            count = await svc.cleanup_orphaned_jobs("test-session")

            assert count == 0


class TestCleanupSnapshotsIfLastSession:
    """测试 cleanup_snapshots_if_last_session"""

    @pytest.mark.asyncio
    async def test_cleans_up_when_no_remaining_sessions(self):
        """场景 A：剩余 session 数 = 0 → 调用 GitManager.cleanup()"""
        workspace = "/tmp/test-workspace"

        with patch("broca.session.database.db_manager") as mock_db_mgr, \
             patch("broca.snapshot.git_manager.GitManager") as MockGitMgr:
            # mock DB 查询返回 0
            mock_session = AsyncMock()
            mock_db_mgr.get_session = MagicMock(return_value=_async_context_manager(mock_session))
            mock_result = MagicMock()
            mock_result.one = MagicMock(return_value=0)
            mock_session.exec = AsyncMock(return_value=mock_result)

            # mock GitManager
            mock_gm = MagicMock()
            mock_gm.repo_path = MagicMock()
            mock_gm.repo_path.exists = MagicMock(return_value=True)
            MockGitMgr.return_value = mock_gm

            from broca.session.cleanup_service import SessionCleanupService
            svc = SessionCleanupService()
            await svc.cleanup_snapshots_if_last_session(workspace)

            mock_gm.acquire_lock.assert_called_once()
            mock_gm.cleanup.assert_called_once()
            mock_gm.release_lock.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_when_sessions_remain(self):
        """场景 B：剩余 session 数 > 0 → 不操作"""
        workspace = "/tmp/test-workspace"

        with patch("broca.session.database.db_manager") as mock_db_mgr, \
             patch("broca.snapshot.git_manager.GitManager") as MockGitMgr:
            # mock DB 查询返回 2
            mock_session = AsyncMock()
            mock_db_mgr.get_session = MagicMock(return_value=_async_context_manager(mock_session))
            mock_result = MagicMock()
            mock_result.one = MagicMock(return_value=2)
            mock_session.exec = AsyncMock(return_value=mock_result)

            from broca.session.cleanup_service import SessionCleanupService
            svc = SessionCleanupService()
            await svc.cleanup_snapshots_if_last_session(workspace)

            # GitManager 不应被实例化
            MockGitMgr.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_workspace_is_none(self):
        """workspace 为 None → 直接跳过"""
        from broca.session.cleanup_service import SessionCleanupService
        svc = SessionCleanupService()
        # 不应抛异常
        await svc.cleanup_snapshots_if_last_session(None)


class TestCleanupSessionResilience:
    """测试 cleanup_session 容错性"""

    @pytest.mark.asyncio
    async def test_single_failure_does_not_block_others(self):
        """一个子方法抛异常，其他子方法仍执行，cleanup_session 不向上抛"""
        from broca.session.cleanup_service import SessionCleanupService
        svc = SessionCleanupService()

        with patch.object(svc, "cleanup_workspace_files", side_effect=PermissionError("denied")), \
             patch.object(svc, "cleanup_runner_logs", new=AsyncMock()) as mock_logs, \
             patch.object(svc, "cleanup_orphaned_jobs", new=AsyncMock(return_value=0)) as mock_jobs, \
             patch.object(svc, "cleanup_snapshots_if_last_session", new=AsyncMock()) as mock_snap:
            # 不应抛异常
            await svc.cleanup_session("/tmp/ws", "test-session")

            # 其他方法仍被执行
            mock_logs.assert_called_once_with("test-session")
            mock_jobs.assert_called_once_with("test-session")
            mock_snap.assert_called_once_with("/tmp/ws")

    @pytest.mark.asyncio
    async def test_all_failures_do_not_raise(self):
        """所有子方法都失败时，cleanup_session 仍不抛异常"""
        from broca.session.cleanup_service import SessionCleanupService
        svc = SessionCleanupService()

        with patch.object(svc, "cleanup_workspace_files", side_effect=OSError("fail")), \
             patch.object(svc, "cleanup_runner_logs", side_effect=OSError("fail")), \
             patch.object(svc, "cleanup_orphaned_jobs", side_effect=OSError("fail")), \
             patch.object(svc, "cleanup_snapshots_if_last_session", side_effect=OSError("fail")):
            # 不应抛异常
            await svc.cleanup_session("/tmp/ws", "test-session")


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------

def _async_context_manager(cm):
    """创建一个 async context manager mock"""
    cm.__aenter__ = AsyncMock(return_value=cm)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm
