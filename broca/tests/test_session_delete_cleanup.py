"""
Session 删除 API 集成测试

验证删除 API 的端到端清理流程：
- 单删：DB 删除 + 文件清理 + 日志清理 + 快照清理
- 批量删：所有 session 完整清理
- 容错：清理异常不影响 API 返回
- 快照：最后 session 删除时清理 repo，否则保留
"""

import asyncio
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def workspace_dir(tmp_path):
    """创建临时 workspace 目录结构"""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def setup_session_files(workspace_dir, tmp_path):
    """
    创建模拟的 session 文件和 runner 日志。

    返回 (session_id, workspace_str, session_dir, log_dir)
    """
    session_id = "test-integration-session"
    workspace = str(workspace_dir)

    # 创建 session workspace 文件
    session_dir = workspace_dir / ".broca" / session_id
    session_dir.mkdir(parents=True)
    (session_dir / "session-memory.md").write_text("frozen memory")
    (session_dir / "session-memory_latest.md").write_text("snapshot memory")
    agents_dir = session_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / "assistant.json").write_text('{"name": "assistant"}')

    # 创建 runner 日志目录（模拟 ~/.broca/logs/runners/）
    # 通过 patch Path.home 在测试中处理
    return session_id, workspace, session_dir


# ------------------------------------------------------------------
# 单删集成测试
# ------------------------------------------------------------------

class TestDeleteSessionCleanup:
    """测试 DELETE /session/{id} 的完整清理链路"""

    @pytest.mark.asyncio
    async def test_delete_session_cleans_files(self, tmp_path):
        """删除 session 后，workspace 文件 + runner 日志被清理"""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        session_id = "session-abc"

        # 准备文件
        session_dir = workspace / ".broca" / session_id
        session_dir.mkdir(parents=True)
        (session_dir / "session-memory.md").write_text("test")

        # mock session service
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.workspace = str(workspace)

        mock_session_service = MagicMock()
        mock_session_service.get = AsyncMock(return_value=mock_session)
        mock_session_service.delete = AsyncMock(return_value=True)

        mock_runner = MagicMock()
        mock_runner.stop_session = AsyncMock(return_value=True)

        # patch Path.home for runner logs
        fake_home = tmp_path / "home"
        log_dir = fake_home / ".broca" / "logs" / "runners" / session_id
        log_dir.mkdir(parents=True)
        (log_dir / "20260101.log").write_text("log")

        with patch("broca.session.database.db_manager") as mock_db_mgr, \
             patch("broca.snapshot.git_manager.GitManager") as MockGitMgr, \
             patch("pathlib.Path.home", return_value=fake_home):
            # mock DB 查询（workspace 下无剩余 session → 触发 snapshot cleanup）
            mock_db_session = AsyncMock()
            mock_db_mgr.get_session = MagicMock(return_value=_acm(mock_db_session))
            mock_result = MagicMock()
            mock_result.one = MagicMock(return_value=0)  # 无剩余 session
            mock_db_session.exec = AsyncMock(return_value=mock_result)

            mock_gm = MagicMock()
            mock_gm.repo_path = MagicMock()
            mock_gm.repo_path.exists = MagicMock(return_value=False)  # 无 repo
            MockGitMgr.return_value = mock_gm

            # 直接调用 cleanup_service 模拟 API 行为
            from broca.session.cleanup_service import SessionCleanupService
            svc = SessionCleanupService()
            await svc.cleanup_session(str(workspace), session_id)

        # 验证文件被清理
        assert not session_dir.exists()
        assert not log_dir.exists()

    @pytest.mark.asyncio
    async def test_delete_session_cleans_orphaned_jobs(self):
        """删除 session 后，关联的 scheduled_job 被删除"""
        session_id = "session-jobs"

        mock_job = MagicMock()
        mock_job.status = "active"
        mock_job.job_id = "job-1"

        mock_db_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all = MagicMock(return_value=[mock_job])
        mock_db_session.exec = AsyncMock(return_value=mock_result)
        mock_db_session.delete = AsyncMock()
        mock_db_session.commit = AsyncMock()
        mock_db_session.add = MagicMock()

        with patch("broca.session.database.db_manager") as mock_db_mgr:
            mock_db_mgr.get_session = MagicMock(return_value=_acm(mock_db_session))

            from broca.session.cleanup_service import SessionCleanupService
            svc = SessionCleanupService()
            count = await svc.cleanup_orphaned_jobs(session_id)

            assert count == 1
            assert mock_db_session.delete.call_count == 1

    @pytest.mark.asyncio
    async def test_delete_session_snapshot_cleanup_on_last_session(self):
        """最后一个 session 删除时，snapshot repo 被清理"""
        workspace = "/tmp/ws-last"

        mock_gm = MagicMock()
        mock_gm.repo_path = MagicMock()
        mock_gm.repo_path.exists = MagicMock(return_value=True)

        mock_db_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.one = MagicMock(return_value=0)  # 无剩余
        mock_db_session.exec = AsyncMock(return_value=mock_result)

        with patch("broca.session.database.db_manager") as mock_db_mgr, \
             patch("broca.snapshot.git_manager.GitManager") as MockGitMgr:
            mock_db_mgr.get_session = MagicMock(return_value=_acm(mock_db_session))
            MockGitMgr.return_value = mock_gm

            from broca.session.cleanup_service import SessionCleanupService
            svc = SessionCleanupService()
            await svc.cleanup_snapshots_if_last_session(workspace)

            mock_gm.cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_session_keeps_snapshot_when_other_sessions_exist(self):
        """还有 session 存在时，snapshot repo 保留"""
        workspace = "/tmp/ws-keep"

        mock_db_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.one = MagicMock(return_value=1)  # 还有 1 个
        mock_db_session.exec = AsyncMock(return_value=mock_result)

        with patch("broca.session.database.db_manager") as mock_db_mgr, \
             patch("broca.snapshot.git_manager.GitManager") as MockGitMgr:
            mock_db_mgr.get_session = MagicMock(return_value=_acm(mock_db_session))

            from broca.session.cleanup_service import SessionCleanupService
            svc = SessionCleanupService()
            await svc.cleanup_snapshots_if_last_session(workspace)

            # GitManager 不应被调用
            MockGitMgr.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_failure_does_not_fail_delete(self, tmp_path):
        """清理异常不影响 API 返回（cleanup_session 不向上抛）"""
        workspace = str(tmp_path / "ws")

        with patch.object(
            _get_svc(), "cleanup_workspace_files",
            side_effect=PermissionError("Access denied")
        ), patch.object(
            _get_svc(), "cleanup_runner_logs",
            side_effect=OSError("disk full")
        ):
            svc = _get_svc()
            # 不应抛异常
            await svc.cleanup_session(workspace, "test-session")


