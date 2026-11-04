"""
Session Runner 子进程

作为独立进程运行，负责：
1. 加载指定的 Session 和 Agent
2. 维护与 Web 进程的 IPC 通信通道
3. 执行 Agent 的消息循环
4. 定期上报心跳和状态信息
5. 处理来自 Web 进程的控制命令

启动方式：python -m broca.session_runner.runner --session-id <id> [options]

Phase 3 Task 3.4：原先的 8 个模块级全局变量（``_running`` / ``_shutdown_event`` /
``_ipc_lost`` / ``_agent_factory`` / ``_agents`` / ``_session_manager`` /
``_crew_runner`` / ``_start_time``）已全部收进 :class:`SessionRunnerProcess`，
进程内状态不再跨实例共享，测试可直接实例化而不必 monkeypatch 全局。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import threading
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

# AgentFactory is now accessed via ComponentRegistry (broca.components)
from broca.errors import BrocaError, ValidationError
from broca.logging_config import get_logger, init_logging
from broca.session_runner.backpressure import (
    DEFAULT_QUEUE_SIZE,
    DroppedEvents,
    put_with_backpressure,
)
from broca.session_runner.ipc import (
    IPCChannel,
    IPCClient,
    IPCConnectionError,
    create_ipc_message,
    create_response_message,
)
from broca.session_runner.models import (
    IPCMessage,
    IPCMessageType,
    IPCStatusCode,
    RunnerResourceUsage,
    RunnerStatus,
)
from broca.session_runner.protocol import MessageRouter, handles

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型检查
    from broca.components.agent_factory import AgentFactory

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    """解析命令行参数（契约由 manager 侧的 build_runner_argv 镜像，勿单方面增删）"""
    parser = argparse.ArgumentParser(description="Session Runner 子进程")
    parser.add_argument("--session-id", required=True, help="Session ID")
    parser.add_argument("--workspace", default=None, help="工作空间路径")
    parser.add_argument("--log-file", default=None, help="日志文件路径")
    parser.add_argument("--log-level", default="INFO", help="日志级别")
    parser.add_argument("--config", default=None, help="配置文件路径 (configs.json)")
    return parser.parse_args()


def collect_resource_usage() -> Dict[str, Any]:
    """采集当前进程的资源使用情况"""
    try:
        import psutil

        proc = psutil.Process()
        mem = proc.memory_info()
        # interval=None 表示非阻塞：返回自上次调用以来的平均 CPU 占用。
        # 不要用 interval=0.1（会同步 sleep 100ms，卡住心跳所在的事件循环）
        cpu_percent = proc.cpu_percent(interval=None)
        create_time = proc.create_time()
        uptime = time.time() - create_time

        usage = RunnerResourceUsage(
            cpu_percent=cpu_percent,
            memory_rss=mem.rss,
            memory_percent=proc.memory_percent(),
            num_threads=proc.num_threads(),
            uptime_seconds=round(uptime, 1),
        )
        return usage.to_dict()
    except ImportError:
        return {"cpu_percent": 0, "memory_rss": 0, "status": "psutil_not_available"}
    except Exception as e:
        return {"error": str(e)}


def get_heartbeat_interval() -> float:
    """心跳上报间隔（秒），来自 configs.json → execution.runner_heartbeat_interval"""
    try:
        from broca.configs import get_configs

        return float(getattr(get_configs().execution, "runner_heartbeat_interval", 5))
    except Exception:
        return 5.0


def get_queue_size() -> int:
    """IPC 监听队列上限，来自 configs.json → execution.runner_ipc_queue_size。

    与 manager 侧共用同一个配置项：两侧背压阈值必须一致，否则父进程丢心跳、
    子进程却把命令堆到 OOM，灰度/排障时无法用同一个指标判断。
    """
    try:
        from broca.configs import get_configs

        return int(
            getattr(
                get_configs().execution, "runner_ipc_queue_size", DEFAULT_QUEUE_SIZE
            )
        )
    except Exception:
        return DEFAULT_QUEUE_SIZE


class SessionRunnerProcess:
    """一个 Session Runner 子进程的全部状态与循环。"""

    def __init__(self, args: argparse.Namespace, ipc: IPCChannel) -> None:
        self.args = args
        self.ipc = ipc
        self.running = False
        self.ipc_lost = False
        self.shutdown_event: Optional[asyncio.Event] = None
        self.agent_factory: Optional[AgentFactory] = None
        self.agents: List[Any] = []
        self.session_manager: Any = None
        self.crew_runner: Optional[Any] = None
        self.crew_task: Optional[asyncio.Task] = None
        self.start_time: float = 0.0
        self.agent_tasks: List[asyncio.Task] = []
        # IPC 队列背压计数（Task 4.4）：经 CMD_GET_STATS 暴露给父进程
        self.dropped_events = DroppedEvents()
        # 实例级路由表（无模块级单例）：CMD_* → _handle_cmd_*
        self.router = MessageRouter.from_class(type(self), "runner")

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def request_shutdown(self, reason: str) -> None:
        """统一收敛「停止」语义：running=False + 唤醒所有等待中的循环。

        历史上这三件事散落在 4 处（CMD_SHUTDOWN / 心跳发送失败 / IPC 断开 /
        信号处理），任一处漏掉就会留下卡死的循环。
        """
        logger.info("Runner shutdown requested: %s", reason)
        self.running = False
        if self.shutdown_event is not None:
            self.shutdown_event.set()

    def mark_ipc_lost(self, reason: str) -> None:
        """IPC 断开（后端崩溃）→ 触发 shutdown，避免成为孤儿进程。"""
        self.ipc_lost = True
        self.request_shutdown(f"ipc lost: {reason}")

    async def run(self) -> None:
        """异步主逻辑（原 async_main）。"""
        self.running = True
        self.start_time = time.time()
        self.shutdown_event = asyncio.Event()

        try:
            await self._bootstrap()

            # === 6. 并发运行：心跳 + IPC监听 + Agent监控 ===
            await asyncio.gather(
                self._heartbeat_loop(),
                self._ipc_listener_loop(),
                self._agent_monitor_loop(),
                return_exceptions=True,
            )

            await self._shutdown()
            logger.info("Runner shutdown complete")

        except BrocaError as e:
            logger.error("Runner BrocaError: %s", e, exc_info=True)
            self._send_error(e.to_dict())
            raise
        except Exception as e:
            logger.error("Runner fatal error: %s", e, exc_info=True)
            self._send_error({"error": str(e)})
            raise

    async def _bootstrap(self) -> None:
        """恢复 Agent、发 READY、连接 SocketIO、启动 Agent 消息循环。"""
        from broca.components import ComponentRegistry
        from broca.components.agent_factory import AgentFactory as AgentFactoryABC

        # === 1. 初始化数据库连接（由 SessionManager / Service 内部管理） ===
        logger.info("Initializing session: %s", self.args.session_id)

        # === 2. 创建 AgentFactory 并恢复 Agent ===
        self.agent_factory = ComponentRegistry.get_instance().get(AgentFactoryABC)
        self.agents = await self.agent_factory.restore_agents_from_session(
            self.args.session_id
        )

        if not self.agents:
            error_msg = "No agents restored from session"
            logger.error(error_msg)
            self.ipc.send_message(
                create_ipc_message(
                    IPCMessageType.EVT_ERROR,
                    self.args.session_id,
                    payload={"error": error_msg},
                    status=IPCStatusCode.ERROR,
                )
            )
            self.running = False
            return

        self.session_manager = self.agents[0].session_manager
        logger.info(
            "Restored %d agents for session %s",
            len(self.agents),
            self.args.session_id,
        )

        # === 3. 发送 READY 事件 ===
        self.ipc.send_message(
            create_ipc_message(
                IPCMessageType.EVT_READY,
                self.args.session_id,
                payload={
                    "agent_count": len(self.agents),
                    "agent_ids": [a.agent_id for a in self.agents],
                    "agent_names": [a.name for a in self.agents],
                },
            )
        )
        logger.info("Runner READY signal sent")

        # === 4. 并行连接 Agent 到 SocketIO Server ===
        connect_results = await asyncio.gather(
            *[agent.connect() for agent in self.agents], return_exceptions=True
        )
        for idx, result in enumerate(connect_results):
            agent = self.agents[idx]
            if isinstance(result, Exception):
                logger.error("Agent %s connect failed: %s", agent.agent_id, result)
            else:
                logger.info("Agent %s connected to SocketIO", agent.agent_id)

        # === 5. 启动 Agent 消息循环 ===
        for agent in self.agents:
            self.agent_tasks.append(asyncio.create_task(agent.start()))
            logger.info("Agent %s message loop started", agent.agent_id)

    async def _shutdown(self) -> None:
        """停止 Agent、等待收尾、断开连接、发送 EVT_SHUTDOWN_COMPLETE。"""
        logger.info("Shutting down agents...")
        for agent in self.agents:
            agent.stop()

        # 给 Agent 短暂时间完成收尾（2s 足够，超时直接 cancel）
        if self.agent_tasks:
            _done, pending = await asyncio.wait(self.agent_tasks, timeout=2.0)
            for task in pending:
                task.cancel()
            self._log_agent_task_failures()

        if self.agents:
            await asyncio.gather(
                *(agent.disconnect() for agent in self.agents),
                return_exceptions=True,
            )

        try:
            self.ipc.send_message(
                create_ipc_message(
                    IPCMessageType.EVT_SHUTDOWN_COMPLETE,
                    self.args.session_id,
                    payload={"message": "Runner shutdown complete"},
                )
            )
        except Exception:  # noqa: BLE001 - 连接已断时忽略
            pass

    def _log_agent_task_failures(self) -> None:
        """Agent 任务结束后取回异常并记 ERROR（否则告警只在解释器退出时冒出来）。"""
        for task in self.agent_tasks:
            if task.cancelled():
                continue
            exc = task.exception()
            if exc is not None:
                logger.error("Agent task failed: %s", exc, exc_info=exc)

    def _send_error(self, payload: Dict[str, Any]) -> None:
        try:
            self.ipc.send_message(
                create_ipc_message(
                    IPCMessageType.EVT_ERROR,
                    self.args.session_id,
                    payload=payload,
                    status=IPCStatusCode.ERROR,
                )
            )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # 循环
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self, interval: Optional[float] = None) -> None:
        """心跳发送循环。"""
        if interval is None:
            interval = get_heartbeat_interval()
        while self.running:
            try:
                heartbeat_msg = create_ipc_message(
                    IPCMessageType.EVT_HEARTBEAT,
                    self.ipc.session_id,
                    payload={
                        "resource_usage": collect_resource_usage(),
                        "status": RunnerStatus.ALIVE.value,
                        "agent_count": len(self.agents),
                        "agent_statuses": {
                            a.agent_id: a.status
                            for a in self.agents
                            if hasattr(a, "status")
                        },
                    },
                )
                self.ipc.send_message(heartbeat_msg)
            except IPCConnectionError:
                logger.warning("Heartbeat send failed, IPC connection may be lost")
                self.mark_ipc_lost("heartbeat send failed")
                break
            except Exception as e:  # noqa: BLE001 - 单次心跳失败不应终止循环
                logger.error("Heartbeat error: %s", e)

            # 用 event 替代 sleep，shutdown 时立即唤醒
            if await self._wait_or_shutdown(interval):
                break

    async def _ipc_listener_loop(self) -> None:
        """IPC 命令监听循环。

        使用专用 daemon 线程执行阻塞的 receive_message，通过
        asyncio.Queue + call_soon_threadsafe 将消息送回 event loop，
        避免占用默认线程池。

        注意：multiprocessing.connection.Client 底层是 socket。
        send() 和 recv() 是不同方向的独立操作，可在不同线程/协程中并发调用。
        heartbeat_loop（event loop 线程）调用 send，_thread_poll（daemon 线程）调用 recv。
        """
        loop = asyncio.get_running_loop()
        # 有界队列（Task 4.4）：事件循环被长工具调用卡住时，轮询线程仍在投递，
        # 无界队列会一直涨到 OOM。上限与 manager 侧共用同一个配置项。
        msg_queue: asyncio.Queue = asyncio.Queue(maxsize=get_queue_size())

        def _enqueue(msg: Any) -> None:
            """事件循环线程内入队（asyncio.Queue 非线程安全）。

            ``None`` 是断连哨兵，用 ``force=True`` 保证一定入队 ——
            哨兵丢了监听循环就永远退不出去。
            """
            put_with_backpressure(
                msg_queue,
                msg,
                self.dropped_events,
                session_id=self.args.session_id,
                force=msg is None,
            )

        def _thread_poll() -> None:
            while self.running and not self.ipc_lost:
                try:
                    msg = self.ipc.receive_message(0.5)
                    if msg:
                        loop.call_soon_threadsafe(_enqueue, msg)
                except IPCConnectionError as e:
                    logger.warning("IPC connection lost: %s", e)
                    loop.call_soon_threadsafe(_enqueue, None)
                    break
                except Exception as e:  # noqa: BLE001
                    logger.error("IPC listener thread error: %s", e)
                    loop.call_soon_threadsafe(_enqueue, None)
                    break

        threading.Thread(
            target=_thread_poll, name="ipc-poll-runner", daemon=True
        ).start()

        while self.running and not self.ipc_lost:
            try:
                msg = await asyncio.wait_for(msg_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if msg is None:
                # IPC 断开（后端崩溃）→ 触发全局 shutdown，避免孤儿进程
                self.mark_ipc_lost("listener queue closed")
                break
            await self.handle_ipc_command(msg)

    async def _agent_monitor_loop(self) -> None:
        """检查 Agent 是否仍在运行，如果全部停止则触发 runner 关闭。"""
        while self.running:
            all_stopped = True
            for agent in self.agents:
                if getattr(agent, "running", False):
                    all_stopped = False
                    break

            if all_stopped and self.agents:
                logger.info("All agents have stopped, shutting down runner")
                self.request_shutdown("all agents stopped")
                break

            if await self._wait_or_shutdown(1.0):
                break

    async def _wait_or_shutdown(self, timeout: float) -> bool:
        """等待 timeout 秒；shutdown 事件被 set 时立即返回 True。"""
        if self.shutdown_event is None:
            await asyncio.sleep(timeout)
            return False
        try:
            await asyncio.wait_for(self.shutdown_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    # ------------------------------------------------------------------
    # IPC 命令处理
    # ------------------------------------------------------------------

    async def handle_ipc_command(self, msg: IPCMessage) -> None:
        """处理来自 Web 进程的 IPC 控制命令（路由表分发）。"""
        logger.info("Received IPC command: %s", msg.type.value)
        await self.router.dispatch(msg, self)

    @handles(IPCMessageType.CMD_STATUS, side="runner")
    async def _handle_cmd_status(self, msg: IPCMessage) -> None:
        """返回当前状态（回显 request message_id，供 Manager 精确匹配响应）。"""
        self.ipc.send_message(
            create_response_message(
                msg,
                status=IPCStatusCode.SUCCESS,
                payload={
                    "status": RunnerStatus.ALIVE.value
                    if self.running
                    else RunnerStatus.SHUTTING_DOWN.value,
                    "agent_count": len(self.agents),
                    "resource_usage": collect_resource_usage(),
                    "uptime": time.time() - self.start_time if self.start_time else 0,
                },
            )
        )

    @handles(IPCMessageType.CMD_GET_STATS, side="runner")
    async def _handle_cmd_get_stats(self, msg: IPCMessage) -> None:
        """返回各 Agent 的统计信息。"""
        stats: Dict[str, Any] = {}
        for agent in self.agents:
            try:
                stats[agent.agent_id] = agent.get_stats()
            except Exception:  # noqa: BLE001 - 单个 agent 取统计失败不影响整体
                pass
        self.ipc.send_message(
            create_response_message(
                msg,
                status=IPCStatusCode.SUCCESS,
                payload={
                    "agents_stats": stats,
                    # 背压可观测性（Task 4.4）：other > 0 说明真丢了命令
                    "dropped_events": self.dropped_events.to_dict(),
                },
            )
        )

    @handles(IPCMessageType.CMD_ABORT, side="runner")
    async def _handle_cmd_abort(self, msg: IPCMessage) -> None:
        """中止所有 Agent 的执行。"""
        for agent in self.agents:
            try:
                await agent.abort()
                logger.info("Agent %s aborted", agent.agent_id)
            except Exception as e:  # noqa: BLE001
                logger.error("Failed to abort agent %s: %s", agent.agent_id, e)

        self.ipc.send_message(
            create_response_message(
                msg,
                status=IPCStatusCode.SUCCESS,
                payload={"message": "All agents aborted"},
            )
        )

    @handles(IPCMessageType.CMD_SHUTDOWN, side="runner")
    async def _handle_cmd_shutdown(self, msg: IPCMessage) -> None:
        """优雅关闭。"""
        logger.info("Received shutdown command")
        self.ipc.send_message(
            create_response_message(
                msg,
                status=IPCStatusCode.SUCCESS,
                payload={"message": "Shutting down..."},
            )
        )
        self.request_shutdown("shutdown command")

    @handles(IPCMessageType.CMD_RUN_CREW, side="runner")
    async def _handle_cmd_run_crew(self, msg: IPCMessage) -> None:
        """启动一次编排（同一时刻只允许一个）。"""
        from broca.orchestration.crew import CrewConfig
        from broca.session_runner.orchestrator_runner import CrewOrchestratorRunner

        # 已有编排在跑 → 拒绝，避免 crew_runner 单例被静默覆盖
        if self.crew_runner is not None:
            active_crew_id = getattr(self.crew_runner, "_crew_id", "unknown")
            logger.warning(
                "Reject CMD_RUN_CREW: crew '%s' is still running", active_crew_id
            )
            self.ipc.send_message(
                create_response_message(
                    msg,
                    status=IPCStatusCode.ERROR,
                    payload={
                        "error": "Another crew is already running",
                        "active_crew_id": active_crew_id,
                    },
                )
            )
            return

        yaml_content = msg.payload.get("yaml_content")
        yaml_path = msg.payload.get("yaml_path")

        try:
            if yaml_content:
                crew_config = CrewConfig.from_yaml(yaml_content)
            elif yaml_path:
                crew_config = CrewConfig.from_yaml_file(yaml_path)
            else:
                raise ValidationError("Either yaml_content or yaml_path is required")

            agent_refs = self._match_crew_agents(crew_config)

            if not agent_refs:
                self.ipc.send_message(
                    create_response_message(
                        msg,
                        status=IPCStatusCode.ERROR,
                        payload={
                            "error": (
                                f"No agents matched. Crew requires: "
                                f"{[a.name for a in crew_config.agents]}, "
                                f"Session has: {[a.name for a in self.agents]}"
                            )
                        },
                    )
                )
                return

            crew_runner = CrewOrchestratorRunner(
                session_id=msg.session_id,
                ipc_client=self.ipc,
                agent_factory=self.agent_factory,
                session_manager=self.session_manager,
            )
            self.crew_runner = crew_runner
            execution_id = msg.payload.get("execution_id")

            # 持引用 + done_callback 记异常：裸 create_task 的异常会被静默吞掉
            self.crew_task = asyncio.create_task(
                self._run_crew_safe(crew_runner, crew_config, agent_refs, execution_id)
            )
            self.crew_task.add_done_callback(self._log_crew_task_result)

            self.ipc.send_message(
                create_response_message(
                    msg,
                    status=IPCStatusCode.SUCCESS,
                    payload={
                        "message": "Crew orchestration started",
                        "crew_id": crew_config.name,
                        "agent_count": len(agent_refs),
                        "orchestrator_type": crew_config.orchestrator.type.value,
                    },
                )
            )

        except Exception as e:  # noqa: BLE001 - 任何启动失败都要回响应
            logger.error("Failed to start crew: %s", e)
            self.ipc.send_message(
                create_response_message(
                    msg, status=IPCStatusCode.ERROR, payload={"error": str(e)}
                )
            )

    async def _run_crew_safe(
        self,
        crew_runner: Any,
        crew_config: Any,
        agent_refs: Dict[str, Any],
        execution_id: Optional[str],
    ) -> None:
        """后台运行编排（带异常兜底，防止静默失败）。"""
        try:
            await crew_runner.run_crew(
                crew_config, agent_refs, execution_id=execution_id
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Crew background task failed: %s", e, exc_info=True)
            try:
                crew_runner._send_crew_event(
                    IPCMessageType.EVT_CREW_ERROR,
                    {
                        "crew_id": crew_config.name,
                        "execution_id": execution_id,
                        "status": "error",
                        "error": f"Background task failed: {e}",
                    },
                )
            except Exception:  # noqa: BLE001
                pass
        finally:
            # 编排执行完毕，清除引用（不管成功/失败/取消）
            if self.crew_runner is crew_runner:
                self.crew_runner = None

    def _log_crew_task_result(self, task: "asyncio.Task") -> None:
        """记录后台编排任务的最终结果（正常取消不记 ERROR）。"""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Crew background task crashed: %s", exc, exc_info=exc)

    @handles(IPCMessageType.CMD_ABORT_CREW, side="runner")
    async def _handle_cmd_abort_crew(self, msg: IPCMessage) -> None:
        """中止编排。"""
        crew_id = msg.payload.get("crew_id")
        logger.info("Aborting crew: %s", crew_id)

        if self.crew_runner is None:
            logger.warning("No active crew runner to abort (crew_id=%s)", crew_id)
            self.ipc.send_message(
                create_response_message(
                    msg,
                    status=IPCStatusCode.ERROR,
                    payload={
                        "error": f"No active crew runner for {crew_id}",
                        "success": False,
                    },
                )
            )
            return

        try:
            aborted = await self.crew_runner.abort_crew()
            if aborted:
                logger.info("Crew '%s' aborted successfully", crew_id)
                self.ipc.send_message(
                    create_response_message(
                        msg,
                        status=IPCStatusCode.SUCCESS,
                        payload={
                            "message": f"Crew {crew_id} aborted",
                            "success": True,
                        },
                    )
                )
            else:
                logger.warning("No active orchestrator to abort for crew '%s'", crew_id)
                self.ipc.send_message(
                    create_response_message(
                        msg,
                        status=IPCStatusCode.ERROR,
                        payload={
                            "error": f"No active orchestrator for crew {crew_id}",
                            "success": False,
                        },
                    )
                )
        except Exception as e:  # noqa: BLE001
            logger.error("Error aborting crew: %s", e)
            self.ipc.send_message(
                create_response_message(
                    msg,
                    status=IPCStatusCode.ERROR,
                    payload={"error": str(e), "success": False},
                )
            )

    def _match_crew_agents(self, crew_config: Any) -> Dict[str, Any]:
        """把 crew 配置里的 agent 名字映射到本 session 的 Agent 实例。"""
        agent_refs: Dict[str, Any] = {}
        missing: List[str] = []
        for agent_cfg in crew_config.agents:
            agent = next((a for a in self.agents if a.name == agent_cfg.name), None)
            if agent is None:
                missing.append(agent_cfg.name)
                logger.warning(
                    "Agent '%s' not found in session, skipping", agent_cfg.name
                )
            else:
                agent_refs[agent_cfg.name] = agent

        if missing:
            logger.warning(
                "Crew agents not found in session: %s. Available agents: %s",
                missing,
                [a.name for a in self.agents],
            )
        return agent_refs


def main() -> None:
    """Runner 进程入口"""
    args = parse_args()

    # 兜底：手动 `python -m broca.session_runner.runner` 启动时环境变量可能缺失
    os.environ.setdefault("BROCA_RUNNER_CHILD", "1")

    # 尽早初始化配置（必须在其他 broca 模块使用前）
    if args.config:
        from broca.configs import get_configs

        get_configs(config_path=args.config)

    init_logging(log_file=args.log_file, log_level=args.log_level)

    logger.info(
        "Session Runner starting - session_id=%s workspace=%s config=%s",
        args.session_id,
        args.workspace,
        args.config,
    )

    # 初始化 IPC 客户端
    ipc_client = IPCClient(args.session_id)
    try:
        ipc_client.connect()
        logger.info("IPC client connected")
    except IPCConnectionError as e:
        logger.error("Failed to connect IPC: %s", e)
        sys.exit(1)

    runner = SessionRunnerProcess(args, ipc_client)

    # 注册信号处理
    def _signal_handler(signum, frame) -> None:
        runner.request_shutdown(f"signal {signum}")

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        asyncio.run(runner.run())
    except KeyboardInterrupt:
        logger.info("Runner interrupted by user")
    except Exception as e:
        logger.error("Runner crashed: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        ipc_client.close()


if __name__ == "__main__":  # pragma: no cover - 进程入口
    main()
