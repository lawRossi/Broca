"""
Tests for runner startup cleanup (restore_active_sessions) and
graceful process termination (RunnerReaper.terminate_by_pid).

Covers the behavior change: after web service restart, orphaned
runner processes (still alive but IPC-broken) are killed, marked dead,
and associated Agent records are reset to 'disconnected'.
"""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.session_runner.models import RunnerProcessInfo, RunnerStatus
from broca.session_runner.process.reaper import RunnerReaper

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runner_record(session_id: str, pid: int | None, status: str = "alive"):
    """Create a mock SessionRunner DB record."""
    record = MagicMock()
    record.session_id = session_id
    record.pid = pid
    record.status = status
    record.error_message = None
    return record


def _make_agent_record(session_id: str, agent_id: str, agent_status: str = "running"):
    """Create a mock Agent DB record."""
    agent = MagicMock()
    agent.agent_id = agent_id
    agent.session_id = session_id
    agent.agent_status = agent_status
    return agent


def _acm(cm):
    """Create async context manager mock (mirrors project helper)."""
    cm.__aenter__ = AsyncMock(return_value=cm)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _mock_db_with_data(runner_records: list, agent_records: list):
    """
    Create a mock db_manager whose get_session() returns a session that:
    - First .exec() call returns runner records
    - Subsequent .exec() calls return agent records (grouped by session)
    """
    mock_db_session = AsyncMock()
    mock_db_session.add = MagicMock()
    mock_db_session.commit = AsyncMock()

    # Track exec calls: first is runner query, rest are agent queries
    call_count = [0]

    async def fake_exec(stmt):
        call_count[0] += 1
        if call_count[0] == 1:
            # Runner query
            result = MagicMock()
            result.all = MagicMock(return_value=runner_records)
            return result
        else:
            # Agent query — return agents for the current session
            # (we can't easily tell which session, so return all agents
            #  and let the test verify the correct ones are modified)
            result = MagicMock()
            result.all = MagicMock(return_value=agent_records)
            return result

    mock_db_session.exec = fake_exec

    mock_db_mgr = MagicMock()
    mock_db_mgr.get_session = MagicMock(return_value=_acm(mock_db_session))
    return mock_db_mgr, mock_db_session


def _get_manager():
    """Get a fresh IPCSessionRunner singleton (reset between tests)."""
    from broca.session_runner.manager import IPCSessionRunner

    IPCSessionRunner._instance = None
    mgr = IPCSessionRunner()
    return mgr


# ---------------------------------------------------------------------------
# restore_active_sessions
# ---------------------------------------------------------------------------


def _make_info(session_id: str, pid: int | None, status: RunnerStatus = RunnerStatus.ALIVE):
    """构造纯数据 RunnerProcessInfo（repo.list_active 的返回类型）。"""
    return RunnerProcessInfo(
        session_id=session_id,
        process=None,
        pid=pid,
        status=status,
    )


def _mock_repo(infos: list, disconnected_count: int = 0) -> AsyncMock:
    """用 AsyncMock 替换 RunnerRepository，返回给定的纯数据记录。"""
    repo = AsyncMock()
    repo.list_active = AsyncMock(return_value=infos)
    repo.upsert = AsyncMock()
    repo.mark_agents_disconnected = AsyncMock(return_value=disconnected_count)
    return repo


