"""
Runner 心跳与状态收敛回归测试

覆盖修复前的三个真实缺陷：
1. 进程已退出却只把状态改成 ERROR，条目永不出清 → /runner/status 永久返回
   error，前端卡片永久显示"进程异常"。
2. 心跳从不落库（_save_runner_to_db 只在 start_session 调用一次），
   DB 的 status/last_heartbeat 永远停留在启动瞬间。
3. IPC 监听循环一旦抛异常就静默死掉且不重启；send_command 直接 recv 抢消息，
   会把心跳当响应吞掉。

以及 P1 的阻塞问题：
4. IPCServer.receive_message 把 poll(5s) 放在发送锁内，阻塞事件循环下发命令。
"""

import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.session_runner.manager import HEARTBEAT_GRACE_MULTIPLIER, IPCSessionRunner
from broca.session_runner.monitor import HeartbeatMonitor
from broca.session_runner.models import (
    IPCMessage,
    IPCMessageType,
    RunnerProcessInfo,
    RunnerStatus,
)
from broca.session_runner.ipc import IPCConnectionError, IPCServer, create_ipc_message
from broca.session_runner.process.registry import RunnerHandle

SESSION_ID = "session_heartbeat_test"


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_runner_info(
    status: RunnerStatus = RunnerStatus.ALIVE,
    heartbeat_age: float | None = 5.0,
    poll_returncode: int | None = None,
    session_id: str = SESSION_ID,
) -> RunnerProcessInfo:
    """构造一个带假进程的 RunnerProcessInfo"""
    process = MagicMock()
    process.poll = MagicMock(return_value=poll_returncode)
    now = datetime.now(timezone.utc)
    return RunnerProcessInfo(
        session_id=session_id,
        process=process,
        pid=4321,
        status=status,
        started_at=now - timedelta(seconds=600),
        ipc_address=f"/tmp/broca_runner_{session_id}.sock",
        last_heartbeat=(
            None if heartbeat_age is None else now - timedelta(seconds=heartbeat_age)
        ),
    )


def _feed(manager, session_id: str, messages) -> "asyncio.Queue":
    """把消息塞进该 session 的 IPC 队列（模拟 IPCPoller 的投递）。"""
    manager._poller.register(session_id, object())  # 连接对象只需非 None
    queue = manager._poller.queue(session_id)
    for msg in messages:
        queue.put_nowait(msg)
    return queue


def _register(manager, info: RunnerProcessInfo, ipc=None) -> RunnerHandle:
    """把 RunnerProcessInfo（+ 可选假 IPC）注册进 registry（替代旧的并行 dict）。"""
    handle = RunnerHandle(info=info, ipc=ipc)
    manager._registry.add(handle)
    return handle


@pytest.fixture
def manager():
    """干净的 RunnerManager 单例（避免测试间串状态）"""
    mgr = IPCSessionRunner()
    # Task 2.3 起全部运行时状态收在 RunnerRegistry，一个 clear() 即可隔离
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

    # monitor 持有的是构造时注入的协作者，需重新装配
    mgr._monitor = HeartbeatMonitor(
        policy=mgr._monitor.policy,
        registry=mgr._registry,
        repo=repo,
        reaper=mgr._reaper,
        events=events,
    )

    yield mgr

    for handle in mgr._registry.all():
        if handle.poll_task is not None and not handle.poll_task.done():
            handle.poll_task.cancel()
    for session_id in mgr._poller.registered():
        mgr._poller.unregister(session_id)
    mgr._registry.clear()


# ---------------------------------------------------------------------------
# P0-1: 进程退出 → 收敛为 DEAD 并清理
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_exit_converges_to_dead_and_cleans_up(manager):
    """进程已退出时必须收敛为 DEAD：写库、通知、标记断连、移除内存条目。

    回归 bug：旧实现只把 status 改成 ERROR 且不移除条目，
    /runner/status 会永久返回 error（前端永久"进程异常"）。
    """
    _register(manager, _make_runner_info(
        status=RunnerStatus.ALIVE,
        heartbeat_age=600.0,
        poll_returncode=-9,
    ))

    await manager._monitor.check_once(45.0)

    # 内存条目必须被移除（否则就是僵尸状态）
    assert SESSION_ID not in manager._registry
    # 状态收敛为 dead 并落库
    repo = manager._repo
    repo.upsert.assert_awaited_once()
    persisted = repo.upsert.await_args.args[0]
    assert persisted.status == RunnerStatus.DEAD
    assert "exited with code -9" in (persisted.error_message or "")
    # 通知 + agent 断连
    manager._events.emit.assert_awaited_once()
    assert manager._events.emit.await_args.args[0] == "session_crashed"
    repo.mark_agents_disconnected.assert_awaited_once_with(SESSION_ID)


