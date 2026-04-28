"""
Session Runner 模块

提供 Session 独立进程运行能力，包含：
- IPC 通信：跨平台进程间通信
- Runner 子进程：独立运行 Agent 的进程
- Manager：管理子进程生命周期
- 心跳检测：进程健康监控
"""

from broca.session_runner.ipc import IPCClient, IPCServer, create_ipc_message, create_response_message
from broca.session_runner.manager import RunnerManager
from broca.session_runner.models import (
    IPCStatusCode,
    IPCMessage,
    IPCMessageType,
    RunnerProcessInfo,
    RunnerResourceUsage,
    RunnerStatus,
)

__all__ = [
    "IPCClient",
    "IPCServer",
    "create_ipc_message",
    "create_response_message",
    "RunnerManager",
    "IPCMessage",
    "IPCMessageType",
    "IPCStatusCode",
    "RunnerProcessInfo",
    "RunnerResourceUsage",
    "RunnerStatus",
]
