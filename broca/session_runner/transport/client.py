"""IPC 客户端（运行在 Runner 子进程中）。

负责连接 Web 进程的 IPC 服务端，发送事件、接收控制命令。

与 Server 共享 ``_BaseIPC``：``send_message`` 同样受 ``_send_lock`` 保护
（Windows AF_PIPE 命名管道是串行的，并发 send 会交错破坏消息帧）。
"""

from __future__ import annotations

import logging
import time

from multiprocessing.connection import Client

from broca.session_runner.transport.base import IPCConnectionError, _BaseIPC

logger = logging.getLogger(__name__)


class IPCClient(_BaseIPC):
    """IPC 客户端（在 Runner 进程中运行）"""

    _NO_CONNECTION_MSG = "IPC client not connected"

    def __init__(self, session_id: str):
        super().__init__(session_id)
        self._connected = False

    async def start(self) -> None:
        """Protocol 兼容：包装 connect()。"""
        if not self.connect():
            raise IPCConnectionError(f"IPCClient failed to connect to {self.address}")

    def connect(self, retries: int = 3, delay: float = 0.5) -> bool:
        """连接到 Web 进程的 IPC 服务端。

        带短重试：覆盖「server 刚 bind、client 抢先 connect」的窗口。

        Args:
            retries: 最大尝试次数
            delay: 每次重试之间的等待（秒）

        Returns:
            是否连接成功
        """
        last_error: Exception | None = None
        for attempt in range(1, max(1, retries) + 1):
            try:
                self._connection = Client(
                    address=self.address,
                    family=self.family,
                )
                self._connected = True
                logger.info(
                    "IPC client connected to %s (family=%s)", self.address, self.family
                )
                return True

            except (ConnectionRefusedError, FileNotFoundError, OSError, EOFError) as e:
                last_error = e
                if attempt < retries:
                    logger.debug(
                        "IPC connect attempt %d/%d failed for %s: %s (retrying in %.1fs)",
                        attempt,
                        retries,
                        self.session_id,
                        e,
                        delay,
                    )
                    time.sleep(delay)

        raise IPCConnectionError(
            f"Failed to connect IPC client for {self.session_id}: {last_error}"
        ) from last_error

    def close(self) -> None:
        """关闭 IPC 连接（幂等）。"""
        self._connected = False
        super().close()
        logger.info("IPC client closed for session %s", self.session_id)
