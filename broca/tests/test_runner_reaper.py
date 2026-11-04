"""RunnerReaper 多因子判活 + RunnerRegistry 回归测试（Phase 2 Task 2.3）

核心风险（P2-1）：仅凭 ``pid_exists(pid)`` 判活不可信 —— PID 会被系统复用，
把无关进程当成 runner 杀掉是真实事故。``is_alive`` 必须同时校验
①进程存在 ②create_time 与记录一致 ③cmdline 含模块标识 + session_id，
任一不满足都**不得 kill**。
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from broca.session_runner.models import RunnerProcessInfo, RunnerStatus
from broca.session_runner.process.reaper import (
    CMDLINE_MODULE_MARKER,
    CREATE_TIME_TOLERANCE,
    RunnerReaper,
)
from broca.session_runner.process.registry import RunnerHandle, RunnerRegistry

SESSION_ID = "session-reaper-test"
STARTED_AT = datetime.now(timezone.utc) - timedelta(seconds=60)


def _make_info(pid: int = 4242, session_id: str = SESSION_ID) -> RunnerProcessInfo:
    """构造纯数据 RunnerProcessInfo（不带 process，模拟从 DB 恢复的记录）。"""
    return RunnerProcessInfo(
        session_id=session_id,
        process=None,
        pid=pid,
        status=RunnerStatus.ALIVE,
        started_at=STARTED_AT,
    )


class _FakePsutilProcess:
    """可控的 psutil.Process 替身。"""

    def __init__(self, create_time: float, cmdline, exc: Exception | None = None):
        self._create_time = create_time
        self._cmdline = cmdline
        self._exc = exc

    def create_time(self) -> float:
        if self._exc is not None:
            raise self._exc
        return self._create_time

    def cmdline(self):
        if isinstance(self._cmdline, Exception):
            raise self._cmdline
        return self._cmdline


def _patch_psutil(monkeypatch, fake_process):
    """把 psutil.Process 换成工厂函数；pid_exists 恒为 True（PID 存在）。"""
    import psutil

    monkeypatch.setattr(psutil, "pid_exists", lambda pid: True)
    monkeypatch.setattr(psutil, "Process", lambda pid: fake_process)


# ---------------------------------------------------------------------------
# 判活：绝不误杀
# ---------------------------------------------------------------------------


def test_pid_reuse_is_not_killed(monkeypatch):
    """PID 被复用（create_time 差 1 小时）→ 判死，且 terminate_orphans 不得 kill。"""
    # 无关进程：创建时间与记录差 3600s，远超容差
    fake = _FakePsutilProcess(
        create_time=STARTED_AT.timestamp() + 3600,
        cmdline=["/usr/bin/python3", "-m", CMDLINE_MODULE_MARKER, "--session-id", SESSION_ID],
    )
    _patch_psutil(monkeypatch, fake)

    info = _make_info()
    assert RunnerReaper().is_alive(info) is False

    with patch.object(
        RunnerReaper, "terminate_by_pid", AsyncMock(return_value=True)
    ) as mock_kill:
        import asyncio

        killed = asyncio.run(RunnerReaper().terminate_orphans([info]))

    assert killed == 0
    mock_kill.assert_not_awaited()


def test_cmdline_mismatch_is_not_killed(monkeypatch):
    """create_time 一致但 cmdline 不含模块标识 → 判死（不是我们的 runner）。"""
    fake = _FakePsutilProcess(
        create_time=STARTED_AT.timestamp() + CREATE_TIME_TOLERANCE / 2,
        cmdline=["/usr/bin/python3", "-c", "import http.server"],
    )
    _patch_psutil(monkeypatch, fake)

    assert RunnerReaper().is_alive(_make_info()) is False


def test_cmdline_session_id_mismatch_is_not_killed(monkeypatch):
    """cmdline 含模块标识但 session_id 不同（同机另一个 runner）→ 判死。"""
    fake = _FakePsutilProcess(
        create_time=STARTED_AT.timestamp(),
        cmdline=[
            "/usr/bin/python3",
            "-m",
            CMDLINE_MODULE_MARKER,
            "--session-id",
            "another-session",
        ],
    )
    _patch_psutil(monkeypatch, fake)

    assert RunnerReaper().is_alive(_make_info()) is False


def test_windows_empty_cmdline_degrades_to_two_factors(monkeypatch):
    """Windows 取不到 cmdline → 降级两因子，必须判活（不得因取不到就判死）。"""
    fake = _FakePsutilProcess(
        create_time=STARTED_AT.timestamp(),
        cmdline=[],  # Windows 常见：空 cmdline
    )
    _patch_psutil(monkeypatch, fake)

    assert RunnerReaper().is_alive(_make_info()) is True


def test_genuine_runner_is_killed(monkeypatch):
    """三因子全中 → 判活，terminate_orphans 必须调用 terminate_by_pid 一次。"""
    fake = _FakePsutilProcess(
        create_time=STARTED_AT.timestamp() + 0.05,
        cmdline=[
            "/usr/bin/python3",
            "-m",
            CMDLINE_MODULE_MARKER,
            "--session-id",
            SESSION_ID,
        ],
    )
    _patch_psutil(monkeypatch, fake)

    info = _make_info()
    assert RunnerReaper().is_alive(info) is True

    with patch.object(
        RunnerReaper, "terminate_by_pid", AsyncMock(return_value=True)
    ) as mock_kill:
        import asyncio

        killed = asyncio.run(RunnerReaper().terminate_orphans([info]))

    assert killed == 1
    mock_kill.assert_awaited_once_with(info.pid, session_id=SESSION_ID)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_active_count_includes_error_status():
    """ERROR / SHUTTING_DOWN 的活进程也占并发名额（P2-2：旧实现漏算）。"""
    registry = RunnerRegistry()
    for idx, status in enumerate(
        [
            RunnerStatus.STARTING,
            RunnerStatus.ALIVE,
            RunnerStatus.ERROR,
            RunnerStatus.SHUTTING_DOWN,
            RunnerStatus.DEAD,
        ]
    ):
        info = _make_info(session_id=f"session-{idx}")
        info.status = status
        registry.add(RunnerHandle(info=info))

    # DEAD 不计，其余 4 个都算
    assert len(registry) == 5
    assert registry.active_count() == 4


def test_registry_is_thread_safe():
    """并发 add/get/pop 不丢条目、不抛异常（IPC 线程与事件循环都会访问）。"""
    registry = RunnerRegistry()
    total = 200
    errors: list[BaseException] = []

    def _worker(start: int) -> None:
        try:
            for idx in range(start, total, 8):
                info = _make_info(session_id=f"session-{idx}")
                registry.add(RunnerHandle(info=info))
                registry.get(f"session-{idx}")
        except BaseException as exc:  # pragma: no cover - 失败时用于报错
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(registry) == total
    assert sorted(registry.keys()) == sorted(f"session-{i}" for i in range(total))
