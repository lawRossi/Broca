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
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from broca.components.session_runner import SessionRunner as SessionRunnerABC
from broca.errors import SessionError, ValidationError
from broca.session.session_manager import SessionManager
from broca.session_runner.ipc import (
    IPCChannel,
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
from broca.utils.datetime_util import serialize_dt

logger = logging.getLogger(__name__)

# 心跳巡检策略
# 1) 先看进程是否还活着（process.poll）：进程已退出 → 直接收敛为 DEAD
# 2) 进程存活但心跳超时 → 先宽限，连续 N 次巡检都超时才升级为 ERROR，
#    避免 runner 事件循环短暂卡顿（长工具调用、快照加锁等）被误判为异常
HEARTBEAT_GRACE_MULTIPLIER = 3
# 心跳落库的最小间隔（秒）：避免每次巡检都写库，又保证 DB 不会长期陈旧
HEARTBEAT_PERSIST_INTERVAL = 60.0


class RunnerManagerError(SessionError):
    """Runner Manager 异常"""

    pass


class IPCSessionRunner(SessionRunnerABC):
    """
    Runner 进程管理器（默认实现）

    单例，管理所有 Session Runner 子进程。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(IPCSessionRunner, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            # 进程状态映射表: {session_id: RunnerProcessInfo}
            self._runners: Dict[str, RunnerProcessInfo] = {}
            # IPC 通道映射: {session_id: IPCChannel}
            self._ipc_servers: Dict[str, IPCChannel] = {}
            # IPC 监听线程映射: {session_id: threading.Thread}
            self._ipc_listener_threads: Dict[str, threading.Thread] = {}
            # IPC 监听任务映射: {session_id: asyncio.Task}
            self._ipc_listener_tasks: Dict[str, asyncio.Task] = {}
            # 等待中的 IPC 命令响应: {message_id: asyncio.Future}
            # 由唯一的 IPC 监听循环分发 RESPONSE，避免多消费者抢消息吞掉心跳
            self._pending_responses: Dict[str, asyncio.Future] = {}
            # 配置
            # 心跳阈值（configs.json → execution 分组）
            self._heartbeat_interval = 5.0
            self._heartbeat_timeout = 45.0
            self._heartbeat_check_interval = 15.0
            try:
                from broca.configs import get_configs
                _cfg = get_configs()
                # 未来可加入 configs.json 的 execution.max_concurrent_runners
                self._max_concurrent_runners = getattr(_cfg.execution, "max_concurrent_runners", 10)
                self._heartbeat_interval = float(
                    getattr(_cfg.execution, "runner_heartbeat_interval", 5)
                )
                self._heartbeat_timeout = float(
                    getattr(_cfg.execution, "runner_heartbeat_timeout", 45)
                )
                self._heartbeat_check_interval = float(
                    getattr(_cfg.execution, "runner_heartbeat_check_interval", 15)
                )
            except Exception:
                self._max_concurrent_runners = 10
            self._runner_script = self._find_runner_script()
            # 事件处理
            self._event_handlers: Dict[str, List[Callable]] = {}
            # 心跳监控任务
            self._heartbeat_monitor_task: Optional[asyncio.Task] = None
            # 心跳上报的 agent 状态缓存: {session_id: {agent_id: status}}
            # 用于变更检测，避免每次心跳都产生无效 DB 写入
            self._agent_status_cache: Dict[str, Dict[str, str]] = {}
            # 已落库的 runner 状态缓存: {session_id: (status, last_heartbeat)}
            # 心跳监控循环据此只写有变化的行，避免每 15s 全量写库
            self._db_state_cache: Dict[str, tuple] = {}
            # 日志目录
            self._log_dir = Path.home() / ".broca/logs/runners"

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
                    # Convert DB status string to RunnerStatus enum
                    try:
                        status = RunnerStatus(db_runner.status)
                    except ValueError:
                        status = RunnerStatus.UNKNOWN

                    return RunnerProcessInfo(
                        session_id=db_runner.session_id,
                        process=None,
                        pid=db_runner.pid,
                        status=status,
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
        # 传递配置文件路径，确保子进程使用与父进程相同的配置
        try:
            from broca.configs import get_configs
            _cfg = get_configs()
            if _cfg.config_source_path:
                cmd_parts.append(f'--config "{_cfg.config_source_path}"')
        except Exception:
            pass

        cmd_str = " ".join(cmd_parts)

        logger.info("Starting runner for session %s: %s", session_id, cmd_str)
        logger.info("Runner log file: %s", log_file)

        try:
            # 构建子进程环境：确保 PYTHONPATH 指向正确的 broca 包
            env = os.environ.copy()
            # 将 broca 包所在目录（项目根）放到 PYTHONPATH 最前面
            broca_pkg_dir = str(Path(__file__).resolve().parents[2])  # broca/session_runner/manager.py → 项目根
            existing_pp = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = broca_pkg_dir + (f":{existing_pp}" if existing_pp else "")
            # 清除 VIRTUAL_ENV 防止 shell 激活错误的 venv
            env.pop("VIRTUAL_ENV", None)
            env.pop("VIRTUAL_ENV_PROMPT", None)
            # 跳过 litellm 远程 model cost map 拉取（避免 5s SSL 超时）
            env["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"

            # 启动子进程
            process = subprocess.Popen(
                cmd_str,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
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

                # 等待 Runner 的首条消息（READY 或 ERROR），最多等 30 秒
                # 用循环 + 短超时代替单次长超时，避免 poll() 在某些情况下误判
                first_msg = None
                for attempt in range(6):  # 6 × 5s = 30s 总超时
                    first_msg = await loop.run_in_executor(
                        None, ipc_server.receive_message, 5.0
                    )
                    if first_msg is not None:
                        break
                    logger.debug(
                        "Waiting for first message from runner (attempt %d/6)...",
                        attempt + 1,
                    )

                if first_msg and first_msg.type == IPCMessageType.EVT_READY:
                    runner_info.status = RunnerStatus.ALIVE
                    runner_info.last_heartbeat = datetime.now(timezone.utc)
                    logger.info(
                        "Session %s runner READY (agents: %s)",
                        session_id,
                        first_msg.payload.get("agent_count", 0),
                    )
                elif first_msg and first_msg.type == IPCMessageType.EVT_ERROR:
                    # Runner 初始化失败（如无效 tool 配置），立即抛出错误
                    error_payload = first_msg.payload
                    logger.error(
                        "Session %s runner initialization failed: %s",
                        session_id,
                        error_payload,
                    )
                    runner_info.status = RunnerStatus.ERROR
                    runner_info.error_message = error_payload.get("message") or str(
                        error_payload
                    )
                    runner_info.recovery_hint = error_payload.get("recovery_hint")
                    # 先通知前端，再清理
                    await self._trigger_event("runner_error", runner_info)
                    await self._kill_runner(session_id)
                    await self._cleanup_runner(session_id)
                    raise RunnerManagerError(runner_info.error_message)
                else:
                    # 超时或未知消息类型
                    msg_type = first_msg.type.value if first_msg else "None"
                    logger.error(
                        "Session %s runner did not send READY in time (got: %s), aborting",
                        session_id,
                        msg_type,
                    )
                    await self._kill_runner(session_id)
                    await self._cleanup_runner(session_id)
                    raise RunnerManagerError(
                        f"Runner for session {session_id} did not send READY within 30s (got: {msg_type})"
                    )

            except IPCTimeoutError:
                logger.error("Session %s runner connection timeout", session_id)
                await self._kill_runner(session_id)
                await self._cleanup_runner(session_id)
                raise RunnerManagerError(
                    f"Runner for session {session_id} did not connect within timeout"
                )
            except IPCConnectionError as e:
                logger.error("Session %s runner IPC error: %s", session_id, e)
                await self._kill_runner(session_id)
                await self._cleanup_runner(session_id)
                raise RunnerManagerError(
                    f"Runner IPC error for session {session_id}: {e}"
                ) from e

            # 触发事件
            await self._trigger_event("session_started", runner_info)

            # 持久化到数据库
            await self._save_runner_to_db(runner_info)

            # 启动 IPC 消息监听循环（接收 heartbeat / response 等）
            # 保存 task 引用：既便于 stop_session 主动取消，也避免异常被静默吞掉
            self._ipc_listener_tasks[session_id] = asyncio.create_task(
                self._ipc_listener_loop(session_id),
                name=f"ipc-listener-{session_id}",
            )

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
        """根据 PID 终止进程（先 SIGTERM 优雅退出，超时后 SIGKILL 兜底）"""
        try:
            if sys.platform == "win32":
                import ctypes

                handle = ctypes.windll.kernel32.OpenProcess(1, False, pid)
                ctypes.windll.kernel32.TerminateProcess(handle, 1)
                ctypes.windll.kernel32.CloseHandle(handle)
            else:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    logger.debug("Process pid=%d already dead", pid)
                    return True
                # 等待进程优雅退出（2s）
                for _ in range(20):
                    await asyncio.sleep(0.1)
                    try:
                        os.kill(pid, 0)  # 检查是否还活着
                    except ProcessLookupError:
                        logger.info("Process pid=%d exited after SIGTERM", pid)
                        return True
                # 超时，SIGKILL 兜底
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            logger.info("Killed process by pid=%d", pid)
            return True
        except ProcessLookupError:
            logger.debug("Process pid=%d already dead", pid)
            return True
        except Exception as e:
            logger.warning("Failed to kill process pid=%d: %s", pid, e)
            return False

    def _cancel_ipc_listener_task(self, session_id: str) -> None:
        """取消 IPC 监听任务（幂等）"""
        task = self._ipc_listener_tasks.pop(session_id, None)
        if task is not None and not task.done():
            task.cancel()

    async def _cleanup_ipc_resources(self, session_id: str) -> None:
        """清理 IPC 相关资源（socket 文件、监听线程等）"""
        # 取消监听任务（否则任务会随 _runners 变化自行退出，但引用会残留）
        self._cancel_ipc_listener_task(session_id)
        # 清理监听线程（daemon 线程随 ipc_server.close() 触发 IPCConnectionError 自然退出）
        self._ipc_listener_threads.pop(session_id, None)

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
            # 1) 先标记为正在关闭，让 _ipc_listener_loop 退出
            runner_info.status = RunnerStatus.SHUTTING_DOWN
            # 从 _runners 中移除，使监听循环退出 while 条件
            self._runners.pop(session_id, None)

            # 2) 通过 IPC 发送关闭命令
            ipc_server = self._ipc_servers.get(session_id)
            if ipc_server:
                try:
                    shutdown_msg = create_ipc_message(
                        IPCMessageType.CMD_SHUTDOWN,
                        session_id,
                        payload={"reason": "user_request"},
                    )
                    ipc_server.send_message(shutdown_msg)
                    logger.info(
                        "Sent shutdown command to session %s runner", session_id
                    )
                except IPCConnectionError:
                    logger.warning(
                        "Failed to send shutdown via IPC for %s (connection may already be closed)",
                        session_id,
                    )

            # 3) 等待进程退出（不要通过 IPC 读响应——_ipc_listener_loop 已退出，且
            #    连接上可能有旧消息残留导致竞争；直接等进程退出更可靠）
            try:
                runner_info.process.wait(timeout=timeout)
                logger.info("Runner %s process exited gracefully", session_id)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Runner %s did not exit in time, force killing", session_id
                )
                # 注意：不能通过 _kill_runner(session_id) 杀（_runners 已 pop），
                # 直接在此处用 runner_info 杀进程组
                self._force_kill_process(runner_info)

            # 4) 清理资源
            await self._cleanup_runner(session_id)
            await self._remove_runner_from_db(session_id)
            logger.info("Session %s runner stopped", session_id)

            await self._trigger_event("session_stopped", runner_info)
            return True

        except Exception as e:
            logger.error("Failed to stop runner for session %s: %s", session_id, e)
            # 异常时也确保进程被杀（防止僵尸）
            self._force_kill_process(runner_info)
            return False

    def _force_kill_process(self, runner_info) -> None:
        """强制终止指定 Runner 进程（直接操作 runner_info，不依赖 _runners 字典）"""
        if not runner_info or not runner_info.process:
            return

        try:
            pid = runner_info.pid
            if pid is None:
                return
            if sys.platform == "win32":
                runner_info.process.kill()
            else:
                # 先 SIGTERM 给进程组（允许短暂清理），再 SIGKILL 兜底
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    runner_info.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
                    try:
                        runner_info.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        logger.error(
                            "Runner %s (pid=%d) survived SIGKILL — possible zombie",
                            runner_info.session_id, pid,
                        )
            runner_info.process.wait(timeout=2)
            logger.info("Runner %s (pid=%d) force killed", runner_info.session_id, pid)
        except Exception as e:
            logger.error("Failed to kill runner %s: %s", runner_info.session_id, e)

    async def _kill_runner(self, session_id: str) -> None:
        """强制终止 Runner 进程（通过 session_id 查找）"""
        runner_info = self._runners.get(session_id)
        if runner_info:
            self._force_kill_process(runner_info)
        else:
            # _runners 中已移除，尝试从 IPC 记录中获取 pid
            logger.warning("_kill_runner: session %s not in _runners, skipping", session_id)

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

        # 清理心跳状态缓存，避免 session 重启后残留旧数据影响变更检测
        self._agent_status_cache.pop(session_id, None)
        self._db_state_cache.pop(session_id, None)

        # 清理 IPC socket 文件
        await self._cleanup_ipc_resources(session_id)

    async def restart_session(self, session_id: str) -> RunnerProcessInfo:
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
        session_manager = SessionManager()
        session = await session_manager.get_session(session_id)
        if not session:
            raise ValidationError(f"Session {session_id} not found")
        workspace = session.workspace

        # 停止旧的（兼容内存和 DB 两种场景）
        await self.stop_session(session_id)

        # 启动新的
        return await self.start_session(session_id=session_id, workspace=workspace)

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

    async def send_command(
        self,
        session_id: str,
        msg_type: IPCMessageType,
        payload: Dict[str, Any],
        timeout: float = 10.0,
    ) -> Optional[Dict[str, Any]]:
        """
        向指定 Session 的 Runner 发送 IPC 命令并等待响应

        实现要点（修复两个历史问题）：
        1. send_message 是同步阻塞调用，放到线程池执行，避免卡住事件循环；
        2. 不再自己 recv 抢消息（那会把心跳当响应吞掉），而是注册一个
           以 message_id 为键的 Future，由唯一的 IPC 监听循环分发响应。

        Args:
            session_id: Session ID
            msg_type: IPC 消息类型
            payload: 消息载荷
            timeout: 等待响应超时（秒）

        Returns:
            响应数据，失败返回 {"error": ...}
        """
        ipc_server = self._ipc_servers.get(session_id)
        if not ipc_server:
            logger.warning("No IPC server found for session %s", session_id)
            return None

        loop = asyncio.get_running_loop()
        msg = create_ipc_message(msg_type, session_id, payload=payload)
        future: asyncio.Future = loop.create_future()
        self._pending_responses[msg.message_id] = future

        try:
            await loop.run_in_executor(None, ipc_server.send_message, msg)
            response = await asyncio.wait_for(future, timeout=timeout)
            return response.payload
        except asyncio.TimeoutError:
            logger.error(
                "IPC command %s for session %s timed out after %.0fs",
                msg_type.value,
                session_id,
                timeout,
            )
            return {"error": "No response from runner"}
        except IPCConnectionError as e:
            logger.error("IPC send command failed for session %s: %s", session_id, e)
            return {"error": str(e)}
        except Exception as e:
            logger.error("Failed to send command to session %s: %s", session_id, e)
            return {"error": str(e)}
        finally:
            self._pending_responses.pop(msg.message_id, None)

    def _runner_info_to_dict(self, info: RunnerProcessInfo) -> Dict[str, Any]:
        """将 RunnerProcessInfo 转为字典"""
        return {
            "session_id": info.session_id,
            "pid": info.pid,
            "status": info.status.value,
            "started_at": serialize_dt(info.started_at),
            "ipc_address": info.ipc_address,
            "resource_usage": info.resource_usage,
            "last_heartbeat": serialize_dt(info.last_heartbeat),
            "restart_count": info.restart_count,
            "error_message": info.error_message,
            "heartbeat_stale": info.heartbeat_stale,
            "missed_heartbeats": info.missed_heartbeats,
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
        if msg.type == IPCMessageType.RESPONSE:
            # 命令响应：只由监听循环分发，按 message_id 唤醒等待者。
            # 这样 send_command 不再直接 recv，也就不会把心跳当响应吞掉。
            future = self._pending_responses.pop(msg.message_id, None)
            if future is not None and not future.done():
                future.set_result(msg)
            else:
                logger.debug(
                    "Dropped unmatched IPC response for session %s (id=%s)",
                    session_id,
                    msg.message_id,
                )
            return

        runner_info = self._runners.get(session_id)
        if not runner_info:
            return

        if msg.type == IPCMessageType.EVT_HEARTBEAT:
            # 更新心跳
            runner_info.last_heartbeat = datetime.now(timezone.utc)
            runner_info.resource_usage = msg.payload.get("resource_usage", {})
            # 心跳恢复：清除巡检期累积的"心跳陈旧"标记
            if runner_info.heartbeat_stale or runner_info.missed_heartbeats:
                logger.info(
                    "Runner %s heartbeat recovered (was stale, missed=%d)",
                    session_id,
                    runner_info.missed_heartbeats,
                )
                runner_info.heartbeat_stale = False
                runner_info.missed_heartbeats = 0
            if runner_info.status == RunnerStatus.ERROR and runner_info.error_message:
                logger.info(
                    "Runner %s recovered from error state: %s",
                    session_id,
                    runner_info.error_message,
                )
                runner_info.error_message = None

            # 更新运行状态
            status_str = msg.payload.get("status")
            if status_str:
                try:
                    runner_info.status = RunnerStatus(status_str)
                except ValueError:
                    pass

            # 将心跳上报的 agent 状态同步到 DB（仅变化时写入）
            # 心跳每 5s 上报一次各 agent 的实时状态，作为 DB 中 agent_status 的
            # 权威来源：短暂断线重连、心跳超时误判等场景下可自动自愈，
            # 避免前端轮询读到过期的 disconnected 状态
            agent_statuses = msg.payload.get("agent_statuses")
            if isinstance(agent_statuses, dict) and agent_statuses:
                asyncio.ensure_future(
                    self._sync_agent_statuses(session_id, agent_statuses)
                )
            # DB 持久化由心跳监控循环的 _persist_runner_state() 定期统一处理

        elif msg.type == IPCMessageType.EVT_ERROR:
            runner_info.status = RunnerStatus.ERROR
            error_payload = msg.payload
            runner_info.error_message = error_payload.get("message") or str(
                error_payload
            )
            runner_info.recovery_hint = error_payload.get("recovery_hint")
            logger.error(
                "Runner error for session %s: %s",
                session_id,
                runner_info.error_message,
            )
            # 触发 runner_error 事件，通知前端
            asyncio.ensure_future(self._trigger_event("runner_error", runner_info))

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

        # 编排事件处理
        elif msg.type in (
            IPCMessageType.EVT_CREW_START,
            IPCMessageType.EVT_CREW_PROGRESS,
            IPCMessageType.EVT_CREW_COMPLETE,
            IPCMessageType.EVT_CREW_ERROR,
        ):
            self._handle_crew_event(session_id, msg)

    def _handle_crew_event(self, session_id: str, msg: IPCMessage) -> None:
        """处理编排事件"""
        payload = msg.payload
        execution_id = payload.get("execution_id")
        crew_id = payload.get("crew_id", "unknown")
        if msg.type == IPCMessageType.EVT_CREW_START:
            logger.info(
                "[Crew] '%s' started (session=%s, exec=%s, type=%s)",
                crew_id,
                session_id,
                execution_id,
                payload.get("orchestrator_type", "?"),
            )

        elif msg.type == IPCMessageType.EVT_CREW_PROGRESS:
            progress = payload.get("progress", 0)
            phase = payload.get("current_phase", "")
            logger.info(
                "[Crew] '%s' progress: %.0f%% (session=%s, exec=%s, phase=%s)",
                crew_id,
                progress * 100,
                session_id,
                execution_id,
                phase,
            )

        elif msg.type == IPCMessageType.EVT_CREW_COMPLETE:
            logger.info(
                "[Crew] '%s' completed (session=%s, exec=%s)",
                crew_id,
                session_id,
                execution_id,
            )

        elif msg.type == IPCMessageType.EVT_CREW_ERROR:
            error = payload.get("error", "unknown error")
            logger.error(
                "[Crew] '%s' failed: %s (session=%s, exec=%s)",
                crew_id,
                error,
                session_id,
                execution_id,
            )

        # 触发已注册的 crew 事件回调
        handlers = self._event_handlers.get("crew_event", [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.create_task(handler(session_id, msg))
                else:
                    handler(session_id, msg)
            except Exception as e:
                logger.error("Crew event handler error: %s", e)

    # ==================== 心跳监控 ====================

    async def start_heartbeat_monitor(
        self, interval: Optional[float] = None, timeout: Optional[float] = None
    ) -> None:
        """
        启动心跳监控

        阈值统一来自 configs.json 的 execution 分组：
        - runner_heartbeat_check_interval → interval
        - runner_heartbeat_timeout        → timeout
        （此前散落在 manager 的默认参数里，另有已删除的死代码
          session_runner/heartbeat.py 使用 30/60 的另一套阈值）

        Args:
            interval: 检查间隔（秒），None 时读配置
            timeout: 心跳超时阈值（秒），None 时读配置
        """
        if self._heartbeat_monitor_task and not self._heartbeat_monitor_task.done():
            logger.warning("Heartbeat monitor already running")
            return

        interval = (
            float(self._heartbeat_check_interval)
            if interval is None
            else interval
        )
        timeout = float(self._heartbeat_timeout) if timeout is None else timeout

        if timeout < self._heartbeat_interval * 3:
            logger.warning(
                "Heartbeat timeout (%ss) is too close to the report interval (%ss); "
                "false positives are likely. Recommended: timeout >= 3 x interval.",
                timeout,
                self._heartbeat_interval,
            )

        self._heartbeat_monitor_task = asyncio.create_task(
            self._heartbeat_monitor_loop(interval, timeout)
        )
        logger.info(
            "Heartbeat monitor started (interval=%ss, timeout=%ss, grace=%ss)",
            interval,
            timeout,
            timeout * HEARTBEAT_GRACE_MULTIPLIER,
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
                # 把内存中的 runner 状态/心跳周期写入 DB（仅写有变化的行）
                await self._persist_runner_state()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat monitor error: %s", e)

    async def _persist_runner_state(self) -> None:
        """把内存中的 Runner 状态与心跳时间同步到 DB。

        历史问题：_save_runner_to_db() 只在 start_session 时调用一次，
        DB 里的 status/last_heartbeat 永远停留在启动瞬间，导致
        _get_runner_from_db() / restore_active_sessions() 读到脏数据。
        这里按 HEARTBEAT_PERSIST_INTERVAL 节流写入。
        """
        now = datetime.now(timezone.utc)
        for session_id, info in list(self._runners.items()):
            prev = self._db_state_cache.get(session_id)
            status = info.status.value
            if prev is not None:
                prev_status, prev_hb = prev
                same_status = prev_status == status
                hb_fresh = (
                    prev_hb is not None
                    and (now - prev_hb).total_seconds() < HEARTBEAT_PERSIST_INTERVAL
                )
                if same_status and hb_fresh:
                    continue
            try:
                await self._save_runner_to_db(info)
                self._db_state_cache[session_id] = (status, now)
            except Exception as e:
                logger.warning(
                    "Failed to persist runner state for session %s: %s", session_id, e
                )

    async def _check_heartbeats(self, timeout: float) -> None:
        """
        巡检所有 Runner 的存活状态。

        判定顺序（重要）：
        1. 进程已退出（process.poll() 非 None）→ 立即收敛为 DEAD 并清理，
           不再让条目永久停留在 error 状态（历史 bug：进程早已不存在，
           /runner/status 却一直返回 error，前端永久显示"进程异常"）。
        2. 进程存活但心跳超时 → 先打"心跳陈旧"标记并宽限
           HEARTBEAT_GRACE_MULTIPLIER 倍阈值，仍无心跳才升级为 ERROR；
           升级后继续巡检，心跳恢复即自动回到 ALIVE。

        Args:
            timeout: 心跳超时阈值（秒）
        """
        now = datetime.now(timezone.utc)
        dead_sessions: list[str] = []
        grace = timeout * HEARTBEAT_GRACE_MULTIPLIER

        for session_id, runner_info in list(self._runners.items()):
            # STARTING 阶段由 start_session 自己负责（它会等 READY 并自行清理），
            # 这里只在明显卡死后兜底，避免与启动流程竞态重复清理
            if runner_info.status == RunnerStatus.STARTING:
                started_at = runner_info.started_at
                if started_at is not None:
                    if (now - started_at).total_seconds() < grace:
                        continue

            # ---- 1) 进程维度：进程没了就是死了，与心跳无关 ----
            process = runner_info.process
            if process is not None:
                returncode = process.poll()
                if returncode is not None:
                    logger.error(
                        "Runner %s (pid=%s) has exited with code %s",
                        session_id,
                        runner_info.pid,
                        returncode,
                    )
                    runner_info.status = RunnerStatus.DEAD
                    runner_info.error_message = f"Process exited with code {returncode}"
                    dead_sessions.append(session_id)
                    continue

            # ---- 2) 心跳维度：只对"本应活着"的状态做判定 ----
            if runner_info.status not in (RunnerStatus.ALIVE, RunnerStatus.ERROR):
                continue
            if runner_info.last_heartbeat is None:
                continue

            elapsed = (now - runner_info.last_heartbeat).total_seconds()
            if elapsed <= timeout:
                runner_info.heartbeat_stale = False
                runner_info.missed_heartbeats = 0
                continue

            runner_info.missed_heartbeats += 1
            runner_info.heartbeat_stale = True

            if elapsed <= grace:
                # 宽限期内：只记录，不改状态，避免事件循环短暂卡顿被误判
                logger.warning(
                    "Runner %s heartbeat delayed (elapsed=%.1fs, timeout=%ds, "
                    "missed=%d, grace=%ds)",
                    session_id,
                    elapsed,
                    timeout,
                    runner_info.missed_heartbeats,
                    grace,
                )
                continue

            if runner_info.status != RunnerStatus.ERROR:
                logger.error(
                    "Runner %s heartbeat lost (elapsed=%.1fs > grace=%ds, pid=%s alive)",
                    session_id,
                    elapsed,
                    grace,
                    runner_info.pid,
                )
                runner_info.status = RunnerStatus.ERROR
                runner_info.error_message = f"Heartbeat lost ({elapsed:.0f}s)"
                # 进程还活着，条目保留继续巡检，心跳恢复会自动回到 ALIVE；
                # 此时不把 agent 标记为 disconnected，避免前端反复闪断。
                await self._trigger_event("session_crashed", runner_info)

        # ---- 3) 收敛真正死亡的 runner ----
        for session_id in dead_sessions:
            await self._converge_dead_runner(session_id)

    async def _converge_dead_runner(self, session_id: str) -> None:
        """把已死亡的 Runner 收敛掉：置 DEAD、清理 IPC/内存、写库、通知前端。

        历史问题：进程退出后只把状态改成 ERROR，既不移除内存条目也不写库，
        导致 /runner/status 永远返回 error（前端永久"进程异常"）。
        """
        runner_info = self._runners.get(session_id)
        if runner_info is None:
            return

        runner_info.status = RunnerStatus.DEAD
        runner_info.heartbeat_stale = False
        runner_info.missed_heartbeats = 0
        reason = runner_info.error_message or "Process exited"

        # 先写库（dead），再清理内存，保证外部读 DB 也能看到真实状态
        try:
            await self._save_runner_to_db(runner_info)
            self._db_state_cache[session_id] = (runner_info.status.value, None)
        except Exception as e:
            logger.warning(
                "Failed to persist dead runner for session %s: %s", session_id, e
            )

        # 通知前端 + 标记 agent 断连
        await self._trigger_event("session_crashed", runner_info)
        await self._mark_session_agents_disconnected(session_id)

        # 清理 IPC 资源与内存条目。
        # 内存条目必须移除，否则 /runner/status 会一直返回这条僵尸记录
        # （历史 bug：进程早已不存在，前端却永久显示"进程异常"）。
        # DB 记录保留为 dead，便于排查历史失败原因。
        self._runners.pop(session_id, None)
        self._agent_status_cache.pop(session_id, None)
        await self._cleanup_ipc_resources(session_id)
        logger.warning(
            "Runner for session %s converged to DEAD (%s)", session_id, reason
        )

    async def _mark_session_agents_disconnected(self, session_id: str) -> None:
        """当 Runner 进程死亡时，将该 Session 下所有 Agent 标记为 disconnected

        Args:
            session_id: 要标记的 Session ID
        """
        try:
            from sqlmodel import select

            from broca.session.database import db_manager
            from broca.session.models import Agent

            async with db_manager.get_session() as session:
                stmt = select(Agent).where(Agent.session_id == session_id)
                result = await session.exec(stmt)
                agents = result.all()
                for agent in agents:
                    agent.agent_status = "disconnected"
                session.add_all(agents)
                await session.commit()
                if agents:
                    logger.info(
                        "Marked %d agents as disconnected for session %s",
                        len(agents),
                        session_id,
                    )
            # 清除状态缓存，确保后续心跳恢复时能重新同步真实状态
            # （否则缓存与心跳 payload 相同会跳过写入，DB 永远停留在 disconnected）
            self._agent_status_cache.pop(session_id, None)
        except Exception as e:
            logger.error(
                "Failed to mark agents disconnected for session %s: %s",
                session_id,
                e,
            )

    async def _sync_agent_statuses(
        self, session_id: str, agent_statuses: Dict[str, str]
    ) -> None:
        """将 Runner 心跳上报的 agent 状态同步到数据库

        心跳每 5s 携带一次 {agent_id: status} 映射。通过变更检测，
        仅当状态与上次同步结果不同时才写库，避免频繁无效 IO。

        该机制保证 DB 中的 agent_status 能在断线重连、心跳超时误判等
        场景下自动恢复为 Runner 上报的真实状态（自愈）。

        Args:
            session_id: Session ID
            agent_statuses: {agent_id: status} 映射
        """
        cached = self._agent_status_cache.get(session_id)
        if cached == agent_statuses:
            return

        changed_count = 0
        try:
            from sqlmodel import select

            from broca.session.database import db_manager
            from broca.session.models import Agent

            async with db_manager.get_session() as session:
                stmt = select(Agent).where(Agent.session_id == session_id)
                result = await session.exec(stmt)
                agents = result.all()
                changed = []
                for agent in agents:
                    new_status = agent_statuses.get(agent.agent_id)
                    if new_status and new_status != agent.agent_status:
                        agent.agent_status = new_status
                        changed.append(agent)
                if changed:
                    changed_count = len(changed)
                    session.add_all(changed)
                    await session.commit()

            # 仅在成功后更新缓存；写库失败时保留旧缓存以便下次重试
            self._agent_status_cache[session_id] = dict(agent_statuses)
            if changed_count:
                logger.debug(
                    "Synced %d agent statuses from heartbeat for session %s",
                    changed_count,
                    session_id,
                )
        except Exception as e:
            logger.error(
                "Failed to sync agent statuses for session %s: %s", session_id, e
            )

    def _start_poll_thread(
        self,
        session_id: str,
        ipc_server: Any,
        loop: asyncio.AbstractEventLoop,
        msg_queue: "asyncio.Queue",
    ) -> threading.Thread:
        """启动 IPC 轮询线程（唯一消费者），消息经 asyncio.Queue 送回事件循环。"""

        def _thread_poll() -> None:
            while session_id in self._runners:
                try:
                    msg = ipc_server.receive_message(5.0)
                    if msg is not None:
                        loop.call_soon_threadsafe(msg_queue.put_nowait, msg)
                except IPCConnectionError as e:
                    logger.warning(
                        "IPC connection lost for session %s: %s", session_id, e
                    )
                    loop.call_soon_threadsafe(msg_queue.put_nowait, None)
                    break
                except Exception as e:
                    logger.error("IPC listener thread error for %s: %s", session_id, e)
                    loop.call_soon_threadsafe(msg_queue.put_nowait, None)
                    break

        thread = threading.Thread(
            target=_thread_poll, name=f"ipc-poll-{session_id}", daemon=True
        )
        thread.start()
        self._ipc_listener_threads[session_id] = thread
        return thread

    async def _ipc_listener_loop(self, session_id: str) -> None:
        """
        IPC 消息监听循环，持续接收 Runner 发来的消息（heartbeat / response 等）。

        使用专用 daemon 线程执行阻塞的 receive_message，通过
        asyncio.Queue + call_soon_threadsafe 将消息送回 event loop，
        避免占用默认线程池。

        自愈保证（历史 bug：这里一旦抛异常，任务静默死掉，该 session 的
        心跳再也不会被消费，45s 后被判 error 且永久无法恢复）：
        - 单条消息处理失败只记录日志，不中断循环
        - 轮询线程意外退出时自动重启
        """
        ipc_server = self._ipc_servers.get(session_id)
        if not ipc_server:
            logger.warning("IPC server not found for session %s", session_id)
            return

        loop = asyncio.get_running_loop()
        msg_queue: asyncio.Queue = asyncio.Queue()
        thread = self._start_poll_thread(session_id, ipc_server, loop, msg_queue)

        while session_id in self._runners:
            try:
                try:
                    msg = await asyncio.wait_for(msg_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # 线程意外死亡 → 重启，保证心跳通道不断
                    if not thread.is_alive() and session_id in self._runners:
                        ipc_server = self._ipc_servers.get(session_id)
                        if ipc_server is None:
                            break
                        logger.warning(
                            "IPC poll thread for session %s died, restarting",
                            session_id,
                        )
                        thread = self._start_poll_thread(
                            session_id, ipc_server, loop, msg_queue
                        )
                    continue

                if msg is None:
                    break

                try:
                    self._handle_runner_event(session_id, msg)
                except Exception as e:
                    # 单条消息处理异常不允许拖垮整个监听循环
                    logger.error(
                        "Failed to handle IPC message %s for session %s: %s",
                        getattr(msg, "type", "?"),
                        session_id,
                        e,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    "IPC listener loop error for session %s: %s", session_id, e
                )
                await asyncio.sleep(0.5)

    # ==================== 生命周期管理（Web 服务启停） ====================

    async def restore_active_sessions(self) -> int:
        """
        启动时回收所有残留 runner（非 dead 状态的 SessionRunner 记录）：
        - IPC 连接在服务重启后无法重建，任何残留 runner 进程均已无意义
        - pid 对应的进程存活 → kill + 标记 dead + 重置关联 Agent 状态
        - 进程已不存在或无 pid → 直接标记 dead + 重置关联 Agent 状态

        Returns:
            检查的总记录数
        """
        try:
            from sqlmodel import select

            from broca.session.database import db_manager
            from broca.session.models import Agent, SessionRunner

            async with db_manager.get_session() as session:
                # 查询所有非 dead 状态的 runner 记录（含 alive/starting/error/shutting_down）
                # 只要 pid 对应的进程还活着，就 kill — IPC 已断，进程无意义
                stmt = select(SessionRunner).where(
                    SessionRunner.status != "dead"  # type: ignore[operator]
                )
                result = await session.exec(stmt)
                active_runners = result.all()

            checked = 0
            killed = 0
            marked_dead = 0

            for runner in active_runners:
                checked += 1
                if not runner.pid:
                    # 没有 PID，直接标记为 dead
                    runner.status = "dead"
                    runner.error_message = "No PID recorded, marked dead on startup"
                    marked_dead += 1
                    logger.warning(
                        "Session %s runner has no PID, marked dead",
                        runner.session_id,
                    )
                else:
                    # 检查进程是否还在运行
                    if await self._find_runner_process_by_pid(runner.pid):
                        # IPC 已断，残留 runner 无法通信，终止并标记 dead
                        killed += 1
                        logger.info(
                            "Session %s runner (pid=%d) still running after restart, "
                            "killing orphaned process",
                            runner.session_id,
                            runner.pid,
                        )
                        await self._force_kill_process_by_pid(runner.pid)
                        runner.status = "dead"
                        runner.error_message = (
                            f"Orphaned runner (pid={runner.pid}) killed on startup: "
                            "IPC connection lost after service restart"
                        )
                    else:
                        # 进程已不存在，标记为 dead
                        marked_dead += 1
                        runner.status = "dead"
                        runner.error_message = "Process not found on startup, marked dead"
                        logger.warning(
                            "Session %s runner (pid=%d) process not found, marked dead",
                            runner.session_id,
                            runner.pid,
                        )

                # 统一更新 DB：runner 记录 + 关联 Agent 状态
                async with db_manager.get_session() as db_sess:
                    db_sess.add(runner)
                    # 将该 session 下所有 Agent 的 agent_status 重置为 disconnected
                    agent_stmt = (
                        select(Agent)
                        .where(Agent.session_id == runner.session_id)
                        .where(Agent.agent_status != "disconnected")  # type: ignore[attr-defined]
                    )
                    agent_result = await db_sess.exec(agent_stmt)
                    stale_agents = agent_result.all()
                    for agent in stale_agents:
                        agent.agent_status = "disconnected"
                        db_sess.add(agent)
                    await db_sess.commit()

                if stale_agents:
                    logger.info(
                        "Session %s: reset %d agent(s) to 'disconnected'",
                        runner.session_id,
                        len(stale_agents),
                    )

            logger.info(
                "Restore check complete: %d checked, %d killed, %d marked dead",
                checked,
                killed,
                marked_dead,
            )
            return checked

        except Exception as e:
            logger.error("Failed to restore active sessions: %s", e)
            return 0

    async def shutdown_all(self) -> int:
        """
        关闭所有 Runner 进程

        在 Web 服务关闭时调用。仅停止子进程，不执行资源清理
        （不删除 DB 记录、不清理文件/日志/快照）。

        设计意图：服务重启后 session 应可恢复（Runner 进程重新启动，
        session 文件/日志/快照均保留）。资源清理由用户主动删除
        session 时通过 SessionCleanupService 触发。

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

# Backward-compatibility alias
RunnerManager = IPCSessionRunner
