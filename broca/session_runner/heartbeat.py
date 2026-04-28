"""
心跳与健康检查模块

提供心跳记录管理、健康检查判定等核心能力。
Runner 端的心跳发送和 Manager 端的心跳接收已在 runner.py 和 manager.py 中实现。
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from broca.session_runner.models import RunnerStatus

logger = logging.getLogger(__name__)


# 健康检查阈值常量
HEARTBEAT_TIMEOUT_WARNING = 30  # 30秒无心跳 → WARNING
HEARTBEAT_TIMEOUT_ERROR = 60  # 60秒无心跳 → ERROR
CPU_THRESHOLD_WARNING = 80.0  # CPU > 80% → WARNING
CPU_THRESHOLD_ERROR = 95.0  # CPU > 95% → ERROR
MEMORY_THRESHOLD_WARNING = 500  # 内存 > 500MB → WARNING
MEMORY_THRESHOLD_ERROR = 1000  # 内存 > 1GB → ERROR


@dataclass
class HeartbeatRecord:
    """单次心跳记录"""

    timestamp: datetime
    resource_usage: Dict[str, Any]
    status: str


@dataclass
class HeartbeatTracker:
    """
    心跳追踪器

    维护一个 Session 的心跳历史记录，用于健康检查判定。
    """

    session_id: str
    max_records: int = 60  # 保留最近 60 条记录（5分钟 @ 5秒间隔）
    records: deque = field(default_factory=deque)
    last_heartbeat: Optional[datetime] = None
    _start_time: float = field(default_factory=time.time)

    def __post_init__(self):
        """初始化后设置 deque 的 maxlen"""
        self.records = deque(maxlen=self.max_records)

    def add_record(
        self, resource_usage: Dict[str, Any], status: str
    ) -> HeartbeatRecord:
        """
        添加心跳记录

        Args:
            resource_usage: 资源使用信息
            status: 状态字符串

        Returns:
            创建的心跳记录
        """
        now = datetime.now(timezone.utc)
        record = HeartbeatRecord(
            timestamp=now,
            resource_usage=resource_usage,
            status=status,
        )
        self.records.append(record)
        self.last_heartbeat = now
        return record

    def get_health_status(self) -> Dict[str, Any]:
        """
        计算当前健康状态

        Returns:
            健康检查结果字典
        """
        now = datetime.now(timezone.utc)
        elapsed = (
            (now - self.last_heartbeat).total_seconds()
            if self.last_heartbeat
            else float("inf")
        )

        # 心跳超时判定
        if elapsed > HEARTBEAT_TIMEOUT_ERROR:
            heartbeat_status = "critical"
            status = RunnerStatus.ERROR.value
        elif elapsed > HEARTBEAT_TIMEOUT_WARNING:
            heartbeat_status = "warning"
            status = RunnerStatus.ALIVE.value
        else:
            heartbeat_status = "healthy"
            status = RunnerStatus.ALIVE.value

        # 计算最近 N 条记录的平均资源使用
        recent = (
            list(self.records)[-10:] if len(self.records) > 10 else list(self.records)
        )
        avg_cpu = 0.0
        avg_memory = 0
        if recent:
            cpu_values = [r.resource_usage.get("cpu_percent", 0) for r in recent]
            memory_values = [r.resource_usage.get("memory_rss", 0) for r in recent]
            avg_cpu = sum(cpu_values) / len(cpu_values)
            avg_memory = (
                sum(memory_values) // len(memory_values) if memory_values else 0
            )

        # CPU 超限判定
        if avg_cpu > CPU_THRESHOLD_ERROR:
            cpu_status = "critical"
        elif avg_cpu > CPU_THRESHOLD_WARNING:
            cpu_status = "warning"
        else:
            cpu_status = "healthy"

        # 内存超限判定
        memory_mb = avg_memory / (1024 * 1024)
        if memory_mb > MEMORY_THRESHOLD_ERROR:
            memory_status = "critical"
        elif memory_mb > MEMORY_THRESHOLD_WARNING:
            memory_status = "warning"
        else:
            memory_status = "healthy"

        # 综合判定
        all_statuses = [heartbeat_status, cpu_status, memory_status]
        if "critical" in all_statuses:
            overall = "critical"
        elif "warning" in all_statuses:
            overall = "warning"
        else:
            overall = "healthy"

        return {
            "session_id": self.session_id,
            "overall": overall,
            "status": status,
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "heartbeat": {
                "status": heartbeat_status,
                "last_heartbeat": self.last_heartbeat.isoformat()
                if self.last_heartbeat
                else None,
                "elapsed_seconds": round(elapsed, 1),
            },
            "cpu": {
                "status": cpu_status,
                "average_percent": round(avg_cpu, 1),
            },
            "memory": {
                "status": memory_status,
                "average_mb": round(memory_mb, 1),
                "average_rss": avg_memory,
            },
            "record_count": len(self.records),
        }

    def is_alive(self, timeout: float = HEARTBEAT_TIMEOUT_ERROR) -> bool:
        """
        检查 Runner 是否存活

        Args:
            timeout: 超时阈值（秒）

        Returns:
            是否存活
        """
        if not self.last_heartbeat:
            return False
        elapsed = (datetime.now(timezone.utc) - self.last_heartbeat).total_seconds()
        return elapsed < timeout


# 全局心跳追踪器映射
_heartbeat_trackers: Dict[str, HeartbeatTracker] = {}


def get_heartbeat_tracker(session_id: str) -> HeartbeatTracker:
    """
    获取或创建 Session 的心跳追踪器

    Args:
        session_id: Session ID

    Returns:
        心跳追踪器
    """
    if session_id not in _heartbeat_trackers:
        _heartbeat_trackers[session_id] = HeartbeatTracker(session_id=session_id)
    return _heartbeat_trackers[session_id]


def remove_heartbeat_tracker(session_id: str) -> None:
    """
    移除 Session 的心跳追踪器

    Args:
        session_id: Session ID
    """
    _heartbeat_trackers.pop(session_id, None)
