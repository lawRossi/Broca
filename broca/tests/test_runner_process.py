"""`SessionRunnerProcess` 测试（Phase 3 Task 3.4）

历史问题：`runner.py` 是「8 个模块级全局变量 + 233 行 if/elif」的过程式脚本，
两个实例无法共存，测试只能靠 monkeypatch 全局变量。
"""

from __future__ import annotations

import argparse
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.session_runner.models import IPCMessageType, IPCStatusCode
from broca.session_runner.runner import SessionRunnerProcess


def _make_args(session_id: str = "session-process") -> argparse.Namespace:
    return argparse.Namespace(
        session_id=session_id,
        workspace="/tmp/ws",
        log_file=None,
        log_level="INFO",
        config=None,
    )


def _make_ipc() -> MagicMock:
    ipc = MagicMock()
    ipc.session_id = "session-process"
    ipc.sent = []
    ipc.send_message = MagicMock(side_effect=lambda msg: ipc.sent.append(msg))
    return ipc


def _make_process(session_id: str = "session-process") -> SessionRunnerProcess:
    return SessionRunnerProcess(_make_args(session_id), _make_ipc())


def _make_cmd(msg_type: IPCMessageType, payload=None) -> MagicMock:
    msg = MagicMock()
    msg.type = msg_type
    msg.session_id = "session-process"
    msg.message_id = "msg-1"
    msg.payload = payload or {}
    return msg


# ---------------------------------------------------------------------------
# 实例隔离
# ---------------------------------------------------------------------------


def test_two_instances_do_not_share_state():
    """两个实例的 agents / running / crew_runner 必须完全独立（无模块级全局）。"""
    a = _make_process("session-a")
    b = _make_process("session-b")

    a.agents = [MagicMock(name="agent-a")]
    a.running = True
    a.crew_runner = MagicMock()

    assert b.agents == []
    assert b.running is False
    assert b.crew_runner is None
    assert a.ipc is not b.ipc


# ---------------------------------------------------------------------------
# request_shutdown
# ---------------------------------------------------------------------------


def test_request_shutdown_sets_all_flags():
    """request_shutdown 必须同时清 running 并 set shutdown_event（唤醒所有循环）。"""
    process = _make_process()
    process.running = True
    process.shutdown_event = asyncio.Event()

    process.request_shutdown("test")

    assert process.running is False
    assert process.shutdown_event.is_set()
    assert process.ipc_lost is False


def test_mark_ipc_lost_also_requests_shutdown():
    """IPC 断开 → ipc_lost 置位 + 触发 shutdown（避免孤儿进程）。"""
    process = _make_process()
    process.running = True
    process.shutdown_event = asyncio.Event()

    process.mark_ipc_lost("backend died")

    assert process.ipc_lost is True
    assert process.running is False
    assert process.shutdown_event.is_set()


# ---------------------------------------------------------------------------
# 编排互斥
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_crew_is_rejected_while_first_running():
    """已有编排在跑时，第二次 CMD_RUN_CREW 必须返回 ERROR 且带 active_crew_id。"""
    process = _make_process()
    active = MagicMock()
    active._crew_id = "crew-active"
    process.crew_runner = active

    msg = _make_cmd(IPCMessageType.CMD_RUN_CREW, {"yaml_content": "name: x"})
    await process.handle_ipc_command(msg)

    assert len(process.ipc.sent) == 1
    response = process.ipc.sent[0]
    assert response.status == IPCStatusCode.ERROR
    assert response.payload["active_crew_id"] == "crew-active"
    # 第一个编排仍在，可继续 abort
    assert process.crew_runner is active


@pytest.mark.asyncio
async def test_abort_crew_reports_error_when_none_active():
    """没有活跃编排时 CMD_ABORT_CREW 返回 ERROR（而不是静默成功）。"""
    process = _make_process()
    msg = _make_cmd(IPCMessageType.CMD_ABORT_CREW, {"crew_id": "crew-1"})

    await process.handle_ipc_command(msg)

    assert process.ipc.sent[0].status == IPCStatusCode.ERROR
    assert process.ipc.sent[0].payload["success"] is False


# ---------------------------------------------------------------------------
# Agent 任务异常
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_task_exception_is_logged(caplog):
    """Agent 任务抛异常后必须被取回并记 ERROR（否则告警只在退出时冒出来）。"""

    async def _boom():
        raise RuntimeError("agent crashed")

    process = _make_process()
    process.agent_tasks = [asyncio.create_task(_boom())]
    await asyncio.gather(*process.agent_tasks, return_exceptions=True)

    with caplog.at_level("ERROR", logger="broca.session_runner.runner"):
        process._log_agent_task_failures()

    assert any("agent crashed" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# 命令分发基础
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_shutdown_responds_then_stops():
    process = _make_process()
    process.running = True
    process.shutdown_event = asyncio.Event()

    await process.handle_ipc_command(_make_cmd(IPCMessageType.CMD_SHUTDOWN))

    assert process.ipc.sent[0].status == IPCStatusCode.SUCCESS
    assert process.running is False
    assert process.shutdown_event.is_set()


@pytest.mark.asyncio
async def test_unknown_command_does_not_raise(caplog):
    process = _make_process()
    msg = _make_cmd(IPCMessageType.CMD_STATUS)
    msg.type = MagicMock(value="unknown_cmd")

    with caplog.at_level("WARNING", logger="broca.session_runner.runner"):
        await process.handle_ipc_command(msg)

    assert not process.ipc.sent


@pytest.mark.asyncio
async def test_cmd_status_reports_agent_count():
    process = _make_process()
    process.running = True
    process.start_time = 0.0
    process.agents = [MagicMock(), MagicMock()]

    await process.handle_ipc_command(_make_cmd(IPCMessageType.CMD_STATUS))

    payload = process.ipc.sent[0].payload
    assert payload["agent_count"] == 2


# ---------------------------------------------------------------------------
# 日志目录
# ---------------------------------------------------------------------------


def test_setup_logging_handles_bare_filename(tmp_path):
    """log_file 只有文件名（dirname 为空）时不得抛 FileNotFoundError。"""
    from broca.session_runner.runner import setup_logging

    with patch("broca.session_runner.runner.logging.basicConfig"):
        setup_logging("runner.log")
        setup_logging(str(tmp_path / "nested" / "runner.log"))

    assert (tmp_path / "nested").is_dir()
