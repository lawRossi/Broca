"""Runner 内存注册表。

此前 ``IPCSessionRunner`` 用 7 个并行 dict 维护同一批 session 的状态::

    _runners / _ipc_servers / _ipc_listener_threads / _ipc_listener_tasks
    / _agent_status_cache / _db_state_cache / _pending_responses

它们必须同步增删，任何一处漏改都会产生「有 runner 没 ipc」「有 cache 没 runner」
之类的幽灵状态。这里收成一个 ``RunnerRegistry: dict[str, RunnerHandle]``：
测试也只需 ``registry.clear()`` 一行。
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from broca.session_runner.models import RunnerProcessInfo, RunnerStatus

# 「进程存活即计数」的状态集合（修正 P2-2：旧实现只数 ALIVE/STARTING，
# ERROR/SHUTTING_DOWN 的活进程不占名额，并发上限形同虚设）
_ACTIVE_STATUSES = frozenset(
    {
        RunnerStatus.STARTING,
        RunnerStatus.ALIVE,
        RunnerStatus.ERROR,
        RunnerStatus.SHUTTING_DOWN,
    }
)


@dataclass
class RunnerHandle:
    """一个 session 的全部运行时状态。"""

    info: RunnerProcessInfo
    ipc: Any = None  # IPCChannel（IPCServer）
    poll_thread: Optional[threading.Thread] = None
    poll_task: Optional[asyncio.Task] = None
    agent_status_cache: Optional[dict] = None
    db_state_cache: Optional[tuple] = None
    pending_responses: dict = field(default_factory=dict)


class RunnerRegistry:
    """线程安全的 ``session_id -> RunnerHandle`` 注册表。

    用 ``RLock`` 保护：IPC 轮询线程与事件循环都会访问。
    """

    def __init__(self) -> None:
        self._handles: dict[str, RunnerHandle] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(self, handle: RunnerHandle) -> None:
        with self._lock:
            self._handles[handle.info.session_id] = handle

    def get(self, session_id: str) -> Optional[RunnerHandle]:
        with self._lock:
            return self._handles.get(session_id)

    def pop(self, session_id: str) -> Optional[RunnerHandle]:
        with self._lock:
            return self._handles.pop(session_id, None)

    def all(self) -> list[RunnerHandle]:
        with self._lock:
            return list(self._handles.values())

    def clear(self) -> None:
        with self._lock:
            self._handles.clear()

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._handles.keys())

    def __contains__(self, session_id: object) -> bool:
        with self._lock:
            return session_id in self._handles

    def __len__(self) -> int:
        with self._lock:
            return len(self._handles)

    def active_count(self) -> int:
        """活跃 runner 数：进程存活即计数（含 ERROR / SHUTTING_DOWN）。"""
        with self._lock:
            return sum(
                1
                for handle in self._handles.values()
                if handle.info.status in _ACTIVE_STATUSES
            )
