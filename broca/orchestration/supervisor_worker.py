"""
Supervisor-Worker 主管-工人拓扑编排器

一个 Supervisor Agent 负责分解任务、委派给多个 Worker Agent 并行执行、
质量检查、结果汇总。支持多轮迭代优化。

拓扑特征：
- Supervisor 计划生成和任务分解
- Worker 并行执行子任务
- Supervisor 质量检查和迭代优化
- 最终结果汇总合成
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
from broca.orchestration.prompt_loader import PromptLoader

logger = get_logger(__name__)


class SupervisorWorkerOrchestrator(Orchestrator):
    """
    主管-工人拓扑编排器

    Supervisor Agent 负责将目标分解为子任务并委派给 Worker，
    然后对结果进行质量检查，支持多轮迭代优化。
    """

    def __init__(self, crew_config: CrewConfig, context: Optional[CrewContext] = None):
        super().__init__(crew_config, context)

    @property
    def supervisor(self) -> Optional[Any]:
        """获取 Supervisor Agent"""
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.SUPERVISOR:
                return self.context.get_agent(agent_cfg.name)
        return None

    @property
    def workers(self) -> List[Any]:
        """获取所有 Worker Agent"""
        workers = []
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.WORKER:
                agent = self.context.get_agent(agent_cfg.name)
                if agent:
                    workers.append(agent)
        return workers

    @property
    def worker_names(self) -> List[str]:
        return [
            a_cfg.name for a_cfg in self.crew.agents
            if a_cfg.role == AgentRole.WORKER
        ]

    async def run(self) -> OrchestrationResult:
        """执行 Supervisor-Worker 编排"""
        crew_id = self.crew.name
        result = OrchestrationResult(
            crew_id=crew_id,
            status=ExecutionStatus.RUNNING,
            phases=[],
        )

        max_rounds = self.crew.orchestrator.max_rounds
        objective = await self.context.blackboard.get("objective", "")

        if not objective:
            result.status = ExecutionStatus.FAILED
            result.error = "No 'objective' found in Blackboard"
            return result

        accumulated_results = {}

        for attempt in range(max_rounds):
            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                break

            phase_name = f"iteration_{attempt + 1}"
            phase = PhaseResult(
                name=phase_name,
                status=PhaseStatus.RUNNING,
                agents=[self.crew.agents[0].name] + self.worker_names,
                started_at=datetime.now(timezone.utc),
            )
            result.phases.append(phase)

            logger.info(
                f"Supervisor-Worker iteration {attempt + 1}/{max_rounds}: "
                f"objective='{objective[:50]}...'"
            )

            try:
                # Phase A: Supervisor 计划生成
                plan = await self._generate_plan(attempt, objective)
                await self.context.blackboard.set(
                    f"plan_iteration_{attempt + 1}",
                    plan,
                    producer="supervisor",
                )

                # Phase B: Worker 并行执行
                worker_results = await self._execute_in_parallel(plan)
                accumulated_results[f"iteration_{attempt + 1}"] = worker_results
                await self.context.blackboard.set(
                    f"worker_results_iteration_{attempt + 1}",
                    worker_results,
                    producer="supervisor",
                )

                # Phase C: Supervisor 质量检查
                is_acceptable = await self._quality_check(worker_results, attempt, max_rounds)

                phase.output = {
                    "plan": plan,
                    "worker_results": worker_results,
                    "is_acceptable": is_acceptable,
                }
                phase.status = PhaseStatus.COMPLETED
                self.notify_progress(result.phases, max_rounds)
                phase.completed_at = datetime.now(timezone.utc)

                if is_acceptable:
                    # 质量达标，但需检查是否已被中止
                    if self._check_aborted():
                        phase.status = PhaseStatus.FAILED
                        phase.error = "Execution aborted"
                        phase.completed_at = datetime.now(timezone.utc)
                        result.status = ExecutionStatus.ABORTED
                        result.error = "Aborted after acceptable iteration"
                        break

                    # 合成最终结果
                    synthesis = await self._synthesize(accumulated_results, final=False)
                    result.status = ExecutionStatus.COMPLETED
                    result.final_output = {
                        "iterations_completed": attempt + 1,
                        "synthesis": synthesis,
                        "accumulated": accumulated_results,
                    }
                    break

            except Exception as e:
                logger.error(f"Supervisor-Worker iteration {attempt + 1} failed: {e}")
                phase.status = PhaseStatus.FAILED
                phase.error = str(e)
                phase.completed_at = datetime.now(timezone.utc)

                # 如果编排已被中止，按中止处理而非失败
                if self._check_aborted():
                    result.status = ExecutionStatus.ABORTED
                    result.error = f"Aborted during iteration {attempt + 1}"
                    break

                if attempt == max_rounds - 1:
                    result.status = ExecutionStatus.FAILED
                    result.error = f"All {max_rounds} iterations failed. Last error: {e}"
                    break
                else:
                    # 继续下一轮迭代
                    continue

        # 如果所有轮次都用完仍未达标，使用当前最佳结果
        if result.status == ExecutionStatus.RUNNING:
            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.error = "Aborted during execution"
            else:
                synthesis = await self._synthesize(accumulated_results, final=True)
                result.status = ExecutionStatus.COMPLETED
                result.final_output = {
                    "iterations_completed": max_rounds,
                    "synthesis": synthesis,
                    "note": "Max rounds reached. Using best available results.",
                    "accumulated": accumulated_results,
                }

        result.completed_at = datetime.now(timezone.utc)
        result.blackboard_snapshot = await self.context.blackboard.to_dict()
        return result

    async def _generate_plan(self, attempt: int, objective: str) -> Dict[str, Any]:
        """
        生成工作计划

        在真实环境中，Supervisor Agent 会调用 LLM 生成计划。
        当前简化实现返回一个基本的任务分配。
        """
        worker_count = len(self.worker_names)

        if attempt == 0:
            # 首轮：生成初始计划
            tasks = []
            for i, w_name in enumerate(self.worker_names):
                task = PromptLoader.render(
                    "supervisor_worker",
                    "generate_plan_initial.j2",
                    index=i,
                    objective=objective,
                )
                tasks.append({
                    "agent": w_name,
                    "task": task,
                })
            return {
                "objective": objective,
                "tasks": tasks,
                "attempt": attempt + 1,
            }
        else:
            # 后续轮次：根据上一轮结果修订计划
            prev_results = await self.context.blackboard.get(
                f"worker_results_iteration_{attempt}", {}
            )
            tasks = []
            for w_name in self.worker_names:
                task = PromptLoader.render(
                    "supervisor_worker",
                    "generate_plan_refine.j2",
                    objective=objective,
                    previous_results_summary=str(prev_results)[:200],
                )
                tasks.append({
                    "agent": w_name,
                    "task": task,
                })
            return {
                "objective": objective,
                "tasks": tasks,
                "previous_results_summary": str(prev_results)[:200],
                "attempt": attempt + 1,
            }

    async def _execute_in_parallel(self, plan: Dict[str, Any]) -> Dict[str, str]:
        """并行执行 Worker 任务"""
        tasks = plan.get("tasks", [])

        async def execute_single(task_def: Dict[str, Any]) -> tuple:
            agent_name = task_def["agent"]
            task_desc = task_def["task"]
            target_agent = self.context.get_agent(agent_name)

            if target_agent is None:
                return (agent_name, f"Error: Agent '{agent_name}' not found")

            try:
                from broca.session import MessageProtocol
                from broca.execution_engine import ExecutionStatus

                trigger_message = MessageProtocol.create_user_message(content=task_desc)
                execution_result = await target_agent.run(trigger_message, from_agent=True)

                if execution_result.status == ExecutionStatus.COMPLETED:
                    message = target_agent.context.get_latest_assistant_message()
                    return (agent_name, message or "Task completed (no output)")
                else:
                    return (agent_name, f"Error: {execution_result.error}")
            except Exception as e:
                logger.error(f"Worker '{agent_name}' execution error: {e}")
                return (agent_name, f"Error: {e}")

        results = await asyncio.gather(*[execute_single(t) for t in tasks])
        return dict(results)

    async def _quality_check(
        self,
        worker_results: Dict[str, str],
        attempt: int,
        max_rounds: int,
    ) -> bool:
        """
        质量检查

        最后一轮自动达标，否则由 Supervisor 判断。
        简化实现：识别是否有明显错误。
        """
        # 最后一轮自动通过
        if attempt >= max_rounds - 1:
            return True

        # 检查是否有错误
        for agent_name, result in worker_results.items():
            if result.startswith("Error:"):
                return False

        return True

    async def _synthesize(
        self,
        accumulated_results: Dict[str, Any],
        final: bool = False,
    ) -> Dict[str, Any]:
        """合成最终结果"""
        return {
            "type": "final" if final else "interim",
            "iterations_completed": len(accumulated_results),
            "summary": f"Synthesized results from {len(accumulated_results)} iteration(s)",
            "detail": accumulated_results,
        }
