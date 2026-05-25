"""
Session Runner 编排入口模块

在 Runner 子进程中执行编排，与现有 Agent 消息循环集成。
编排器直接调用 Agent（本地方法调用），零跨进程延迟。
编排进度通过 IPC 通道推送到 Web 进程。
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from broca.logging_config import get_logger
from broca.orchestration.blackboard import Blackboard, set_blackboard, remove_blackboard
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
from broca.session_runner.models import IPCMessageType, IPCStatusCode

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
    ) -> OrchestrationResult:
        """
        运行编排

        Args:
            crew_config: Crew 配置
            agent_refs: Agent 引用字典 {name: agent}

        Returns:
            编排执行结果
        """
        self._crew_id = crew_config.name
        self._running = True

        # 1. 创建 Blackboard 并注册
        blackboard = Blackboard()
        if crew_config.blackboard:
            initial = crew_config.blackboard.get("initial_entries", [])
            for entry in initial:
                if isinstance(entry, dict):
                    key = entry.get("key")
                    value = entry.get("value")
                    if key is not None:
                        await blackboard.set(key, value, producer="init")

        set_blackboard(self.session_id, blackboard)

        # 2. 创建 CrewContext 并注册 Agent
        context = CrewContext(
            crew_config=crew_config,
            blackboard=blackboard,
            agent_factory=self.agent_factory,
            session_manager=self.session_manager,
        )
        for name, agent in agent_refs.items():
            context.register_agent(name, agent)

        # 3. 创建编排器
        self._orchestrator = OrchestratorFactory.create(crew_config, context)

        # 4. 发送编排开始事件
        self._send_crew_event(IPCMessageType.EVT_CREW_START, {
            "crew_id": self._crew_id,
            "orchestrator_type": crew_config.orchestrator.type.value,
            "agent_count": len(agent_refs),
        })

        # 5. 执行编排（在后台任务中运行，同时推送进度）
        try:
            self._task = asyncio.create_task(self._run_with_progress())

            result = await self._task

            # 6. 发送完成事件
            if result.status == ExecutionStatus.COMPLETED:
                self._send_crew_event(IPCMessageType.EVT_CREW_COMPLETE, {
                    "crew_id": self._crew_id,
                    "status": result.status.value,
                    "phases": [p.to_dict() for p in result.phases],
                    "final_output": result.final_output,
                    "progress": result.progress,
                })
            else:
                self._send_crew_event(IPCMessageType.EVT_CREW_ERROR, {
                    "crew_id": self._crew_id,
                    "status": result.status.value,
                    "error": result.error,
                    "phases": [p.to_dict() for p in result.phases],
                })

            return result

        except asyncio.CancelledError:
            logger.info(f"Crew '{self._crew_id}' execution cancelled")
            if self._orchestrator:
                await self._orchestrator.abort()

            self._send_crew_event(IPCMessageType.EVT_CREW_ERROR, {
                "crew_id": self._crew_id,
                "status": "aborted",
                "error": "Execution cancelled",
            })
            raise

        except Exception as e:
            logger.error(f"Crew '{self._crew_id}' execution error: {e}")
            self._send_crew_event(IPCMessageType.EVT_CREW_ERROR, {
                "crew_id": self._crew_id,
                "status": "error",
                "error": str(e),
            })
            raise

        finally:
            self._running = False
            remove_blackboard(self.session_id)
            self._orchestrator = None
            self._task = None

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
            self._send_crew_event(IPCMessageType.EVT_CREW_PROGRESS, {
                "crew_id": self._crew_id,
                "progress": result.progress,
                "current_phase": result.current_phase,
                "phases_completed": sum(
                    1 for p in result.phases
                    if p.status.value in ("completed", "failed")
                ),
                "phases_total": len(result.phases),
                "status": result.status.value,
            })

            return result
        finally:
            unsubscribe()

    def _on_blackboard_event(self, event) -> None:
        """黑板事件回调（用于实时进度推送）"""
        logger.debug(f"Blackboard event: {event.key} ({event.event_type.value})")

    def _send_crew_event(self, event_type: IPCMessageType, payload: Dict[str, Any]) -> None:
        """发送编排事件到 Web 进程"""
        try:
            msg = create_ipc_message(
                event_type,
                self.session_id,
                payload=payload,
            )
            self.ipc_client.send_message(msg)
        except Exception as e:
            logger.warning(f"Failed to send crew event: {e}")

    async def abort_crew(self) -> bool:
        """中止当前编排"""
        if self._orchestrator:
            await self._orchestrator.abort()
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