@pytest.mark.asyncio
async def test_process_exit_converges_even_if_status_is_error(manager):
    """已经处于 error 的僵尸条目也必须被收敛（旧实现会永久跳过）。"""
    _register(manager, _make_runner_info(
        status=RunnerStatus.ERROR,
        heartbeat_age=999.0,
        poll_returncode=-9,
    ))

    await manager._monitor.check_once(45.0)

    assert SESSION_ID not in manager._registry


# ---------------------------------------------------------------------------
# P0-1: 心跳短暂延迟 → 不误判
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_heartbeat_delay_is_not_marked_error(manager):
    """心跳超时但仍在宽限期内（进程存活）时，不允许改状态。

    回归 bug：事件循环卡顿几十秒就被判 ERROR，前端误报"进程异常"。
    """
    info = _make_runner_info(
        status=RunnerStatus.ALIVE,
        heartbeat_age=50.0,  # > timeout(45) 但 < grace(135)
        poll_returncode=None,
    )
    _register(manager, info)

    await manager._monitor.check_once(45.0)

    assert info.status == RunnerStatus.ALIVE
    assert info.heartbeat_stale is True
    assert info.missed_heartbeats == 1
    manager._events.emit.assert_not_awaited()
    manager._repo.mark_agents_disconnected.assert_not_awaited()


@pytest.mark.asyncio
async def test_heartbeat_lost_beyond_grace_marks_error_but_keeps_entry(manager):
    """超过宽限期仍无心跳 → ERROR，但条目保留以便心跳恢复后自愈。"""
    grace = 45.0 * HEARTBEAT_GRACE_MULTIPLIER
    info = _make_runner_info(
        status=RunnerStatus.ALIVE,
        heartbeat_age=grace + 30.0,
        poll_returncode=None,
    )
    _register(manager, info)

    await manager._monitor.check_once(45.0)

    assert info.status == RunnerStatus.ERROR
    assert "Heartbeat lost" in (info.error_message or "")
    assert SESSION_ID in manager._registry  # 进程还活着，保留继续巡检
    # 进程存活时不把 agent 标记为 disconnected，避免前端反复闪断
    manager._repo.mark_agents_disconnected.assert_not_awaited()


@pytest.mark.asyncio
async def test_heartbeat_recovery_restores_alive(manager):
    """心跳恢复后自动回到 ALIVE 并清空错误信息/陈旧标记。"""
    info = _make_runner_info(
        status=RunnerStatus.ALIVE,
        heartbeat_age=45.0 * HEARTBEAT_GRACE_MULTIPLIER + 30.0,
        poll_returncode=None,
    )
    _register(manager, info)
    await manager._monitor.check_once(45.0)
    assert info.status == RunnerStatus.ERROR

    heartbeat = create_ipc_message(
        IPCMessageType.EVT_HEARTBEAT,
        SESSION_ID,
        payload={"status": "alive", "resource_usage": {"cpu_percent": 1.0}},
    )
    await manager._handle_runner_event(SESSION_ID, heartbeat)

    assert info.status == RunnerStatus.ALIVE
    assert info.error_message is None
    assert info.heartbeat_stale is False
    assert info.missed_heartbeats == 0


# ---------------------------------------------------------------------------
# P0-2: 心跳落库
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_runner_state_writes_once_then_throttles(manager):
    """心跳状态必须落库，且在 HEARTBEAT_PERSIST_INTERVAL 内不重复写。"""
    _register(manager, _make_runner_info(status=RunnerStatus.ALIVE))

    await manager._monitor._persist_states()
    # P1-5：批量落库（单事务），走 repo.upsert_many
    assert manager._repo.upsert_many.await_count == 1
    assert manager._registry.get(SESSION_ID).db_state_cache[0] == "alive"

    # 状态与心跳时间都没变 → 节流，不再写
    await manager._monitor._persist_states()
    assert manager._repo.upsert_many.await_count == 1

    # 状态变化 → 立即写
    manager._registry.get(SESSION_ID).info.status = RunnerStatus.ERROR
    await manager._monitor._persist_states()
    assert manager._repo.upsert_many.await_count == 2


