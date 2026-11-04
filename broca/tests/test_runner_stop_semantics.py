"""优雅停止 vs 进程崩溃的语义回归测试（P0-5 + P2-3）

历史 bug：
- ``process.poll()`` 判死时不区分状态：用户主动 stop 只置 ``SHUTTING_DOWN``，
  巡检却照样判 ``dead`` 并触发 ``session_crashed``，前端把正常停止误报为崩溃；
- ``stop_session`` 先移除内存条目再发 shutdown，导致 ``SHUTTING_DOWN``
  对外不可见、``RESPONSE`` 永远被丢弃。
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.components.session_runner import SessionRunner as SessionRunnerABC
from broca.session_runner import manager as manager_module
from broca.session_runner.manager import IPCSessionRunner
from broca.session_runner.monitor import HeartbeatMonitor
from broca.session_runner.models import (
    IPCMessageType,
    RunnerProcessInfo,
    RunnerStatus,
)
from broca.session_runner.ipc import create_ipc_message
from broca.session_runner.process.registry import RunnerHandle

SESSION_ID = "session_stop_semantics"

API_FILE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "broca-web"
    / "backend"
    / "app"
    / "api"
    / "session_runner.py"
)


def _make_runner_info(
    status: RunnerStatus = RunnerStatus.ALIVE,
    poll_returncode: int | None = None,
) -> RunnerProcessInfo:
    process = MagicMock()
    process.poll = MagicMock(return_value=poll_returncode)
    process.wait = MagicMock(return_value=0)
    now = datetime.now(timezone.utc)
    return RunnerProcessInfo(
        session_id=SESSION_ID,
        process=process,
        pid=4321,
        status=status,
        started_at=now - timedelta(seconds=600),
        last_heartbeat=now - timedelta(seconds=1),
    )


def _register(manager, info: RunnerProcessInfo, ipc=None) -> RunnerHandle:
    """把 RunnerProcessInfo（+ 可选假 IPC）注册进 registry。"""
    handle = RunnerHandle(info=info, ipc=ipc)
    manager._registry.add(handle)
    return handle


class _FakeIPCServer:
    """记录 send_message 调用的假 IPC 服务端。"""

    def __init__(self) -> None:
        self.sent: list = []
        self.closed = False

    def send_message(self, msg) -> None:
        self.sent.append(msg)

    def receive_message(self, timeout: float = 0.0):
        return None

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def manager():
    IPCSessionRunner._instance = None
    mgr = IPCSessionRunner()
    mgr._registry.clear()

    # Task 3.1：心跳巡检迁入 HeartbeatMonitor，DB/事件协作者改为 mock
    repo = MagicMock()
    repo.upsert = AsyncMock()
    repo.upsert_many = AsyncMock()
    repo.delete = AsyncMock()
    repo.mark_agents_disconnected = AsyncMock(return_value=1)
    mgr._repo = repo

    events = MagicMock()
    events.emit = AsyncMock()
    events.emit_soon = MagicMock()
    mgr._events = events

    mgr._monitor = HeartbeatMonitor(
        policy=mgr._monitor.policy,
        registry=mgr._registry,
        repo=repo,
        reaper=mgr._reaper,
        events=events,
    )
    yield mgr

    mgr._registry.clear()


# ---------------------------------------------------------------------------
# 事件语义分流
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_stop_emits_session_stopped_not_crashed(manager):
    """主动 stop 后必须发 session_stopped，session_crashed 计数为 0。"""
    info = _make_runner_info(status=RunnerStatus.ALIVE)
    _register(manager, info, ipc=_FakeIPCServer())

    assert await manager.stop_session(SESSION_ID, timeout=1.0) is True

    events = [call.args[0] for call in manager._events.emit.await_args_list]
    assert events == ["session_stopped"], events
    assert "session_crashed" not in events


@pytest.mark.asyncio
async def test_stop_requested_survives_heartbeat_check(manager):
    """巡检看到 stop_requested 的已退出进程时，走 stopped 而不是 crashed。"""
    info = _make_runner_info(
        status=RunnerStatus.SHUTTING_DOWN, poll_returncode=0
    )
    info.stop_requested = True
    _register(manager, info)

    await manager._monitor.check_once(45.0)

    events = [call.args[0] for call in manager._events.emit.await_args_list]
    assert events == ["session_stopped"], events
    # 主动停止不产生「断连」告警
    manager._repo.mark_agents_disconnected.assert_not_awaited()
    assert SESSION_ID not in manager._registry


@pytest.mark.asyncio
async def test_unexpected_exit_still_emits_session_crashed(manager):
    """非主动退出（poll 返回非 0）仍然必须触发 session_crashed。"""
    info = _make_runner_info(status=RunnerStatus.ALIVE, poll_returncode=1)
    _register(manager, info)

    await manager._monitor.check_once(45.0)

    events = [call.args[0] for call in manager._events.emit.await_args_list]
    assert events == ["session_crashed"], events
    manager._repo.mark_agents_disconnected.assert_awaited_once_with(SESSION_ID)


# ---------------------------------------------------------------------------
# SHUTTING_DOWN 对外可见
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutting_down_status_visible_via_get_status(manager):
    """stop 进行中（进程尚未退出）时 get_status 必须返回 shutting_down。"""
    info = _make_runner_info(status=RunnerStatus.ALIVE)
    _register(manager, info)

    # request_stop 只标记不等待，是「停止进行中」的可观测窗口
    result = await manager.request_stop(SESSION_ID)
    assert result["status"] == "stopping"

    status = manager.get_status(SESSION_ID)
    assert status is not None, "stop 进行中条目不能被移除"
    assert status["status"] == RunnerStatus.SHUTTING_DOWN.value


@pytest.mark.asyncio
async def test_request_stop_sends_shutdown_and_keeps_entry(manager):
    """request_stop 必须发出 CMD_SHUTDOWN 并保留条目（P2-3 回归）。"""
    info = _make_runner_info(status=RunnerStatus.ALIVE)
    fake = _FakeIPCServer()
    _register(manager, info, ipc=fake)

    await manager.request_stop(SESSION_ID)

    assert SESSION_ID in manager._registry
    assert info.stop_requested is True
    assert len(fake.sent) == 1
    assert fake.sent[0].type == IPCMessageType.CMD_SHUTDOWN


# ---------------------------------------------------------------------------
# 抽象泄漏：API 层不得触碰私有属性
# ---------------------------------------------------------------------------


def test_request_stop_does_not_touch_private_attrs():
    """API 层源码中不得出现对管理器私有状态字典的访问。"""
    source = API_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.attr, str):
            if node.attr in {"_runners", "_ipc_servers"}:
                offenders.append(f"{node.lineno}: {node.attr}")

    assert not offenders, f"API 层仍在访问私有属性: {offenders}"


# ---------------------------------------------------------------------------
# ABC 契约
# ---------------------------------------------------------------------------


def test_request_stop_declared_in_abc():
    """request_stop 必须在 ABC 中声明，且实现类已实现（不在 __abstractmethods__）。"""
    assert "request_stop" in SessionRunnerABC.__abstractmethods__
    assert "request_stop" not in IPCSessionRunner.__abstractmethods__


def test_request_stop_is_async():
    """ABC 中的 request_stop 必须是协程方法（API 层以 await 调用）。"""
    import inspect

    assert inspect.iscoroutinefunction(SessionRunnerABC.request_stop)
    assert inspect.iscoroutinefunction(IPCSessionRunner.request_stop)
