"""IPC 通信模块（薄壳）。

实现已拆分到 ``broca.session_runner.transport``：
``addresses`` / ``base`` / ``server`` / ``client``。

本模块只做 re-export，保证既有引用
（``manager.py``、``runner.py``、``orchestrator_runner.py``、测试）不破。
"""

from broca.session_runner.transport.addresses import (
    AF_UNIX_PATH_BUDGET,
    AF_UNIX_PATH_MAX,
    get_ipc_address,
    get_ipc_family,
)
from broca.session_runner.transport.base import (
    IPCChannel,
    IPCConnectionError,
    IPCTimeoutError,
    create_ipc_message,
    create_response_message,
)
from broca.session_runner.transport.client import IPCClient
from broca.session_runner.transport.server import IPCServer

__all__ = [
    "AF_UNIX_PATH_BUDGET",
    "AF_UNIX_PATH_MAX",
    "IPCChannel",
    "IPCClient",
    "IPCConnectionError",
    "IPCServer",
    "IPCTimeoutError",
    "create_ipc_message",
    "create_response_message",
    "get_ipc_address",
    "get_ipc_family",
]
