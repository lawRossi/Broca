"""IPC 地址生成。

AF_UNIX 路径长度是硬约束（108 字节，含结尾 NUL）。macOS 上
``tempfile.gettempdir()`` 实测 48 字符，``48 + 1 + len("broca_runner_") +
64 + len(".sock") = 131 > 108``——固定截断到 64 会让每次 ``start_session``
都抛 ``OSError: AF_UNIX path too long``。因此这里按「剩余预算」动态决定
是否走 sha1 摘要分支。
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile

# AF_UNIX 路径上限（Linux/macOS 均为 108 字节，含结尾 NUL）
AF_UNIX_PATH_MAX = 108
# 预留 8 字节余量：不同系统对 sun_path 的 NUL 终止处理略有差异
AF_UNIX_PATH_BUDGET = 100
_PREFIX = "broca_runner_"
_SUFFIX = ".sock"
# 摘要长度：sha1 前 16 个 hex 字符，碰撞概率可忽略
_DIGEST_LEN = 16


def _socket_basename(session_id: str, budget: int) -> str:
    """按剩余预算生成 socket 文件名。

    超长 id 用 sha1 摘要：长度恒定，且避免「两个长 id 截断后同名」。
    """
    if budget <= 0 or len(session_id) > budget:
        digest = hashlib.sha1(session_id.encode()).hexdigest()[:_DIGEST_LEN]
        return f"{_PREFIX}{digest}{_SUFFIX}"
    return f"{_PREFIX}{session_id}{_SUFFIX}"


def get_ipc_address(session_id: str) -> str:
    """根据平台生成 IPC 地址。"""
    if sys.platform == "win32":
        # 命名管道无长度限制
        return rf"\\.\pipe\broca_runner_{session_id}"

    tmp = tempfile.gettempdir()
    budget = AF_UNIX_PATH_BUDGET - len(tmp) - 1 - len(_PREFIX) - len(_SUFFIX)
    return os.path.join(tmp, _socket_basename(session_id, budget))


def get_ipc_family() -> str:
    """根据平台返回 IPC 协议族。"""
    if sys.platform == "win32":
        return "AF_PIPE"
    return "AF_UNIX"
