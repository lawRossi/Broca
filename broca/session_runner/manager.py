"""
Session Runner Manager

在 Web 进程中运行，负责管理所有 Session Runner 子进程的生命周期。
提供统一的进程控制接口，监控子进程健康状态。
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from broca.session_runner.ipc import (
    IPCConnectionError,
    IPCServer,
    IPCTimeoutError,
    create_ipc_message,
)
from broca.session_runner.models import (
    IPCMessage,
    IPCMessageType,
    RunnerProcessInfo,
    RunnerStatus,
)
from broca.session_runner.recovery import SessionRecoveryManager

logger = logging.getLogger(__name__)


class RunnerManagerError(Exception):
    """Runner Manager 异常"""

    pass


class RunnerManager:
    """
    Runner 进程管理器

    单例，管理所有 Session Runner 子进程。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RunnerManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            # 进程状态映射表: {session_id: RunnerProcessInfo}
            self._runners: Dict[str, RunnerProcessInfo] = {}
            # IPC 服务端映射: {session_id: IPCServer}
            self._ipc_servers: Dict[str, IPCServer] = {}
            # 配置
            self._max_concurrent_runners = int(
                os.getenv("MAX_CONCURRENT_RUNNERS", "10")
            )
            self._runner_script = self._find_runner_script()
            # 事件处理
            self._event_handlers: Dict[str, List[Callable]] = {}
            # 心跳监控任务
            self._heartbeat_monitor_task: Optional[asyncio.Task] = None
            # 日志目录
            self._log_dir = Path.home() / ".broca/logs/runners"
            # 恢复管理器
            # self._recovery_manager = SessionRecoveryManager()
            # self._recovery_manager.set_restart_handler(self._auto_restart_session)
            # 注册崩溃事件处理
            # self.on("session_crashed", self._handle_session_crashed)
            logger.info(
                "RunnerManager initialized (max_runners=%d, script=%s)",
                self._max_concurrent_runners,
                self._runner_script,
            )

    def _find_runner_script(self) -> str:
        """查找 runner.py 脚本路径"""
        # 优先使用模块方式启动 python -m broca.session_runner.runner
        return "python -m broca.session_runner.runner"

    def _get_runner_log_file(self, session_id: str) -> str:
        """获取 Runner 进程的日志文件路径"""
        log_dir = os.path.join(self._log_dir, session_id)
        os.makedirs(log_dir, exist_ok=True)
        return os.path.join(log_dir, f"{datetime.now().strftime('%Y%m%d')}.log")

    # ==================== 进程生命周期管理 ====================

    async def _save_runner_to_db(self, runner_info: RunnerProcessInfo) -> None:
        """将 Runner 信息持久化到数据库"""
        try:
            from sqlmodel import select

            from broca.session.database import db_manager
            from broca.session.models import SessionRunner

            async with db_manager.get_session() as session:
                # 检查是否已存在
                stmt = select(SessionRunner).where(
                    SessionRunner.session_id == runner_info.session_id
                )
                result = await session.exec(stmt)
                existing = result.first()

                if existing:
                    # 更新
                    existing.pid = runner_info.pid
                    existing.status = runner_info.status.value
                    existing.ipc_address = runner_info.ipc_address
                    existing.last_heartbeat = runner_info.last_heartbeat
                    existing.restart_count = runner_info.restart_count
                    existing.resource_info = runner_info.resource_usage
                    existing.error_message = runner_info.error_message
                    session.add(existing)
                else:
                    # 创建
                    db_runner = SessionRunner(
                        runner_id=f"runner_{runner_info.session_id[:16]}",
                        session_id=runner_info.session_id,
                        pid=runner_info.pid,
                        status=runner_info.status.value,
                        ipc_address=runner_info.ipc_address,
                        ipc_family=runner_info.ipc_family,
                        started_at=runner_info.started_at,
                        last_heartbeat=runner_info.last_heartbeat,
                        restart_count=runner_info.restart_count,
                        resource_info=runner_info.resource_usage,
                        error_message=runner_info.error_message,
                    )
                    session.add(db_runner)

                await session.commit()
        except Exception as e:
            logger.warning("Failed to save runner to DB: %s", e)

    async def _remove_runner_from_db(self, session_id: str) -> None:
        """从数据库删除 Runner 记录"""
        try:
            from sqlmodel import select

            from broca.session.database import db_manager
            from broca.session.models import SessionRunner

            async with db_manager.get_session() as session:
                stmt = select(SessionRunner).where(
                    SessionRunner.session_id == session_id
                )
                result = await session.exec(stmt)
                db_runner = result.first()
                if db_runner:
                    await session.delete(db_runner)

                await session.commit()
        except Exception as e:
            logger.warning("Failed to remove runner from DB: %s", e)

    async def _get_runner_from_db(self, session_id: str) -> Optional[RunnerProcessInfo]:
        """从数据库获取 Runner 记录"""
        try:
            from sqlmodel import select

            from broca.session.database import db_manager
            from broca.session.models import SessionRunner

            async with db_manager.get_session() as session:
                stmt = select(SessionRunner).where(
                    SessionRunner.session_id == session_id
                )
                result = await session.exec(stmt)
                db_runner = result.first()
                if db_runner:
                    return RunnerProcessInfo(
                        session_id=db_runner.session_id,
                        process=None,
                        pid=db_runner.pid,
                        status=db_runner.status,
                        started_at=db_runner.started_at,
                        ipc_address=db_runner.ipc_address,
                        ipc_family=db_runner.ipc_family,
                        last_heartbeat=db_runner.last_heartbeat,
                        restart_count=db_runner.restart_count,
                        resource_usage=db_runner.resource_info,
                        error_message=db_runner.error_message,
                    )
                return None
        except Exception as e:
            logger.warning("Failed to get runner from DB: %s", e)
            return None

    async def start_session(
        self,
        session_id: str,
        workspace: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> RunnerProcessInfo:
        """
        启动一个新的 Session Runner 进程

        Args:
            session_id: Session ID
            workspace: 工作空间路径
            provider: LLM Provider
            model: LLM Model

        Returns:
            RunnerProcessInfo: Runner 进程信息

        Raises:
            RunnerManagerError: 启动失败
        """
        # 检查并发限制
        active_count = self._get_active_runner_count()
        if active_count >= self._max_concurrent_runners:
            raise RunnerManagerError(
                f"Max concurrent runners reached ({self._max_concurrent_runners})"
            )

        # 检查是否已存在
        if session_id in self._runners:
            existing = self._runners[session_id]
            if existing.status in (RunnerStatus.ALIVE, RunnerStatus.STARTING):
                raise RunnerManagerError(
                    f"Session {session_id} already has a running runner (status={existing.status.value})"
                )
            # 清理旧的记录
            await self._cleanup_runner(session_id)

        # 启动 IPC 服务端
        ipc_server = IPCServer(session_id)
        try:
            await ipc_server.start()
        except IPCConnectionError as e:
            raise RunnerManagerError(f"Failed to start IPC server: {e}") from e

        # 准备启动命令
        log_file = self._get_runner_log_file(session_id)
        cmd_parts = [
            self._runner_script,
            f"--session-id {session_id}",
        ]
        if workspace:
            cmd_parts.append(f"--workspace {workspace}")
        if provider:
            cmd_parts.append(f"--provider {provider}")
        if model:
            cmd_parts.append(f"--model {model}")
        cmd_parts.append(f"--log-file {log_file}")
        cmd_parts.append("--log-level INFO")

        cmd_str = " ".join(cmd_parts)

        logger.info("Starting runner for session %s: %s", session_id, cmd_str)
        logger.info("Runner log file: %s", log_file)

        try:
            # 启动子进程
            process = subprocess.Popen(
                cmd_str,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid if sys.platform != "win32" else None,
                cwd=workspace,
            )

            runner_info = RunnerProcessInfo(
                session_id=session_id,
                process=process,
                pid=process.pid,
                status=RunnerStatus.STARTING,
                started_at=datetime.now(timezone.utc),
                ipc_address=ipc_server.address,
                ipc_family=ipc_server.family,
            )

            # 注册到管理器
            self._runners[session_id] = runner_info
            self._ipc_servers[session_id] = ipc_server

            # 等待 Runner 连接（带超时）— 在线程池中执行以避免阻塞事件循环
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, ipc_server.accept, 15.0)
                logger.info("Runner for session %s connected via IPC", session_id)

                # 等待 READY 事件（同样在线程池中执行）
                ready_msg = await loop.run_in_executor(
                    None, ipc_server.receive_message, 15.0
                )
                if ready_msg and ready_msg.type == IPCMessageType.EVT_READY:
                    runner_info.status = RunnerStatus.ALIVE
                    runner_info.last_heartbeat = datetime.now(timezone.utc)
                    logger.info(
                        "Session %s runner READY (agents: %s)",
                        session_id,
                        ready_msg.payload.get("agent_count", 0),
                    )
                else:
                    logger.warning(
                        "Session %s runner did not send READY, got: %s",
                        session_id,
                        ready_msg.type.value if ready_msg else "None",
                    )
                    runner_info.status = RunnerStatus.ALIVE

            except IPCTimeoutError:
                logger.error("Session %s runner connection timeout", session_id)
                await self._kill_runner(session_id)
                raise RunnerManagerError(
                    f"Runner for session {session_id} did not connect within timeout"
                )
            except IPCConnectionError as e:
                logger.error("Session %s runner IPC error: %s", session_id, e)
                await self._kill_runner(session_id)
                raise RunnerManagerError(
                    f"Runner IPC error for session {session_id}: {e}"
                ) from e

            # 触发事件
            await self._trigger_event("session_started", runner_info)

            # 持久化到数据库
            await self._save_runner_to_db(runner_info)

            return runner_info

        except RunnerManagerError:
            raise
        except Exception as e:
            logger.error("Failed to start runner for session %s: %s", session_id, e)
            await self._cleanup_runner(session_id)
            raise RunnerManagerError(f"Failed to start runner: {e}") from e

    async def _find_runner_process_by_pid(self, pid: int) -> bool:
        """检查指定 PID 的进程是否还存在"""
        try:
            import psutil

            return psutil.pid_exists(pid)
        except ImportError:
            # 没有 psutil 时用 os.kill 方式检查
            try:
                os.kill(pid, 0)
                return True
            except (OSError, PermissionError):
                return False

    async def _force_kill_process_by_pid(self, pid: int) -> bool:
        """根据 PID 强制杀死进程"""
        try:
            if sys.platform == "win32":
                import ctypes

                handle = ctypes.windll.kernel32.OpenProcess(1, False, pid)
                ctypes.windll.kernel32.TerminateProcess(handle, 1)
                ctypes.windll.kernel32.CloseHandle(handle)
            else:
                os.kill(pid, signal.SIGKILL)
            logger.info("Force killed process by pid=%d", pid)
            return True
        except ProcessLookupError:
            logger.debug("Process pid=%d already dead", pid)
            return True
        except Exception as e:
            logger.warning("Failed to force kill process pid=%d: %s", pid, e)
            return False

    async def _cleanup_ipc_resources(self, session_id: str) -> None:
        """清理 IPC 相关资源（socket 文件等）"""
        # 关闭 IPC 服务端（如果有）
        ipc_server = self._ipc_servers.pop(session_id, None)
        if ipc_server:
            try:
                ipc_server.close()
            except Exception:
                pass

        # 清理 Unix socket 文件
        if sys.platform != "win32":
            socket_path = f"/tmp/broca_runner_{session_id}.sock"
            try:
                if os.path.exists(socket_path):
                    os.unlink(socket_path)
                    logger.debug("Cleaned up IPC socket: %s", socket_path)
            except Exception as e:
                logger.warning("Failed to clean IPC socket %s: %s", socket_path, e)

    async def stop_session(self, session_id: str, timeout: float = 5.0) -> bool:
        """
        优雅停止 Session Runner 进程

        Args:
            session_id: Session ID
            timeout: 等待进程退出的超时时间（秒）

        Returns:
            是否成功停止
        """
        runner_info = self._runners.get(session_id)
        if not runner_info:
            # 内存中无记录，尝试从数据库恢复进程信息并进行清理
            logger.warning(
                "Session %s not found in memory, trying DB recovery...", session_id
            )
            db_runner = await self._get_runner_from_db(session_id)
            if db_runner and db_runner.pid:
                pid = db_runner.pid
                logger.info(
                    "Found stale runner for session %s in DB (pid=%d), cleaning up...",
                    session_id,
                    pid,
                )
                # 检查进程是否还在运行
                if await self._find_runner_process_by_pid(pid):
                    await self._force_kill_process_by_pid(pid)
                # 清理 IPC 资源
                await self._cleanup_ipc_resources(session_id)
                # 从数据库删除记录
                await self._remove_runner_from_db(session_id)
                logger.info(
                    "Session %s stale runner cleaned up (pid=%d)", session_id, pid
                )
                return True
            else:
                # DB 也没记录，至少清理一下残留的 IPC 资源
                await self._cleanup_ipc_resources(session_id)
                logger.info(
                    "Session %s has no runner records, cleaned IPC resources",
                    session_id,
                )
                return False

        logger.info(
            "Stopping runner for session %s (pid=%d)", session_id, runner_info.pid
        )

        try:
            # 通过 IPC 发送关闭命令
            ipc_server = self._ipc_servers.get(session_id)
            if ipc_server:
                try:
                    shutdown_msg = create_ipc_message(
                        IPCMessageType.CMD_SHUTDOWN,
                        session_id,
                        payload={"reason": "user_request"},
                    )
                    ipc_server.send_message(shutdown_msg)

                    # 等待关闭完成事件
                    try:
                        resp = ipc_server.receive_message(timeout=timeout)
                        logger.info(
                            "Session %s shutdown response: %s",
                            session_id,
                            resp.type.value if resp else "timeout",
                        )
                    except IPCConnectionError:
                        logger.warning(
                            "IPC connection lost during shutdown of %s", session_id
                        )
                except IPCConnectionError:
                    logger.warning("Failed to send shutdown via IPC for %s", session_id)

            # 等待进程退出
            try:
                runner_info.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Runner %s did not exit in time, force killing", session_id
                )
                await self._kill_runner(session_id)

            await self._cleanup_runner(session_id)
            # 从数据库删除
            await self._remove_runner_from_db(session_id)
            logger.info("Session %s runner stopped", session_id)

            await self._trigger_event("session_stopped", runner_info)
            return True

        except Exception as e:
            logger.error("Failed to stop runner for session %s: %s", session_id, e)
            return False

    async def _kill_runner(self, session_id: str) -> None:
        """强制终止 Runner 进程"""
        runner_info = self._runners.get(session_id)
        if not runner_info or not runner_info.process:
            return

        try:
            pid = runner_info.pid
            if sys.platform == "win32":
                runner_info.process.terminate()
            else:
                # 使用进程组杀死所有子进程
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            runner_info.process.wait(timeout=5)
            logger.info("Runner %s (pid=%d) force killed", session_id, pid)
        except Exception as e:
            logger.error("Failed to kill runner %s: %s", session_id, e)

    async def _cleanup_runner(self, session_id: str) -> None:
        """清理 Runner 相关资源"""
        # 关闭 IPC 服务端
        ipc_server = self._ipc_servers.pop(session_id, None)
        if ipc_server:
            try:
                ipc_server.close()
            except Exception:
                pass

        # 清理进程记录
        runner_info = self._runners.pop(session_id, None)
        if runner_info:
            runner_info.status = RunnerStatus.DEAD

        # 清理 IPC socket 文件
        await self._cleanup_ipc_resources(session_id)

    async def restart_session(
        self,
        session_id: str,
        workspace: str = None,
        provider: str = None,
        model: str = None,
    ) -> RunnerProcessInfo:
        """
        重启 Session Runner 进程

        Args:
            session_id: Session ID
            workspace: 工作空间路径（未提供时尝试从旧信息恢复）
            provider: LLM Provider（未提供时尝试从旧信息恢复）
            model: LLM Model（未提供时尝试从旧信息恢复）

        Returns:
            新的 RunnerProcessInfo
        """
        # 获取旧的 workspace/provider/model 信息（优先从内存，其次从 DB）
        old_info = self._runners.get(session_id)
        if not old_info:
            db_runner = await self._get_runner_from_db(session_id)
            if db_runner:
                resource_usage = db_runner.resource_usage or {}
                workspace = resource_usage.get("workspace") or workspace
                provider = resource_usage.get("provider") or provider
                model = resource_usage.get("model") or model
                logger.info("Restored old config from DB for session %s", session_id)
        else:
            workspace = old_info.resource_usage.get("workspace") or workspace
            provider = old_info.resource_usage.get("provider") or provider
            model = old_info.resource_usage.get("model") or model

        # 停止旧的（兼容内存和 DB 两种场景）
        await self.stop_session(session_id)

        # 启动新的
        return await self.start_session(
            session_id=session_id,
            workspace=workspace,
            provider=provider,
            model=model,
        )

    def get_session_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取 Session Runner 进程状态

        Args:
            session_id: Session ID

        Returns:
            状态信息字典，不存在返回 None
        """
        runner_info = self._runners.get(session_id)
        if not runner_info:
            return None

        return self._runner_info_to_dict(runner_info)

    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        列出所有 Session Runner 进程

        Returns:
            Runner 信息列表
        """
        return [self._runner_info_to_dict(info) for info in self._runners.values()]

    def get_stats(self) -> Dict[str, Any]:
        """
        获取 Runner 统计信息

        Returns:
            统计信息
        """
        total = len(self._runners)
        by_status: Dict[str, int] = {}
        for info in self._runners.values():
            status = info.status.value
            by_status[status] = by_status.get(status, 0) + 1

        return {
            "total_runners": total,
            "max_concurrent": self._max_concurrent_runners,
            "available_slots": max(0, self._max_concurrent_runners - total),
            "by_status": by_status,
            "runners": self.list_sessions(),
        }

    def _runner_info_to_dict(self, info: RunnerProcessInfo) -> Dict[str, Any]:
        """将 RunnerProcessInfo 转为字典"""
        return {
            "session_id": info.session_id,
            "pid": info.pid,
            "status": info.status.value,
            "started_at": info.started_at.isoformat() if info.started_at else None,
            "ipc_address": info.ipc_address,
            "resource_usage": info.resource_usage,
            "last_heartbeat": info.last_heartbeat.isoformat()
            if info.last_heartbeat
            else None,
            "restart_count": info.restart_count,
            "error_message": info.error_message,
            "uptime_seconds": (
                (datetime.now(timezone.utc) - info.started_at).total_seconds()
                if info.started_at
                else 0
            ),
        }

    def _get_active_runner_count(self) -> int:
        """获取活跃 Runner 数量"""
        return sum(
            1
            for info in self._runners.values()
            if info.status in (RunnerStatus.ALIVE, RunnerStatus.STARTING)
        )

    # ==================== IPC 事件接收 ====================

    def _handle_runner_event(self, session_id: str, msg: IPCMessage) -> None:
        """
        处理来自 Runner 进程的 IPC 事件

        Args:
            session_id: Session ID
            msg: IPC 消息
        """
        runner_info = self._runners.get(session_id)
        if not runner_info:
            return

        if msg.type == IPCMessageType.EVT_HEARTBEAT:
            # 更新心跳
            runner_info.last_heartbeat = datetime.now(timezone.utc)
            runner_info.resource_usage = msg.payload.get("resource_usage", {})

            # 更新运行状态
            status_str = msg.payload.get("status")
            if status_str:
                try:
                    runner_info.status = RunnerStatus(status_str)
                except ValueError:
                    pass
            # DB 持久化由心跳监控循环定期统一处理

        elif msg.type == IPCMessageType.EVT_ERROR:
            runner_info.status = RunnerStatus.ERROR
            runner_info.error_message = msg.payload.get("error", "Unknown error")
            logger.error(
                "Runner error for session %s: %s",
                session_id,
                runner_info.error_message,
            )

        elif msg.type == IPCMessageType.EVT_SHUTDOWN_COMPLETE:
            runner_info.status = RunnerStatus.DEAD
            logger.info("Runner confirmed shutdown for session %s", session_id)

        elif msg.type == IPCMessageType.EVT_STATUS_CHANGE:
            status_str = msg.payload.get("status")
            if status_str:
                try:
                    runner_info.status = RunnerStatus(status_str)
                    logger.info(
                        "Runner status changed for session %s: %s",
                        session_id,
                        status_str,
                    )
                except ValueError:
                    pass

    # ==================== 心跳监控 ====================

    async def start_heartbeat_monitor(
        self, interval: float = 15.0, timeout: float = 45.0
    ) -> None:
        """
        启动心跳监控

        Args:
            interval: 检查间隔（秒）
            timeout: 心跳超时阈值（秒）
        """
        if self._heartbeat_monitor_task and not self._heartbeat_monitor_task.done():
            logger.warning("Heartbeat monitor already running")
            return

        self._heartbeat_monitor_task = asyncio.create_task(
            self._heartbeat_monitor_loop(interval, timeout)
        )
        logger.info(
            "Heartbeat monitor started (interval=%ds, timeout=%ds)",
            interval,
            timeout,
        )

    async def stop_heartbeat_monitor(self) -> None:
        """停止心跳监控"""
        if self._heartbeat_monitor_task and not self._heartbeat_monitor_task.done():
            self._heartbeat_monitor_task.cancel()
            try:
                await self._heartbeat_monitor_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_monitor_task = None
            logger.info("Heartbeat monitor stopped")

    async def _heartbeat_monitor_loop(self, interval: float, timeout: float) -> None:
        """心跳监控循环"""
        while True:
            try:
                await asyncio.sleep(interval)
                await self._check_heartbeats(timeout)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat monitor error: %s", e)

    async def _check_heartbeats(self, timeout: float) -> None:
        """
        检查所有 Runner 的心跳

        Args:
            timeout: 心跳超时阈值（秒）
        """
        now = datetime.now(timezone.utc)
        dead_sessions = []

        for session_id, runner_info in self._runners.items():
            if runner_info.status != RunnerStatus.ALIVE:
                continue

            if runner_info.last_heartbeat is None:
                continue

            elapsed = (now - runner_info.last_heartbeat).total_seconds()
            if elapsed > timeout:
                logger.warning(
                    "Runner %s heartbeat timeout (elapsed=%.1fs, timeout=%ds)",
                    session_id,
                    elapsed,
                    timeout,
                )

                # 检查进程是否还在运行
                poll = runner_info.process.poll()
                if poll is not None:
                    # 进程已退出
                    logger.error(
                        "Runner %s (pid=%d) has exited with code %s",
                        session_id,
                        runner_info.pid,
                        poll,
                    )
                    runner_info.status = RunnerStatus.ERROR
                    runner_info.error_message = f"Process exited with code {poll}"
                    dead_sessions.append(session_id)
                else:
                    # 进程还在但心跳超时
                    runner_info.status = RunnerStatus.ERROR
                    runner_info.error_message = f"Heartbeat timeout ({elapsed:.0f}s)"

        # 触发事件
        for session_id in dead_sessions:
            runner_info = self._runners.get(session_id)
            if runner_info:
                await self._trigger_event("session_crashed", runner_info)

    # ==================== 生命周期管理（Web 服务启停） ====================

    async def restore_active_sessions(self) -> int:
        """
        启动时检查数据库中的 SessionRunner 记录：
        - 如果进程实际还在运行，保持记录
        - 如果进程已不存在（服务重启后进程消失），标记为 dead

        Returns:
            检查的总记录数
        """
        try:
            from sqlmodel import select

            from broca.session.database import db_manager
            from broca.session.models import SessionRunner

            async with db_manager.get_session() as session:
                # 查询所有 alive/starting 状态的 runner 记录
                stmt = select(SessionRunner).where(
                    SessionRunner.status.in_(["alive", "starting"])
                )
                result = await session.exec(stmt)
                active_runners = result.all()

            checked = 0
            marked_dead = 0
            still_alive = 0

            for runner in active_runners:
                checked += 1
                if not runner.pid:
                    # 没有 PID，直接标记为 dead
                    runner.status = "dead"
                    runner.error_message = "No PID recorded, marked dead on startup"
                    async with db_manager.get_session() as db_sess:
                        db_sess.add(runner)
                        await db_sess.commit()
                    marked_dead += 1
                    logger.warning(
                        "Session %s runner has no PID, marked dead",
                        runner.session_id,
                    )
                    continue

                # 检查进程是否还在运行
                if await self._find_runner_process_by_pid(runner.pid):
                    still_alive += 1
                    logger.info(
                        "Session %s runner (pid=%d) is still running, keeping alive",
                        runner.session_id,
                        runner.pid,
                    )
                else:
                    # 进程已不存在，标记为 dead
                    runner.status = "dead"
                    runner.error_message = "Process not found on startup, marked dead"
                    async with db_manager.get_session() as db_sess:
                        db_sess.add(runner)
                        await db_sess.commit()
                    marked_dead += 1
                    logger.warning(
                        "Session %s runner (pid=%d) process not found, marked dead",
                        runner.session_id,
                        runner.pid,
                    )

            logger.info(
                "Restore check complete: %d checked, %d alive, %d marked dead",
                checked,
                still_alive,
                marked_dead,
            )
            return checked

        except Exception as e:
            logger.error("Failed to restore active sessions: %s", e)
            return 0

    async def shutdown_all(self) -> int:
        """
        关闭所有 Runner 进程

        在 Web 服务关闭时调用。

        Returns:
            成功关闭的数量
        """
        session_ids = list(self._runners.keys())
        stopped = 0
        for session_id in session_ids:
            try:
                if await self.stop_session(session_id):
                    stopped += 1
            except Exception as e:
                logger.error("Failed to stop runner %s: %s", session_id, e)

        await self.stop_heartbeat_monitor()
        logger.info(
            "Shutdown complete: %d/%d runners stopped", stopped, len(session_ids)
        )
        return stopped

    # ==================== 事件系统 ====================

    def on(self, event: str, handler: Callable) -> None:
        """
        注册事件处理器

        Args:
            event: 事件名 (session_started, session_stopped, session_crashed)
            handler: 处理函数
        """
        self._event_handlers.setdefault(event, []).append(handler)

    async def _trigger_event(self, event: str, runner_info: RunnerProcessInfo) -> None:
        """触发事件"""
        handlers = self._event_handlers.get(event, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(runner_info)
                else:
                    handler(runner_info)
            except Exception as e:
                logger.error("Event handler error for %s: %s", event, e)

    # ==================== 崩溃自动恢复 ====================

    async def _handle_session_crashed(self, runner_info: RunnerProcessInfo) -> None:
        """
        处理 Session 崩溃事件，触发自动恢复

        Args:
            runner_info: 崩溃的 Runner 信息
        """
        logger.warning(
            "Session %s crashed (pid=%d), initiating recovery...",
            runner_info.session_id,
            runner_info.pid,
        )
        await self._recovery_manager.handle_crash(runner_info.session_id)

    async def _auto_restart_session(self, session_id: str) -> None:
        """
        自动重启 Session（由 RecoveryManager 调用）

        Args:
            session_id: 要重启的 Session ID
        """
        logger.info("Auto-restarting session %s...", session_id)
        try:
            await self.restart_session(session_id)
            logger.info("Auto-restart successful for session %s", session_id)
        except RunnerManagerError as e:
            logger.error("Auto-restart failed for session %s: %s", session_id, e)
            raise

    def get_recovery_states(self) -> Dict[str, Dict]:
        """
        获取所有 Session 的恢复状态

        Returns:
            恢复状态字典
        """
        return self._recovery_manager.get_all_states()

    # ==================== 资源查询 ====================

    async def get_resource_usage(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取指定 Runner 的资源使用情况

        Args:
            session_id: Session ID

        Returns:
            资源使用信息
        """
        runner_info = self._runners.get(session_id)
        if not runner_info:
            return None

        # 尝试通过 psutil 获取实时信息
        try:
            import psutil

            try:
                proc = psutil.Process(runner_info.pid)
                mem = proc.memory_info()
                return {
                    "cpu_percent": proc.cpu_percent(interval=0.1),
                    "memory_rss": mem.rss,
                    "memory_rss_mb": round(mem.rss / (1024 * 1024), 2),
                    "memory_percent": proc.memory_percent(),
                    "num_threads": proc.num_threads(),
                    "status": proc.status(),
                    "pid": runner_info.pid,
                }
            except psutil.NoSuchProcess:
                return {"error": "Process not found", "pid": runner_info.pid}
        except ImportError:
            return runner_info.resource_usage