@pytest.mark.asyncio
class TestRestoreActiveSessions:
    """restore_active_sessions: startup cleanup of orphaned runners."""

    async def test_no_active_runners(self):
        """No alive/starting records → returns 0."""
        mgr = _get_manager()
        repo = _mock_repo([])
        mgr._repo = repo

        count = await mgr.restore_active_sessions()

        assert count == 0
        repo.upsert.assert_not_awaited()

    async def test_runner_without_pid_marked_dead(self):
        """Runner with no PID → marked dead, agent reset."""
        mgr = _get_manager()
        info = _make_info("sess-1", pid=None)
        repo = _mock_repo([info], disconnected_count=1)
        mgr._repo = repo

        count = await mgr.restore_active_sessions()

        assert count == 1
        assert info.status == RunnerStatus.DEAD
        assert "No PID" in info.error_message
        repo.upsert.assert_awaited_once_with(info)
        repo.mark_agents_disconnected.assert_awaited_once_with("sess-1")

    async def test_alive_runner_killed_and_agents_reset(self):
        """Runner with alive PID → killed, marked dead, agents reset to disconnected."""
        mgr = _get_manager()
        info = _make_info("sess-alive", pid=12345)
        repo = _mock_repo([info], disconnected_count=1)
        mgr._repo = repo

        with (
            patch.object(mgr._reaper, "is_alive", return_value=True),
            patch.object(
                mgr._reaper, "terminate_by_pid", AsyncMock(return_value=True)
            ) as mock_kill,
        ):
            count = await mgr.restore_active_sessions()

        assert count == 1
        assert info.status == RunnerStatus.DEAD
        assert "Orphaned runner" in info.error_message
        assert "12345" in info.error_message
        mock_kill.assert_awaited_once_with(12345, session_id="sess-alive")
        repo.mark_agents_disconnected.assert_awaited_once_with("sess-alive")

    async def test_dead_process_marked_dead_agents_reset(self):
        """Runner with dead PID → no kill, marked dead, agents reset."""
        mgr = _get_manager()
        info = _make_info("sess-dead", pid=99999)
        repo = _mock_repo([info], disconnected_count=1)
        mgr._repo = repo

        with (
            patch.object(mgr._reaper, "is_alive", return_value=False),
            patch.object(mgr._reaper, "terminate_by_pid", AsyncMock()) as mock_kill,
        ):
            count = await mgr.restore_active_sessions()

        assert count == 1
        assert info.status == RunnerStatus.DEAD
        assert "Process not found" in info.error_message
        mock_kill.assert_not_called()
        repo.mark_agents_disconnected.assert_awaited_once_with("sess-dead")

    async def test_already_disconnected_agent_not_affected(self):
        """Agents already disconnected → repo 返回 0，不影响收敛结果。"""
        mgr = _get_manager()
        info = _make_info("sess-ok", pid=123)
        repo = _mock_repo([info], disconnected_count=0)
        mgr._repo = repo

        with patch.object(mgr._reaper, "is_alive", return_value=False):
            count = await mgr.restore_active_sessions()

        assert count == 1
        assert info.status == RunnerStatus.DEAD
        repo.mark_agents_disconnected.assert_awaited_once_with("sess-ok")

    async def test_mixed_runners_all_reset(self):
        """Multiple runners → all marked dead, all agents reset."""
        mgr = _get_manager()
        infos = [
            _make_info("sess-nopid", pid=None),
            _make_info("sess-alive", pid=111),
            _make_info("sess-gone", pid=222),
        ]
        repo = _mock_repo(infos, disconnected_count=1)
        mgr._repo = repo

        with (
            patch.object(mgr._reaper, "is_alive", side_effect=[False, True, False]),
            patch.object(
                mgr._reaper, "terminate_by_pid", AsyncMock(return_value=True)
            ),
        ):
            count = await mgr.restore_active_sessions()

        assert count == 3
        assert all(i.status == RunnerStatus.DEAD for i in infos)
        assert repo.mark_agents_disconnected.await_count == 3

    async def test_error_status_runner_also_killed(self):
        """Runner with 'error' status (not just alive/starting) → also killed."""
        mgr = _get_manager()
        info = _make_info("sess-err", pid=5555, status=RunnerStatus.ERROR)
        repo = _mock_repo([info], disconnected_count=1)
        mgr._repo = repo

        with (
            patch.object(mgr._reaper, "is_alive", return_value=True),
            patch.object(
                mgr._reaper, "terminate_by_pid", AsyncMock(return_value=True)
            ) as mock_kill,
        ):
            count = await mgr.restore_active_sessions()

        assert count == 1
        assert info.status == RunnerStatus.DEAD
        mock_kill.assert_awaited_once_with(5555, session_id="sess-err")

    async def test_exception_returns_zero(self):
        """Exception during restore → caught, returns 0."""
        mgr = _get_manager()
        repo = AsyncMock()
        repo.list_active = AsyncMock(side_effect=RuntimeError("DB error"))
        mgr._repo = repo

        count = await mgr.restore_active_sessions()

        assert count == 0


# ---------------------------------------------------------------------------
# RunnerReaper.terminate_by_pid (graceful termination)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTerminateByPid:
    """RunnerReaper.terminate_by_pid: SIGTERM → 2s → SIGKILL。"""

    @patch("broca.session_runner.process.reaper.os.kill")
    @patch("sys.platform", "darwin")
    async def test_process_exits_after_sigterm(self, mock_kill):
        """Process responds to SIGTERM → no SIGKILL needed."""
        reaper = RunnerReaper()

        mock_kill.side_effect = [
            None,                # SIGTERM sent
            ProcessLookupError,  # polling: process gone
        ]

        result = await reaper.terminate_by_pid(4242)

        assert result is True
        assert mock_kill.call_args_list[0].args == (4242, signal.SIGTERM)
        sigkill_calls = [
            c for c in mock_kill.call_args_list
            if c.args and c.args[1] == signal.SIGKILL
        ]
        assert len(sigkill_calls) == 0

    @patch("broca.session_runner.process.reaper.os.kill")
    @patch("sys.platform", "darwin")
    async def test_process_survives_sigterm_escalates_to_sigkill(self, mock_kill):
        """Process ignores SIGTERM → SIGKILL after 2s timeout."""
        reaper = RunnerReaper()

        # 1 (SIGTERM) + 20 (still alive polls) + 1 (SIGKILL)
        mock_kill.side_effect = [None] * 22

        with patch(
            "broca.session_runner.process.reaper.asyncio.sleep",
            new=AsyncMock(return_value=None),
        ):
            result = await reaper.terminate_by_pid(9999)

        assert result is True
        last_call = mock_kill.call_args_list[-1]
        assert last_call.args == (9999, signal.SIGKILL)

    @patch("broca.session_runner.process.reaper.os.kill")
    @patch("sys.platform", "darwin")
    async def test_process_already_dead_on_sigterm(self, mock_kill):
        """Process gone before we send SIGTERM → returns True immediately."""
        reaper = RunnerReaper()

        mock_kill.side_effect = ProcessLookupError("No such process")

        result = await reaper.terminate_by_pid(1)

        assert result is True
        assert mock_kill.call_count == 1

    @patch("broca.session_runner.process.reaper.os.kill")
    @patch("sys.platform", "darwin")
    async def test_unexpected_exception_returns_false(self, mock_kill):
        """Unexpected error during kill → returns False."""
        reaper = RunnerReaper()

        mock_kill.side_effect = OSError("Permission denied")

        result = await reaper.terminate_by_pid(42)

        assert result is False