# ------------------------------------------------------------------
# 批量删除集成测试
# ------------------------------------------------------------------

class TestBatchDeleteCleanup:
    """测试批量删除的完整清理流程"""

    @pytest.mark.asyncio
    async def test_batch_delete_sessions_cleans_all(self, tmp_path):
        """批量删除后，所有 session 的文件和日志被清理"""
        # 创建 2 个 workspace 的 session 文件
        ws1 = tmp_path / "ws1"
        ws2 = tmp_path / "ws2"
        ws1.mkdir()
        ws2.mkdir()

        session_ids = ["sess-1", "sess-2"]
        workspaces = {
            "sess-1": str(ws1),
            "sess-2": str(ws2),
        }

        for sid, ws in workspaces.items():
            session_dir = Path(ws) / ".broca" / sid
            session_dir.mkdir(parents=True)
            (session_dir / "test.md").write_text("data")

        # mock DB
        mock_db_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.one = MagicMock(return_value=0)
        mock_db_session.exec = AsyncMock(return_value=mock_result)

        # fake home for logs
        fake_home = tmp_path / "home"
        for sid in session_ids:
            log_dir = fake_home / ".broca" / "logs" / "runners" / sid
            log_dir.mkdir(parents=True)
            (log_dir / "test.log").write_text("log")

        with patch("broca.session.database.db_manager") as mock_db_mgr, \
             patch("broca.snapshot.git_manager.GitManager") as MockGitMgr, \
             patch("pathlib.Path.home", return_value=fake_home):
            mock_db_mgr.get_session = MagicMock(return_value=_acm(mock_db_session))
            mock_gm = MagicMock()
            mock_gm.repo_path = MagicMock()
            mock_gm.repo_path.exists = MagicMock(return_value=False)
            MockGitMgr.return_value = mock_gm

            from broca.session.cleanup_service import SessionCleanupService
            svc = SessionCleanupService()
            for sid in session_ids:
                await svc.cleanup_session(workspaces[sid], sid)

        # 验证所有文件被清理
        for sid, ws in workspaces.items():
            assert not (Path(ws) / ".broca" / sid).exists()

    @pytest.mark.asyncio
    async def test_batch_delete_same_workspace_snapshot_once(self):
        """同 workspace 的多个 session 删除，快照清理只触发一次"""
        workspace = "/tmp/ws-same"

        # 模拟：2 个 session 同 workspace，删除后无剩余
        mock_db_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.one = MagicMock(return_value=0)
        mock_db_session.exec = AsyncMock(return_value=mock_result)

        mock_gm = MagicMock()
        mock_gm.repo_path = MagicMock()
        # 第一次 exists=True（触发 cleanup），第二次 exists=False（跳过）
        exists_calls = [True, False]
        mock_gm.repo_path.exists = MagicMock(side_effect=exists_calls)

        with patch("broca.session.database.db_manager") as mock_db_mgr, \
             patch("broca.snapshot.git_manager.GitManager") as MockGitMgr:
            mock_db_mgr.get_session = MagicMock(return_value=_acm(mock_db_session))
            MockGitMgr.return_value = mock_gm

            from broca.session.cleanup_service import SessionCleanupService
            svc = SessionCleanupService()
            # 模拟批量删除 2 个同 workspace session
            await svc.cleanup_snapshots_if_last_session(workspace)
            await svc.cleanup_snapshots_if_last_session(workspace)

            # cleanup() 只应被调用一次（第一次时 repo 存在）
            assert mock_gm.cleanup.call_count == 1


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _acm(cm):
    """创建 async context manager mock"""
    cm.__aenter__ = AsyncMock(return_value=cm)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _get_svc():
    """获取新的 SessionCleanupService 实例"""
    from broca.session.cleanup_service import SessionCleanupService
    SessionCleanupService._instance = None
    return SessionCleanupService()
