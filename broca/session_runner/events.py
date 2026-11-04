"""Runner 事件与后台任务容器。

Phase 2 Task 2.5 只落地 ``TaskSet``（fire-and-forget 任务的唯一入口）；
事件总线能力在 Phase 3 Task 3.2 补齐。

为什么需要 ``TaskSet``：直接 ``create_task`` 得到的 Task 若没有强引用，
可能被 GC 提前回收（官方文档明确警告）；异常也只会以
"Task exception was never retrieved" 的形式在解释器退出时才冒出来。
``TaskSet.spawn`` 一次解决两件事：**持引用** + **异常落日志**。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

from broca.session_runner.models import IPCMessageType

logger = logging.getLogger(__name__)


class TaskSet:
    """持有 fire-and-forget 任务的容器：强引用 + 异常记录 + 统一关闭。"""

    def __init__(self, name: str) -> None:
        self._name = name
        self._tasks: Set[asyncio.Task] = set()
        self._closed = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def spawn(self, coro: Coroutine[Any, Any, Any], *, name: Optional[str] = None) -> asyncio.Task:
        """启动一个后台任务并持有引用。

        Args:
            coro: 待执行的协程
            name: 任务名（默认取协程的 ``__qualname__``，便于日志排查）

        Returns:
            已创建的 ``asyncio.Task``（调用方若需单独 await/cancel 可直接使用）
        """
        if self._closed:
            raise RuntimeError(f"TaskSet {self._name!r} is already closed")
        label = name or getattr(coro, "__qualname__", "coro")
        task = asyncio.create_task(coro, name=f"{self._name}:{label}")
        self._tasks.add(task)
        task.add_done_callback(self._on_done)
        return task

    async def aclose(self, timeout: Optional[float] = 5.0) -> None:
        """取消所有未完成任务并等待其结束（幂等）。"""
        if self._closed:
            return
        self._closed = True

        pending = [task for task in self._tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending, timeout=timeout)
        self._tasks.clear()

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._tasks)

    @property
    def closed(self) -> bool:
        return self._closed

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _on_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "Background task %s failed: %s",
                task.get_name(),
                exc,
                exc_info=exc,
            )


class EventBus:
    """进程内事件总线：注册 + 串行分发 + 单 handler 异常隔离。

    与 ``TaskSet`` 的分工：
    - ``emit()``：调用方需要「发完再继续」时用（如收敛状态后要保证前端已收到）
    - ``emit_soon()``：fire-and-forget，任务由内部 ``TaskSet`` 持有引用
    """

    def __init__(self, name: str = "events") -> None:
        self._name = name
        self._handlers: Dict[str, List[Callable]] = {}
        self._tasks = TaskSet(f"{name}-emit")

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def on(self, event: str, handler: Callable) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def handlers(self, event: str) -> List[Callable]:
        return list(self._handlers.get(event, ()))

    # ------------------------------------------------------------------
    # 分发
    # ------------------------------------------------------------------

    async def emit(self, event: str, *args: Any) -> None:
        """串行 await 所有 handler；单个 handler 抛异常不影响其余 handler。

        handler 签名与事件对应：``session_crashed`` 传 1 个参数（RunnerProcessInfo），
        ``crew_event`` 传 2 个（session_id, msg）。
        """
        for handler in self.handlers(event):
            try:
                result = handler(*args)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # noqa: BLE001 - 事件总线必须隔离 handler 异常
                logger.error(
                    "Event handler %r for %r failed: %s",
                    getattr(handler, "__qualname__", handler),
                    event,
                    exc,
                    exc_info=exc,
                )

    def emit_soon(self, event: str, *args: Any) -> None:
        """异步分发（不等待），任务由内部 TaskSet 持有引用并记录异常。"""
        self._tasks.spawn(self.emit(event, *args), name=f"emit-{event}")

    # ------------------------------------------------------------------
    # 领域事件：编排（crew）进度
    # ------------------------------------------------------------------

    async def emit_crew_event(self, session_id: str, msg: Any) -> None:
        """把 runner 上报的编排（crew）事件转成日志 + 本地事件分发。"""
        payload = getattr(msg, "payload", None) or {}
        crew_id = payload.get("crew_id", "?")
        execution_id = payload.get("execution_id", "?")

        if msg.type == IPCMessageType.EVT_CREW_START:
            logger.info(
                "[Crew] '%s' started (session=%s, exec=%s, agents=%s)",
                crew_id,
                session_id,
                execution_id,
                payload.get("agent_count", 0),
            )
        elif msg.type == IPCMessageType.EVT_CREW_PROGRESS:
            logger.info(
                "[Crew] '%s' progress: %.0f%% (session=%s, exec=%s, phase=%s)",
                crew_id,
                payload.get("progress", 0) * 100,
                session_id,
                execution_id,
                payload.get("current_phase", ""),
            )
        elif msg.type == IPCMessageType.EVT_CREW_COMPLETE:
            logger.info(
                "[Crew] '%s' completed (session=%s, exec=%s)",
                crew_id,
                session_id,
                execution_id,
            )
        elif msg.type == IPCMessageType.EVT_CREW_ERROR:
            logger.error(
                "[Crew] '%s' failed: %s (session=%s, exec=%s)",
                crew_id,
                payload.get("error", "unknown error"),
                session_id,
                execution_id,
            )

        await self.emit("crew_event", session_id, msg)

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        await self._tasks.aclose()
