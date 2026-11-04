"""IPC 消息路由注册表。

替换两条 if/elif 链：`runner.py` 的 ``handle_ipc_command``（233 行）与
`manager.py` 的 ``_handle_runner_event``（105 行）。

**为什么是 `from_class` 而不是扫描模块**：handler 是类方法（
``async def _handle_cmd_xxx(self, msg)``），定义在**类体**里、不在模块命名空间。
``inspect.getmembers(target_cls, inspect.isfunction)`` 拿到的就是未绑定函数，
``await fn(ctx, msg)`` 中 ``ctx`` 即 ``self``，与 ``(self, msg)`` 签名天然对齐。

**为什么没有模块级 router 实例**：router 由 ``SessionRunnerProcess`` /
``IPCSessionRunner`` 各自在 ``__init__`` 里构建，测试可 per-instance 隔离，
不依赖 import 副作用，也不需要全局 ``reset()``。
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

from broca.session_runner.models import IPCMessage, IPCMessageType
from broca.logging_config import get_logger

logger = get_logger(__name__)

# 装饰器在函数上留下的标记属性名（值为 [(msg_type, side), ...]，支持叠加）
HANDLER_ATTR = "__ipc_handler__"

# 调用约定：handler(ctx, msg) —— ctx 是宿主实例（SessionRunnerProcess / IPCSessionRunner）
HandlerFn = Callable[[Any, IPCMessage], Any]


class MessageRouter:
    """``IPCMessageType -> handler`` 的实例级路由表。"""

    def __init__(
        self, handlers: Iterable[Tuple[IPCMessageType, HandlerFn]] = ()
    ) -> None:
        self._handlers: Dict[IPCMessageType, HandlerFn] = dict(handlers)

    # ------------------------------------------------------------------
    # 注册 / 查询
    # ------------------------------------------------------------------

    def register(self, msg_type: IPCMessageType, fn: HandlerFn) -> None:
        self._handlers[msg_type] = fn

    def handler(self, msg_type: IPCMessageType) -> Optional[HandlerFn]:
        return self._handlers.get(msg_type)

    def registered_types(self) -> list[IPCMessageType]:
        return list(self._handlers)

    def __len__(self) -> int:
        return len(self._handlers)

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    @classmethod
    def from_class(cls, target_cls: type, side: str) -> "MessageRouter":
        """扫描 ``target_cls``（含继承链）中带 ``@handles`` 标记的**方法**。"""
        router = cls()
        for _name, fn in inspect.getmembers(target_cls, predicate=inspect.isfunction):
            for msg_type, marked_side in getattr(fn, HANDLER_ATTR, ()):
                if marked_side == side:
                    router.register(msg_type, fn)
        return router

    # ------------------------------------------------------------------
    # 分发
    # ------------------------------------------------------------------

    async def dispatch(self, msg: IPCMessage, ctx: Any) -> None:
        """按 ``msg.type`` 调用 ``handler(ctx, msg)``；未注册类型只告警不抛。"""
        fn = self.handler(msg.type)
        if fn is None:
            logger.warning(
                "No handler for IPC message type %s (session=%s)",
                getattr(msg.type, "value", msg.type),
                getattr(msg, "session_id", "?"),
            )
            return
        result = fn(ctx, msg)
        if inspect.isawaitable(result):
            await result


def handles(msg_type: IPCMessageType, *, side: str) -> Callable[[HandlerFn], HandlerFn]:
    """装饰器工厂：只给函数打标记，不产生任何模块级状态。"""

    def deco(fn: HandlerFn) -> HandlerFn:
        marks = list(getattr(fn, HANDLER_ATTR, ()))
        marks.append((msg_type, side))
        setattr(fn, HANDLER_ATTR, tuple(marks))
        return fn

    return deco
