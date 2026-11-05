"""IPC 服务端（运行在 Web 进程中）。

每个 Session 对应一个独立实例，负责监听 Runner 子进程的连接、
接收事件、下发控制命令。
"""

from __future__ import annotations

import os
import select
import socket
import threading
from multiprocessing.connection import Listener
from typing import Any

from broca.logging_config import get_logger
from broca.session_runner.transport.addresses import AF_UNIX_PATH_BUDGET
from broca.session_runner.transport.base import (
    IPCConnectionError,
    IPCTimeoutError,
    _BaseIPC,
)

logger = get_logger(__name__)


class IPCServer(_BaseIPC):
    """IPC 服务端（在 Web 进程中运行）"""

    _NO_CONNECTION_MSG = "No IPC connection established"

    def __init__(self, session_id: str):
        super().__init__(session_id)
        self._listener: Listener | None = None

    @property
    def connection(self) -> Any:
        """底层连接（``accept()`` 之后才非 None）。"""
        return self._connection

    # ------------------------------------------------------------------
    # 启动 / 残留清理
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动 IPC 服务端监听"""
        try:
            logger.info(
                "IPC server starting for session %s at %s (family=%s)",
                self.session_id,
                self.address,
                self.family,
            )
            self._guard_address_length()
            self._clear_stale_socket()
            self._listener = Listener(
                address=self.address,
                family=self.family,
                backlog=1,
            )
            logger.info(f"IPC server started for session {self.session_id}")
        except IPCConnectionError:
            raise
        except Exception as e:
            raise IPCConnectionError(
                f"Failed to start IPC server for {self.session_id}: {e}"
            ) from e

    def _guard_address_length(self) -> None:
        """AF_UNIX 路径超限时抛出带指引的异常（不静默截断）。"""
        if self.family != "AF_UNIX":
            return
        if len(self.address) > AF_UNIX_PATH_BUDGET:
            raise IPCConnectionError(
                f"AF_UNIX socket path too long ({len(self.address)} > "
                f"{AF_UNIX_PATH_BUDGET}): {self.address}. "
                "请设置较短的 TMPDIR（例如 TMPDIR=/tmp），"
                "或改用更短的 session_id。"
            )

    def _clear_stale_socket(self) -> None:
        """清理崩溃残留的 socket 文件。

        历史 bug：``Listener`` 绑定前不 unlink 旧 socket。runner 被 kill -9 后
        残留文件会让后续 ``Listener`` 抛 ``EADDRINUSE``，该 session 永久无法再启动。
        """
        if self.family != "AF_UNIX":
            return
        if not os.path.exists(self.address):
            return

        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(0.5)
        try:
            probe.connect(self.address)
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            # 连不上 → 残留文件，清理
            probe.close()
            try:
                os.unlink(self.address)
                logger.info(f"Removed stale IPC socket: {self.address}")
            except FileNotFoundError:
                pass
            return
        else:
            probe.close()
            raise IPCConnectionError(
                f"IPC address {self.address} already in use by a live server"
            )

    # ------------------------------------------------------------------
    # 连接
    # ------------------------------------------------------------------

    def accept(self, timeout: float = 30.0) -> bool:
        """接受 Runner 进程的连接。

        Args:
            timeout: 等待连接的超时时间（秒）

        Returns:
            是否成功接受连接
        """
        if not self._listener:
            raise IPCConnectionError("IPC server not started")

        if self.family == "AF_UNIX":
            # 获取底层 socket 进行超时控制（仅 Unix 的 SocketListener 有 _socket）
            sock = self._listener._listener._socket  # type: ignore[attr-defined]

            ready = select.select([sock], [], [], timeout)
            if not ready[0]:
                raise IPCTimeoutError(
                    f"IPC connection timeout for {self.session_id} after {timeout}s"
                )

            try:
                self._connection = self._listener.accept()
            except Exception as e:
                raise IPCConnectionError(
                    f"Failed to accept IPC connection: {e}"
                ) from e
        else:
            # Windows AF_PIPE：底层是 PipeListener，没有 socket 可供 select。
            # 改用 daemon 线程执行阻塞 accept()，通过 join(timeout) 实现超时控制。
            result: dict[str, Any] = {}

            def _do_accept() -> None:
                try:
                    assert self._listener is not None
                    result["connection"] = self._listener.accept()
                except Exception as e:  # pragma: no cover - 平台相关
                    result["error"] = str(e)

            thread = threading.Thread(
                target=_do_accept,
                name=f"ipc-accept-{self.session_id}",
                daemon=True,
            )
            thread.start()
            thread.join(timeout)

            if thread.is_alive():
                # 超时：accept 线程仍在阻塞等待，close() 关闭 listener 后其自然退出
                raise IPCTimeoutError(
                    f"IPC connection timeout for {self.session_id} after {timeout}s"
                )

            if "error" in result:
                raise IPCConnectionError(
                    f"Failed to accept IPC connection: {result['error']}"
                )

            self._connection = result.get("connection")

        logger.info(f"IPC connection accepted for session {self.session_id}")
        return True

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------

    def close(self) -> None:
        """关闭 IPC 连接和服务端（幂等）。

        约定：**只有本方法负责删除 socket 文件**。manager 侧的清理逻辑
        只调用 ``close()``，避免与 multiprocessing 的 Finalize 回调重复 unlink。
        """
        # 第1步：先关闭底层连接/socket（无需持锁），这会使 poll() 立即返回/报错，
        # 从而让监听线程快速从 receive_message 中退出
        super().close()

        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.close()
            except Exception:
                pass

        # 第2步：清理 Unix Domain Socket 文件（锁外执行）
        if self.family == "AF_UNIX":
            try:
                os.unlink(self.address)
            except FileNotFoundError:
                pass
            except Exception:
                pass

        logger.info(f"IPC server closed for session {self.session_id}")
