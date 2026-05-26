"""
Session Runner 子进程

作为独立进程运行，负责：
1. 加载指定的 Session 和 Agent
2. 维护与 Web 进程的 IPC 通信通道
3. 执行 Agent 的消息循环
4. 定期上报心跳和状态信息
5. 处理来自 Web 进程的控制命令

启动方式：python -m broca.session_runner.runner --session-id <id> [options]
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional

from broca.agent_manager import AgentFactory
from broca.session_runner.ipc import (
    IPCClient,
    IPCConnectionError,
    create_ipc_message,
)
from broca.session_runner.models import (
    IPCMessage,
    IPCMessageType,
    IPCStatusCode,
    RunnerResourceUsage,
    RunnerStatus,
)

logger = logging.getLogger(__name__)

# 全局状态
_running = False
_agent_factory: Optional[AgentFactory] = None
_agents: List[Any] = []
_session_manager: Any = None


def setup_logging(log_file: Optional[str] = None, level: str = "INFO") -> None:
    """配置日志"""
    handlers = [logging.StreamHandler(sys.stderr)]
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="Session Runner 子进程")
    parser.add_argument("--session-id", required=True, help="Session ID")
    parser.add_argument("--workspace", default=None, help="工作空间路径")
    parser.add_argument("--provider", default=None, help="LLM Provider")
    parser.add_argument("--model", default=None, help="LLM Model")
    parser.add_argument("--log-file", default=None, help="日志文件路径")
    parser.add_argument("--log-level", default="INFO", help="日志级别")
    return parser.parse_args()


def collect_resource_usage() -> Dict[str, Any]:
    """采集当前进程的资源使用情况"""
    try:
        import psutil

        proc = psutil.Process()
        mem = proc.memory_info()
        cpu_percent = proc.cpu_percent(interval=0.1)
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


async def heartbeat_loop(ipc_client: IPCClient, interval: float = 5.0) -> None:
    """
    心跳发送循环

    Args:
        ipc_client: IPC 客户端
        interval: 心跳间隔（秒）
    """
    global _running
    while _running:
        try:
            resource_usage = collect_resource_usage()
            heartbeat_msg = create_ipc_message(
                IPCMessageType.EVT_HEARTBEAT,
                ipc_client.session_id,
                payload={
                    "resource_usage": resource_usage,
                    "status": RunnerStatus.ALIVE.value,
                    "agent_count": len(_agents),
                    "agent_statuses": {
                        a.agent_id: a.status for a in _agents if hasattr(a, "status")
                    },
                },
            )
            ipc_client.send_message(heartbeat_msg)
        except IPCConnectionError:
            logger.warning("Heartbeat send failed, IPC connection may be lost")
            break
        except Exception as e:
            logger.error("Heartbeat error: %s", e)

        await asyncio.sleep(interval)


async def handle_ipc_command(msg: IPCMessage, ipc_client: IPCClient) -> None:
    """
    处理来自 Web 进程的 IPC 控制命令

    Args:
        msg: IPC 消息
        ipc_client: IPC 客户端
    """
    global _running, _agents

    logger.info("Received IPC command: %s", msg.type.value)

    if msg.type == IPCMessageType.CMD_STATUS:
        # 返回当前状态
        response = create_ipc_message(
            IPCMessageType.RESPONSE,
            msg.session_id,
            payload={
                "status": RunnerStatus.ALIVE.value
                if _running
                else RunnerStatus.SHUTTING_DOWN.value,
                "agent_count": len(_agents),
                "resource_usage": collect_resource_usage(),
                "uptime": time.time() - _start_time if _start_time else 0,
            },
            status=IPCStatusCode.SUCCESS,
        )
        ipc_client.send_message(response)

    elif msg.type == IPCMessageType.CMD_GET_STATS:
        # 返回统计信息
        stats = {}
        for agent in _agents:
            try:
                stats[agent.agent_id] = agent.get_stats()
            except Exception:
                pass

        response = create_ipc_message(
            IPCMessageType.RESPONSE,
            msg.session_id,
            payload={"agents_stats": stats},
            status=IPCStatusCode.SUCCESS,
        )
        ipc_client.send_message(response)

    elif msg.type == IPCMessageType.CMD_ABORT:
        # 中止所有 Agent 的执行
        for agent in _agents:
            try:
                await agent.abort()
                logger.info("Agent %s aborted", agent.agent_id)
            except Exception as e:
                logger.error("Failed to abort agent %s: %s", agent.agent_id, e)

        response = create_ipc_message(
            IPCMessageType.RESPONSE,
            msg.session_id,
            payload={"message": "All agents aborted"},
            status=IPCStatusCode.SUCCESS,
        )
        ipc_client.send_message(response)

    elif msg.type == IPCMessageType.CMD_SHUTDOWN:
        # 优雅关闭
        logger.info("Received shutdown command")
        response = create_ipc_message(
            IPCMessageType.RESPONSE,
            msg.session_id,
            payload={"message": "Shutting down..."},
            status=IPCStatusCode.SUCCESS,
        )
        ipc_client.send_message(response)

        # 触发关闭
        _running = False

    elif msg.type == IPCMessageType.CMD_RUN_CREW:
        # 运行编排
        from broca.orchestration.crew import CrewConfig
        from broca.session_runner.orchestrator_runner import CrewOrchestratorRunner

        yaml_content = msg.payload.get("yaml_content")
        yaml_path = msg.payload.get("yaml_path")

        try:
            if yaml_content:
                crew_config = CrewConfig.from_yaml(yaml_content)
            elif yaml_path:
                crew_config = CrewConfig.from_yaml_file(yaml_path)
            else:
                raise ValueError("Either yaml_content or yaml_path is required")

            # 收集 Agent 引用
            agent_refs = {}
            missing_agents = []
            for agent_cfg in crew_config.agents:
                agent = None
                for a in _agents:
                    if a.name == agent_cfg.name:
                        agent = a
                        break
                if agent is None:
                    missing_agents.append(agent_cfg.name)
                    logger.warning(f"Agent '{agent_cfg.name}' not found in session, skipping")
                else:
                    agent_refs[agent_cfg.name] = agent

            if missing_agents:
                logger.warning(
                    f"Crew agents not found in session: {missing_agents}. "
                    f"Available agents: {[a.name for a in _agents]}"
                )

            if not agent_refs:
                response = create_ipc_message(
                    IPCMessageType.RESPONSE,
                    msg.session_id,
                    payload={"error": f"No agents matched. Crew requires: {[a.name for a in crew_config.agents]}, Session has: {[a.name for a in _agents]}"},
                    status=IPCStatusCode.ERROR,
                )
                ipc_client.send_message(response)
                return

            # 创建编排运行器并执行
            crew_runner = CrewOrchestratorRunner(
                session_id=msg.session_id,
                ipc_client=ipc_client,
                agent_factory=_agent_factory,
                session_manager=_session_manager,
            )

            execution_id = msg.payload.get("execution_id")

            # 在后台任务中运行编排
            asyncio.create_task(
                crew_runner.run_crew(crew_config, agent_refs, execution_id=execution_id)
            )

            response = create_ipc_message(
                IPCMessageType.RESPONSE,
                msg.session_id,
                payload={
                    "message": "Crew orchestration started",
                    "crew_id": crew_config.name,
                    "agent_count": len(agent_refs),
                    "orchestrator_type": crew_config.orchestrator.type.value,
                },
                status=IPCStatusCode.SUCCESS,
            )
            ipc_client.send_message(response)

        except Exception as e:
            logger.error(f"Failed to start crew: {e}")
            response = create_ipc_message(
                IPCMessageType.RESPONSE,
                msg.session_id,
                payload={"error": str(e)},
                status=IPCStatusCode.ERROR,
            )
            ipc_client.send_message(response)

    elif msg.type == IPCMessageType.CMD_ABORT_CREW:
        # 中止编排
        crew_id = msg.payload.get("crew_id")
        logger.info(f"Aborting crew: {crew_id}")
        response = create_ipc_message(
            IPCMessageType.RESPONSE,
            msg.session_id,
            payload={"message": f"Crew {crew_id} abort initiated"},
            status=IPCStatusCode.SUCCESS,
        )
        ipc_client.send_message(response)

    elif msg.type == IPCMessageType.CMD_EXECUTE:
        # 执行用户消息 - 将消息放入 agent 的队列
        agent_id = msg.payload.get("agent_id")
        message_data = msg.payload.get("message")

        if not agent_id or not message_data:
            response = create_ipc_message(
                IPCMessageType.RESPONSE,
                msg.session_id,
                payload={"error": "agent_id and message are required"},
                status=IPCStatusCode.ERROR,
            )
            ipc_client.send_message(response)
            return

        # 查找目标 agent
        target_agent = None
        for agent in _agents:
            if agent.agent_id == agent_id:
                target_agent = agent
                break

        if not target_agent:
            response = create_ipc_message(
                IPCMessageType.RESPONSE,
                msg.session_id,
                payload={"error": f"Agent {agent_id} not found"},
                status=IPCStatusCode.NOT_FOUND,
            )
            ipc_client.send_message(response)
            return

        # 将消息转换为 Message 对象并放入队列
        try:
            from broca.session.models import Message, MessageRole, MessageType

            user_message = Message(
                message_type=MessageType.USER_MESSAGE,
                role=MessageRole.USER,
                data=message_data,
                sender_id=msg.payload.get("sender_id", "web"),
                receiver_id=agent_id,
                session_id=msg.session_id,
            )
            await target_agent.message_queue.put(user_message)
            logger.info("Dispatched message to agent %s", agent_id)

            response = create_ipc_message(
                IPCMessageType.RESPONSE,
                msg.session_id,
                payload={"message": "Message dispatched"},
                status=IPCStatusCode.SUCCESS,
            )
            ipc_client.send_message(response)
        except Exception as e:
            logger.error("Failed to dispatch message: %s", e)
            response = create_ipc_message(
                IPCMessageType.RESPONSE,
                msg.session_id,
                payload={"error": str(e)},
                status=IPCStatusCode.ERROR,
            )
            ipc_client.send_message(response)


async def ipc_listener_loop(ipc_client: IPCClient) -> None:
    """
    IPC 命令监听循环

    在 executor 中运行阻塞的 receive_message，接收到命令后处理。

    Args:
        ipc_client: IPC 客户端
    """
    global _running
    loop = asyncio.get_event_loop()

    while _running:
        try:
            # 在 executor 中执行阻塞的 receive（带超时）
            msg = await loop.run_in_executor(None, ipc_client.receive_message, 1.0)
            if msg:
                await handle_ipc_command(msg, ipc_client)
        except IPCConnectionError as e:
            logger.warning("IPC connection lost: %s", e)
            break
        except Exception as e:
            logger.error("IPC listener error: %s", e)
            await asyncio.sleep(1)


async def agent_monitor_loop() -> None:
    """
    Agent 监控循环

    检查 Agent 是否仍在运行，如果全部停止则触发 runner 关闭。
    """
    global _running, _agents
    while _running:
        all_stopped = True
        for agent in _agents:
            if hasattr(agent, "running") and agent.running:
                all_stopped = False
                break

        if all_stopped and len(_agents) > 0:
            logger.info("All agents have stopped, shutting down runner")
            _running = False
            break

        await asyncio.sleep(2)


# 记录启动时间
_start_time: float = 0.0


async def async_main(args: argparse.Namespace, ipc_client: IPCClient) -> None:
    """
    异步主逻辑

    Args:
        args: 命令行参数
        ipc_client: IPC 客户端
    """
    global _running, _agent_factory, _agents, _session_manager, _start_time
    _running = True
    _start_time = time.time()

    try:
        # === 1. 初始化数据库连接 ===
        # 数据库连接由 SessionManager / Service 内部管理（SQLModel）
        logger.info("Initializing session: %s", args.session_id)

        # === 2. 创建 AgentFactory 并恢复 Agent ===
        _agent_factory = AgentFactory()
        _agents = await _agent_factory.restore_agents_from_session(args.session_id)

        if not _agents:
            error_msg = "No agents restored from session"
            logger.error(error_msg)
            ipc_client.send_message(
                create_ipc_message(
                    IPCMessageType.EVT_ERROR,
                    args.session_id,
                    payload={"error": error_msg},
                    status=IPCStatusCode.ERROR,
                )
            )
            return

        # 获取 session_manager 引用
        _session_manager = _agents[0].session_manager

        logger.info(
            "Restored %d agents for session %s",
            len(_agents),
            args.session_id,
        )

        # === 3. 并行连接 Agent 到 SocketIO Server ===
        connect_results = await asyncio.gather(*[
            agent.connect() for agent in _agents
        ], return_exceptions=True)
        for i, result in enumerate(connect_results):
            if isinstance(result, Exception):
                logger.error("Agent %s connect failed: %s", _agents[i].agent_id, result)
            else:
                logger.info("Agent %s connected to SocketIO", _agents[i].agent_id)

        # === 4. 启动 Agent 消息循环 ===
        agent_tasks = []
        for agent in _agents:
            task = asyncio.create_task(agent.start())
            agent_tasks.append(task)
            logger.info("Agent %s message loop started", agent.agent_id)

        # === 5. 发送 READY 事件 ===
        ready_msg = create_ipc_message(
            IPCMessageType.EVT_READY,
            args.session_id,
            payload={
                "agent_count": len(_agents),
                "agent_ids": [a.agent_id for a in _agents],
                "agent_names": [a.name for a in _agents],
            },
        )
        ipc_client.send_message(ready_msg)
        logger.info("Runner READY signal sent")

        # === 6. 并发运行：心跳 + IPC监听 + Agent监控 ===
        await asyncio.gather(
            heartbeat_loop(ipc_client),
            ipc_listener_loop(ipc_client),
            agent_monitor_loop(),
            return_exceptions=True,
        )

        # === 7. 等待 Agent 任务结束 ===
        logger.info("Shutting down agents...")
        for agent in _agents:
            agent.stop()

        # 给 Agent 一点时间完成收尾
        if agent_tasks:
            done, pending = await asyncio.wait(agent_tasks, timeout=5.0)
            for task in pending:
                task.cancel()

        # === 8. 断开 Agent 连接 ===
        for agent in _agents:
            try:
                await agent.disconnect()
            except Exception as e:
                logger.warning("Agent %s disconnect error: %s", agent.agent_id, e)

        # === 9. 发送关闭完成事件 ===
        try:
            shutdown_msg = create_ipc_message(
                IPCMessageType.EVT_SHUTDOWN_COMPLETE,
                args.session_id,
                payload={"message": "Runner shutdown complete"},
            )
            ipc_client.send_message(shutdown_msg)
        except Exception:
            pass

        logger.info("Runner shutdown complete")

    except Exception as e:
        logger.error("Runner fatal error: %s", e, exc_info=True)
        try:
            ipc_client.send_message(
                create_ipc_message(
                    IPCMessageType.EVT_ERROR,
                    args.session_id,
                    payload={"error": str(e)},
                    status=IPCStatusCode.ERROR,
                )
            )
        except Exception:
            pass
        raise


def main() -> None:
    """Runner 进程入口"""
    args = parse_args()
    setup_logging(args.log_file, args.log_level)

    logger.info(
        "Session Runner starting - session_id=%s workspace=%s provider=%s model=%s",
        args.session_id,
        args.workspace,
        args.provider,
        args.model,
    )

    # 初始化 IPC 客户端
    ipc_client = IPCClient(args.session_id)
    try:
        ipc_client.connect()
        logger.info("IPC client connected")
    except IPCConnectionError as e:
        logger.error("Failed to connect IPC: %s", e)
        sys.exit(1)

    # 注册信号处理
    def _signal_handler(signum, frame):
        global _running
        logger.info("Received signal %s, shutting down...", signum)
        _running = False

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        asyncio.run(async_main(args, ipc_client))
    except KeyboardInterrupt:
        logger.info("Runner interrupted by user")
    except Exception as e:
        logger.error("Runner crashed: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        ipc_client.close()
        logger.info("Session Runner exited")


if __name__ == "__main__":
    main()
