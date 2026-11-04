"""IPC 单线程多路复用。

历史问题（P1-6）：每个 session 一个 daemon 线程跑阻塞 ``receive_message``，
10 个 session 就是 10 个线程。改为**一个线程**用
``multiprocessing.connection.wait()`` 同时等待所有连接。

线程模型：

    ┌──────────────────────── ipc-poller 线程 ────────────────────────┐
    │ wait(conns, timeout=0.5) → 对每个 ready 的 conn 调 recv()        │
    │        → loop.call_soon_threadsafe(queue.put_nowait, msg)       │
    └─────────────────────────────────────────────────────────────────┘
                              ↓ 每 session 一个 asyncio.Queue
    ┌──────────────────────── 事件循环 ───────────────────────────────┐
    │ _ipc_listener_loop: await queue.get() → router.dispatch(msg)     │
    └─────────────────────────────────────────────────────────────────┘

``wait()`` 是 ``multiprocessing.connection`` 的跨平台实现（POSIX 用
``select``/``poll``，Windows 用 ``WaitForMultipleObjects``），不引入新依赖。
"""

from __future__ import annotations

import asyncio
import threading
from multiprocessing.connection import wait
from typing import Any, Callable, Dict, Optional

from broca.logging_config import get_logger
from broca.session_runner.backpressure import (
    DEFAULT_QUEUE_SIZE,
    DroppedEvents,
    put_with_backpressure,
)

logger = get_logger(__name__)

# 单次 wait 的超时：决定「新增连接」与「stop()」的最大感知延迟
POLL_TIMEOUT = 0.5
# 无连接时的休眠，避免忙等
IDLE_SLEEP = 0.1
# 轮询线程统一前缀（便于测试与线上排查）
THREAD_NAME = "ipc-poller"


