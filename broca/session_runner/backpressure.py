"""IPC 队列背压策略（P1-7）。

历史问题：两处 ``asyncio.Queue`` 都不带 ``maxsize``。

- ``manager.py`` 的 per-session 消费队列（现由 ``poller.py`` 创建）
- ``runner.py`` 的 IPC 监听队列

事件循环被长工具调用 / 慢 DB 查询卡住时，IPC 轮询线程仍在持续投递，
队列无界增长 → 内存持续上涨，最终 OOM。而「卡住轮询线程」不是解法：
那会让所有 session 的心跳一起停摆，被心跳巡检误判为崩溃。

策略（按消息类型分流）：

===========================  ============================================
消息类型                      队列满时的处理
===========================  ============================================
``EVT_HEARTBEAT``            丢弃**最旧的**心跳，保留最新的（心跳可合并）
其它消息（命令/响应/事件）    记 WARNING 后丢弃**新消息**，绝不丢旧的
断连哨兵（``None``）          ``force=True``，丢弃最旧的直到有空间
===========================  ============================================

为什么「其它消息丢新、心跳丢旧」：

- 命令/响应是有状态的（``send_command`` 等一个 RESPONSE），丢掉旧的可能
  让调用方永久等不到响应；丢掉新的只是这一次失败，调用方会超时重试。
- 心跳是幂等的快照，最新一条就覆盖了全部语义，旧的没有任何价值。

所有丢弃都计入 :class:`DroppedEvents`，由 ``get_stats()["dropped_events"]``
暴露 —— 线上看到 ``total > 0`` 就说明消费侧跟不上，需要扩容或查慢操作。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from broca.logging_config import get_logger

logger = get_logger(__name__)

# 队列默认上限（可被 execution.runner_ipc_queue_size 覆盖）
DEFAULT_QUEUE_SIZE = 1000
# 心跳消息的类型值（与 IPCMessageType.EVT_HEARTBEAT 保持一致，
# 这里用字面量避免 backpressure 反向依赖 models 层）
HEARTBEAT_TYPE = "evt_heartbeat"


def is_heartbeat(msg: Any) -> bool:
    """判断消息是否为心跳（兼容 IPCMessage / dict / 已解码字符串）。"""
    if msg is None:
        return False
    msg_type = getattr(msg, "type", None)
    if msg_type is None and isinstance(msg, dict):
        msg_type = msg.get("type")
    value = getattr(msg_type, "value", msg_type)
    return value == HEARTBEAT_TYPE


@dataclass
class DroppedEvents:
    """丢弃计数（区分心跳与其它，便于判断是「可合并」还是「真丢消息」）。"""

    heartbeat: int = 0
    other: int = 0

    @property
    def total(self) -> int:
        return self.heartbeat + self.other

    def to_dict(self) -> dict[str, int]:
        return {"total": self.total, "heartbeat": self.heartbeat, "other": self.other}


def _drop_oldest(queue: "asyncio.Queue") -> bool:
    """无条件丢弃队首一条消息；队列为空返回 False。"""
    try:
        queue.get_nowait()
        return True
    except asyncio.QueueEmpty:
        return False


def _drop_oldest_heartbeat(queue: "asyncio.Queue") -> bool:
    """尝试丢掉最旧的一条心跳，成功返回 True。

    不能简单 ``get_nowait()`` 一丢了之：队列里混着 RESPONSE 时，丢掉队首会让
    ``send_command`` 永远等不到响应（表现为 10s 超时）。因此：
    队首是心跳 → 丢掉；不是心跳 → **放回去**，宁可丢新来的心跳。
    """
    try:
        oldest = queue.get_nowait()
    except asyncio.QueueEmpty:
        return False

    if is_heartbeat(oldest):
        return True

    # 不是心跳：放回队尾（顺序可能变化，但保证不丢非心跳消息）。
    # 刚刚 pop 掉一条，这里必然有空位；万一被并发填满，保守返回 False。
    try:
        queue.put_nowait(oldest)
    except asyncio.QueueFull:  # pragma: no cover - 需要极端并发才会命中
        return False
    return False


def put_with_backpressure(
    queue: "asyncio.Queue",
    msg: Any,
    dropped: DroppedEvents,
    *,
    session_id: str = "",
    force: bool = False,
) -> bool:
    """非阻塞入队；队列满时按背压策略处理。

    Args:
        queue: 目标队列（应带 ``maxsize``）
        msg: 待投递消息
        dropped: 丢弃计数器（原地累加）
        session_id: 仅用于日志
        force: True 表示「必须入队」（断连哨兵），丢弃最旧的直到有空间

    Returns:
        True 表示消息已入队（含「丢旧心跳腾位后入队」），False 表示被丢弃。

    必须在**事件循环线程**内调用（``asyncio.Queue`` 非线程安全）。
    """
    try:
        queue.put_nowait(msg)
        return True
    except asyncio.QueueFull:
        pass

    if force:
        # 断连哨兵：丢多少条旧消息都行，绝不能丢它（否则监听循环永不退出）
        while _drop_oldest(queue):
            try:
                queue.put_nowait(msg)
                return True
            except asyncio.QueueFull:  # pragma: no cover - 单线程下不会命中
                continue
        return False

    if is_heartbeat(msg):
        # 心跳：优先腾掉最旧的心跳，保留最新
        if _drop_oldest_heartbeat(queue):
            try:
                queue.put_nowait(msg)
                dropped.heartbeat += 1
                logger.debug(
                    "IPC queue full for session %s: dropped oldest heartbeat",
                    session_id,
                )
                return True
            except asyncio.QueueFull:  # pragma: no cover - 单线程下不会命中
                pass
        dropped.heartbeat += 1
        logger.debug(
            "IPC queue full for session %s: dropped new heartbeat "
            "(no heartbeat to evict)",
            session_id,
        )
        return False

    # 非心跳：丢新消息，保旧消息
    dropped.other += 1
    logger.warning(
        "IPC queue full for session %s: dropped %s message "
        "(dropped total=%d heartbeat=%d other=%d)",
        session_id,
        type(msg).__name__,
        dropped.total,
        dropped.heartbeat,
        dropped.other,
    )
    return False
