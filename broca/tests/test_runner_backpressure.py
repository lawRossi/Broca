"""队列背压 + 日志轮转测试（Task 4.4 / P1-7）。

历史问题：两处 ``asyncio.Queue`` 都没有 ``maxsize``。事件循环被长工具调用
或慢 DB 查询卡住时，IPC 轮询线程仍在持续投递 → 队列无界增长 → OOM。

本文件的用例锁住三件事：

1. **背压策略**：心跳丢最旧的、其它消息丢新的，且都不阻塞轮询线程；
2. **可观测性**：``get_stats()["dropped_events"]`` 区分 heartbeat / other，
   线上能据此判断「心跳被合并（可接受）」还是「真丢了命令（要查）」；
3. **日志轮转**：子进程长驻，必须由 ``TimedRotatingFileHandler`` 负责跨天
   轮转与保留，而不是靠文件名带日期（那种做法跨天不轮转）。
"""

from __future__ import annotations

import asyncio
import pathlib
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from broca.session_runner.backpressure import (
    DroppedEvents,
    is_heartbeat,
    put_with_backpressure,
)
from broca.session_runner.ipc import create_ipc_message
from broca.session_runner.models import IPCMessageType

SESSION_ID = "session-backpressure"


def _heartbeat(seq: int):
    return create_ipc_message(
        IPCMessageType.EVT_HEARTBEAT, SESSION_ID, payload={"seq": seq}
    )


def _command(seq: int):
    return create_ipc_message(
        IPCMessageType.CMD_STATUS, SESSION_ID, payload={"seq": seq}
    )


def _seq(msg) -> int:
    return msg.payload["seq"]


# ---------------------------------------------------------------------------
# 1. 背压策略
# ---------------------------------------------------------------------------


def test_is_heartbeat_accepts_message_and_dict():
    """心跳识别要兼容 IPCMessage / dict / 裸字符串三种形态。"""
    assert is_heartbeat(_heartbeat(1)) is True
    assert is_heartbeat({"type": "evt_heartbeat"}) is True
    assert is_heartbeat({"type": "cmd_status"}) is False
    assert is_heartbeat(_command(1)) is False
    assert is_heartbeat(None) is False


@pytest.mark.asyncio
async def test_queue_full_drops_oldest_heartbeat():
    """队列满 + 新心跳 → 丢最旧的心跳，保留最新的。"""
    queue: asyncio.Queue = asyncio.Queue(maxsize=3)
    dropped = DroppedEvents()

    for seq in range(3):
        assert put_with_backpressure(queue, _heartbeat(seq), dropped) is True
    assert dropped.total == 0

    # 第 4 条心跳：队列已满 → 丢 seq=0，入队 seq=3
    assert put_with_backpressure(queue, _heartbeat(3), dropped) is True

    remaining = [_seq(queue.get_nowait()) for _ in range(queue.qsize())]
    assert remaining == [1, 2, 3], "必须丢最旧的心跳，保留最新的"
    assert dropped.heartbeat == 1
    assert dropped.other == 0


@pytest.mark.asyncio
async def test_queue_full_drops_non_heartbeat_and_counts():
    """队列满 + 非心跳 → 丢**新**消息（保旧消息），并计入 other。"""
    queue: asyncio.Queue = asyncio.Queue(maxsize=2)
    dropped = DroppedEvents()

    put_with_backpressure(queue, _command(0), dropped)
    put_with_backpressure(queue, _command(1), dropped)

    assert put_with_backpressure(queue, _command(2), dropped) is False

    remaining = [_seq(queue.get_nowait()) for _ in range(queue.qsize())]
    assert remaining == [0, 1], "非心跳消息不能丢旧的（调用方会等不到响应）"
    assert dropped.other == 1
    assert dropped.heartbeat == 0


@pytest.mark.asyncio
async def test_queue_full_heartbeat_does_not_evict_command():
    """队列里最旧的是命令时，不得为了塞心跳而丢掉命令。"""
    queue: asyncio.Queue = asyncio.Queue(maxsize=2)
    dropped = DroppedEvents()

    put_with_backpressure(queue, _command(0), dropped)
    put_with_backpressure(queue, _heartbeat(1), dropped)

    # 再来一条心跳：队首是命令 → 放弃腾位，丢新心跳
    assert put_with_backpressure(queue, _heartbeat(2), dropped) is False

    remaining = queue.qsize()
    assert remaining == 2
    assert dropped.heartbeat == 1
    assert dropped.other == 0


@pytest.mark.asyncio
async def test_force_sentinel_is_never_dropped():
    """断连哨兵（force=True）必须入队，否则监听循环永远退不出去。"""
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    dropped = DroppedEvents()
    put_with_backpressure(queue, _command(0), dropped)

    assert put_with_backpressure(queue, None, dropped, force=True) is True
    assert queue.get_nowait() is None


