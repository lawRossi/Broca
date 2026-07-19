"""
进程管理器模块

管理长时间运行的子进程的生命周期。
使用文件重定向捕获输出，通过进程组和父死亡信号确保进程清理。
"""

import asyncio
import json
import os
import signal
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from broca.logging_config import get_logger

logger = get_logger(__name__)


class ProcessStatus(str, Enum):
    """进程状态枚举"""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    KILLED = "killed"


@dataclass
class ProcessInfo:
    """进程信息数据类"""
    process_id: str
    pid: int
    command: str
    status: ProcessStatus
    start_time: datetime
    end_time: Optional[datetime] = None
    exit_code: Optional[int] = None
    stdout_path: Optional[Path] = None
    stderr_path: Optional[Path] = None
    meta_path: Optional[Path] = None
    _process: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)
    _wait_task: Optional[asyncio.Task] = field(default=None, repr=False)


def _preexec():
    """子进程初始化函数：跨平台进程生命周期防御

    第 1 层 — 独立进程组（所有平台）
        确保 stop_process 能通过 killpg 杀死整个进程树。
        Shell 退出时自动发 SIGHUP 给后台任务（Shell 固有行为）。

    第 2 层 — 父死亡信号（Linux only）
        内核级保证：ProcessManager 进程无论怎么死（段错误/kill -9），
        子进程都立即收到 SIGTERM。
        macOS/Windows：静默降级，不影响主逻辑。
    """
    os.setsid()

    try:
        import ctypes
        libc = ctypes.CDLL(ctypes.util.find_library('c'))
        # PR_SET_PDEATHSIG = 1, SIGTERM = 15
        libc.prctl(1, signal.SIGTERM, 0, 0, 0)
    except Exception:
        pass  # 非 Linux 平台安全降级


