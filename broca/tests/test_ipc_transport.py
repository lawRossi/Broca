"""IPC 传输层（transport/）回归测试

覆盖拆分后必须保持的三个性质：
1. Server/Client 共用 ``_BaseIPC``，双向收发正常；
2. ``send_message`` 的锁在 Client 侧同样生效——4 线程并发 send 不会交错坏帧
   （历史上 Client 没有发送锁，Windows 命名管道上并发写会破坏消息）；
3. ``send`` 与 ``recv`` 用独立锁，``poll()`` 等待期间下发命令不被阻塞。
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid

import pytest

from broca.session_runner.ipc import (
    IPCClient,
    IPCConnectionError,
    IPCServer,
    create_ipc_message,
)
from broca.session_runner.models import IPCMessageType
from broca.session_runner.transport.base import _BaseIPC
from broca.session_runner.transport.client import IPCClient as TransportClient
from broca.session_runner.transport.server import IPCServer as TransportServer


def _sid() -> str:
    return f"ipc_transport_{uuid.uuid4().hex[:10]}"


async def _start_pair() -> tuple[IPCServer, IPCClient]:
    """启动一对已连通的 server/client。"""
    session_id = _sid()
    server = IPCServer(session_id)
    await server.start()
    client = IPCClient(session_id)
    client.connect()
    server.accept(timeout=5.0)
    return server, client


# ---------------------------------------------------------------------------
# 1) 双向收发
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_client_roundtrip() -> None:
    """server ↔ client 双向各发 10 条，内容与顺序一致。"""
    server, client = await _start_pair()
    try:
        for i in range(10):
            client.send_message(
                create_ipc_message(
                    IPCMessageType.EVT_HEARTBEAT, server.session_id, payload={"i": i}
                )
            )
            received = server.receive_message(timeout=5.0)
            assert received is not None
            assert received.payload == {"i": i}

        for i in range(10):
            server.send_message(
                create_ipc_message(
                    IPCMessageType.CMD_STATUS, server.session_id, payload={"j": i}
                )
            )
            received = client.receive_message(timeout=5.0)
            assert received is not None
            assert received.payload == {"j": i}
    finally:
        client.close()
        server.close()


# ---------------------------------------------------------------------------
# 2) 并发 send 不交错
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_send_is_not_interleaved() -> None:
    """4 线程并发 send 各 100 条，接收端必须拿到 400 条且全部可解析。"""
    server, client = await _start_pair()
    total = 400
    try:
        def _worker(tag: int) -> None:
            for i in range(100):
                client.send_message(
                    create_ipc_message(
                        IPCMessageType.EVT_LOG,
                        server.session_id,
                        payload={"tag": tag, "i": i, "pad": "x" * 200},
                    )
                )

        threads = [
            threading.Thread(target=_worker, args=(tag,), daemon=True)
            for tag in range(4)
        ]
        for t in threads:
            t.start()

        received: list = []
        deadline = time.monotonic() + 20.0
        while len(received) < total and time.monotonic() < deadline:
            msg = server.receive_message(timeout=1.0)
            if msg is not None:
                received.append(msg)

        for t in threads:
            t.join(timeout=10.0)

        assert len(received) == total, f"期望 {total} 条，实际 {len(received)} 条"
        tags = {msg.payload["tag"] for msg in received}
        assert tags == {0, 1, 2, 3}
        # 每条消息的 payload 完整（未与其它线程的帧交错）
        for msg in received:
            assert msg.payload["pad"] == "x" * 200
    finally:
        client.close()
        server.close()


# ---------------------------------------------------------------------------
# 3) send 与 recv 解耦
# ---------------------------------------------------------------------------


class _BlockingPollConnection:
    """poll() 会长时间等待的假连接。"""

    def __init__(self, poll_seconds: float):
        self.poll_seconds = poll_seconds
        self.sent: list = []

    def poll(self, timeout: float = 0.0) -> bool:
        time.sleep(min(timeout, self.poll_seconds))
        return False

    def send(self, data) -> None:
        self.sent.append(data)

    def recv(self):  # pragma: no cover - poll 永远返回 False
        raise AssertionError("recv should not be called")

    def close(self) -> None:
        pass


def test_send_and_recv_do_not_block_each_other() -> None:
    """receive_message 的 poll 等待期间，send_message 必须 < 100ms 返回。"""
    server = IPCServer(_sid())
    server._connection = _BlockingPollConnection(poll_seconds=2.0)

    poller = threading.Thread(target=lambda: server.receive_message(2.0), daemon=True)
    poller.start()
    time.sleep(0.2)  # 确保 poll 已在等待中

    msg = create_ipc_message(IPCMessageType.CMD_STATUS, server.session_id, payload={})
    started = time.monotonic()
    server.send_message(msg)
    elapsed = time.monotonic() - started

    assert elapsed < 0.1, f"send_message 被 poll 阻塞了 {elapsed:.3f}s"
    assert server._connection.sent
    poller.join(timeout=5.0)


# ---------------------------------------------------------------------------
# 4) close 幂等 + 结构断言
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_is_idempotent() -> None:
    """连续 close() 3 次不抛异常。"""
    server, client = await _start_pair()
    server.close()
    server.close()
    server.close()
    client.close()
    client.close()
    client.close()


def test_server_and_client_share_base_implementation() -> None:
    """两个子类都必须继承 _BaseIPC，且不再各自重复实现 send_message。"""
    assert issubclass(TransportServer, _BaseIPC)
    assert issubclass(TransportClient, _BaseIPC)
    assert TransportServer.send_message is _BaseIPC.send_message
    assert TransportClient.send_message is _BaseIPC.send_message


@pytest.mark.asyncio
async def test_send_after_close_raises_connection_error() -> None:
    """close 之后再 send 必须抛 IPCConnectionError（而不是静默成功）。"""
    server, client = await _start_pair()
    client.close()
    server.close()
    with pytest.raises(IPCConnectionError):
        client.send_message(
            create_ipc_message(IPCMessageType.CMD_STATUS, client.session_id, payload={})
        )
