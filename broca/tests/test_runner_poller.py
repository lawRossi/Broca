"""IPC 单线程多路复用（IPCPoller）回归测试。

修复前：每个 session 一个 daemon 线程跑阻塞 ``receive_message(5.0)``，
10 个 session = 10 个线程 + 10 个 5 秒超时轮询。

修复后：一个 ``ipc-poller`` 线程用 ``multiprocessing.connection.wait()``
同时等待所有连接，再通过 ``loop.call_soon_threadsafe`` 把消息投递到
每个 session 的 asyncio 队列。

本文件守住 5 件事：
1. 多连接只用一个线程（线程数不随 session 数增长）
2. 连接断开时自动注销，并投递哨兵 ``None``（让消费侧优雅退出）
3. 不忙等（wait 的真实超时被用上，1 秒内调用次数是数量级级的小）
4. wait 期间被注销是安全的（不抛 KeyError / 不杀线程）
5. 线上格式（JSON 字符串）必须被解码；脏数据只丢一条、不杀线程
"""

import asyncio
import json
import multiprocessing
import os
import threading
import time
from typing import Any, List
from unittest.mock import patch

import pytest
import pytest_asyncio

from broca.session_runner.poller import IDLE_SLEEP, POLL_TIMEOUT, THREAD_NAME, IPCPoller

SESSION_A = "session_poller_a"
SESSION_B = "session_poller_b"
SESSION_C = "session_poller_c"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _poll_threads() -> List[threading.Thread]:
    return [t for t in threading.enumerate() if t.name.startswith(THREAD_NAME)]