# ---------------------------------------------------------------------------
# P0-3: IPC 监听自愈
# ---------------------------------------------------------------------------


class _FakeIPCServer:
    """按顺序吐出预设消息的假 IPC 服务端"""

    def __init__(self, messages):
        self._messages = list(messages)
        self.closed = False

    def receive_message(self, timeout: float = 5.0):
        if self._messages:
            item = self._messages.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        time.sleep(0.01)
        return None

    def send_message(self, msg) -> None:
        self.sent = msg

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_ipc_listener_survives_handler_exception(manager, monkeypatch):
    """单条消息处理抛异常不能拖垮监听循环（否则心跳永远不再被消费）。"""
    hb = [
        create_ipc_message(IPCMessageType.EVT_HEARTBEAT, SESSION_ID, payload={"status": "alive"}),
        create_ipc_message(IPCMessageType.EVT_HEARTBEAT, SESSION_ID, payload={"status": "alive"}),
    ]
    _register(
        manager, _make_runner_info(status=RunnerStatus.ALIVE), ipc=_FakeIPCServer(hb)
    )
    _feed(manager, SESSION_ID, hb)

    handled = []

    def flaky_handler(session_id, msg):
        handled.append(msg.type)
        if len(handled) == 1:
            raise RuntimeError("boom")

    # 用 monkeypatch 保证测试结束后恢复，避免污染单例（后续测试会因此静默失败）
    monkeypatch.setattr(manager, "_handle_runner_event", flaky_handler)

    task = asyncio.create_task(manager._ipc_listener_loop(SESSION_ID))
    await asyncio.sleep(0.5)

    # 第一条抛异常后循环仍然活着并处理了第二条
    assert len(handled) >= 2
    assert not task.done()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_ipc_listener_exits_on_connection_lost(manager):
    """IPC 断开时监听循环应退出，把后续判定交给心跳巡检。"""
    _register(
        manager,
        _make_runner_info(status=RunnerStatus.ALIVE),
        ipc=_FakeIPCServer([IPCConnectionError("broken")]),
    )
    # 连接断开 → poller 投递 None → 监听循环退出
    _feed(manager, SESSION_ID, [None])

    await asyncio.wait_for(manager._ipc_listener_loop(SESSION_ID), timeout=3.0)


# ---------------------------------------------------------------------------
# P1-4: 命令响应按 message_id 分发，不吞心跳
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_command_resolves_by_message_id_and_keeps_heartbeats(manager):
    """send_command 不再自己 recv：响应由监听循环按 message_id 分发。

    回归 bug：旧实现直接 receive_message，会把并发的 EVT_HEARTBEAT
    当成命令响应返回，同时这次心跳被丢弃。
    """
    fake = _FakeIPCServer([])
    _register(manager, _make_runner_info(status=RunnerStatus.ALIVE), ipc=fake)

    task = asyncio.create_task(
        manager.send_command(SESSION_ID, IPCMessageType.CMD_STATUS, {})
    )
    await asyncio.sleep(0.05)

    # 心跳先到：不应唤醒命令等待者
    await manager._handle_runner_event(
        SESSION_ID,
        create_ipc_message(
            IPCMessageType.EVT_HEARTBEAT, SESSION_ID, payload={"status": "alive"}
        ),
    )
    assert not task.done()

    # 命令响应到达（回显请求 message_id）
    await manager._handle_runner_event(
        SESSION_ID,
        IPCMessage(
            type=IPCMessageType.RESPONSE,
            session_id=SESSION_ID,
            message_id=fake.sent.message_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload={"status": "alive"},
        ),
    )

    result = await asyncio.wait_for(task, timeout=2.0)
    assert result == {"status": "alive"}
    assert manager._registry.get(SESSION_ID).pending_responses == {}


@pytest.mark.asyncio
async def test_send_command_times_out_without_response(manager):
    """没有响应时按超时返回错误，且清理 pending future。"""
    _register(
        manager, _make_runner_info(status=RunnerStatus.ALIVE), ipc=_FakeIPCServer([])
    )

    result = await manager.send_command(
        SESSION_ID, IPCMessageType.CMD_STATUS, {}, timeout=0.2
    )

    assert result == {"error": "No response from runner"}
    assert manager._registry.get(SESSION_ID).pending_responses == {}


