"""Runner 进程判活与回收。

**多因子判活（P2-1）**：仅凭 ``pid_exists(pid)`` 不可信——PID 会被系统复用，
把无关进程当成 runner 杀掉是真实事故。``is_alive`` 要求同时满足：

1. ``psutil.pid_exists(pid)``
2. ``create_time()`` 与记录的 ``started_at`` 相差 < 5s
3. ``cmdline()`` 同时包含 ``broca.session_runner.runner`` 与 ``session_id``

任一不满足 → 返回 ``False`` 且**绝不 kill**。

Windows 降级：``cmdline()`` 可能返回空 list 或抛 ``AccessDenied``，
此时降级为两因子（①+②），不得因取不到 cmdline 就判死。

所有杀进程路径都是异步的（``asyncio.sleep`` 轮询 + ``asyncio.to_thread``），
不会阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from typing import Any, Optional
from broca.logging_config import get_logger

logger = get_logger(__name__)

# create_time 容差：Popen 到 psutil 读取的窗口通常 < 100ms
CREATE_TIME_TOLERANCE = 5.0
# cmdline 必须包含的模块标识
CMDLINE_MODULE_MARKER = "broca.session_runner.runner"
# SIGTERM → SIGKILL 的轮询步长与次数
TERMINATE_POLL_INTERVAL = 0.1
TERMINATE_POLL_ATTEMPTS = 20


def _pid_exists(pid: int) -> bool:
    """跨平台 PID 存在性检查（优先 psutil）。"""
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:  # pragma: no cover - psutil 是项目依赖
        try:
            os.kill(pid, 0)
            return True
        except (OSError, PermissionError):
            return False


class RunnerReaper:
    """判活与杀进程。"""

    # ------------------------------------------------------------------
    # 判活
    # ------------------------------------------------------------------

    def is_alive(self, handle: Any) -> bool:
        """多因子判活。返回 False 时调用方**不得** kill 该 PID。"""
        info = handle.info if hasattr(handle, "info") else handle

        process = getattr(info, "process", None)
        if process is not None:
            try:
                if process.poll() is not None:
                    return False
            except Exception:  # pragma: no cover - 已销毁的 Popen
                pass

        pid = getattr(info, "pid", None)
        if pid is None:
            return False

        try:
            import psutil
        except ImportError:  # pragma: no cover
            return _pid_exists(pid)

        # ---- 因子 1：进程存在 ----
        try:
            proc = psutil.Process(pid)
            create_time = proc.create_time()
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            # 存在但无权限读取 → 保守视为存活（绝不 kill）
            return True

        # ---- 因子 2：创建时间与记录一致 ----
        started_at = getattr(info, "started_at", None)
        if started_at is not None:
            try:
                delta = abs(create_time - started_at.timestamp())
            except Exception:  # pragma: no cover - naive datetime
                delta = 0.0
            if delta >= CREATE_TIME_TOLERANCE:
                logger.debug(
                    "PID %s create_time mismatch (delta=%.2fs) — not our runner",
                    pid,
                    delta,
                )
                return False

        # ---- 因子 3：cmdline 同时包含模块标识与 session_id ----
        try:
            cmdline = proc.cmdline()
        except (psutil.AccessDenied, psutil.ZombieProcess, OSError):
            cmdline = []

        if not cmdline:
            # Windows / 权限受限：降级为两因子（不得判死）
            logger.debug(
                "cmdline unavailable for PID %s — degrading to two factors", pid
            )
            return True

        joined = " ".join(cmdline)
        session_id = getattr(info, "session_id", "")
        if CMDLINE_MODULE_MARKER not in joined:
            logger.debug(f"PID {pid} cmdline missing module marker — not our runner")
            return False
        if session_id and session_id not in joined:
            logger.debug(f"PID {pid} cmdline missing session_id — not our runner")
            return False

        return True

    # ------------------------------------------------------------------
    # 回收
    # ------------------------------------------------------------------

    async def terminate(self, handle: Any, timeout: float = 5.0) -> bool:
        """终止 handle 对应的进程（进程组 SIGTERM → 超时 SIGKILL），全异步。"""
        info = handle.info if hasattr(handle, "info") else handle
        process = getattr(info, "process", None)
        pid = getattr(info, "pid", None)
        session_id = getattr(info, "session_id", "?")

        if process is None and pid is None:
            return False

        try:
            if sys.platform == "win32":
                if process is not None:
                    process.kill()
                    await asyncio.to_thread(process.wait, timeout)
                elif pid is not None:
                    import ctypes

                    handle_win = ctypes.windll.kernel32.OpenProcess(1, False, pid)
                    ctypes.windll.kernel32.TerminateProcess(handle_win, 1)
                    ctypes.windll.kernel32.CloseHandle(handle_win)
                return True

            # POSIX：先给进程组 SIGTERM（允许短暂清理），再 SIGKILL 兜底
            if pid is not None:
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    if process is not None:
                        try:
                            process.terminate()
                        except Exception:
                            pass

            if process is not None:
                try:
                    await asyncio.to_thread(process.wait, timeout)
                    logger.info(f"Runner {session_id} (pid={pid}) exited gracefully")
                    return True
                except subprocess.TimeoutExpired:
                    pass

            if pid is not None:
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                if process is not None:
                    try:
                        await asyncio.to_thread(process.wait, 3.0)
                    except subprocess.TimeoutExpired:
                        logger.error(
                            "Runner %s (pid=%s) survived SIGKILL — possible zombie",
                            session_id,
                            pid,
                        )

            logger.info(f"Runner {session_id} (pid={pid}) force killed")
            return True
        except Exception as e:
            logger.error(f"Failed to terminate runner {session_id}: {e}")
            return False

    async def terminate_by_pid(
        self, pid: int, *, session_id: Optional[str] = None
    ) -> bool:
        """按 PID 终止（SIGTERM → 2s → SIGKILL）。"""
        label = session_id or "?"
        try:
            if sys.platform == "win32":  # pragma: no cover - 平台相关
                import ctypes

                handle = ctypes.windll.kernel32.OpenProcess(1, False, pid)
                ctypes.windll.kernel32.TerminateProcess(handle, 1)
                ctypes.windll.kernel32.CloseHandle(handle)
                return True

            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                logger.debug(f"Process pid={pid} already dead")
                return True

            for _ in range(TERMINATE_POLL_ATTEMPTS):
                await asyncio.sleep(TERMINATE_POLL_INTERVAL)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    logger.info(f"Process pid={pid} exited after SIGTERM")
                    return True

            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            logger.info(f"Killed process by pid={pid} (session={label})")
            return True
        except ProcessLookupError:
            logger.debug(f"Process pid={pid} already dead")
            return True
        except Exception as e:
            logger.warning(f"Failed to kill process pid={pid}: {e}")
            return False

    async def terminate_orphans(self, records: list) -> int:
        """回收启动时残留的 runner 进程。

        **必须**先通过 ``is_alive`` 多因子校验，避免 PID 复用误杀无关进程。
        调用方应传入 ``RunnerProcessInfo``（纯数据）列表。

        Returns:
            实际被终止的进程数
        """
        killed = 0
        for info in records:
            pid = getattr(info, "pid", None)
            if not pid:
                continue
            if not self.is_alive(info):
                continue
            logger.info(
                "Session %s runner (pid=%s) still running after restart, "
                "killing orphaned process",
                getattr(info, "session_id", "?"),
                pid,
            )
            if await self.terminate_by_pid(
                pid, session_id=getattr(info, "session_id", None)
            ):
                killed += 1
        return killed
