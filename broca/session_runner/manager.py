"""
Session Runner Manager

在 Web 进程中运行，负责管理所有 Session Runner 子进程的生命周期。
提供统一的进程控制接口，监控子进程健康状态。
"""

import asyncio
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from broca.components.session_runner import SessionRunner as SessionRunnerABC
from broca.errors import SessionError, ValidationError
from broca.session.session_manager import SessionManager
from broca.session_runner.ipc import (
    IPCConnectionError,
    IPCServer,
    IPCTimeoutError,
    create_ipc_message,
)
from broca.session_runner.events import EventBus, TaskSet
# HEARTBEAT_* 常量在 monitor.py，此处 re-export 保持既有测试引用
from broca.session_runner.monitor import (  # noqa: F401
    HEARTBEAT_GRACE_MULTIPLIER,
    HEARTBEAT_PERSIST_INTERVAL,
    HealthPolicy,
    HeartbeatMonitor,
    release_handle,
)
from broca.session_runner.models import (
    IPCMessage,
    IPCMessageType,
    RunnerProcessInfo,
    RunnerStatus,
    decode_ipc_message,
)

# 子进程启动相关实现已迁至 process/launcher.py，此处 re-export 保持既有引用
# （broca/tests/test_runner_launcher.py 仍从本模块导入这些符号）。
from broca.session_runner.process.launcher import (  # noqa: F401
    RUNNER_MODULE,
    RunnerLauncher,
    build_runner_argv,
    build_runner_env,
    platform_popen_kwargs,
    repo_root,
)
from broca.session_runner.poller import IPCPoller
from broca.session_runner.process.reaper import RunnerReaper
from broca.session_runner.protocol import MessageRouter, handles
from broca.session_runner.process.registry import RunnerHandle, RunnerRegistry
from broca.session_runner.repository import RunnerRepository
from broca.logging_config import get_logger

logger = get_logger(__name__)

