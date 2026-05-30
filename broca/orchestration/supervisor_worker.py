"""
Supervisor-Worker 主管-工人拓扑编排器

一个 Supervisor Agent 负责将目标分解为子任务（通过 task_management 工具）、
委派给多个 Worker Agent 并行执行（Worker 自主从黑板拉取任务）、
质量检查（LLM 评估）、结果汇总（LLM 合成）。支持多轮迭代优化。

拓扑特征：
- Supervisor 通过工具创建子任务并记录到黑板
- Worker 自主从黑板拉取任务详情并执行
- Supervisor 质量检查（LLM 评估）
- 支持多轮迭代优化
- 最终结果汇总合成（LLM 合成）
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from broca.logging_config import get_logger
from broca.orchestration.crew import AgentRole, CrewConfig
from broca.orchestration.orchestrator import (
    CrewContext,
    ExecutionStatus,
    OrchestrationResult,
    Orchestrator,
    OrchestrationStopRequest,
    PhaseResult,
    PhaseStatus,
    execute_agents_in_parallel,
    check_blackboard_for_stop,
)
from broca.orchestration.prompt_loader import PromptLoader

logger = get_logger(__name__)


class SupervisorWorkerOrchestrator(Orchestrator):
    """
    主管-工人拓扑编排器

    Supervisor Agent 通过工具创建子任务 → Worker 自主拉取并执行 →
    Supervisor LLM 质量检查 → 达标则 LLM 合成最终结果。
    支持多轮迭代优化。
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
            a_cfg.name
            for a_cfg in self.crew.agents
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

        accumulated_results: Dict[str, Any] = {}

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
                # ═══════════════════════════════════════
                # Phase A: Supervisor 创建任务
                # ═══════════════════════════════════════
                await self._generate_plan(attempt, objective, max_rounds)

                # 从黑板读取任务分配
                sub_tasks = await self._read_task_assignments()

                # ═══════════════════════════════════════
                # Phase B: Worker 并行执行
                # ═══════════════════════════════════════
                worker_results = await self._execute_workers(sub_tasks)
                accumulated_results[f"iteration_{attempt + 1}"] = worker_results

                await self.context.blackboard.set(
                    f"worker_results_iteration_{attempt + 1}",
                    worker_results,
                    producer="supervisor",
                )

                # ═══════════════════════════════════════
                # Phase C: Supervisor 质量检查
                # ═══════════════════════════════════════
                is_acceptable = await self._quality_check(
                    objective, worker_results, attempt, max_rounds
                )

                phase.output = {
                    "worker_results": worker_results,
                    "is_acceptable": is_acceptable,
                }
                phase.status = PhaseStatus.COMPLETED
                self.notify_progress(result.phases, max_rounds)
                phase.completed_at = datetime.now(timezone.utc)

                if is_acceptable:
                    if self._check_aborted():
                        phase.status = PhaseStatus.FAILED
                        phase.error = "Execution aborted"
                        phase.completed_at = datetime.now(timezone.utc)
                        result.status = ExecutionStatus.ABORTED
                        result.error = "Aborted after acceptable iteration"
                        break

                    # 合成最终结果
                    synthesis = await self._synthesize(objective, accumulated_results)
                    result.status = ExecutionStatus.COMPLETED
                    result.final_output = {
                        "iterations_completed": attempt + 1,
                        "synthesis": synthesis,
                        "accumulated": accumulated_results,
                    }
                    break

            except OrchestrationStopRequest as stop_req:
                logger.warning(
                    f"Supervisor-Worker iteration {attempt + 1} stop requested: "
                    f"{stop_req}"
                )
                phase.status = PhaseStatus.FAILED
                phase.error = str(stop_req)
                phase.completed_at = datetime.now(timezone.utc)
                await self.abort()
                result.status = ExecutionStatus.ABORTED
                result.error = str(stop_req)
                break

            except Exception as e:
                logger.error(
                    f"Supervisor-Worker iteration {attempt + 1} failed: {e}"
                )
                phase.status = PhaseStatus.FAILED
                phase.error = str(e)
                phase.completed_at = datetime.now(timezone.utc)

                if self._check_aborted():
                    result.status = ExecutionStatus.ABORTED
                    result.error = f"Aborted during iteration {attempt + 1}"
                    break

                if attempt == max_rounds - 1:
                    result.status = ExecutionStatus.FAILED
                    result.error = (
                        f"All {max_rounds} iterations failed. Last error: {e}"
                    )
                    break
                continue

        # 所有轮次用完仍未达标
        if result.status == ExecutionStatus.RUNNING:
            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.error = "Aborted during execution"
            else:
                synthesis = await self._synthesize(objective, accumulated_results)
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

    # ═══════════════════════════════════════════════
    # Phase A: Supervisor 创建任务
    # ═══════════════════════════════════════════════

    async def _generate_plan(
        self, attempt: int, objective: str, max_rounds: int
    ) -> None:
        """
        Supervisor Agent 通过 task_management 工具创建子任务，
        并将 {worker_name: task_id} 写入黑板 key `task_assignments`。
        """
        supervisor_agent = self.supervisor
        if supervisor_agent is None:
            raise RuntimeError(
                "No Supervisor Agent found. Supervisor-Worker requires "
                "a supervisor agent (role=supervisor)."
            )

        # 首轮与后续轮次提示略有不同
        prev_summary = ""
        if attempt > 0:
            prev_results = await self.context.blackboard.get(
                f"worker_results_iteration_{attempt}", {}
            )
            prev_summary = str(prev_results)[:500]

        prompt = PromptLoader.render(
            "supervisor_worker",
            "supervisor_plan.j2",
            objective=objective,
            workers=[{"name": w} for w in self.worker_names],
            worker_count=len(self.worker_names),
            previous_summary=prev_summary,
        )

        from broca.session import MessageProtocol
        from broca.execution_engine import ExecutionStatus as ES

        trigger_message = MessageProtocol.create_user_message(content=prompt)
        exec_result = await supervisor_agent.run(trigger_message, from_agent=True)

        if exec_result.status != ES.COMPLETED:
            raise RuntimeError(f"Supervisor Agent failed: {exec_result.error}")

    async def _read_task_assignments(self) -> List[Dict[str, str]]:
        """从黑板读取 Supervisor 写入的任务分配"""
        assignments = await self.context.blackboard.get("task_assignments")
        if not assignments or not isinstance(assignments, dict):
            raise RuntimeError(
                "Supervisor completed but no task assignments found "
                "in blackboard key 'task_assignments'"
            )

        sub_tasks = []
        for worker_name in self.worker_names:
            task_id = assignments.get(worker_name)
            if task_id:
                sub_tasks.append({"agent": worker_name, "task_id": task_id})
            else:
                logger.warning(
                    f"Worker '{worker_name}' has no task assignment"
                )
        return sub_tasks

    # ═══════════════════════════════════════════════
    # Phase B: Worker 并行执行
    # ═══════════════════════════════════════════════

    async def _execute_workers(
        self, sub_tasks: List[Dict[str, str]]
    ) -> Dict[str, str]:
        """
        Worker 通过黑板 + task_management 自主拉取任务并执行。
        """
        tasks = []
        for st in sub_tasks:
            worker_prompt = PromptLoader.render(
                "supervisor_worker",
                "worker_prompt.j2",
                agent_name=st["agent"],
            )
            tasks.append((st["agent"], worker_prompt))
        return await execute_agents_in_parallel(self.context, tasks)

    # ═══════════════════════════════════════════════
    # Phase C: Supervisor 质量检查
    # ═══════════════════════════════════════════════

    async def _quality_check(
        self,
        objective: str,
        worker_results: Dict[str, str],
        attempt: int,
        max_rounds: int,
    ) -> bool:
        """
        Supervisor Agent (LLM) 评估 Worker 结果质量。
        最后一轮自动通过。
        """
        if attempt >= max_rounds - 1:
            return True

        supervisor_agent = self.supervisor
        if supervisor_agent is None:
            # 无 Supervisor 时简单检查错误
            return not any(
                r.startswith("Error:") for r in worker_results.values()
            )

        prompt = PromptLoader.render(
            "supervisor_worker",
            "supervisor_quality_check.j2",
            objective=objective,
            worker_results=worker_results,
            attempt=attempt + 1,
            max_rounds=max_rounds,
        )

        from broca.session import MessageProtocol
        from broca.execution_engine import ExecutionStatus as ES

        trigger_message = MessageProtocol.create_user_message(content=prompt)
        exec_result = await supervisor_agent.run(trigger_message, from_agent=True)

        if exec_result.status != ES.COMPLETED:
            logger.warning(
                f"Quality check failed: {exec_result.error}, "
                f"assuming acceptable"
            )
            return True

        response = (
            supervisor_agent.context.get_latest_assistant_message() or ""
        ).strip().upper()

        return "PASS" in response

    # ═══════════════════════════════════════════════
    # Synthesis: Supervisor 合成最终结果
    # ═══════════════════════════════════════════════

    async def _synthesize(
        self,
        objective: str,
        accumulated_results: Dict[str, Any],
    ) -> str:
        """
        Supervisor Agent (LLM) 综合所有 Worker 结果生成最终报告。
        """
        supervisor_agent = self.supervisor
        if supervisor_agent is None:
            # 无 Supervisor 时简单拼接
            parts = []
            for iter_name, results in accumulated_results.items():
                parts.append(f"=== {iter_name} ===")
                for worker_name, output in results.items():
                    parts.append(f"[{worker_name}]:\n{output}")
            return "\n\n".join(parts)

        prompt = PromptLoader.render(
            "supervisor_worker",
            "supervisor_synthesize.j2",
            objective=objective,
            accumulated=accumulated_results,
        )

        from broca.session import MessageProtocol
        from broca.execution_engine import ExecutionStatus as ES

        trigger_message = MessageProtocol.create_user_message(content=prompt)
        exec_result = await supervisor_agent.run(trigger_message, from_agent=True)

        if exec_result.status == ES.COMPLETED:
            return (
                supervisor_agent.context.get_latest_assistant_message()
                or "Synthesis completed (no output)"
            )
        else:
            logger.warning(
                f"Synthesis failed: {exec_result.error}, "
                f"falling back to concatenation"
            )
            parts = []
            for iter_name, results in accumulated_results.items():
                parts.append(f"=== {iter_name} ===")
                for worker_name, output in results.items():
                    parts.append(f"[{worker_name}]:\n{output}")
            return "\n\n".join(parts)