# ---------------------------------------------------------------------------
# P1-4: IPC 收发解耦（poll 不再阻塞 send）
# ---------------------------------------------------------------------------


class _BlockingPollConnection:
    """poll() 会长时间等待的假连接"""

    def __init__(self, poll_seconds: float):
        self.poll_seconds = poll_seconds
        self.sent = []

    def poll(self, timeout: float = 0.0) -> bool:
        time.sleep(min(timeout, self.poll_seconds))
        return False

    def send(self, data) -> None:
        self.sent.append(data)

    def recv(self):  # pragma: no cover - poll 永远返回 False
        raise AssertionError("recv should not be called")

    def close(self) -> None:
        pass


def test_receive_message_does_not_block_send():
    """receive_message 的 poll 等待期间，send_message 必须立即可用。

    回归 bug：poll(5s) 在发送锁内执行，导致事件循环下发命令被卡 5s。
    """
    server = IPCServer(SESSION_ID)
    server._connection = _BlockingPollConnection(poll_seconds=3.0)

    poller = threading.Thread(target=lambda: server.receive_message(3.0), daemon=True)
    poller.start()
    time.sleep(0.2)  # 确保 poll 已经在等待中

    msg = create_ipc_message(IPCMessageType.CMD_STATUS, SESSION_ID, payload={})
    started = time.monotonic()
    server.send_message(msg)
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, f"send_message blocked for {elapsed:.2f}s during poll"
    assert server._connection.sent
    poller.join(timeout=5.0)


# ---------------------------------------------------------------------------
# 阈值配置化（原 heartbeat.py 死代码的 30/60 已删除，阈值统一进 configs.json）
# ---------------------------------------------------------------------------


def test_execution_config_exposes_heartbeat_settings():
    """configs.json 的 execution 分组必须接受并保留心跳三项配置。"""
    from broca.configs import ExecutionConfig

    cfg = ExecutionConfig.from_config(
        {
            "runner_heartbeat_interval": 3,
            "runner_heartbeat_timeout": 30,
            "runner_heartbeat_check_interval": 10,
        }
    )

    assert cfg.runner_heartbeat_interval == 3
    assert cfg.runner_heartbeat_timeout == 30
    assert cfg.runner_heartbeat_check_interval == 10


def test_default_heartbeat_settings_are_consistent():
    """默认阈值必须自洽：超时 >= 3 x 上报间隔，否则必然误判。"""
    from broca.configs import ExecutionConfig

    cfg = ExecutionConfig()
    assert cfg.runner_heartbeat_timeout >= cfg.runner_heartbeat_interval * 3
    assert cfg.runner_heartbeat_check_interval < cfg.runner_heartbeat_timeout


@pytest.mark.asyncio
async def test_start_heartbeat_monitor_uses_config_thresholds(manager, monkeypatch):
    """监控循环的 interval/timeout 必须来自配置而不是硬编码默认值。"""
    from broca.session_runner.monitor import HealthPolicy

    manager._monitor = HeartbeatMonitor(
        policy=HealthPolicy(interval=5.0, timeout=21.0, check_interval=7.0),
        registry=manager._registry,
        repo=manager._repo,
        reaper=manager._reaper,
        events=manager._events,
    )

    captured: dict = {}

    async def fake_loop(interval: float, timeout: float) -> None:
        captured["interval"] = interval
        captured["timeout"] = timeout

    monkeypatch.setattr(manager._monitor, "_loop", fake_loop)

    await manager.start_heartbeat_monitor()
    await asyncio.sleep(0)
    await manager.stop_heartbeat_monitor()

    assert captured == {"interval": 7.0, "timeout": 21.0}


@pytest.mark.asyncio
async def test_explicit_args_override_config(manager, monkeypatch):
    """显式传参仍优先于配置（兼容旧调用）。"""
    captured: dict = {}

    async def fake_loop(interval: float, timeout: float) -> None:
        captured["interval"] = interval
        captured["timeout"] = timeout

    monkeypatch.setattr(manager._monitor, "_loop", fake_loop)

    await manager.start_heartbeat_monitor(interval=1.0, timeout=2.0)
    await asyncio.sleep(0)
    await manager.stop_heartbeat_monitor()

    assert captured == {"interval": 1.0, "timeout": 2.0}
