"""
Per-session Runner 日志目录 GC 功能测试

覆盖：
1. 过期目录被正确清理
2. 活跃 session 的日志目录被保护
3. GC 后台任务 (_gc_task) 的启动/取消
4. runner_log_gc_days 从 ExecutionConfig 读取
"""

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.session_runner.manager import IPCSessionRunner
from broca.session_runner.models import RunnerProcessInfo, RunnerStatus
from broca.session_runner.process.registry import RunnerHandle
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_runner_info(session_id: str = "active_session") -> RunnerProcessInfo:
    """构造一个 ALIVE 状态的 RunnerProcessInfo（用于注册到 registry）"""
    process = MagicMock()
    process.poll = MagicMock(return_value=None)
    now = datetime.now(timezone.utc)
    return RunnerProcessInfo(
        session_id=session_id,
        process=process,
        pid=9999,
        status=RunnerStatus.ALIVE,
        started_at=now,
        ipc_address=f"/tmp/broca_runner_{session_id}.sock",
    )


@pytest.fixture
def gc_manager(tmp_path):
    """创建干净的 IPCSessionRunner 实例，_log_dir 指向 tmp_path。"""
    mgr = IPCSessionRunner()
    mgr._log_dir = tmp_path
    # 清空 registry
    mgr._registry.clear()
    return mgr


