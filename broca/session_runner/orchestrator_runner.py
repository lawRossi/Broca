"""
Session Runner 编排入口模块

在 Runner 子进程中执行编排，与现有 Agent 消息循环集成。
编排器直接调用 Agent（本地方法调用），零跨进程延迟。
编排进度通过 IPC 通道推送到 Web 进程。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from broca.logging_config import get_logger
from broca.orchestration.blackboard import Blackboard
from broca.orchestration.crew import CrewConfig
from broca.orchestration.orchestrator import (
    CrewContext,
    ExecutionStatus,
    OrchestrationResult,
    Orchestrator,
    OrchestratorFactory,
)
from broca.session_runner.ipc import (
    IPCClient,
    create_ipc_message,
)
from broca.session_runner.models import IPCMessageType
from broca.tools.blackboard import remove_blackboard, set_blackboard

logger = get_logger(__name__)


class CrewOrchestratorRunner:
    """
    编排运行器

    在 Runner 进程中管理编排的执行生命周期。
    编排器直接调用 Agent，使用 IPC 推送进度。
    """

    def __init__(
        self,
        session_id: str,
        ipc_client: IPCClient,
        agent_factory: Any = None,
        session_manager: Any = None,
    ):
        self.session_id = session_id
        self.ipc_client = ipc_client
        self.agent_factory = agent_factory
        self.session_manager = session_manager

        self._orchestrator: Optional[Orchestrator] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._crew_id: Optional[str] = None
        self._execution_id: Optional[str] = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def crew_id(self) -> Optional[str]:
        return self._crew_id

    async def run_crew(
        self,
        crew_config: CrewConfig,
        agent_refs: Dict[str, Any],
        execution_id: Optional[str] = None,
    ) -> OrchestrationResult:
        """
        运行编排

        Args:
            crew_config: Crew 配置
            agent_refs: Agent 引用字典 {name: agent}
            execution_id: 执行 ID（用于事件关联）

        Returns:
            编排执行结果
        """
        self._crew_id = crew_config.name
        self._execution_id = execution_id
        self._running = True

        # 设置 execution_id，后续 agent 保存消息时自动注入
        if self.session_manager and execution_id:
            self.session_manager.current_execution_id = execution_id

        # 1. 创建 Blackboard 并注册
        namespace = crew_config.name
        blackboard = Blackboard()
        if crew_config.blackboard:
            initial = crew_config.blackboard.get("initial_entries", [])
            for entry in initial:
                if isinstance(entry, dict):
                    key = entry.get("key")
                    value = entry.get("value")
                    if key is not None:
                        # 用 namespace 前缀存储，使 Agent 通过工具能正确读到
                        await blackboard.set(
                            f"{namespace}.{key}", value, producer="init"
                        )

        set_blackboard(self.session_id, self._execution_id, blackboard)

        # 2. 创建 CrewContext 并注册 Agent
        context = CrewContext(
            crew_config=crew_config,
            blackboard=blackboard,
            agent_factory=self.agent_factory,
            session_manager=self.session_manager,
        )
        for name, agent in agent_refs.items():
            context.register_agent(name, agent)
            # 注入 execution_id，使黑板工具能正确定位黑板实例
            if hasattr(agent, "execution_engine") and self._execution_id:
                agent.execution_engine.execution_id = self._execution_id

        # 2.5 根据 use_history 配置清空 Agent 上下文历史
        #    默认清历史，让 agent 每次执行从干净状态开始
        for agent_cfg in crew_config.agents:
            agent = agent_refs.get(agent_cfg.name)
            if agent and not agent_cfg.use_history:
                agent.context._init_history()
                logger.info(
                    f"Cleared history for agent '{agent_cfg.name}' "
                    f"(use_history={agent_cfg.use_history})"
                )

        # 3. 创建编排器
        self._orchestrator = OrchestratorFactory.create(crew_config, context)
        # 设置进度回调，阶段完成时推送实时进度
        self._orchestrator.progress_callback = self._on_phase_complete

        # 4. 发送编排开始事件
        self._send_crew_event(
            IPCMessageType.EVT_CREW_START,
            {
                "crew_id": self._crew_id,
                "orchestrator_type": crew_config.orchestrator.type.value,
                "agent_count": len(agent_refs),
            },
        )

        # 5. 执行编排（在后台任务中运行，同时推送进度）
        try:
            self._task = asyncio.create_task(self._run_with_progress())

            result = await self._task

            # 6. 发送完成事件
            if result.status == ExecutionStatus.COMPLETED:
                self._send_crew_event(
                    IPCMessageType.EVT_CREW_COMPLETE,
                    {
                        "crew_id": self._crew_id,
                        "execution_id": self._execution_id,
                        "status": result.status.value,
                        "phases": [p.to_dict() for p in result.phases],
                        "final_output": result.final_output,
                        "progress": result.progress,
                    },
                )
            elif result.status == ExecutionStatus.ABORTED:
                self._send_crew_event(
                    IPCMessageType.EVT_CREW_ERROR,
                    {
                        "crew_id": self._crew_id,
                        "execution_id": self._execution_id,
                        "status": "aborted",
                        "error": result.error or "Execution aborted by user",
                        "phases": [p.to_dict() for p in result.phases],
                    },
                )
            else:
                self._send_crew_event(
                    IPCMessageType.EVT_CREW_ERROR,
                    {
                        "crew_id": self._crew_id,
                        "execution_id": self._execution_id,
                        "status": result.status.value,
                        "error": result.error,
                        "phases": [p.to_dict() for p in result.phases],
                    },
                )

            return result

        except asyncio.CancelledError:
            logger.info(f"Crew '{self._crew_id}' execution cancelled")
            if self._orchestrator:
                await self._orchestrator.abort()

            self._send_crew_event(
                IPCMessageType.EVT_CREW_ERROR,
                {
                    "crew_id": self._crew_id,
                    "status": "aborted",
                    "error": "Execution cancelled",
                },
            )
            raise

        except Exception as e:
            logger.error(f"Crew '{self._crew_id}' execution error: {e}")
            self._send_crew_event(
                IPCMessageType.EVT_CREW_ERROR,
                {
                    "crew_id": self._crew_id,
                    "status": "error",
                    "error": str(e),
                },
            )
            raise

        finally:
            self._running = False
            remove_blackboard(self.session_id, self._execution_id)
            self._orchestrator = None
            self._task = None
            # 清除 execution_id
            if self.session_manager:
                self.session_manager.current_execution_id = None

    async def _run_with_progress(self) -> OrchestrationResult:
        """带进度推送的编排执行"""
        if not self._orchestrator:
            raise RuntimeError("Orchestrator not initialized")

        # 订阅黑板事件以推送进度
        unsubscribe = self._orchestrator.context.blackboard.subscribe(
            self._on_blackboard_event
        )

        try:
            result = await self._orchestrator.run()

            # 推送最终进度
            self._send_crew_event(
                IPCMessageType.EVT_CREW_PROGRESS,
                {
                    "crew_id": self._crew_id,
                    "progress": result.progress,
                    "current_phase": result.current_phase,
                    "phases_completed": sum(
                        1
                        for p in result.phases
                        if p.status.value in ("completed", "failed")
                    ),
                    "phases_total": len(result.phases),
                    "status": result.status.value,
                },
            )

            return result
        finally:
            unsubscribe()

    def _on_phase_complete(self, phases: List[Any], total: int) -> None:
        """阶段完成回调：计算进度并推送"""
        completed = sum(1 for p in phases if p.status.value in ("completed", "failed"))
        progress = completed / total if total > 0 else 0

        self._send_crew_event(
            IPCMessageType.EVT_CREW_PROGRESS,
            {
                "crew_id": self._crew_id,
                "execution_id": self._execution_id,
                "progress": progress,
                "current_phase": phases[-1].name if phases else "",
                "phases": [p.to_dict() for p in phases],
                "phases_completed": completed,
                "phases_total": total,
                "status": "running",
            },
        )

    def _on_blackboard_event(self, event) -> None:
        """黑板事件回调（用于实时进度推送）"""
        logger.debug(f"Blackboard event: {event.key} ({event.event_type.value})")

        # 当一轮讨论完成时，推送进度
        if event.key.startswith("round_") and event.event_type.value == "created":
            import re

            match = re.match(r"round_(\d+)", event.key)
            if match:
                current_round = int(match.group(1))
                max_rounds = (
                    self._orchestrator.crew.orchestrator.max_rounds
                    if hasattr(self._orchestrator, "crew")
                    else 1
                )
                progress = current_round / max_rounds
                self._send_crew_event(
                    IPCMessageType.EVT_CREW_PROGRESS,
                    {
                        "crew_id": self._crew_id,
                        "execution_id": self._execution_id,
                        "progress": progress,
                        "current_phase": f"round_{current_round}",
                        "phases_completed": current_round,
                        "phases_total": max_rounds,
                        "status": "running",
                    },
                )

    def _send_crew_event(
        self, event_type: IPCMessageType, payload: Dict[str, Any]
    ) -> None:
        """发送编排事件到 Web 进程"""
        try:
            # 始终携带 execution_id 以便 Web 进程关联执行记录
            if self._execution_id and "execution_id" not in payload:
                payload["execution_id"] = self._execution_id
            msg = create_ipc_message(
                event_type,
                self.session_id,
                payload=payload,
            )
            self.ipc_client.send_message(msg)
        except Exception as e:
            logger.warning(f"Failed to send crew event: {e}")

    async def abort_crew(self) -> bool:
        """中止当前编排

        注意：不依赖 task.cancel() 来中断执行，因为 CancelledError 会被
        execution_engine 捕获并转换为普通结果，无法可靠传播到 run_crew()。
        改用 _aborted 标志，由编排器在步骤边界检查并优雅停止。
        """
        if self._orchestrator:
            await self._orchestrator.abort()
            # 如果有正在执行的任务，取消它以加速停止（CancelledError 会被
            # execution_engine 捕获并转换为 ABORTED 状态，编排器据此中止）
            if self._task and not self._task.done():
                self._task.cancel()
            logger.info(f"Crew '{self._crew_id}' aborted by user")
            return True
        return False

    async def get_crew_status(self) -> Dict[str, Any]:
        """获取编排状态"""
        if not self._orchestrator:
            return {"running": False, "crew_id": self._crew_id}

        return {
            "running": self._running,
            "crew_id": self._crew_id,
            "orchestrator_type": self._orchestrator.orchestrator_type.value,
            "is_aborted": self._orchestrator.is_aborted,
        }
