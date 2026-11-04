"""IPC 传输层公共实现。

``IPCServer``（Web 进程）与 ``IPCClient``（Runner 进程）共享同一套
编解码与收发逻辑，此前在两个类里重复实现（其中 Client 侧**没有**发送锁，
Windows 命名管道并发写会交错破坏消息帧）。
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from broca.errors import CommunicationError
from broca.session_runner.models import (
    decode_ipc_message,
    IPCMessage,
    IPCMessageType,
    IPCStatusCode,
)
from broca.session_runner.transport.addresses import get_ipc_address, get_ipc_family
from broca.logging_config import get_logger

logger = get_logger(__name__)


class IPCConnectionError(CommunicationError):
    """IPC 连接异常"""


class IPCTimeoutError(CommunicationError):
    """IPC 超时异常"""


@runtime_checkable
class IPCChannel(Protocol):
    """IPC 通道统一接口。

    IPCServer（Web 进程）和 IPCClient（Runner 进程）均满足此 Protocol。
    发送和接收是独立操作，可在不同线程/协程中并发调用。
    """

    session_id: str
    address: str

    async def start(self) -> None: ...
    def send_message(self, msg: IPCMessage) -> None: ...
    def receive_message(self, timeout: float = 10.0) -> IPCMessage | None: ...
    def close(self) -> None: ...


class _BaseIPC:
    """Server / Client 的公共基类。

    锁设计（重要）：
    - ``_send_lock``：防止并发 send 交错写坏消息帧。**Client 也必须持有**，
      否则 Windows 命名管道上并发 send 会交错（历史 bug）。
    - ``_recv_lock``：与 ``_send_lock`` **分离**。历史上二者共用一把锁，
      ``poll(5s)`` 期间事件循环下发命令被卡 5 秒。
    """

    # 子类覆盖，用于「未连接」时的报错措辞
    _NO_CONNECTION_MSG = "No IPC connection established"

    session_id: str
    address: str
    family: str
    _connection: Any
    _send_lock: threading.Lock
    _recv_lock: threading.Lock

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.address = get_ipc_address(session_id)
        self.family = get_ipc_family()
        self._connection: Any = None
        self._send_lock = threading.Lock()
        self._recv_lock = threading.Lock()

    # ------------------------------------------------------------------
    # 编解码
    # ------------------------------------------------------------------

    def _encode(self, msg: IPCMessage) -> str:
        return json.dumps(msg.to_dict())

    def _decode(self, raw: Any) -> IPCMessage:
        return decode_ipc_message(raw)

    # ------------------------------------------------------------------
    # 收发
    # ------------------------------------------------------------------

    def send_message(self, msg: IPCMessage) -> None:
        """发送消息（统一走 ``_send_lock``，保证帧不被交错）。"""
        connection = self._connection
        if not connection:
            raise IPCConnectionError(self._NO_CONNECTION_MSG)

        with self._send_lock:
            try:
                connection.send(self._encode(msg))
                logger.debug("IPC sent: %s (%s)", msg.type.value, self.session_id)
            except (BrokenPipeError, ConnectionError, EOFError) as e:
                raise IPCConnectionError(
                    f"IPC send failed (connection broken): {e}"
                ) from e

    def receive_message(self, timeout: float = 10.0) -> IPCMessage | None:
        """接收消息。

        约定：同一连接只允许一个消费者线程调用本方法。
        ``poll()`` 不持任何锁，因此等待期间 ``send_message`` 不受影响。
        """
        connection = self._connection
        if not connection:
            raise IPCConnectionError(self._NO_CONNECTION_MSG)

        try:
            if not connection.poll(timeout):
                return None

            with self._recv_lock:
                raw_data = connection.recv()
            msg = self._decode(raw_data)
            logger.debug("IPC received: %s (%s)", msg.type.value, self.session_id)
            return msg
        except (BrokenPipeError, ConnectionError, EOFError) as e:
            raise IPCConnectionError(
                f"IPC receive failed (connection broken): {e}"
            ) from e

    def close(self) -> None:
        """关闭底层连接（幂等）。"""
        connection = self._connection
        self._connection = None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 消息创建辅助函数
# ---------------------------------------------------------------------------


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
    """创建对请求的响应消息（回显 request 的 message_id）"""
    return IPCMessage(
        type=IPCMessageType.RESPONSE,
        session_id=request.session_id,
        message_id=request.message_id,
        timestamp=datetime.now(UTC).isoformat(),
        payload=payload or {},
        status=status,
    )