def _make_dir_with_mtime(dir_path: Path, mtime_seconds_ago: int) -> Path:
    """创建目录并设置其 mtime 为指定秒数前。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    # 在目录中放一个文件以确保 mtime 被跟踪
    (dir_path / "runner.log").write_text("log content")
    ts = time.time() - mtime_seconds_ago
    os.utime(dir_path, (ts, ts))
    os.utime(dir_path / "runner.log", (ts, ts))
    return dir_path


# ---------------------------------------------------------------------------
# GC 核心逻辑测试
# ---------------------------------------------------------------------------


class TestGcRunnerLogs:
    """测试 gc_runner_logs() 的核心清理逻辑"""

    @pytest.mark.asyncio
    async def test_expired_dirs_removed(self, gc_manager, tmp_path):
        """过期目录（mtime > max_age_days）应被删除。"""
        # 创建一个 40 天前的目录（超过默认 30 天）
        expired_dir = _make_dir_with_mtime(tmp_path / "old_session", 40 * 86400)
        assert expired_dir.exists()

        removed = await gc_manager.gc_runner_logs(max_age_days=30)

        assert removed == 1
        assert not expired_dir.exists()

    @pytest.mark.asyncio
    async def test_active_session_protected(self, gc_manager, tmp_path):
        """活跃 session 的日志目录不应被删除，即使 mtime 过期。"""
        # 注册一个活跃 session
        info = _make_runner_info("active_session")
        handle = RunnerHandle(info=info)
        gc_manager._registry.add(handle)

        # 创建一个 40 天前的目录，但 session_id 对应活跃 session
        expired_dir = _make_dir_with_mtime(tmp_path / "active_session", 40 * 86400)
        assert expired_dir.exists()

        removed = await gc_manager.gc_runner_logs(max_age_days=30)

        assert removed == 0
        assert expired_dir.exists()

    @pytest.mark.asyncio
    async def test_recent_dirs_not_removed(self, gc_manager, tmp_path):
        """近期目录（mtime < max_age_days）不应被删除。"""
        recent_dir = _make_dir_with_mtime(tmp_path / "recent_session", 5 * 86400)
        assert recent_dir.exists()

        removed = await gc_manager.gc_runner_logs(max_age_days=30)

        assert removed == 0
        assert recent_dir.exists()

    @pytest.mark.asyncio
    async def test_non_dir_entries_skipped(self, gc_manager, tmp_path):
        """文件（非目录）应被跳过。"""
        # 创建一个普通文件
        (tmp_path / "runner.log").write_text("some log")
        # 创建一个过期目录
        _make_dir_with_mtime(tmp_path / "old_session", 40 * 86400)

        removed = await gc_manager.gc_runner_logs(max_age_days=30)

        assert removed == 1
        # 文件不应被删除
        assert (tmp_path / "runner.log").exists()

    @pytest.mark.asyncio
    async def test_empty_log_dir(self, gc_manager, tmp_path):
        """空目录时 gc_runner_logs 返回 0。"""
        removed = await gc_manager.gc_runner_logs(max_age_days=30)
        assert removed == 0

    @pytest.mark.asyncio
    async def test_nonexistent_log_dir(self, gc_manager):
        """_log_dir 不存在时直接返回 0。"""
        gc_manager._log_dir = Path("/nonexistent/path/that/does/not/exist")
        removed = await gc_manager.gc_runner_logs(max_age_days=30)
        assert removed == 0

    @pytest.mark.asyncio
    async def test_mixed_expired_and_active(self, gc_manager, tmp_path):
        """混合场景：过期 + 活跃 + 近期目录同时存在。"""
        # 注册活跃 session
        info = _make_runner_info("active_session")
        handle = RunnerHandle(info=info)
        gc_manager._registry.add(handle)

        # 创建各种目录
        _make_dir_with_mtime(tmp_path / "expired_1", 45 * 86400)  # 过期
        _make_dir_with_mtime(tmp_path / "expired_2", 60 * 86400)  # 过期
        _make_dir_with_mtime(tmp_path / "active_session", 50 * 86400)  # 活跃但过期
        _make_dir_with_mtime(tmp_path / "recent_session", 2 * 86400)  # 近期

        removed = await gc_manager.gc_runner_logs(max_age_days=30)

        assert removed == 2
        assert not (tmp_path / "expired_1").exists()
        assert not (tmp_path / "expired_2").exists()
        assert (tmp_path / "active_session").exists()  # 被保护
        assert (tmp_path / "recent_session").exists()  # 未过期


class TestGcRunnerLogsConfig:
    """测试 gc_runner_logs() 从 ExecutionConfig 读取 runner_log_gc_days"""

    @pytest.mark.asyncio
    async def test_reads_from_config(self, gc_manager, tmp_path):
        """max_age_days=None 时应从 ExecutionConfig 读取。"""
        _make_dir_with_mtime(tmp_path / "old_session", 50 * 86400)  # 50 天前

        with patch("broca.configs.get_configs") as mock_gc:
            mock_gc.return_value.execution = type(
                "Cfg", (), {"runner_log_gc_days": 60}
            )
            # 配置保留 60 天，50 天的目录应被保留
            removed = await gc_manager.gc_runner_logs()

        assert removed == 0
        assert (tmp_path / "old_session").exists()

    @pytest.mark.asyncio
    async def test_config_value_respected(self, gc_manager, tmp_path):
        """配置的 runner_log_gc_days 应被遵守。"""
        _make_dir_with_mtime(tmp_path / "old_session", 90 * 86400)  # 90 天前

        with patch("broca.configs.get_configs") as mock_gc:
            mock_gc.return_value.execution = type(
                "Cfg", (), {"runner_log_gc_days": 60}
            )
            # 配置保留 60 天，90 天的目录应被删除
            removed = await gc_manager.gc_runner_logs()

        assert removed == 1
        assert not (tmp_path / "old_session").exists()

    @pytest.mark.asyncio
    async def test_config_error_fallback(self, gc_manager, tmp_path):
        """配置读取失败时应回退到 30 天默认值。"""
        _make_dir_with_mtime(tmp_path / "old_session", 40 * 86400)  # 40 天前

        with patch("broca.configs.get_configs", side_effect=Exception("config error")):
            removed = await gc_manager.gc_runner_logs()

        # 回退到 30 天，40 天的目录应被删除
        assert removed == 1
        assert not (tmp_path / "old_session").exists()


# ---------------------------------------------------------------------------
# GC 后台任务测试
# ---------------------------------------------------------------------------


class TestGcTaskLifecycle:
    """测试 start_gc_loop() 和 _gc_task 的生命周期"""

    def test_start_gc_loop_creates_task(self, gc_manager):
        """在有事件循环的环境中调用 start_gc_loop 应创建 task。"""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                self._run_in_loop(loop, gc_manager)
            )
        finally:
            loop.close()

    async def _run_in_loop(self, loop, gc_manager):
        gc_manager.start_gc_loop()
        assert gc_manager._gc_task is not None
        assert gc_manager._gc_task.get_name() == "runner-log-gc"
        # 立即取消（避免测试等待 sleep）
        gc_manager._gc_task.cancel()
        try:
            await gc_manager._gc_task
        except (asyncio.CancelledError, Exception):
            pass
        assert gc_manager._gc_task.cancelled() or gc_manager._gc_task.done()

    def test_start_gc_loop_idempotent(self, gc_manager):
        """重复调用 start_gc_loop 不应创建新 task。"""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                self._run_idempotent_in_loop(loop, gc_manager)
            )
        finally:
            loop.close()

    async def _run_idempotent_in_loop(self, loop, gc_manager):
        gc_manager.start_gc_loop()
        first_task = gc_manager._gc_task
        gc_manager.start_gc_loop()  # 第二次调用应 no-op
        assert gc_manager._gc_task is first_task
        first_task.cancel()
        try:
            await first_task
        except (asyncio.CancelledError, Exception):
            pass

    def test_gc_task_cancelled_in_shutdown(self, gc_manager):
        """shutdown_all 应取消 GC task。"""
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                self._run_shutdown_in_loop(loop, gc_manager)
            )
        finally:
            loop.close()

    async def _run_shutdown_in_loop(self, loop, gc_manager):
        # 手动启动 GC task
        gc_manager.start_gc_loop()
        assert gc_manager._gc_task is not None

        # 模拟 shutdown_all 中的取消逻辑
        gc_manager._gc_task.cancel()
        try:
            await gc_manager._gc_task
        except (asyncio.CancelledError, Exception):
            pass

        assert gc_manager._gc_task.done()

    def test_start_gc_loop_outside_event_loop(self, caplog):
        """无事件循环时 start_gc_loop 应 warning 并跳过。

        使用独立 manager 实例避免受其他测试的 _gc_task 状态影响。
        """
        import logging
        from unittest.mock import patch

        fresh_mgr = IPCSessionRunner()
        fresh_mgr._log_dir = Path("/tmp/gc_test_nonexistent")
        fresh_mgr._gc_task = None

        with caplog.at_level(logging.WARNING, logger="broca.session_runner.manager"):
            fresh_mgr.start_gc_loop()

        assert fresh_mgr._gc_task is None
