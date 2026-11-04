"""EventBus 测试（Phase 3 Task 3.2）

历史问题：事件处理散在 manager 里，`_handle_crew_event` 用裸
`asyncio.create_task(handler(...))` 分发 —— 任务无引用、异常静默丢失。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.session_runner.events import EventBus
from broca.session_runner.models import IPCMessageType

import logging
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _stdlib_logger():
    """确保 caplog 可捕获 events 模块的日志。"""
    stdlib_logger = logging.getLogger("broca.session_runner.events")
    with patch("broca.session_runner.events.logger", stdlib_logger):
        yield stdlib_logger


def _make_msg(msg_type=IPCMessageType.EVT_CREW_PROGRESS, payload=None):
    msg = MagicMock()
    msg.type = msg_type
    msg.payload = payload or {
        "crew_id": "crew-1",
        "execution_id": "exec-1",
        "progress": 0.5,
        "current_phase": "writing",
    }
    return msg


@pytest.mark.asyncio
async def test_handler_exception_does_not_break_others():
    """单个 handler 抛异常不影响后续 handler。"""
    bus = EventBus("test")
    calls: list[str] = []

    def _boom(payload):
        calls.append("boom")
        raise RuntimeError("kaboom")

    def _ok(payload):
        calls.append("ok")

    bus.on("evt", _boom)
    bus.on("evt", _ok)

    await bus.emit("evt", {"x": 1})

    assert calls == ["boom", "ok"]
    await bus.aclose()


@pytest.mark.asyncio
async def test_async_and_sync_handlers_both_supported():
    """同步与异步 handler 混用都能被正确 await / 调用。"""
    bus = EventBus("test")
    seen: list[tuple[str, object]] = []

    def _sync(payload):
        seen.append(("sync", payload))

    async def _async(payload):
        await asyncio.sleep(0)
        seen.append(("async", payload))

    bus.on("evt", _sync)
    bus.on("evt", _async)

    await bus.emit("evt", "payload")

    assert seen == [("sync", "payload"), ("async", "payload")]
    await bus.aclose()


@pytest.mark.asyncio
async def test_emit_soon_tasks_are_tracked_and_closed():
    """emit_soon 的任务被 TaskSet 持有引用，aclose 时统一取消。"""
    bus = EventBus("test")
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow(payload):
        started.set()
        await release.wait()

    bus.on("evt", _slow)
    bus.emit_soon("evt", None)
    await started.wait()

    assert len(bus._tasks) == 1

    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(bus._tasks) == 0

    bus.emit_soon("evt", None)
    await asyncio.sleep(0)
    await bus.aclose()
    assert len(bus._tasks) == 0


@pytest.mark.asyncio
async def test_emit_passes_multiple_args():
    """crew_event 的 handler 签名是 (session_id, msg) —— emit 必须透传多个参数。"""
    bus = EventBus("test")
    received: list[tuple] = []

    async def _handler(session_id, msg):
        received.append((session_id, msg))

    bus.on("crew_event", _handler)
    msg = _make_msg()

    await bus.emit("crew_event", "session-1", msg)

    assert received == [("session-1", msg)]
    await bus.aclose()


@pytest.mark.asyncio
async def test_emit_crew_event_logs_and_forwards(caplog):
    """编排事件既写日志，也转发给注册的 crew_event handler。"""
    bus = EventBus("test")
    forwarded: list[tuple] = []

    async def _handler(session_id, msg):
        forwarded.append((session_id, msg))

    bus.on("crew_event", _handler)

    with caplog.at_level("INFO", logger="broca.session_runner.events"):
        await bus.emit_crew_event("session-1", _make_msg())

    assert forwarded and forwarded[0][0] == "session-1"
    assert any("50%" in record.getMessage() for record in caplog.records)
    await bus.aclose()


@pytest.mark.asyncio
async def test_emit_crew_event_error_is_logged_at_error_level(caplog):
    bus = EventBus("test")
    msg = _make_msg(IPCMessageType.EVT_CREW_ERROR, {"crew_id": "c", "error": "bad"})

    with caplog.at_level("ERROR", logger="broca.session_runner.events"):
        await bus.emit_crew_event("session-1", msg)

    assert any("bad" in record.getMessage() for record in caplog.records)
    await bus.aclose()