class ProcessManager:
    """进程管理器（单例）

    管理所有长时间运行的子进程，包括启动、状态查询、停止和清理。
    输出通过 shell 重定向到文件，不做内存缓冲。
    """

    _instance = None
    OUTPUT_DIR = Path(".broca/process_outputs")
    _CLEANUP_INTERVAL = 3600  # 清理间隔：1小时
    _MAX_PROCESS_AGE = 3600   # 进程记录最大保留时间：1小时

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self._processes: Dict[str, ProcessInfo] = {}
            self._cleanup_task: Optional[asyncio.Task] = None
            logger.info("ProcessManager initialized")

    # ─── 公共 API ────────────────────────────────────────────────

    async def start_process(
        self,
        command: str,
        cwd: Optional[str] = None,
        process_id: Optional[str] = None,
    ) -> ProcessInfo:
        """启动一个长时间运行的进程

        Args:
            command: 要执行的 shell 命令
            cwd: 工作目录（默认为当前目录）
            process_id: 自定义进程 ID（可选）。若不提供则自动生成。

        Returns:
            ProcessInfo: 进程信息，包含 process_id
        """
        if process_id is None:
            process_id = f"proc_{uuid.uuid4().hex[:12]}"
        proc_dir = self.OUTPUT_DIR / process_id
        proc_dir.mkdir(parents=True, exist_ok=True)

        stdout_path = proc_dir / "stdout.log"
        stderr_path = proc_dir / "stderr.log"
        meta_path = proc_dir / "meta.json"

        # 写入初始 meta.json
        start_time = datetime.now(timezone.utc)
        self._write_meta(meta_path, {
            "process_id": process_id,
            "command": command,
            "status": ProcessStatus.RUNNING.value,
            "pid": None,
            "start_time": start_time.isoformat(),
            "end_time": None,
            "exit_code": None,
        })

        # 构造包装命令：将 stdout/stderr 重定向到文件
        # 使用 ( ) 确保整个命令的输出被捕获
        wrapped_command = f"({command}) > {stdout_path} 2> {stderr_path}"

        logger.info(
            f"Starting process: {process_id}, command: {command[:100]}..."
        )

        try:
            process = await asyncio.create_subprocess_shell(
                wrapped_command,
                shell=True,
                cwd=cwd,
                preexec_fn=_preexec,
                # 不设置 stdout/stderr 管道 — 输出直接写入文件
            )

            # 更新 meta.json 中的 pid
            self._write_meta(meta_path, {
                "pid": process.pid,
            })

            info = ProcessInfo(
                process_id=process_id,
                pid=process.pid,
                command=command,
                status=ProcessStatus.RUNNING,
                start_time=start_time,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                meta_path=meta_path,
                _process=process,
            )

            self._processes[process_id] = info

            # 后台等待进程结束
            info._wait_task = asyncio.create_task(
                self._wait_process(process_id)
            )

            # 确保清理任务在运行
            self._ensure_cleanup_task()

            logger.info(
                f"Process started: {process_id} (PID: {process.pid})"
            )
            return info

        except Exception as e:
            logger.error(f"Failed to start process {process_id}: {e}")
            # 清理已创建的文件
            import shutil
            shutil.rmtree(proc_dir, ignore_errors=True)
            raise

    def get_status(self, process_id: str) -> Optional[ProcessInfo]:
        """查询进程状态

        Args:
            process_id: 进程 ID

        Returns:
            Optional[ProcessInfo]: 进程信息，不存在则返回 None
        """
        return self._processes.get(process_id)

    async def stop_process(
        self, process_id: str, force: bool = False
    ) -> bool:
        """停止一个进程

        Args:
            process_id: 进程 ID
            force: 是否强制停止（SIGKILL vs SIGTERM）

        Returns:
            bool: 是否成功停止
        """
        info = self._processes.get(process_id)
        if not info:
            logger.warning(f"Process not found: {process_id}")
            return False

        if info.status != ProcessStatus.RUNNING:
            logger.warning(
                f"Process {process_id} is not running (status: {info.status})"
            )
            return False

        sig = signal.SIGKILL if force else signal.SIGTERM
        sig_name = "SIGKILL" if force else "SIGTERM"
        new_status = ProcessStatus.KILLED if force else ProcessStatus.STOPPED

        logger.info(
            f"Stopping process {process_id} (PID: {info.pid}) with {sig_name}"
        )

        try:
            if sys.platform == "win32":
                # Windows 不支持 killpg/进程组，回退到 terminate
                if force:
                    info._process.kill()
                else:
                    info._process.terminate()
            else:
                # 杀整个进程组（由 os.setsid 创建）
                os.killpg(info.pid, sig)
        except ProcessLookupError:
            logger.warning(f"Process {process_id} already dead")
            return False
        except Exception as e:
            logger.error(
                f"Failed to stop process {process_id}: {e}"
            )
            return False

        info.status = new_status
        info.end_time = datetime.now(timezone.utc)
        if info.meta_path is not None:
            self._write_meta(info.meta_path, {
                "status": new_status.value,
                "end_time": info.end_time.isoformat(),
            })

        logger.info(f"Process {process_id} stopped with {sig_name}")
        return True

    def list_processes(self) -> List[ProcessInfo]:
        """列出所有被管理的进程

        Returns:
            List[ProcessInfo]: 进程信息列表
        """
        return list(self._processes.values())

    async def cleanup(self):
        """正常关闭时，清理所有存活进程（第 3 层防御）"""
        cleaned = 0
        for process_id, info in list(self._processes.items()):
            if info.status == ProcessStatus.RUNNING:
                try:
                    if sys.platform == "win32":
                        info._process.terminate()
                    else:
                        os.killpg(info.pid, signal.SIGTERM)
                    cleaned += 1
                    logger.info(
                        f"Cleaned up process {process_id} (PID: {info.pid})"
                    )
                except (ProcessLookupError, AttributeError) as e:
                    logger.debug(
                        f"Process {process_id} already gone: {e}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to cleanup process {process_id}: {e}"
                    )

        self._processes.clear()
        if self._cleanup_task:
            self._cleanup_task.cancel()
            self._cleanup_task = None

        logger.info(
            f"ProcessManager cleaned up {cleaned} running processes"
        )

    # ─── 内部方法 ────────────────────────────────────────────────

    async def _wait_process(self, process_id: str):
        """后台等待进程结束并更新状态"""
        info = self._processes.get(process_id)
        if not info or not info._process:
            return

        try:
            exit_code = await info._process.wait()
            info.exit_code = exit_code
            info.end_time = datetime.now(timezone.utc)

            if info.status == ProcessStatus.RUNNING:
                # 没有被 stop_process 中断
                if exit_code == 0:
                    info.status = ProcessStatus.COMPLETED
                else:
                    info.status = ProcessStatus.FAILED
            # 如果已经被 stop_process 设置过 STOPPED/KILLED，保留原状态

            # 更新 meta.json
            if info.meta_path is not None:
                self._write_meta(info.meta_path, {
                    "status": info.status.value,
                    "exit_code": exit_code,
                    "end_time": info.end_time.isoformat(),
                })

            logger.info(
                f"Process {process_id} finished: "
                f"status={info.status.value}, exit_code={exit_code}"
            )

        except asyncio.CancelledError:
            logger.debug(f"Wait task cancelled for process {process_id}")
        except Exception as e:
            logger.error(
                f"Error waiting for process {process_id}: {e}"
            )

    def _write_meta(self, meta_path: Path, updates: dict):
        """安全的 meta.json 写入（部分更新）"""
        try:
            data = {}
            if meta_path.exists():
                with open(meta_path, "r") as f:
                    data = json.load(f)
            data.update(updates)
            with open(meta_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to write meta {meta_path}: {e}")

    def _ensure_cleanup_task(self):
        """确保定时清理任务在运行"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(
                self._periodic_cleanup()
            )

    async def _periodic_cleanup(self):
        """定期清理已结束的进程记录和输出文件"""
        while True:
            try:
                await asyncio.sleep(self._CLEANUP_INTERVAL)
                self._cleanup_old()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Periodic cleanup error: {e}")

    def _cleanup_old(self):
        """清理已结束超过 1 小时的进程记录和输出目录"""
        now = datetime.now(timezone.utc)
        to_remove = []

        for process_id, info in self._processes.items():
            if info.status == ProcessStatus.RUNNING:
                continue

            if info.end_time:
                age = (now - info.end_time).total_seconds()
                if age > self._MAX_PROCESS_AGE:
                    to_remove.append(process_id)

        for process_id in to_remove:
            info = self._processes.pop(process_id, None)
            if info and info.meta_path:
                # 清理输出目录
                proc_dir = info.meta_path.parent
                import shutil
                shutil.rmtree(proc_dir, ignore_errors=True)
                logger.debug(f"Cleaned up old process: {process_id}")
