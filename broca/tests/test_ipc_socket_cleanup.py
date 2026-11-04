"""IPC socket 残留与地址生成回归测试（P0-4）

历史 bug：``IPCServer.start()`` 在 ``Listener(...)`` 之前不清理残留 socket 文件。
runner 被 ``kill -9`` 后 socket 文件留在 ``/tmp``，后续 ``Listener`` 抛
``EADDRINUSE`` —— **该 session 永久无法再启动**。

同时覆盖 AF_UNIX 路径长度约束：macOS 的 ``tempfile.gettempdir()`` 实测 48 字符，
``48 + 1 + len("broca_runner_") + 64 + len(".sock") = 131 > 108``，
固定 ``session_id[:64]`` 会让每次 ``start_session`` 都失败。
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import uuid

import pytest

from broca.session_runner.ipc import IPCConnectionError, IPCServer
from broca.session_runner.manager import build_runner_env, repo_root
from broca.session_runner.models import get_ipc_address

_INTEGRATION_ENABLED = os.environ.get("BROCA_RUN_INTEGRATION") == "1"


def _unique_session_id() -> str:
    return f"session_sock_{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# 残留 socket 清理
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_socket_is_unlinked() -> None:
    """存在残留 socket 文件（无服务端监听）时必须能启动并清理旧文件。"""
    session_id = _unique_session_id()
    address = get_ipc_address(session_id)

    # 手工制造残留：bind 后立刻 close，文件留在磁盘上但没有 listener
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(address)
    stale.close()
    assert os.path.exists(address), "前置条件失败：残留 socket 未创建"

    server = IPCServer(session_id)
    try:
        await server.start()
        assert os.path.exists(address)
    finally:
        server.close()


@pytest.mark.asyncio
async def test_live_socket_is_rejected() -> None:
    """同一 session 的第二个 server 必须被拒绝，且不得删除活着的 socket。"""
    session_id = _unique_session_id()
    first = IPCServer(session_id)
    await first.start()
    try:
        second = IPCServer(session_id)
        with pytest.raises(IPCConnectionError):
            await second.start()
        # 活着的 socket 不能被误删
        assert os.path.exists(first.address)
    finally:
        first.close()


# ---------------------------------------------------------------------------
# 地址生成
# ---------------------------------------------------------------------------


def test_address_not_hardcoded_tmp() -> None:
    """地址必须基于 tempfile.gettempdir()，而不是硬编码 /tmp。"""
    address = get_ipc_address(_unique_session_id())
    assert address.startswith(tempfile.gettempdir())


def test_address_length_guard() -> None:
    """超长 session_id 必须被摘要到 <= 100 字节，且不同 id 不碰撞。"""
    tmpdir = tempfile.gettempdir()

    long_a = "x" * 200
    long_b = "y" * 200
    path_a = get_ipc_address(long_a)
    path_b = get_ipc_address(long_b)

    assert len(path_a) <= 100, f"路径过长（{len(path_a)}）: {path_a}"
    assert path_a.startswith(tmpdir)
    assert path_a != path_b, "两个不同的长 id 摘要后发生碰撞"

    # 36 字符 UUID 在 macOS（tempdir=48）下同样超预算，必须走摘要分支
    uuid_id = "12345678-1234-1234-1234-123456789012"
    path_uuid = get_ipc_address(uuid_id)
    assert len(path_uuid) <= 100, f"UUID 路径过长（{len(path_uuid)}）: {path_uuid}"


def test_address_is_stable_for_same_id() -> None:
    """同一 session_id 必须生成稳定地址（重启后能定位到同一个残留文件）。"""
    session_id = _unique_session_id()
    assert get_ipc_address(session_id) == get_ipc_address(session_id)


# ---------------------------------------------------------------------------
# 集成：真实进程被 SIGKILL 后仍可重新 bind
# ---------------------------------------------------------------------------

_CHILD_SCRIPT = """
import asyncio
import sys

from broca.session_runner.ipc import IPCServer


async def main() -> None:
    server = IPCServer(sys.argv[1])
    await server.start()
    print("BOUND", flush=True)
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, server.accept, 30.0)
    except Exception:
        pass
    await asyncio.sleep(60)


asyncio.run(main())
"""


@pytest.mark.integration
@pytest.mark.skipif(
    not _INTEGRATION_ENABLED, reason="set BROCA_RUN_INTEGRATION=1 to run"
)
def test_restart_after_sigkill() -> None:
    """真实子进程 bind → os.kill(pid, 9) → 主进程立刻重新 bind，循环 3 次。"""
    session_id = _unique_session_id()
    env = build_runner_env()

    for round_no in range(3):
        proc = subprocess.Popen(
            [sys.executable, "-c", _CHILD_SCRIPT, session_id],
            cwd=str(repo_root()),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            # 等子进程完成 bind
            line = proc.stdout.readline()
            assert "BOUND" in line, (
                f"round {round_no}: 子进程未 bind 成功\n"
                f"stdout={line}\nstderr={proc.stderr.read() if proc.stderr else ''}"
            )

            proc.kill()
            proc.wait(timeout=30)
        finally:
            if proc.poll() is None:  # pragma: no cover
                proc.kill()
                proc.wait(timeout=30)

        # 残留文件必须存在（模拟硬崩溃）
        address = get_ipc_address(session_id)
        deadline = time.time() + 5.0
        while not os.path.exists(address) and time.time() < deadline:
            time.sleep(0.05)
        assert os.path.exists(address), f"round {round_no}: 残留 socket 未留下"

        # 立刻重新 bind —— 旧实现会在这里抛 EADDRINUSE
        server = IPCServer(session_id)
        try:
            asyncio.run(server.start())
        finally:
            server.close()

        assert not os.path.exists(address), f"round {round_no}: close() 未清理 socket"
