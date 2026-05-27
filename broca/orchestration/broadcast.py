"""
Broadcast 广播拓扑编排器

同一任务分发给多个 Agent 独立处理（并行），最后聚合结果。

拓扑特征：
- Dispatcher Agent 将任务分解为并行子任务
- 并行执行所有子任务
- Aggregator Agent 汇总整合结果
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from broca.logging_config import get_logger
from broca.orchestration.crew import AgentRole, CrewConfig
from broca.orchestration.orchestrator import (
    CrewContext,
    ExecutionStatus,
    OrchestrationResult,
    Orchestrator,
    PhaseResult,
    PhaseStatus,
)

logger = get_logger(__name__)


class BroadcastOrchestrator(Orchestrator):
    """
    广播拓扑编排器

    Dispatcher 分解任务 → Worker 并行执行 → Aggregator 汇总。
    """

    def __init__(self, crew_config: CrewConfig, context: Optional[CrewContext] = None):
        super().__init__(crew_config, context)

    @property
    def dispatcher(self) -> Optional[Any]:
        """获取 Dispatcher Agent"""
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.DISPATCHER:
                return self.context.get_agent(agent_cfg.name)
        return None

    @property
    def aggregator(self) -> Optional[Any]:
        """获取 Aggregator Agent"""
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.AGGREGATOR:
                return self.context.get_agent(agent_cfg.name)
        return None

    @property
    def workers(self) -> List[Dict[str, Any]]:
        """获取所有 Worker"""
        workers = []
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.WORKER:
                agent = self.context.get_agent(agent_cfg.name)
                if agent:
                    workers.append({"agent": agent, "config": agent_cfg})
        return workers

    async def run(self) -> OrchestrationResult:
        """执行广播编排"""
        crew_id = self.crew.name
        result = OrchestrationResult(
            crew_id=crew_id,
            status=ExecutionStatus.RUNNING,
            phases=[],
        )

        task = await self.context.blackboard.get("task", "")
        if not task:
            result.status = ExecutionStatus.FAILED
            result.error = "No 'task' found in Blackboard"
            return result

        try:
            # Phase 1: Dispatcher 分解任务
            phase1 = PhaseResult(
                name="dispatch",
                status=PhaseStatus.RUNNING,
                agents=[self.crew.agents[0].name] if self.crew.agents else [],
                started_at=datetime.now(timezone.utc),
            )
            result.phases.append(phase1)

            sub_tasks = await self._dispatch(task)
            await self.context.blackboard.set("sub_tasks", sub_tasks, producer="dispatcher")

            phase1.status = PhaseStatus.COMPLETED
            self.notify_progress(result.phases, 3)
            phase1.output = {"sub_tasks_count": len(sub_tasks)}
            phase1.completed_at = datetime.now(timezone.utc)

            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.completed_at = datetime.now(timezone.utc)
                return result

            # Phase 2: Worker 并行执行
            phase2 = PhaseResult(
                name="parallel_execution",
                status=PhaseStatus.RUNNING,
                agents=[w["config"].name for w in self.workers],
                started_at=datetime.now(timezone.utc),
            )
            result.phases.append(phase2)

            worker_results = await self._execute_workers(sub_tasks)
            await self.context.blackboard.set(
                "worker_results", worker_results, producer="workers"
            )

            phase2.status = PhaseStatus.COMPLETED
            self.notify_progress(result.phases, 3)
            phase2.output = {"results_count": len(worker_results)}
            phase2.completed_at = datetime.now(timezone.utc)

            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.completed_at = datetime.now(timezone.utc)
                return result

            # Phase 3: Aggregator 汇总
            phase3 = PhaseResult(
                name="aggregation",
                status=PhaseStatus.RUNNING,
                agents=[self.aggregator_config_name()] if self.aggregator else [],
                started_at=datetime.now(timezone.utc),
            )
            result.phases.append(phase3)

            aggregated = await self._aggregate(task, worker_results)
            await self.context.blackboard.set(
                "aggregated_result", aggregated, producer="aggregator"
            )

            phase3.status = PhaseStatus.COMPLETED
            self.notify_progress(result.phases, 3)
            phase3.output = {"aggregated": True}
            phase3.completed_at = datetime.now(timezone.utc)

            result.status = ExecutionStatus.COMPLETED

        except Exception as e:
            logger.error(f"Broadcast execution failed: {e}")
            result.status = ExecutionStatus.FAILED
            result.error = str(e)

        result.completed_at = datetime.now(timezone.utc)
        result.blackboard_snapshot = await self.context.blackboard.to_dict()
        result.final_output = {
            "task": task,
            "worker_results": worker_results if 'worker_results' in dir() else {},
            "aggregated": aggregated if 'aggregated' in dir() else None,
        }

        return result

    def aggregator_config_name(self) -> str:
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.AGGREGATOR:
                return agent_cfg.name
        return "aggregator"

    async def _dispatch(self, task: str) -> List[Dict[str, str]]:
        """分解任务为并行子任务"""
        worker_count = max(len(self.workers), 1)
        sub_tasks = []

        for i, worker in enumerate(self.workers):
            sub_tasks.append({
                "agent": worker["config"].name,
                "task": f"Perspective {i + 1}/{worker_count}: Analyze the following from your unique angle.\n\n{task}",
                "index": i,
            })

        return sub_tasks

    async def _execute_workers(
        self, sub_tasks: List[Dict[str, str]]
    ) -> Dict[str, str]:
        """并行执行所有 Worker 任务"""

        async def execute_single(sub_task: Dict[str, str]) -> tuple:
            agent_name = sub_task["agent"]
            task_desc = sub_task["task"]
            agent = self.context.get_agent(agent_name)

            if agent is None:
                return (agent_name, f"Error: Agent '{agent_name}' not found")

            try:
                from broca.session import MessageProtocol
                from broca.execution_engine import ExecutionStatus

                trigger_message = MessageProtocol.create_user_message(content=task_desc)
                execution_result = await agent.run(trigger_message, from_agent=True)

                if execution_result.status == ExecutionStatus.COMPLETED:
                    message = agent.context.get_latest_assistant_message()
                    return (agent_name, message or "(no output)")
                else:
                    return (agent_name, f"Error: {execution_result.error}")
            except Exception as e:
                return (agent_name, f"Error: {e}")

        results = await asyncio.gather(*[execute_single(t) for t in sub_tasks])
        return dict(results)

    async def _aggregate(
        self, task: str, worker_results: Dict[str, str]
    ) -> Dict[str, Any]:
        """汇总 Worker 结果"""
        return {
            "task": task,
            "worker_count": len(worker_results),
            "results": worker_results,
            "summary": f"Aggregated {len(worker_results)} worker results.",
        }