# Agent 状态跨 session 批量的聚合窗口（秒）。
# 心跳每 5s 一次、10 个 session 分散到达；给一个短窗口把同一批心跳
# 合并成一次 commit（N session → 1 次），窗口过大会让 DB 状态陈旧。
AGENT_STATUS_FLUSH_DELAY = 0.2


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
            # 单一注册表：{session_id: RunnerHandle}
            # （此前是 7 个并行 dict，任何一处漏改都会产生幽灵状态）
            self._registry = RunnerRegistry()
            # 配置
            try:
                from broca.configs import get_configs

                # 未来可加入 configs.json 的 execution.max_concurrent_runners
                self._max_concurrent_runners = getattr(
                    get_configs().execution, "max_concurrent_runners", 10
                )
            except Exception:
                self._max_concurrent_runners = 10
            # 持久化仓库（收敛所有 DB 直写）
            self._repo = RunnerRepository()
            # 进程启动 / 判活回收
            self._launcher = RunnerLauncher()
            self._reaper = RunnerReaper()
            # fire-and-forget 任务的唯一入口（持引用 + 异常落日志）
            self._tasks = TaskSet("runner-manager")
            # 事件总线（session_started / session_stopped / session_crashed / crew_event）
            self._events = EventBus("runner-manager")
            # IPC 单线程多路复用（Task 4.2）：一个 ipc-poller 线程轮询所有连接，
            # 线程数恒为 O(1)。灰度期曾保留「每 session 一线程」的回滚路径，
            # 已在 Phase 4 收尾下线（备份见 docs/legacy/session_runner/）
            self._queue_size = self._read_queue_size()
            self._poller = IPCPoller(
                queue_size=self._queue_size, decode=decode_ipc_message
            )
            # Agent 状态跨 session 批量写缓冲（Task 4.3）：
            # {session_id: {agent_id: status}}，由 flush task 合并成一次 commit
            self._pending_agent_status: Dict[str, Dict[str, str]] = {}
            self._agent_flush_task: Optional[asyncio.Task] = None
            # 实例级路由表（无模块级单例）：EVT_* / RESPONSE → _handle_*
            self._router = MessageRouter.from_class(type(self), "manager")
            # 心跳巡检（策略 + 巡检循环 + 状态落库 + 收敛）
            self._monitor = HeartbeatMonitor(
                policy=HealthPolicy.from_config(),
                registry=self._registry,
                repo=self._repo,
                reaper=self._reaper,
                events=self._events,
            )
            # 日志目录
            self._log_dir = Path.home() / ".broca/logs/runners"
            # Per-session runner 日志目录 GC
            self._gc_task: Optional[asyncio.Task] = None

            logger.info(
                "RunnerManager initialized (max_runners=%d, module=%s)",
                self._max_concurrent_runners,
                RUNNER_MODULE,
            )

    @staticmethod
    def _read_queue_size() -> int:
        try:
            from broca.configs import get_configs

            return int(getattr(get_configs().execution, "runner_ipc_queue_size", 1000))
        except Exception:  # noqa: BLE001
            return 1000

    def _get_runner_log_file(self, session_id: str) -> str:
        """获取 Runner 进程的日志文件路径（固定文件名，按天轮转）。

        历史问题：此前文件名带 ``%Y%m%d``，靠「每天换一个文件」实现归档。
        但子进程是长驻的 —— 跨天时 ``FileHandler`` 仍写旧文件，实际效果是
        「跨天不轮转」，且永远没有清理机制。现在固定为 ``runner.log``，
        由 runner 侧 ``TimedRotatingFileHandler(when="midnight", backupCount=7)``
        负责轮转与保留，父进程只决定目录。
        """
        log_dir = os.path.join(self._log_dir, session_id)
        os.makedirs(log_dir, exist_ok=True)
        return os.path.join(log_dir, "runner.log")

    # ==================== Per-session 日志目录 GC ====================

    async def gc_runner_logs(self, max_age_days: Optional[int] = None) -> int:
        """清理超过 max_age_days 未修改的 runner 日志目录。

        通过 RunnerRegistry 获取活跃 session 集合，GC 时跳过这些 session 的目录。

        Args:
            max_age_days: 保留天数，None 时从 ExecutionConfig.runner_log_gc_days 读取。

        Returns:
            删除的目录数
        """
        if max_age_days is None:
            try:
                from broca.configs import get_configs
                max_age_days = int(
                    getattr(get_configs().execution, "runner_log_gc_days", 30)
                )
            except Exception:  # noqa: BLE001
                max_age_days = 30

        if not self._log_dir.exists():
            return 0

        active_sessions = set(self._registry.keys())
        now = time.time()
        max_age_seconds = max_age_days * 86400
        removed = 0

        for entry in self._log_dir.iterdir():
            if not entry.is_dir():
                continue
            if entry.name in active_sessions:
                continue
            try:
                mtime = entry.stat().st_mtime
                if now - mtime > max_age_seconds:
                    shutil.rmtree(entry, ignore_errors=True)
                    removed += 1
            except OSError:
                continue

        return removed

    def start_gc_loop(self) -> None:
        """启动 per-session 日志目录的定期 GC 后台任务。"""
        if self._gc_task is not None and not self._gc_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("start_gc_loop called outside event loop, skipping")
            return
        self._gc_task = asyncio.create_task(
            self._runner_log_gc_loop(), name="runner-log-gc"
        )

    async def _runner_log_gc_loop(self) -> None:
        """定期清理过期的 runner 日志目录。"""
        from broca.logging_config import get_gc_interval

        gc_interval = get_gc_interval()
        while True:
            await asyncio.sleep(gc_interval)
            try:
                removed = await self.gc_runner_logs()
                if removed:
                    logger.info(f"GC: removed {removed} stale runner log dirs")
            except Exception as e:
                logger.warning(f"GC runner logs error: {e}")

    # ==================== 进程生命周期管理 ====================

    async def _save_runner_to_db(self, runner_info: RunnerProcessInfo) -> None:
        """将单个 Runner 信息持久化到数据库（委托 RunnerRepository）。"""
        await self._save_runners_to_db([runner_info])

    async def _save_runners_to_db(
        self, runner_infos: list[RunnerProcessInfo]
    ) -> None:
        """批量持久化（单事务、一次 commit），委托 RunnerRepository。"""
        if not runner_infos:
            return
        try:
            await self._repo.upsert_many(runner_infos)
        except Exception as e:
            logger.warning(f"Failed to save runners to DB: {e}")

    async def _remove_runner_from_db(self, session_id: str) -> None:
        """从数据库删除 Runner 记录（委托 RunnerRepository）。"""
        try:
            await self._repo.delete(session_id)
        except Exception as e:
            logger.warning(f"Failed to remove runner from DB: {e}")

    async def _get_runner_from_db(self, session_id: str) -> Optional[RunnerProcessInfo]:
        """从数据库获取 Runner 记录（委托 RunnerRepository）。"""
        try:
            return await self._repo.get(session_id)
        except Exception as e:
            logger.warning(f"Failed to get runner from DB: {e}")
            return None

    async def start_session(
        self,
        session_id: str,
        workspace: Optional[str] = None,
        **kwargs: Any,
    ) -> RunnerProcessInfo:
        """启动一个新的 Session Runner 进程。

        Args:
            session_id: Session ID
            workspace: 工作空间路径
            **kwargs: 兼容 ABC 的 ``**kwargs`` 契约；provider/model 等 LLM 选择
                由 runner 从 session 记录读取，不再经 argv 传递。

        Raises:
            RunnerManagerError: 启动失败
        """
        # 确保 per-session 日志目录 GC 循环已启动（幂等：已有 task 时直接返回）
        self.start_gc_loop()

        if kwargs:
            logger.debug(
                "start_session ignores extra kwargs: %s", sorted(kwargs)
            )
        await self._check_quota(session_id)
        ipc_server = await self._open_ipc_server(session_id)

        try:
            handle = self._spawn(session_id, workspace, ipc_server)
            await self._await_ready(handle)
            await self._events.emit("session_started", handle.info)
            await self._save_runner_to_db(handle.info)
            self._attach_listener(handle)
            return handle.info
        except RunnerManagerError:
            raise
        except Exception as e:
            logger.error(f"Failed to start runner for session {session_id}: {e}")
            await self._cleanup_runner(session_id)
            raise RunnerManagerError(f"Failed to start runner: {e}") from e

    async def _check_quota(self, session_id: str) -> None:
        """并发上限 + 重复启动检查（进程存活即计数，含 ERROR / SHUTTING_DOWN）。"""
        if self._get_active_runner_count() >= self._max_concurrent_runners:
            raise RunnerManagerError(
                f"Max concurrent runners reached ({self._max_concurrent_runners})"
            )

        existing = self._registry.get(session_id)
        if existing is None:
            return
        if existing.info.status in (RunnerStatus.ALIVE, RunnerStatus.STARTING):
            raise RunnerManagerError(
                f"Session {session_id} already has a running runner "
                f"(status={existing.info.status.value})"
            )
        await self._cleanup_runner(session_id)

    async def _open_ipc_server(self, session_id: str) -> IPCServer:
        ipc_server = IPCServer(session_id)
        try:
            await ipc_server.start()
        except IPCConnectionError as e:
            raise RunnerManagerError(f"Failed to start IPC server: {e}") from e
        return ipc_server

    def _spawn(
        self, session_id: str, workspace: Optional[str], ipc_server: IPCServer
    ) -> RunnerHandle:
        """拉起子进程并注册 handle（info + ipc + 各缓存收在同一对象里）。"""
        log_file = self._get_runner_log_file(session_id)
        logger.info(f"Runner log file: {log_file}")

        process = self._launcher.spawn(
            session_id=session_id,
            workspace=workspace,
            log_file=log_file,
            config_path=self._config_path(),
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
        handle = RunnerHandle(info=runner_info, ipc=ipc_server)
        self._registry.add(handle)
        return handle

    def _config_path(self) -> Optional[str]:
        try:
            from broca.configs import get_configs

            path = get_configs().config_source_path
            return str(path) if path else None
        except Exception:  # noqa: BLE001 - 配置不可用时用默认值启动
            return None

    async def _await_ready(self, handle: RunnerHandle) -> None:
        """等待 Runner 连接并收到首条消息（READY / ERROR），超时 15s + 30s。"""
        session_id = handle.info.session_id
        ipc_server = handle.ipc
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, ipc_server.accept, 15.0)
            logger.info(f"Runner for session {session_id} connected via IPC")
            first_msg = await self._read_first_message(ipc_server)
            await self._apply_first_message(handle, first_msg)
        except IPCTimeoutError:
            await self._abort_start(session_id, "did not connect within timeout")
        except IPCConnectionError as e:
            await self._abort_start(session_id, f"IPC error: {e}")

    async def _read_first_message(self, ipc_server: IPCServer) -> Optional[IPCMessage]:
        """轮询首条消息：6 × 5s = 30s 总超时（短超时避免 poll() 误判）。"""
        loop = asyncio.get_event_loop()
        for attempt in range(6):
            msg = await loop.run_in_executor(None, ipc_server.receive_message, 5.0)
            if msg is not None:
                return msg
            logger.debug(f"Waiting for first message (attempt {attempt + 1}/6)...")
        return None

    async def _apply_first_message(
        self, handle: RunnerHandle, first_msg: Optional[IPCMessage]
    ) -> None:
        session_id = handle.info.session_id
        runner_info = handle.info

        if first_msg is not None and first_msg.type == IPCMessageType.EVT_READY:
            runner_info.status = RunnerStatus.ALIVE
            runner_info.last_heartbeat = datetime.now(timezone.utc)
            logger.info(
                "Session %s runner READY (agents: %s)",
                session_id,
                first_msg.payload.get("agent_count", 0),
            )
            return

        if first_msg is not None and first_msg.type == IPCMessageType.EVT_ERROR:
            payload = first_msg.payload
            logger.error(f"Session {session_id} runner init failed: {payload}")
            runner_info.status = RunnerStatus.ERROR
            runner_info.error_message = payload.get("message") or str(payload)
            runner_info.recovery_hint = payload.get("recovery_hint")
            await self._events.emit("runner_error", runner_info)
            await self._abort_start(session_id, runner_info.error_message)

        msg_type = first_msg.type.value if first_msg else "None"
        logger.error(
            "Session %s runner did not send READY in time (got: %s)", session_id, msg_type
        )
        await self._abort_start(
            session_id, f"did not send READY within 30s (got: {msg_type})"
        )

    async def _abort_start(self, session_id: str, reason: str) -> None:
        """启动失败清理：杀进程 + 释放资源 + 抛 RunnerManagerError。"""
        await self._kill_runner(session_id)
        await self._cleanup_runner(session_id)
        raise RunnerManagerError(f"Runner for session {session_id} {reason}")

    def _attach_listener(self, handle: RunnerHandle) -> None:
        """注册连接并把消费 task 挂到 handle 上（便于 stop 时取消）。

        时序：必须在 ``_await_ready()`` 之后调用 —— 只有 ``accept()`` 完成后
        ``ipc_server.connection`` 才非 None，否则会注册一个 None 并静默丢消息。
        """
        session_id = handle.info.session_id
        ipc_server = handle.ipc
        # 时序断言：connection 只有在 accept() 完成后才非 None。
        # 这里若为 None 说明 start_session 的调用顺序被改坏了，
        # 必须显式失败而不是注册一个 None 静默丢消息。
        connection = getattr(ipc_server, "connection", None) if ipc_server else None
        if connection is None:
            raise RunnerManagerError(
                f"IPC connection not established for session {session_id}; "
                "_attach_listener must run after _await_ready()"
            )
        self._poller.start(asyncio.get_running_loop())
        self._poller.register(session_id, connection)
        handle.poll_task = asyncio.create_task(
            self._ipc_listener_loop(session_id), name=f"ipc-listener-{session_id}"
        )

    def _cancel_ipc_listener_task(self, session_id: str) -> None:
        """取消 IPC 监听任务（幂等）。"""
        handle = self._registry.get(session_id)
        if handle is not None:
            release_handle(handle)

    async def _cleanup_ipc_resources(self, session_id: str) -> None:
        """释放该 session 的 IPC 资源（取消监听任务 + 注销连接 + 关闭 server）。

        约定：**只有 ``IPCServer.close()`` 负责删除 socket 文件**，这里不手动
        unlink —— 否则会与 ``close()`` 内的 unlink 竞争，出现 ``FileNotFoundError``。
        """
        self._cancel_ipc_listener_task(session_id)
        self._poller.unregister(session_id)

    async def stop_session(self, session_id: str, timeout: float = 5.0) -> bool:
        """
        优雅停止 Session Runner 进程

        Args:
            session_id: Session ID
            timeout: 等待进程退出的超时时间（秒）

        Returns:
            是否成功停止
        """
        handle = self._registry.get(session_id)
        if handle is None:
            return await self._recover_stale_runner(session_id)

        runner_info = handle.info
        logger.info(
            "Stopping runner for session %s (pid=%d)", session_id, runner_info.pid
        )

        try:
            # 1) 标记为正在关闭 —— **保留条目**，让 get_status() 能看到
            #    shutting_down（旧实现先 pop 条目，导致状态对外不可见、
            #    RESPONSE 永远被丢弃）
            runner_info.status = RunnerStatus.SHUTTING_DOWN
            runner_info.stop_requested = True

            # 2) 通过 IPC 发送关闭命令
            ipc_server = handle.ipc
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

            # 3) 等待进程退出（不要通过 IPC 读响应——连接上可能有旧消息残留
            #    导致竞争；直接等进程退出更可靠）
            await self._await_exit_or_kill(handle, timeout)

            # 4) 收敛为「已停止」（不是崩溃）
            await self._monitor.converge_stopped(session_id)
            logger.info(f"Session {session_id} runner stopped")
            return True

        except Exception as e:
            logger.error(f"Failed to stop runner for session {session_id}: {e}")
            # 异常时也确保进程被杀（防止僵尸）
            await self._reaper.terminate(handle)
            return False

    async def _recover_stale_runner(self, session_id: str) -> bool:
        """内存中无记录时，从 DB 恢复并清理残留进程/资源。"""
        logger.warning(
            "Session %s not found in memory, trying DB recovery...", session_id
        )
        db_runner = await self._get_runner_from_db(session_id)
        if not db_runner or not db_runner.pid:
            await self._cleanup_ipc_resources(session_id)
            logger.info(
                "Session %s has no runner records, cleaned IPC resources", session_id
            )
            return False

        pid = db_runner.pid
        logger.info(
            "Found stale runner for session %s in DB (pid=%d), cleaning up...",
            session_id,
            pid,
        )
        # 多因子判活后再杀（防 PID 复用误杀无关进程）
        if self._reaper.is_alive(db_runner):
            await self._reaper.terminate_by_pid(pid, session_id=session_id)
        await self._cleanup_ipc_resources(session_id)
        await self._remove_runner_from_db(session_id)
        logger.info(f"Session {session_id} stale runner cleaned up (pid={pid})")
        return True

    async def _await_exit_or_kill(self, handle: RunnerHandle, timeout: float) -> None:
        """等待进程退出；超时则强制回收。全部异步，不阻塞事件循环。"""
        runner_info = handle.info
        process = runner_info.process
        if process is None:
            return
        try:
            await asyncio.to_thread(process.wait, timeout)
            logger.info(f"Runner {runner_info.session_id} process exited gracefully")
        except subprocess.TimeoutExpired:
            logger.warning(
                "Runner %s did not exit in time, force killing",
                runner_info.session_id,
            )
            await self._reaper.terminate(handle)

    async def request_stop(self, session_id: str) -> dict:
        """请求停止 runner：标记 + 发送 CMD_SHUTDOWN，立即返回（不等进程退出）。

        API 层的 ``POST /{session_id}/runner/stop`` 只依赖本方法，不再触碰
        管理器内部状态字典。

        Returns:
            {"session_id": str, "status": "stopping" | "stopped", "message": str}
        """
        handle = self._registry.get(session_id)
        if handle is None:
            # 没有活跃 runner，清理 IPC 残留
            await self._cleanup_ipc_resources(session_id)
            return {
                "session_id": session_id,
                "status": "stopped",
                "message": "No active runner",
            }

        runner_info = handle.info
        runner_info.status = RunnerStatus.SHUTTING_DOWN
        runner_info.stop_requested = True

        ipc_server = handle.ipc
        if ipc_server:
            try:
                ipc_server.send_message(
                    create_ipc_message(
                        IPCMessageType.CMD_SHUTDOWN,
                        session_id,
                        payload={"reason": "user_request"},
                    )
                )
                logger.info(f"Sent shutdown command to session {session_id} runner")
            except IPCConnectionError:
                logger.warning(
                    "Failed to send shutdown via IPC for %s (connection may already be closed)",
                    session_id,
                )

        return {
            "session_id": session_id,
            "status": "stopping",
            "message": "Runner stopping",
        }

    async def _kill_runner(self, session_id: str) -> None:
        """强制终止 Runner 进程（通过 session_id 查找）。"""
        handle = self._registry.get(session_id)
        if handle is None:
            logger.warning(f"_kill_runner: session {session_id} not registered, skipping")
            return
        await self._reaper.terminate(handle)

    async def _cleanup_runner(self, session_id: str) -> None:
        """清理 Runner 相关资源并出表。"""
        self._poller.unregister(session_id)
        handle = self._registry.pop(session_id)
        if handle is None:
            return
        handle.info.status = RunnerStatus.DEAD
        # 清理缓存，避免 session 重启后残留旧数据影响变更检测
        handle.agent_status_cache = None
        handle.db_state_cache = None
        # 取消监听任务 + 关闭 IPC（close() 负责 unlink socket）
        release_handle(handle)

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

    def get_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取 Session Runner 进程状态（ABC 契约）。

        Returns:
            状态信息字典，不存在返回 None
        """
        handle = self._registry.get(session_id)
        if handle is None:
            return None
        return handle.info.to_dict()

    def get_session_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """**已废弃**：请改用 :meth:`get_status`（保留一版以兼容既有调用方）。"""
        import warnings

        warnings.warn(
            "get_session_status() is deprecated, use get_status()",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.get_status(session_id)

    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        列出所有 Session Runner 进程

        Returns:
            Runner 信息列表
        """
        return [handle.info.to_dict() for handle in self._registry.all()]

    def get_stats(self) -> Dict[str, Any]:
        """
        获取 Runner 统计信息

        Returns:
            统计信息
        """
        total = len(self._registry)
        by_status: Dict[str, int] = {}
        for handle in self._registry.all():
            status = handle.info.status.value
            by_status[status] = by_status.get(status, 0) + 1

        return {
            "total_runners": total,
            "max_concurrent": self._max_concurrent_runners,
            "available_slots": max(0, self._max_concurrent_runners - total),
            "by_status": by_status,
            "runners": self.list_sessions(),
            # IPC 多路复用可观测性（Task 4.2）：线程数恒为 0/1。
            # dropped_events.total > 0 说明消费侧跟不上（Task 4.4 背压）：
            # heartbeat 大 = 心跳被合并（可接受），other 大 = 真丢了消息（要查）
            "dropped_events": self._poller.dropped_events,
            "ipc": {
                "poller_running": self._poller.running,
                "poller_connections": len(self._poller.registered()),
                "queue_size": self._queue_size,
                "dropped_count": self._poller.dropped_count,
                "dropped_events": self._poller.dropped_events,
            },
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
        handle = self._registry.get(session_id)
        if handle is None or handle.ipc is None:
            logger.warning(f"No IPC server found for session {session_id}")
            return None
        ipc_server = handle.ipc

        loop = asyncio.get_running_loop()
        msg = create_ipc_message(msg_type, session_id, payload=payload)
        future: asyncio.Future = loop.create_future()
        handle.pending_responses[msg.message_id] = future

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
            logger.error(f"IPC send command failed for session {session_id}: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Failed to send command to session {session_id}: {e}")
            return {"error": str(e)}
        finally:
            handle.pending_responses.pop(msg.message_id, None)

    def _get_active_runner_count(self) -> int:
        """获取活跃 Runner 数量（含 STARTING / ALIVE / ERROR / SHUTTING_DOWN）"""
        return self._registry.active_count()

    # ==================== IPC 事件接收 ====================

    async def _handle_runner_event(self, session_id: str, msg: IPCMessage) -> None:
        """处理来自 Runner 进程的 IPC 事件（路由表分发）。"""
        await self._router.dispatch(msg, self)

    # ---- 各事件处理器（@handles 标记，由 self._router 分发） ----

    @handles(IPCMessageType.RESPONSE, side="manager")
    async def _handle_evt_response(self, msg: IPCMessage) -> None:
        """命令响应：按 message_id 唤醒等待者。

        只由监听循环分发 —— send_command 不再直接 recv，也就不会把心跳当响应吞掉。
        """
        session_id = msg.session_id
        handle = self._registry.get(session_id)
        future = (
            handle.pending_responses.pop(msg.message_id, None)
            if handle is not None
            else None
        )
        if future is not None and not future.done():
            future.set_result(msg)
        else:
            logger.debug(
                "Dropped unmatched IPC response for session %s (id=%s)",
                session_id,
                msg.message_id,
            )

    @handles(IPCMessageType.EVT_HEARTBEAT, side="manager")
    async def _handle_evt_heartbeat(self, msg: IPCMessage) -> None:
        session_id = msg.session_id
        handle = self._registry.get(session_id)
        if handle is None:
            return
        runner_info = handle.info

        runner_info.last_heartbeat = datetime.now(timezone.utc)
        runner_info.resource_usage = msg.payload.get("resource_usage", {})
        # 心跳恢复：清除巡检期累积的「心跳陈旧」标记
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

        status_str = msg.payload.get("status")
        if status_str:
            try:
                runner_info.status = RunnerStatus(status_str)
            except ValueError:
                pass

        # 把心跳上报的 agent 状态同步到 DB（仅变化时写入）。
        # 心跳每 5s 上报一次各 agent 的实时状态，作为 DB 中 agent_status 的
        # 权威来源：短暂断线重连、心跳超时误判等场景下可自动自愈，
        # 避免前端轮询读到过期的 disconnected 状态。
        agent_statuses = msg.payload.get("agent_statuses")
        if isinstance(agent_statuses, dict) and agent_statuses:
            self._schedule_agent_status_sync(handle, agent_statuses)
        # DB 持久化由心跳监控循环的 HeartbeatMonitor._persist_states() 统一处理

    @handles(IPCMessageType.EVT_ERROR, side="manager")
    async def _handle_evt_error(self, msg: IPCMessage) -> None:
        session_id = msg.session_id
        handle = self._registry.get(session_id)
        if handle is None:
            return
        runner_info = handle.info

        runner_info.status = RunnerStatus.ERROR
        error_payload = msg.payload
        runner_info.error_message = error_payload.get("message") or str(error_payload)
        runner_info.recovery_hint = error_payload.get("recovery_hint")
        logger.error(
            "Runner error for session %s: %s", session_id, runner_info.error_message
        )
        # 触发 runner_error 事件，通知前端
        self._events.emit_soon("runner_error", runner_info)

    @handles(IPCMessageType.EVT_SHUTDOWN_COMPLETE, side="manager")
    async def _handle_evt_shutdown_complete(self, msg: IPCMessage) -> None:
        handle = self._registry.get(msg.session_id)
        if handle is None:
            return
        handle.info.status = RunnerStatus.DEAD
        logger.info(f"Runner confirmed shutdown for session {msg.session_id}")

    @handles(IPCMessageType.EVT_STATUS_CHANGE, side="manager")
    async def _handle_evt_status_change(self, msg: IPCMessage) -> None:
        handle = self._registry.get(msg.session_id)
        if handle is None:
            return
        status_str = msg.payload.get("status")
        if not status_str:
            return
        try:
            handle.info.status = RunnerStatus(status_str)
            logger.info(
                "Runner status changed for session %s: %s", msg.session_id, status_str
            )
        except ValueError:
            pass

    @handles(IPCMessageType.EVT_READY, side="manager")
    async def _handle_evt_ready(self, msg: IPCMessage) -> None:
        """迟到的 READY（正常路径在 start_session 里已被消费）。"""
        logger.debug(
            "Late EVT_READY from session %s (agents=%s)",
            msg.session_id,
            msg.payload.get("agent_count", 0),
        )

    @handles(IPCMessageType.EVT_COMPLETED, side="manager")
    async def _handle_evt_completed(self, msg: IPCMessage) -> None:
        logger.info(f"Runner reported completion for session {msg.session_id}")

    @handles(IPCMessageType.EVT_LOG, side="manager")
    async def _handle_evt_log(self, msg: IPCMessage) -> None:
        logger.info(f"[runner {msg.session_id}] {msg.payload.get('message', '')}")

    @handles(IPCMessageType.EVT_CREW_START, side="manager")
    @handles(IPCMessageType.EVT_CREW_PROGRESS, side="manager")
    @handles(IPCMessageType.EVT_CREW_COMPLETE, side="manager")
    @handles(IPCMessageType.EVT_CREW_ERROR, side="manager")
    async def _handle_evt_crew(self, msg: IPCMessage) -> None:
        """编排事件只做日志 + 转发给注册的 handler，走 TaskSet 持引用。"""
        self._tasks.spawn(self._events.emit_crew_event(msg.session_id, msg))

    # ==================== 心跳监控 ====================

    async def start_heartbeat_monitor(
        self, interval: Optional[float] = None, timeout: Optional[float] = None
    ) -> None:
        """启动心跳监控（委托 HeartbeatMonitor）。

        Args:
            interval: 检查间隔（秒），None 时读配置
            timeout: 心跳超时阈值（秒），None 时读配置
        """
        await self._monitor.start(interval=interval, timeout=timeout)

    async def stop_heartbeat_monitor(self) -> None:
        """停止心跳监控（委托 HeartbeatMonitor）。"""
        await self._monitor.stop()

    def _schedule_agent_status_sync(
        self, handle: RunnerHandle, agent_statuses: Dict[str, str]
    ) -> None:
        """把一次心跳上报的 agent 状态加入待写缓冲（不直接写库）。

        Task 4.3 的跨 session 批量：心跳每 5s 一次、10 个 session 分散到达。
        若每个 session 各自写库，就是每秒 2 次 commit，写放大与 session 数
        线性相关。这里改为「入缓冲 + 单次 flush」：

        - 变更检测：与上次同步值相同则直接返回（零成本）
        - 缓存乐观更新：先记下已提交的期望值，flush 失败再回滚以便重试
        - 在途去重：flush task 未完成时不重复 spawn
        """
        session_id = handle.info.session_id
        if handle.agent_status_cache == agent_statuses:
            return

        # 乐观更新：失败时由 _flush_agent_statuses 回滚为 None
        handle.agent_status_cache = dict(agent_statuses)
        self._pending_agent_status[session_id] = dict(agent_statuses)
        self._ensure_agent_flush_scheduled()

    def _ensure_agent_flush_scheduled(self) -> None:
        """确保只有一个在途 flush task（幂等）。"""
        task = self._agent_flush_task
        if task is not None and not task.done():
            return
        self._agent_flush_task = self._tasks.spawn(
            self._flush_agent_statuses(), name="flush-agent-status"
        )

    async def _flush_agent_statuses(self) -> None:
        """聚合窗口结束后一次性写入所有待同步的 session（单次 commit）。"""
        await asyncio.sleep(AGENT_STATUS_FLUSH_DELAY)

        pending = self._pending_agent_status
        self._pending_agent_status = {}
        if not pending:
            return

        try:
            changed_count = await self._repo.set_agent_statuses(pending)
        except Exception as e:  # noqa: BLE001 - 写库失败不能拖垮心跳链路
            logger.error(f"Failed to flush agent statuses: {e}")
            # 回滚缓存，下一个心跳会重新入缓冲
            for session_id in pending:
                handle = self._registry.get(session_id)
                if handle is not None:
                    handle.agent_status_cache = None
            return

        if changed_count:
            logger.debug(
                "Synced %d agent statuses across %d session(s)",
                changed_count,
                len(pending),
            )

    async def _ipc_listener_loop(self, session_id: str) -> None:
        """消费该 session 的 IPC 消息队列，逐条交给 router 分发。

        消息由 ``IPCPoller`` 的单线程投递到队列；这里只负责消费，不再自己起线程。

        自愈保证（历史 bug：这里一旦抛异常，任务静默死掉，该 session 的
        心跳再也不会被消费，45s 后被判 error 且永久无法恢复）：
        - 单条消息处理失败只记录日志，不中断循环
        - 队列投递 ``None`` 视为连接断开，退出循环把判定交给心跳巡检
        """
        queue = self._poller.queue(session_id)
        if queue is None:
            logger.warning(f"IPC queue not found for session {session_id}")
            return

        while session_id in self._registry:
            try:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if msg is None:
                    break

                try:
                    await self._handle_runner_event(session_id, msg)
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
        """启动时回收所有残留 runner（非 dead 状态的 SessionRunner 记录）。

        IPC 连接在服务重启后无法重建，任何残留 runner 进程均已无意义：
        - 进程存活 → kill（多因子判活，防 PID 复用误杀）+ 标记 dead
        - 进程不存在或无 pid → 直接标记 dead
        两种情况都会把关联 Agent 重置为 disconnected。

        实现要点：``repo.list_active()`` 返回**纯数据**（RunnerProcessInfo），
        不再把 detached ORM 对象 ``session.add()`` 到另一个 session。

        Returns:
            检查的总记录数
        """
        # 确保 GC 循环已启动（restore 路径可能先于 start_session 被调用）
        self.start_gc_loop()

        try:
            records = await self._repo.list_active()
        except Exception as e:
            logger.error(f"Failed to restore active sessions: {e}")
            return 0

        killed = 0
        try:
            for info in records:
                if await self._retire_orphan(info):
                    killed += 1
                await self._repo.upsert(info)
                reset = await self._repo.mark_agents_disconnected(info.session_id)
                if reset:
                    logger.info(
                        "Session %s: reset %d agent(s) to 'disconnected'",
                        info.session_id,
                        reset,
                    )
        except Exception as e:
            logger.error(f"Failed to restore active sessions: {e}")
            return 0

        logger.info(
            "Restore check complete: %d checked, %d killed", len(records), killed
        )
        return len(records)

    async def _retire_orphan(self, info: RunnerProcessInfo) -> bool:
        """把一条残留记录标记为 dead；返回是否真的杀掉了一个活进程。"""
        info.status = RunnerStatus.DEAD

        if not info.pid:
            info.error_message = "No PID recorded, marked dead on startup"
            logger.warning(f"Session {info.session_id} runner has no PID, marked dead")
            return False

        if not self._reaper.is_alive(info):
            info.error_message = "Process not found on startup, marked dead"
            logger.warning(
                "Session %s runner (pid=%d) process not found, marked dead",
                info.session_id,
                info.pid,
            )
            return False

        # IPC 已断，残留 runner 无法通信，终止并标记 dead
        logger.info(
            "Session %s runner (pid=%d) still running after restart, killing orphan",
            info.session_id,
            info.pid,
        )
        await self._reaper.terminate_by_pid(info.pid, session_id=info.session_id)
        info.error_message = (
            f"Orphaned runner (pid={info.pid}) killed on startup: "
            "IPC connection lost after service restart"
        )
        return True

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
        session_ids = self._registry.keys()
        stopped = 0
        for session_id in session_ids:
            try:
                if await self.stop_session(session_id):
                    stopped += 1
            except Exception as e:
                logger.error(f"Failed to stop runner {session_id}: {e}")

        await self.stop_heartbeat_monitor()
        # 取消 GC 后台任务
        if self._gc_task is not None:
            self._gc_task.cancel()
            try:
                await self._gc_task
            except (asyncio.CancelledError, Exception):
                pass
        # stop() 内部 join 轮询线程（最长 2s），必须离开事件循环执行
        await asyncio.to_thread(self._poller.stop)
        # 关闭所有 fire-and-forget 任务，避免事件循环关闭时留下
        # "Task was destroyed but it is pending" 告警
        await self._tasks.aclose()
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
        self._events.on(event, handler)

# Backward-compatibility alias
RunnerManager = IPCSessionRunner
