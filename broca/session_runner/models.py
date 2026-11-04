"""
Session Runner 数据结构定义

定义 Runner 进程管理相关的数据结构和状态枚举。
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class RunnerStatus(str, Enum):
    """Runner 进程状态枚举"""

    STARTING = "starting"  # 启动中
    ALIVE = "alive"  # 运行正常
    SHUTTING_DOWN = "shutting_down"  # 正在关闭
    DEAD = "dead"  # 已停止
    ERROR = "error"  # 异常
    UNKNOWN = "unknown"  # 未知


class IPCMessageType(str, Enum):
    """IPC 消息类型枚举"""

    # Web → Runner 控制命令
    CMD_ABORT = "cmd_abort"  # 中止当前执行
    CMD_STATUS = "cmd_status"  # 查询状态
    CMD_SHUTDOWN = "cmd_shutdown"  # 优雅关闭
    CMD_GET_STATS = "cmd_get_stats"  # 获取统计信息

    # Web → Runner 编排命令
    CMD_RUN_CREW = "cmd_run_crew"  # 运行编排
    CMD_ABORT_CREW = "cmd_abort_crew"  # 中止编排

    # Runner → Web 事件通知
    EVT_READY = "evt_ready"  # 启动完成
    EVT_HEARTBEAT = "evt_heartbeat"  # 心跳
    EVT_STATUS_CHANGE = "evt_status_change"  # 状态变更
    EVT_ERROR = "evt_error"  # 错误信息
    EVT_COMPLETED = "evt_completed"  # 执行完成
    EVT_LOG = "evt_log"  # 日志信息
    EVT_SHUTDOWN_COMPLETE = "evt_shutdown_complete"  # 关闭完成

    # Runner → Web 编排事件
    EVT_CREW_START = "evt_crew_start"  # 编排开始
    EVT_CREW_PROGRESS = "evt_crew_progress"  # 编排进度
    EVT_CREW_COMPLETE = "evt_crew_complete"  # 编排完成
    EVT_CREW_ERROR = "evt_crew_error"  # 编排错误

    # 响应
    RESPONSE = "response"  # 通用响应


class IPCStatusCode(str, Enum):
    """IPC 响应状态码"""

    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"
    INVALID = "invalid"


@dataclass
class IPCMessage:
    """IPC 消息结构"""

    type: IPCMessageType  # 消息类型
    session_id: str  # Session ID
    message_id: str  # 消息唯一ID
    timestamp: str  # ISO 格式时间戳
    payload: Dict[str, Any] = field(default_factory=dict)  # 消息载荷
    status: Optional[IPCStatusCode] = None  # 响应状态码

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "type": self.type.value,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "status": self.status.value if self.status else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IPCMessage":
        """从字典反序列化"""
        return cls(
            type=IPCMessageType(data["type"]),
            session_id=data["session_id"],
            message_id=data["message_id"],
            timestamp=data["timestamp"],
            payload=data.get("payload", {}),
            status=IPCStatusCode(data["status"]) if data.get("status") else None,
        )


def decode_ipc_message(raw: Any) -> "IPCMessage":
    """把 IPC 线上格式（JSON 字符串或 dict）还原成 :class:`IPCMessage`。

    放在 models 层（无依赖）而不是 transport 层，是因为两处消费者都需要它：
    - ``_BaseIPC._decode``（传统的单消费者 ``receive_message`` 路径）
    - ``IPCPoller``（多路复用路径直接对底层 connection 调 ``recv()``）
    """
    data = json.loads(raw) if isinstance(raw, str) else raw
    return IPCMessage.from_dict(data)


@dataclass
class RunnerProcessInfo:
    """Runner 进程信息"""

    session_id: str
    process: Any  # subprocess.Popen 对象
    pid: Optional[int] = None
    status: RunnerStatus = RunnerStatus.UNKNOWN
    started_at: Optional[datetime] = None
    ipc_address: Optional[str] = None  # IPC 地址（平台自适应）
    ipc_family: Optional[str] = None  # IPC 协议族
    resource_usage: Optional[Dict[str, Any]] = None
    last_heartbeat: Optional[datetime] = None
    restart_count: int = 0
    error_message: Optional[str] = None
    recovery_hint: Optional[str] = None
    # 心跳健康度（由心跳监控循环维护，用于区分"进程已死"与"心跳短暂延迟"）
    heartbeat_stale: bool = False  # 最近一次巡检发现心跳已超过阈值
    missed_heartbeats: int = 0  # 连续心跳超时的巡检次数（收到心跳即清零）
    # 优雅停止标记：用户主动 stop 时置 True，巡检据此分流到
    # HeartbeatMonitor.converge_stopped（发 session_stopped）而非 session_crashed
    stop_requested: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """序列化为对外 API 字典（/runner/status、/runner/list 的载荷）。"""
        from broca.utils.datetime_util import serialize_dt

        uptime = 0.0
        if self.started_at is not None:
            uptime = (datetime.now(timezone.utc) - self.started_at).total_seconds()

        return {
            "session_id": self.session_id,
            "pid": self.pid,
            "status": self.status.value,
            "started_at": serialize_dt(self.started_at),
            "ipc_address": self.ipc_address,
            "resource_usage": self.resource_usage,
            "last_heartbeat": serialize_dt(self.last_heartbeat),
            "restart_count": self.restart_count,
            "error_message": self.error_message,
            "heartbeat_stale": self.heartbeat_stale,
            "missed_heartbeats": self.missed_heartbeats,
            "uptime_seconds": uptime,
        }


@dataclass
class RunnerResourceUsage:
    """Runner 进程资源使用信息"""

    cpu_percent: float = 0.0
    memory_rss: int = 0  # RSS 内存（字节）
    memory_percent: float = 0.0
    num_threads: int = 0
    uptime_seconds: float = 0.0
    status: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cpu_percent": self.cpu_percent,
            "memory_rss": self.memory_rss,
            "memory_rss_mb": round(self.memory_rss / (1024 * 1024), 2),
            "memory_percent": self.memory_percent,
            "num_threads": self.num_threads,
            "uptime_seconds": self.uptime_seconds,
            "status": self.status,
        }


# IPC 地址生成工具（实现已迁至 transport/addresses.py，此处保留一行转发，
# 保证 `from broca.session_runner.models import get_ipc_address` 的既有引用不变）
from broca.session_runner.transport.addresses import (  # noqa: E402,F401
    AF_UNIX_PATH_BUDGET,
    AF_UNIX_PATH_MAX,
    get_ipc_address,
    get_ipc_family,
)