async def _wait_for(predicate, timeout: float = 3.0) -> bool:
    """在超时内轮询等待 predicate() 为真。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


@pytest_asyncio.fixture
async def poller():
    """一个已启动的 IPCPoller，测试结束自动停线程。"""
    p = IPCPoller()
    p.start(asyncio.get_running_loop())
    try:
        yield p
    finally:
        p.stop()


# ---------------------------------------------------------------------------
# 1. 单线程多连接
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_thread_handles_multiple_connections():
    """10 个连接、1 个线程：每个队列各自收到属于自己的消息。

    AC 口径：``threading.active_count()`` 增量 ≤ 3，且新增线程名全部以
    ``ipc-poller`` 为前缀。``active_count()`` 是进程级全局量，只看增量
    会被 pytest 前序测试的遗留线程干扰，所以同时校验线程名。
    """
    session_ids = [f"session_poller_{i}" for i in range(10)]

    poller = IPCPoller()
    before_threads = set(threading.enumerate())
    before_count = threading.active_count()

    poller.start(asyncio.get_running_loop())
    pipes = {}
    try:
        for session_id in session_ids:
            parent, child = multiprocessing.Pipe()
            pipes[session_id] = (parent, child)
            poller.register(session_id, parent)

        assert poller.running is True

        new_threads = set(threading.enumerate()) - before_threads
        assert threading.active_count() - before_count <= 3
        assert len(new_threads) == 1, f"10 个 session 起了 {len(new_threads)} 个线程"
        assert all(t.name.startswith(THREAD_NAME) for t in new_threads), (
            f"新增线程名不是 ipc-poller 前缀: {[t.name for t in new_threads]}"
        )
        assert poller.thread in new_threads
        assert len(poller.registered()) == 10

        for session_id, (_, child) in pipes.items():
            child.send(f"hello-{session_id}")

        for session_id in session_ids:
            queue = poller.queue(session_id)
            assert queue is not None
            msg = await asyncio.wait_for(queue.get(), timeout=5.0)
            assert msg == f"hello-{session_id}"
    finally:
        for parent, child in pipes.values():
            parent.close()
            child.close()
        poller.stop()


@pytest.mark.asyncio
async def test_unregister_removes_queue(poller):
    """注销后 queue() 返回 None，重复注销不抛异常。"""
    parent, child = multiprocessing.Pipe()
    poller.register(SESSION_A, parent)
    assert poller.queue(SESSION_A) is not None

    poller.unregister(SESSION_A)
    assert poller.queue(SESSION_A) is None
    assert SESSION_A not in poller.registered()

    poller.unregister(SESSION_A)  # 幂等
    parent.close()
    child.close()


# ---------------------------------------------------------------------------
# 2. 断连处理
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broken_connection_is_unregistered(poller):
    """对端关闭 → recv 抛 EOFError → 自动注销 + 投递 None 哨兵。"""
    parent, child = multiprocessing.Pipe()
    poller.register(SESSION_A, parent)
    queue = poller.queue(SESSION_A)

    child.close()  # 模拟 runner 子进程崩溃

    msg = await asyncio.wait_for(queue.get(), timeout=3.0)
    assert msg is None, "断连必须投递 None，否则消费侧会永久阻塞"

    assert await _wait_for(lambda: SESSION_A not in poller.registered()), (
        "断连的连接必须被注销，否则 wait() 会持续对死连接报错"
    )

    # 线程仍存活，继续服务其他 session
    assert poller.running is True
    parent.close()


@pytest.mark.asyncio
async def test_other_sessions_survive_one_broken_connection(poller):
    """一个 session 断连不影响另一个 session 的消息投递。"""
    parent_a, child_a = multiprocessing.Pipe()
    parent_b, child_b = multiprocessing.Pipe()
    poller.register(SESSION_A, parent_a)
    poller.register(SESSION_B, parent_b)

    queue_a = poller.queue(SESSION_A)
    queue_b = poller.queue(SESSION_B)

    child_a.close()
    child_b.send("still-alive")

    assert await asyncio.wait_for(queue_a.get(), timeout=3.0) is None
    assert await asyncio.wait_for(queue_b.get(), timeout=3.0) == "still-alive"

    parent_a.close()
    parent_b.close()
    child_b.close()


# ---------------------------------------------------------------------------
# 3. 不忙等
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poller_does_not_busy_wait(poller):
    """1 秒内 wait() 调用次数必须是「数量级级别的小」，不能是忙等。

    真实 ``wait(timeout=0.5)`` 每秒约 2 次；忙等实现会达到数千次。
    阈值取 20（10 倍余量），只判数量级，不贴近上限。
    """
    from broca.session_runner import poller as poller_module

    real_wait = poller_module.wait
    calls = {"n": 0}

    def counting_wait(object_list, timeout=None):
        calls["n"] += 1
        return real_wait(object_list, timeout)

    parent, child = multiprocessing.Pipe()
    poller.register(SESSION_A, parent)

    with patch.object(poller_module, "wait", counting_wait):
        await asyncio.sleep(1.0)

    parent.close()
    child.close()

    assert calls["n"] >= 1, "wait() 根本没被调用，测试无效"
    assert calls["n"] <= 20, (
        f"1 秒内 wait() 被调用 {calls['n']} 次 —— 存在忙等（应 ≈ 1s/{POLL_TIMEOUT}s）"
    )


@pytest.mark.asyncio
async def test_poller_sleeps_when_no_connections(poller):
    """空连接列表时不能忙等（wait([]) 会立即返回）。"""
    assert poller.registered() == []
    cpu_before = time.process_time()
    await asyncio.sleep(0.6)
    cpu_used = time.process_time() - cpu_before
    # 忙等会在 0.6s 内烧掉大量 CPU；正常应远低于 0.1s
    assert cpu_used < 0.1, f"无连接时忙等，0.6s 内消耗 {cpu_used:.3f}s CPU"
    assert IDLE_SLEEP > 0


# ---------------------------------------------------------------------------
# 4. 并发注销安全性
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unregister_during_wait_is_safe(poller):
    """wait() 持有旧快照时被注销：不抛异常、不杀线程、其它 session 不受影响。"""
    parent_a, child_a = multiprocessing.Pipe()
    parent_b, child_b = multiprocessing.Pipe()
    poller.register(SESSION_A, parent_a)
    poller.register(SESSION_B, parent_b)
    queue_b = poller.queue(SESSION_B)

    # 在 wait 的窗口期内注销 A（此时线程大概率持有一份含 A 的快照）
    poller.unregister(SESSION_A)
    await asyncio.sleep(POLL_TIMEOUT * 1.5)

    assert poller.running is True
    assert poller.thread is not None and poller.thread.is_alive()

    child_b.send("b-ok")
    assert await asyncio.wait_for(queue_b.get(), timeout=3.0) == "b-ok"

    parent_a.close()
    parent_b.close()
    child_a.close()
    child_b.close()


@pytest.mark.asyncio
async def test_register_rejects_none_connection(poller):
    """register(None) 必须报错 —— 否则会静默丢消息（accept 未完成）。"""
    with pytest.raises(ValueError, match="None connection"):
        poller.register(SESSION_A, None)


@pytest.mark.asyncio
async def test_start_and_stop_are_idempotent():
    """start/stop 幂等，stop 后线程退出。"""
    p = IPCPoller()
    p.start(asyncio.get_running_loop())
    p.start(asyncio.get_running_loop())
    assert len([t for t in _poll_threads() if t.is_alive()]) >= 1
    p.stop()
    p.stop()
    assert p.running is False


# ---------------------------------------------------------------------------
# 5. manager 集成：注册 / 消费 / 统计
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def manager():
    """重置单例的 poller 相关状态，避免跨测试污染。"""
    from broca.session_runner.manager import IPCSessionRunner

    mgr = IPCSessionRunner()
    saved_poller = mgr._poller
    try:
        yield mgr
    finally:
        mgr._poller.stop()
        for session_id in mgr._registry.keys():
            mgr._registry.pop(session_id)
        mgr._poller = saved_poller


class _FakeIPCServer:
    """最小 IPC server 桩：提供 connection / receive_message。"""

    def __init__(self, messages: List[Any] | None = None):
        self.connection = object()
        self._messages = list(messages or [])

    def receive_message(self, timeout=None):
        if self._messages:
            return self._messages.pop(0)
        raise TimeoutError("no more messages")


def _handle_for(session_id: str):
    from datetime import datetime, timezone

    from broca.session_runner.models import RunnerProcessInfo, RunnerStatus
    from broca.session_runner.process.registry import RunnerHandle

    info = RunnerProcessInfo(
        session_id=session_id,
        process=None,
        pid=1234,
        status=RunnerStatus.ALIVE,
        started_at=datetime.now(timezone.utc),
        ipc_address=f"/tmp/broca_{session_id}.sock",
        last_heartbeat=datetime.now(timezone.utc),
    )
    return RunnerHandle(info=info)


@pytest.mark.asyncio
async def test_attach_listener_uses_poller(manager):
    """_attach_listener 只走 IPCPoller（回滚路径已下线，不再有 per-session 线程）。"""
    manager._poller = IPCPoller()

    server = _FakeIPCServer()
    handle = _handle_for(SESSION_A)
    handle.ipc = server
    manager._registry.add(handle)

    manager._attach_listener(handle)
    try:
        assert SESSION_A in manager._poller.registered()
        assert manager._poller.queue(SESSION_A) is not None
        assert handle.poll_task is not None
        assert handle.poll_thread is None, "不允许再起 per-session 轮询线程"
    finally:
        if handle.poll_task is not None:
            handle.poll_task.cancel()


# ---------------------------------------------------------------------------
# 5.1 线上格式解码（Task 4.2 缺陷①的回归）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poller_decodes_wire_format_into_ipc_message():
    """recv() 拿到的是 JSON 字符串，poller 必须解码成 IPCMessage。

    回归（Task 4.2 缺陷①）：旧实现走 ``IPCServer.receive_message()``，它内部
    做了 ``_decode``，问题被掩盖。漏传 ``decode`` 时所有消息会在 ``msg.type``
    上抛 ``AttributeError``，被 ``_ipc_listener_loop`` 的兜底 except 吞成一行
    日志 —— 表现为「runner 起来了但状态永远不更新」，极难定位。
    """
    from broca.session_runner.ipc import create_ipc_message
    from broca.session_runner.models import IPCMessageType, decode_ipc_message

    p = IPCPoller(decode=decode_ipc_message)
    p.start(asyncio.get_running_loop())
    parent, child = multiprocessing.Pipe()
    try:
        p.register(SESSION_A, parent)
        msg = create_ipc_message(IPCMessageType.EVT_HEARTBEAT, SESSION_A)
        child.send(json.dumps(msg.to_dict()))

        queue = p.queue(SESSION_A)
        received = await asyncio.wait_for(queue.get(), timeout=3.0)

        assert not isinstance(received, (str, bytes)), (
            "poller 必须解码，不能把原始字符串交给消费侧"
        )
        assert received.type == IPCMessageType.EVT_HEARTBEAT
        assert received.session_id == SESSION_A
    finally:
        parent.close()
        child.close()
        p.stop()


@pytest.mark.asyncio
async def test_undecodable_message_is_dropped_without_killing_thread():
    """脏数据只丢这一条：线程必须活着，并继续投递后续消息。"""
    from broca.session_runner.ipc import create_ipc_message
    from broca.session_runner.models import IPCMessageType, decode_ipc_message

    p = IPCPoller(decode=decode_ipc_message)
    p.start(asyncio.get_running_loop())
    parent, child = multiprocessing.Pipe()
    try:
        p.register(SESSION_A, parent)
        queue = p.queue(SESSION_A)

        child.send("not-a-json{{{")
        child.send(
            json.dumps(
                create_ipc_message(IPCMessageType.EVT_HEARTBEAT, SESSION_A).to_dict()
            )
        )

        received = await asyncio.wait_for(queue.get(), timeout=3.0)
        assert received.type == IPCMessageType.EVT_HEARTBEAT
        assert p.running is True
        assert p.thread.is_alive(), "单条脏数据不得杀死轮询线程"
    finally:
        parent.close()
        child.close()
        p.stop()


@pytest.mark.asyncio
async def test_poller_to_listener_loop_end_to_end(manager):
    """poller + _ipc_listener_loop + router 全链路（真实 pipe）。"""
    from broca.session_runner.ipc import create_ipc_message
    from broca.session_runner.models import IPCMessageType

    # 刻意使用 manager 自己构造的 poller（不替换）：
    # 这样 manager 若漏传 decode，本测试会立刻变红
    handle = _handle_for(SESSION_A)
    handle.ipc = _FakeIPCServer()
    manager._registry.add(handle)

    parent, child = multiprocessing.Pipe()
    manager._poller.start(asyncio.get_running_loop())
    manager._poller.register(SESSION_A, parent)

    seen = []

    async def fake_handler(session_id, msg):
        seen.append((session_id, msg.type))

    manager._handle_runner_event = fake_handler
    task = asyncio.create_task(manager._ipc_listener_loop(SESSION_A))
    try:
        child.send(
            json.dumps(
                create_ipc_message(IPCMessageType.EVT_HEARTBEAT, SESSION_A).to_dict()
            )
        )
        assert await _wait_for(lambda: bool(seen)), "消息没有走完 poller → listener"
        assert seen[0] == (SESSION_A, IPCMessageType.EVT_HEARTBEAT)
    finally:
        task.cancel()
        parent.close()
        child.close()


@pytest.mark.asyncio
async def test_stats_reports_ipc_state(manager):
    """get_stats 暴露 IPC 运行状态（线程数恒为 0/1，可据此告警）。"""
    stats = manager.get_stats()
    assert stats["ipc"]["poller_running"] is False
    assert stats["ipc"]["dropped_count"] == 0
    assert stats["ipc"]["queue_size"] > 0
    # 回滚开关已下线，不再有恒为 true 的 multiplexing 字段
    assert "multiplexing" not in stats["ipc"]


@pytest.mark.asyncio
async def test_queue_full_increments_dropped_count():
    """队列满时不阻塞 poller 线程，只累加 dropped_count（背压观测点）。"""
    p = IPCPoller(queue_size=1)
    p.start(asyncio.get_running_loop())
    parent, child = multiprocessing.Pipe()
    try:
        p.register(SESSION_A, parent)
        queue = p.queue(SESSION_A)
        queue.put_nowait("occupier")  # 占满唯一的槽位

        for i in range(3):
            child.send(f"msg-{i}")
        assert await _wait_for(lambda: p.dropped_count >= 3, timeout=3.0), (
            "队列满时消息应被丢弃并计数，而不是阻塞轮询线程"
        )
        # 线程仍活着 —— 背压不能靠「卡住 poller」实现
        assert p.running is True
        assert p.thread.is_alive()
    finally:
        parent.close()
        child.close()
        p.stop()


@pytest.mark.asyncio
async def test_closed_connection_is_pruned(poller):
    """release_handle / ipc.close() 之后连接 fileno 为 None → 必须被剔除。

    否则 ``wait()`` 抛 TypeError（不是 OSError），轮询线程会反复空转报错。
    """
    parent, child = multiprocessing.Pipe()
    poller.register(SESSION_A, parent)
    assert SESSION_A in poller.registered()

    parent.close()  # 模拟 IPCServer.close()

    assert await _wait_for(lambda: SESSION_A not in poller.registered(), timeout=3.0), (
        "已关闭的连接没有被剔除，wait() 会持续报 TypeError"
    )
    assert poller.running is True
    assert poller.thread.is_alive()
    child.close()


@pytest.mark.asyncio
async def test_real_ipc_server_client_through_poller():
    """真实 transport 全链路：IPCServer.accept() → poller → IPCMessage。

    前面的用例用 ``multiprocessing.Pipe()`` 造连接，验证不了「线上格式 +
    真实 accept 时序」。这里用真实 IPCServer / IPCClient 走一遍，确保
    ``register(ipc_server.connection)`` 拿到的是可被 ``wait()`` 使用的对象。
    """
    from broca.session_runner.ipc import IPCServer, create_ipc_message
    from broca.session_runner.models import IPCMessageType, decode_ipc_message
    from broca.session_runner.transport.client import IPCClient

    session_id = f"poller-real-{os.getpid()}"
    server = IPCServer(session_id)
    await server.start()
    client = IPCClient(session_id)

    poller = IPCPoller(decode=decode_ipc_message)
    poller.start(asyncio.get_running_loop())
    try:
        # accept 是阻塞调用，必须先并发起它再 connect，否则互等
        accept_task = asyncio.create_task(asyncio.to_thread(server.accept, 10.0))
        await asyncio.sleep(0.1)
        assert client.connect() is True
        assert await asyncio.wait_for(accept_task, timeout=15.0) is True

        poller.register(session_id, server.connection)
        queue = poller.queue(session_id)

        sent = create_ipc_message(
            IPCMessageType.EVT_HEARTBEAT, session_id, payload={"status": "alive"}
        )
        await asyncio.to_thread(client.send_message, sent)

        received = await asyncio.wait_for(queue.get(), timeout=5.0)
        assert received.__class__.__name__ == "IPCMessage"
        assert received.type == IPCMessageType.EVT_HEARTBEAT
        assert received.session_id == session_id
    finally:
        client.close()
        server.close()
        poller.stop()
