"""
IPC 通信模块

基于 multiprocessing.connection 实现跨平台进程间通信。
Linux/macOS → AF_UNIX (Unix Domain Socket)
Windows → AF_PIPE (Named Pipe)
"""

import json
import logging
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from multiprocessing.connection import Client, Listener
from typing import Any

from broca.errors import CommunicationError
from broca.session_runner.models import (
    IPCMessage,
    IPCMessageType,
    IPCStatusCode,
    get_ipc_address,
    get_ipc_family,
)

logger = logging.getLogger(__name__)


class IPCConnectionError(CommunicationError):
    """IPC 连接异常"""


class IPCTimeoutError(CommunicationError):
    """IPC 超时异常"""


class IPCServer:
    """
    IPC 服务端（在 Web 进程中运行）

    负责监听来自 Runner 进程的连接请求，接收事件和发送控制命令。
    每个 Session 对应一个独立的 IPC 服务端实例。
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.address = get_ipc_address(session_id)
        self.family = get_ipc_family()
        self._listener: Listener | None = None
        self._connection: Any = None
        self._running = False
        self._handlers: dict[IPCMessageType, Callable] = {}
        # 保护连接读写的锁，防止 stop_session 与 _ipc_listener_loop 竞态
        self._lock = threading.Lock()

    def register_handler(self, msg_type: IPCMessageType, handler: Callable) -> None:
        """注册消息处理器"""
        self._handlers[msg_type] = handler

    async def start(self) -> None:
        """启动 IPC 服务端监听"""
        try:
            logger.info(
                "IPC server starting for session %s at %s (family=%s)",
                self.session_id,
                self.address,
                self.family,
            )
            self._listener = Listener(
                address=self.address,
                family=self.family,
                backlog=1,
            )
            self._running = True
            logger.info("IPC server started for session %s", self.session_id)
        except Exception as e:
            raise IPCConnectionError(
                f"Failed to start IPC server for {self.session_id}: {e}"
            ) from e

    def accept(self, timeout: float = 30.0) -> bool:
        """
        接受 Runner 进程的连接

        Args:
            timeout: 等待连接的超时时间（秒）

        Returns:
            是否成功接受连接
        """
        if not self._listener:
            raise IPCConnectionError("IPC server not started")

        if self.family == "AF_UNIX":
            import select

            # 获取底层 socket 进行超时控制（仅 Unix 的 SocketListener 有 _socket）
            sock = self._listener._listener._socket  # type: ignore[attr-defined]

            # 等待连接
            ready = select.select([sock], [], [], timeout)
            if not ready[0]:
                raise IPCTimeoutError(
                    f"IPC connection timeout for {self.session_id} after {timeout}s"
                )

            try:
                self._connection = self._listener.accept()
            except Exception as e:
                raise IPCConnectionError(f"Failed to accept IPC connection: {e}") from e
        else:
            # Windows AF_PIPE：底层是 PipeListener（命名管道），没有 socket 可供
            # select，且 select.select 不支持 Windows 命名管道。
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

        logger.info("IPC connection accepted for session %s", self.session_id)
        return True

    def send_message(self, msg: IPCMessage) -> None:
        """
        发送消息到 Runner 进程

        Args:
            msg: IPC 消息
        """
        if not self._connection:
            raise IPCConnectionError("No IPC connection established")

        with self._lock:
            try:
                data = json.dumps(msg.to_dict())
                self._connection.send(data)
                logger.debug("IPC sent: %s -> %s", msg.type.value, self.session_id)
            except (BrokenPipeError, ConnectionError, EOFError) as e:
                raise IPCConnectionError(
                    f"IPC send failed (connection broken): {e}"
                ) from e

    def receive_message(self, timeout: float = 10.0) -> IPCMessage | None:
        """
        接收来自 Runner 进程的消息

        Args:
            timeout: 接收超时时间（秒）

        Returns:
            接收到的消息，超时返回 None
        """
        if not self._connection:
            raise IPCConnectionError("No IPC connection established")

        with self._lock:
            try:
                if not self._connection.poll(timeout):
                    return None

                raw_data = self._connection.recv()
                data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                msg = IPCMessage.from_dict(data)
                logger.debug("IPC received: %s <- %s", msg.type.value, self.session_id)
                return msg
            except (BrokenPipeError, ConnectionError, EOFError) as e:
                raise IPCConnectionError(
                    f"IPC receive failed (connection broken): {e}"
                ) from e

    def close(self) -> None:
        """关闭 IPC 连接和服务端"""
        # 第1步：先关闭底层连接/socket（无需持锁），这会使 poll() 立即返回/报错，
        # 从而让监听线程快速从 receive_message 中退出
        try:
            if self._connection:
                self._connection.close()
        except Exception:
            pass
        try:
            if self._listener:
                self._listener.close()
        except Exception:
            pass

        # 第2步：持锁清理内部状态
        with self._lock:
            self._connection = None
            self._listener = None
            self._running = False

        # 第3步：清理 Unix Domain Socket 文件（锁外执行）
        if self.family == "AF_UNIX":
            import os

            try:
                if os.path.exists(self.address):
                    os.unlink(self.address)
            except Exception:
                pass

        logger.info("IPC server closed for session %s", self.session_id)


class IPCClient:
    """
    IPC 客户端（在 Runner 进程中运行）

    负责连接 Web 进程的 IPC 服务端，发送事件和接收控制命令。
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.address = get_ipc_address(session_id)
        self.family = get_ipc_family()
        self._connection: Any = None
        self._connected = False

    def connect(self) -> bool:
        """
        连接到 Web 进程的 IPC 服务端

        Returns:
            是否连接成功
        """
        try:
            # 直接使用 multiprocessing.connection.Client
            # 在 Unix 上使用 AF_UNIX，在 Windows 上使用 AF_PIPE
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
            raise IPCConnectionError(
                f"Failed to connect IPC client for {self.session_id}: {e}"
            ) from e

    def send_message(self, msg: IPCMessage) -> None:
        """
        发送消息到 Web 进程

        Args:
            msg: IPC 消息
        """
        if not self._connection:
            raise IPCConnectionError("IPC client not connected")

        try:
            data = json.dumps(msg.to_dict())
            self._connection.send(data)
            logger.debug("IPC sent: %s -> server", msg.type.value)
        except (BrokenPipeError, ConnectionError, EOFError) as e:
            raise IPCConnectionError(f"IPC send failed (connection broken): {e}") from e

    def receive_message(self, timeout: float = 10.0) -> IPCMessage | None:
        """
        接收来自 Web 进程的消息

        Args:
            timeout: 接收超时时间（秒）

        Returns:
            接收到的消息，超时返回 None
        """
        if not self._connection:
            raise IPCConnectionError("IPC client not connected")

        try:
            if not self._connection.poll(timeout):
                return None

            raw_data = self._connection.recv()
            data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            return IPCMessage.from_dict(data)
        except (BrokenPipeError, ConnectionError, EOFError) as e:
            raise IPCConnectionError(
                f"IPC receive failed (connection broken): {e}"
            ) from e

    def close(self) -> None:
        """关闭 IPC 连接"""
        self._connected = False
        try:
            if self._connection:
                self._connection.close()
        except Exception:
            pass
        self._connection = None
        logger.info("IPC client closed for session %s", self.session_id)


# 消息创建辅助函数


def create_ipc_message(
    msg_type: IPCMessageType,
    session_id: str,
    payload: dict[str, Any] | None = None,
    status: IPCStatusCode | None = None,
) -> IPCMessage:
    """创建 IPC 消息"""
    return IPCMessage(
        type=msg_type,
        session_id=session_id,
        message_id=uuid.uuid4().hex[:16],
        timestamp=datetime.now(UTC).isoformat(),
        payload=payload or {},
        status=status,
    )


def create_response_message(
    request: IPCMessage,
    status: IPCStatusCode = IPCStatusCode.SUCCESS,
    payload: dict[str, Any] | None = None,
) -> IPCMessage:
    """创建对请求的响应消息"""
    return IPCMessage(
        type=IPCMessageType.RESPONSE,
        session_id=request.session_id,
        message_id=request.message_id,
        timestamp=datetime.now(UTC).isoformat(),
        payload=payload or {},
        status=status,
    )
