"""
进程崩溃自动恢复模块

当 Runner 进程异常退出或心跳超时时，自动检测并尝试恢复。
支持带退避的重试策略和最大重试次数限制。
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


# 默认恢复配置
DEFAULT_MAX_RESTARTS = 3                # 最大重启次数
DEFAULT_BACKOFF_BASE = 2.0              # 退避基数（秒）
DEFAULT_BACKOFF_MAX = 60.0              # 最大退避间隔（秒）
DEFAULT_RESTART_WINDOW = 300            # 重启计数窗口（5分钟内计数）


@dataclass
class RecoveryConfig:
    """恢复配置"""
    max_restarts: int = DEFAULT_MAX_RESTARTS
    backoff_base: float = DEFAULT_BACKOFF_BASE
    backoff_max: float = DEFAULT_BACKOFF_MAX
    restart_window: float = DEFAULT_RESTART_WINDOW


@dataclass
class RecoveryState:
    """Session 恢复状态"""
    session_id: str
    restart_count: int = 0
    last_restart_at: Optional[datetime] = None
    restart_timestamps: list = field(default_factory=list)
    is_recovering: bool = False
    error_message: Optional[str] = None

    def can_restart(self, config: RecoveryConfig) -> bool:
        """
        检查是否可以继续重启

        在 restart_window 时间窗口内，重启次数不超过 max_restarts。

        Args:
            config: 恢复配置

        Returns:
            是否可以重启
        """
        now = time.time()
        # 清理窗口外的记录
        self.restart_timestamps = [
            t for t in self.restart_timestamps
            if now - t < config.restart_window
        ]
        return len(self.restart_timestamps) < config.max_restarts

    def get_backoff_seconds(self, config: RecoveryConfig) -> float:
        """
        计算下一次重启前的退避时间

        使用指数退避: base * 2^retry_count, 最大不超过 max

        Args:
            config: 恢复配置

        Returns:
            退避时间（秒）
        """
        # 使用窗口内的重启次数计算退避
        retry_count = len(self.restart_timestamps)
        delay = config.backoff_base * (2 ** retry_count)
        return min(delay, config.backoff_max)

    def record_restart(self) -> None:
        """记录一次重启"""
        now = time.time()
        self.restart_timestamps.append(now)
        self.last_restart_at = datetime.now(timezone.utc)
        self.restart_count += 1
        self.is_recovering = False


class SessionRecoveryManager:
    """
    Session 恢复管理器

    监听 Manager 的事件，在进程崩溃时自动执行恢复。
    """

    def __init__(self, config: Optional[RecoveryConfig] = None):
        self.config = config or RecoveryConfig()
        self._states: Dict[str, RecoveryState] = {}
        self._restart_func: Optional[Callable] = None

    def set_restart_handler(self, handler: Callable) -> None:
        """
        设置重启处理函数

        Args:
            handler: 接受 session_id 参数的异步函数
        """
        self._restart_func = handler

    def get_state(self, session_id: str) -> RecoveryState:
        """获取 Session 的恢复状态"""
        if session_id not in self._states:
            self._states[session_id] = RecoveryState(session_id=session_id)
        return self._states[session_id]

    def remove_state(self, session_id: str) -> None:
        """移除 Session 的恢复状态"""
        self._states.pop(session_id, None)

    async def handle_crash(self, session_id: str) -> bool:
        """
        处理进程崩溃事件

        自动判断是否需要重启，执行带退避的重试。

        Args:
            session_id: 崩溃的 Session ID

        Returns:
            是否成功恢复（或正在恢复中）
        """
        state = self.get_state(session_id)

        if state.is_recovering:
            logger.info("Session %s already in recovery, skipping", session_id)
            return True

        if not self._restart_func:
            logger.error("No restart handler set for recovery manager")
            state.error_message = "No restart handler configured"
            return False

        if not state.can_restart(self.config):
            logger.error(
                "Session %s exceeded max restarts (%d) in window (%.0fs)",
                session_id, self.config.max_restarts, self.config.restart_window,
            )
            state.error_message = (
                f"Exceeded max restarts ({self.config.max_restarts}) "
                f"in {self.config.restart_window}s window"
            )
            return False

        # 计算退避时间
        backoff = state.get_backoff_seconds(self.config)
        state.is_recovering = True

        logger.info(
            "Session %s crash detected, restarting in %.1fs (attempt %d/%d)",
            session_id, backoff,
            len(state.restart_timestamps) + 1,
            self.config.max_restarts,
        )

        # 退避等待
        await asyncio.sleep(backoff)

        try:
            # 执行重启
            if asyncio.iscoroutinefunction(self._restart_func):
                await self._restart_func(session_id)
            else:
                self._restart_func(session_id)

            state.record_restart()
            state.error_message = None
            logger.info(
                "Session %s successfully restarted (attempt %d)",
                session_id, len(state.restart_timestamps),
            )
            return True

        except Exception as e:
            state.is_recovering = False
            state.error_message = str(e)
            logger.error(
                "Failed to restart session %s: %s",
                session_id, e,
            )
            return False

    def get_all_states(self) -> Dict[str, Dict]:
        """获取所有 Session 的恢复状态"""
        return {
            sid: {
                "session_id": state.session_id,
                "restart_count": state.restart_count,
                "last_restart_at": state.last_restart_at.isoformat() if state.last_restart_at else None,
                "is_recovering": state.is_recovering,
                "can_restart": state.can_restart(self.config),
                "error_message": state.error_message,
            }
            for sid, state in self._states.items()
        }
