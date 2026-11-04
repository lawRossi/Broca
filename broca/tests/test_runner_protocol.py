"""`MessageRouter` 测试（Phase 3 Task 3.3）

本文件直接锁住分发机制本身：
- `from_class` 必须扫描**类方法**（handler 定义在类体里，不在模块命名空间）
- `dispatch` 的调用约定是 `handler(ctx, msg)`，ctx 即宿主实例
- router 是实例级的，两个实例互不影响（无模块级单例）
- 所有 `CMD_*` / `EVT_*` 枚举值都必须有 handler（死类型会立刻红）
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import logging
from unittest.mock import patch

from broca.session_runner.manager import IPCSessionRunner
from broca.session_runner.models import IPCMessage, IPCMessageType
from broca.session_runner.protocol import HANDLER_ATTR, MessageRouter, handles
from broca.session_runner.runner import SessionRunnerProcess


@pytest.fixture(autouse=True)
def _stdlib_logger():
    """确保 caplog 可捕获 protocol 模块的日志。"""
    stdlib_logger = logging.getLogger("broca.session_runner.protocol")
    with patch("broca.session_runner.protocol.logger", stdlib_logger):
        yield stdlib_logger


def _make_msg(msg_type: IPCMessageType, session_id: str = "s-1") -> MagicMock:
    msg = MagicMock(spec=IPCMessage)
    msg.type = msg_type
    msg.session_id = session_id
    msg.message_id = "m-1"
    msg.payload = {}
    return msg


# ---------------------------------------------------------------------------
# 枚举覆盖（死代码守卫）
# ---------------------------------------------------------------------------


def test_all_cmd_types_have_runner_handler():
    """每个 CMD_* 都必须在 SessionRunnerProcess 上有 handler。"""
    router = MessageRouter.from_class(SessionRunnerProcess, "runner")

    missing = [
        msg_type.value
        for msg_type in IPCMessageType
        if msg_type.name.startswith("CMD_") and router.handler(msg_type) is None
    ]

    assert not missing, f"以下 CMD_* 没有 runner handler（死类型）: {missing}"


def test_all_evt_types_have_manager_handler():
    """每个 EVT_* 都必须在 IPCSessionRunner 上有 handler。"""
    router = MessageRouter.from_class(IPCSessionRunner, "manager")

    missing = [
        msg_type.value
        for msg_type in IPCMessageType
        if msg_type.name.startswith("EVT_") and router.handler(msg_type) is None
    ]

    assert not missing, f"以下 EVT_* 没有 manager handler（死类型）: {missing}"


# ---------------------------------------------------------------------------
# 机制本身
# ---------------------------------------------------------------------------


def test_from_class_discovers_methods():
    """`from_class` 必须发现类体内带 @handles 标记的方法（恰好 2 个）。"""

    class _Target:
        @handles(IPCMessageType.CMD_STATUS, side="x")
        async def _a(self, msg):
            pass

        @handles(IPCMessageType.CMD_ABORT, side="x")
        async def _b(self, msg):
            pass

        async def _unmarked(self, msg):
            pass

    router = MessageRouter.from_class(_Target, "x")

    assert len(router) == 2
    assert router.handler(IPCMessageType.CMD_STATUS) is _Target._a
    assert router.handler(IPCMessageType.CMD_ABORT) is _Target._b
    assert router.handler(IPCMessageType.CMD_SHUTDOWN) is None


def test_stacked_handles_register_each_type():
    """同一方法叠加多个 @handles 时，每个类型都要注册（不是最后一个覆盖）。"""

    class _Target:
        @handles(IPCMessageType.EVT_CREW_START, side="x")
        @handles(IPCMessageType.EVT_CREW_ERROR, side="x")
        async def _crew(self, msg):
            pass

    router = MessageRouter.from_class(_Target, "x")

    assert router.handler(IPCMessageType.EVT_CREW_START) is _Target._crew
    assert router.handler(IPCMessageType.EVT_CREW_ERROR) is _Target._crew


def test_side_filter_is_respected():
    """side 不匹配的标记不得注册（runner / manager 共用同一枚举）。"""

    class _Target:
        @handles(IPCMessageType.CMD_STATUS, side="runner")
        async def _runner_only(self, msg):
            pass

    assert MessageRouter.from_class(_Target, "manager").handler(
        IPCMessageType.CMD_STATUS
    ) is None
    assert MessageRouter.from_class(_Target, "runner").handler(
        IPCMessageType.CMD_STATUS
    ) is not None


@pytest.mark.asyncio
async def test_dispatch_passes_ctx_as_first_arg():
    """调用约定守卫：handler 收到的第一个参数就是 ctx。"""
    received: list[tuple] = []

    class _Target:
        @handles(IPCMessageType.CMD_STATUS, side="x")
        async def _handler(self, msg):
            received.append((self, msg))

    ctx = _Target()
    router = MessageRouter.from_class(_Target, "x")
    msg = _make_msg(IPCMessageType.CMD_STATUS)

    await router.dispatch(msg, ctx)

    assert received == [(ctx, msg)]


@pytest.mark.asyncio
async def test_dispatch_routes_to_correct_handler():
    """dispatch 只调用 msg.type 对应的那一个 handler。"""
    calls: list[str] = []

    class _Target:
        @handles(IPCMessageType.CMD_STATUS, side="x")
        async def _status(self, msg):
            calls.append("status")

        @handles(IPCMessageType.CMD_ABORT, side="x")
        async def _abort(self, msg):
            calls.append("abort")

    router = MessageRouter.from_class(_Target, "x")

    await router.dispatch(_make_msg(IPCMessageType.CMD_ABORT), _Target())
    await router.dispatch(_make_msg(IPCMessageType.CMD_STATUS), _Target())

    assert calls == ["abort", "status"]


@pytest.mark.asyncio
async def test_unknown_type_does_not_raise(caplog):
    """分发未注册类型只记 warning，不抛异常。"""
    router = MessageRouter()

    with caplog.at_level("WARNING", logger="broca.session_runner.protocol"):
        await router.dispatch(_make_msg(IPCMessageType.CMD_STATUS), object())

    assert any("No handler" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_sync_handler_is_supported():
    """同步 handler 也应被支持（dispatch 只在可 await 时才 await）。"""
    calls: list[int] = []

    class _Target:
        @handles(IPCMessageType.CMD_STATUS, side="x")
        def _sync(self, msg):  # noqa: ANN001
            calls.append(1)

    router = MessageRouter.from_class(_Target, "x")
    await router.dispatch(_make_msg(IPCMessageType.CMD_STATUS), _Target())

    assert calls == [1]


def test_router_instances_are_isolated():
    """同一类构建的两个 router 互不影响（无模块级共享状态）。"""
    a = MessageRouter.from_class(SessionRunnerProcess, "runner")
    b = MessageRouter.from_class(SessionRunnerProcess, "runner")

    a.register(IPCMessageType.CMD_STATUS, lambda ctx, msg: None)

    assert a is not b
    assert len(a) == len(b)
    # 原始 handler 未被 a 的覆盖影响 b
    assert b.handler(IPCMessageType.CMD_STATUS) is not a.handler(
        IPCMessageType.CMD_STATUS
    )


def test_handler_attr_is_the_documented_marker():
    """@handles 只打标记，不改变函数本身的可调用性。"""

    async def _fn(ctx, msg):
        pass

    marked = handles(IPCMessageType.CMD_STATUS, side="x")(_fn)

    assert marked is _fn
    assert getattr(marked, HANDLER_ATTR) == ((IPCMessageType.CMD_STATUS, "x"),)
