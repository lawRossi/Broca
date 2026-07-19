"""
Session Runner 数据结构定义

定义 Runner 进程管理相关的数据结构和状态枚举。
"""

import sys
from dataclasses import dataclass, field
from datetime import datetime
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
    CMD_EXECUTE = "cmd_execute"  # 执行用户消息
    CMD_ABORT = "cmd_abort"  # 中止当前执行
    CMD_STATUS = "cmd_status"  # 查询状态
    CMD_SHUTDOWN = "cmd_shutdown"  # 优雅关闭
    CMD_GET_STATS = "cmd_get_stats"  # 获取统计信息
    CMD_RESTART = "cmd_restart"  # 重启（由 Manager 处理）

    # Web → Runner 编排命令
    CMD_RUN_CREW = "cmd_run_crew"  # 运行编排
    CMD_ABORT_CREW = "cmd_abort_crew"  # 中止编排
    CMD_CREW_STATUS = "cmd_crew_status"  # 查询编排状态

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


# IPC 地址生成工具


def get_ipc_address(session_id: str) -> str:
    """根据平台生成 IPC 地址"""
    if sys.platform == "win32":
        return rf"\\.\pipe\broca_runner_{session_id}"
    else:
        return f"/tmp/broca_runner_{session_id}.sock"


def get_ipc_family() -> str:
    """根据平台返回 IPC 协议族"""
    if sys.platform == "win32":
        return "AF_PIPE"
    else:
        return "AF_UNIX"