# ---------------------------------------------------------------------------
# 2. 可观测性：get_stats()["dropped_events"]
# ---------------------------------------------------------------------------


def test_dropped_count_in_stats():
    """manager.get_stats() 必须暴露 dropped_events（区分 heartbeat / other）。"""
    from broca.session_runner.manager import IPCSessionRunner

    IPCSessionRunner._instance = None
    mgr = IPCSessionRunner()
    mgr._registry.clear()

    stats = mgr.get_stats()
    assert "dropped_events" in stats
    assert stats["dropped_events"] == {"total": 0, "heartbeat": 0, "other": 0}
    assert "dropped_events" in stats["ipc"]
    assert "queue_size" in stats["ipc"]

    # 模拟丢 2 条心跳 + 1 条命令
    mgr._poller.dropped.heartbeat = 2
    mgr._poller.dropped.other = 1

    stats = mgr.get_stats()
    assert stats["dropped_events"] == {"total": 3, "heartbeat": 2, "other": 1}
    assert stats["ipc"]["dropped_count"] == 3
    mgr._registry.clear()


@pytest.mark.asyncio
async def test_runner_stats_expose_dropped_events():
    """runner 侧 CMD_GET_STATS 也要回传 dropped_events。"""
    from broca.session_runner.runner import SessionRunnerProcess

    ipc = MagicMock()
    args = MagicMock(session_id=SESSION_ID)
    proc = SessionRunnerProcess(args, ipc)
    proc.agents = []
    proc.dropped_events.heartbeat = 4

    request = create_ipc_message(IPCMessageType.CMD_GET_STATS, SESSION_ID)
    await proc._handle_cmd_get_stats(request)

    payload = ipc.send_message.call_args.args[0].payload
    assert payload["dropped_events"] == {"total": 4, "heartbeat": 4, "other": 0}


# ---------------------------------------------------------------------------
# 3. 长期守卫：不得再出现无界队列
# ---------------------------------------------------------------------------


def test_no_unbounded_asyncio_queue_in_source():
    """``broca/session_runner/`` 下不允许出现无 maxsize 的 ``asyncio.Queue``。

    这是 Task 4.4 的长期守卫：无界队列在事件循环卡顿时必然 OOM，
    且问题只在压力下暴露，code review 很容易漏掉。
    """
    root = pathlib.Path(__file__).resolve().parents[1] / "session_runner"
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "asyncio.Queue()" in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"发现无界队列：{offenders}"


# ---------------------------------------------------------------------------
# 4. 日志轮转
# ---------------------------------------------------------------------------


def test_log_rotation_creates_backup(tmp_path):
    """跨天轮转必须产生带日期后缀的备份文件，且备份数受 backupCount 约束。"""
    import logging
    from logging.handlers import TimedRotatingFileHandler

    from broca.logging_config import get_runner_log_backup_days

    log_file = tmp_path / "runner.log"
    handler = TimedRotatingFileHandler(
        str(log_file),
        when="midnight",
        backupCount=get_runner_log_backup_days(),
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    record_logger = logging.getLogger("broca.tests.log_rotation")
    record_logger.setLevel(logging.INFO)
    record_logger.addHandler(handler)
    record_logger.propagate = False
    try:
        record_logger.info("before rollover")
        handler.flush()

        # 模拟跨天：把 rollover 时间点提前一天，再触发轮转
        handler.rolloverAt = 0
        handler.doRollover()
        record_logger.info("after rollover")
        handler.flush()

        backups = sorted(p.name for p in tmp_path.iterdir() if p.name != "runner.log")
        assert backups, "doRollover 必须生成备份文件"
        # 后缀是 %Y-%m-%d（when="midnight"）
        datetime.strptime(backups[0].split("runner.log.")[1], "%Y-%m-%d")
        assert log_file.read_text(encoding="utf-8").strip() == "after rollover"
    finally:
        record_logger.removeHandler(handler)
        handler.close()


def test_runner_log_file_is_fixed_name(tmp_path):
    """父进程给子进程的日志路径必须是固定文件名（轮转交给 handler）。"""
    from broca.session_runner.manager import IPCSessionRunner

    IPCSessionRunner._instance = None
    mgr = IPCSessionRunner()
    mgr._log_dir = tmp_path
    path = pathlib.Path(mgr._get_runner_log_file("session-fixed-log"))
    assert path.name == "runner.log", (
        "日志文件名带日期会导致长驻子进程跨天不轮转（历史 bug）"
    )
    assert path.parent.is_dir(), "日志目录必须被创建"