class IPCPoller:
    """一个线程多路复用所有 session 的 IPC 连接。"""

    def __init__(
        self,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        decode: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        # 线上格式是 JSON 字符串，消费侧需要 IPCMessage 对象。
        # decode 由调用方注入（manager 传 decode_ipc_message），
        # poller 本身不依赖 models 层。
        self._decode = decode or (lambda raw: raw)
        self._connections: Dict[str, Any] = {}
        self._queues: Dict[str, "asyncio.Queue"] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.RLock()
        self._queue_size = queue_size
        # 背压统计（暴露到 get_stats）：区分心跳/其它，便于判断是
        # 「可合并的心跳被合并」还是「真的丢了命令或响应」
        self.dropped = DroppedEvents()

    @property
    def dropped_count(self) -> int:
        """累计丢弃条数（兼容旧调用方 / get_stats）。"""
        return self.dropped.total

    @property
    def dropped_events(self) -> dict[str, int]:
        """丢弃明细：``{"total": n, "heartbeat": n, "other": n}``。"""
        return self.dropped.to_dict()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """启动轮询线程（幂等）。"""
        with self._lock:
            if self._running:
                return
            self._loop = loop
            self._running = True
            self._thread = threading.Thread(
                target=self._poll_loop, name=THREAD_NAME, daemon=True
            )
            self._thread.start()
        logger.info("IPCPoller started (thread=%s)", THREAD_NAME)

    def stop(self) -> None:
        """停止轮询线程（幂等）。"""
        with self._lock:
            self._running = False
            thread = self._thread
            self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=POLL_TIMEOUT * 4)
        logger.info("IPCPoller stopped")

    @property
    def running(self) -> bool:
        return self._running

    @property
    def thread(self) -> Optional[threading.Thread]:
        return self._thread

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def register(self, session_id: str, conn: Any) -> None:
        """注册一个连接（必须在 ``accept()`` 完成后调用，conn 不能为 None）。"""
        if conn is None:
            raise ValueError(
                f"IPCPoller.register got None connection for session {session_id} "
                "— register must happen after accept() completes"
            )
        with self._lock:
            self._connections[session_id] = conn
            self._queues[session_id] = asyncio.Queue(maxsize=self._queue_size)
        logger.debug("IPCPoller registered session %s", session_id)

    def unregister(self, session_id: str) -> None:
        """注销连接（幂等）。"""
        with self._lock:
            self._connections.pop(session_id, None)
            self._queues.pop(session_id, None)

    def queue(self, session_id: str) -> Optional["asyncio.Queue"]:
        """取该 session 的消息队列（未注册返回 None）。"""
        with self._lock:
            return self._queues.get(session_id)

    def registered(self) -> list[str]:
        with self._lock:
            return list(self._connections)

    # ------------------------------------------------------------------
    # 轮询
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """线程主循环：wait 所有连接 → 对 ready 的连接 recv → 投递到队列。"""
        while self._running:
            snapshot = self._live_connections()
            if not snapshot:
                # 空连接列表：wait([]) 会立即返回，必须显式休眠避免忙等
                threading.Event().wait(IDLE_SLEEP)
                continue

            try:
                ready = wait(list(snapshot.values()), timeout=POLL_TIMEOUT)
            except (OSError, ValueError, TypeError) as exc:
                # TypeError: 已关闭的连接 fileno() 为 None（release_handle 之后）
                logger.debug("IPCPoller wait() failed: %s", exc)
                threading.Event().wait(IDLE_SLEEP)
                continue

            for conn in ready:
                session_id = next(
                    (sid for sid, c in snapshot.items() if c is conn), None
                )
                if session_id is None:  # pragma: no cover - 连接已被注销
                    continue
                self._drain(session_id, conn)

    def _live_connections(self) -> Dict[str, Any]:
        """取当前连接快照，并顺手剔除已关闭的连接。

        ``release_handle()`` / ``ipc.close()`` 之后连接对象的 ``fileno()`` 变成
        ``None``，此时 ``wait()`` 抛 ``TypeError`` 而不是 ``OSError``。若不主动
        剔除，一次正常停止就会让轮询线程反复空转报错。
        """
        with self._lock:
            snapshot = dict(self._connections)
        for session_id, conn in list(snapshot.items()):
            if getattr(conn, "closed", False):
                logger.debug("IPCPoller pruning closed connection %s", session_id)
                snapshot.pop(session_id, None)
                self.unregister(session_id)
        return snapshot

    def _drain(self, session_id: str, conn: Any) -> None:
        """从单个连接读取一条消息、解码、投递；断开则注销。"""
        try:
            raw = conn.recv()
        except (EOFError, OSError) as exc:
            logger.warning("IPC connection lost for session %s: %s", session_id, exc)
            # 顺序很关键：先投递 None 哨兵（此时队列还在），再注销。
            # 反过来写会让消费侧永远等不到「连接已断」的信号。
            self._deliver(session_id, None)
            self.unregister(session_id)
            return
        except Exception as exc:  # noqa: BLE001 - 单条消息失败不应杀线程
            logger.error("IPCPoller recv failed for session %s: %s", session_id, exc)
            return

        try:
            msg = self._decode(raw)
        except Exception as exc:  # noqa: BLE001 - 脏数据只丢这一条
            logger.error(
                "IPCPoller failed to decode message for session %s: %s", session_id, exc
            )
            return

        self._deliver(session_id, msg)

    def _deliver(self, session_id: str, msg: Any, *, allow_missing: bool = False) -> None:
        """把消息投递到该 session 的 asyncio 队列（线程安全）。"""
        loop = self._loop
        with self._lock:
            queue = self._queues.get(session_id)
        if loop is None or queue is None:
            if not allow_missing:
                logger.debug("IPCPoller dropping message for unknown session %s", session_id)
            return
        try:
            loop.call_soon_threadsafe(self._put_nowait, session_id, queue, msg)
        except RuntimeError:  # 事件循环已关闭
            logger.debug("Event loop closed, dropping message for %s", session_id)

    def _put_nowait(self, session_id: str, queue: "asyncio.Queue", msg: Any) -> None:
        """在事件循环线程内入队；队列满时按背压策略处理（Task 4.4）。

        策略见 :mod:`broca.session_runner.backpressure`：
        心跳丢最旧的、其它消息丢新的并计数，绝不阻塞轮询线程。
        """
        put_with_backpressure(
            queue, msg, self.dropped, session_id=session_id, force=msg is None
        )
