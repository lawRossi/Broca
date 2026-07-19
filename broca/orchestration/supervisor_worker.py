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

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from broca.errors import OrchestrationError
from broca.logging_config import get_logger
from broca.orchestration.crew import AgentRole, CrewConfig
from broca.orchestration.orchestrator import (
    CrewContext,
    ExecutionStatus,
    OrchestrationResult,
    OrchestrationStopRequest,
    Orchestrator,
    PhaseResult,
    PhaseStatus,
    execute_agents_in_parallel,
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
        self.namespace = crew_config.name
        self.progress_check_key = "objective_met"
        self.completed_tasks: set[str] = set()

    def _ns(self, key: str) -> str:
        return f"{self.namespace}.{key}" if self.namespace else key

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
            a_cfg.name for a_cfg in self.crew.agents if a_cfg.role == AgentRole.WORKER
        ]

    def _phase_name(self, attempt_index: int) -> str:
        return f"{self.crew.name}_iteration_{attempt_index + 1}"

    async def run(self) -> OrchestrationResult:
        """
        执行 Supervisor-Worker 编排（简化版）

        流程：
        1. 初始计划生成（Supervisor 创建子任务）
        2. 循环执行：
           a. Worker 并行执行
           b. 合并步骤：质量检查 + 计划更新（若不达标则创建新任务）
        """
        crew_id = self.crew.name
        result = OrchestrationResult(
            crew_id=crew_id,
            status=ExecutionStatus.RUNNING,
            phases=[],
        )

        max_rounds = self.crew.orchestrator.max_rounds
        objective = await self.context.blackboard.get(self._ns("objective"), "")

        if not objective:
            result.status = ExecutionStatus.FAILED
            result.error = "No 'objective' found in Blackboard"
            return result

        accumulated_results: Dict[str, Any] = {}

        # ═══════════════════════════════════════════════
        # Step 1: 初始计划生成（仅一次）
        # ═══════════════════════════════════════════════
        await self._generate_plan(0, objective, max_rounds)
        sub_tasks = await self._read_task_assignments()

        # ═══════════════════════════════════════════════
        # Step 2: 循环执行 —— 工作 + 检查/更新合并
        # ═══════════════════════════════════════════════
        for attempt in range(max_rounds):
            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                break

            phase_name = self._phase_name(attempt)
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
                # ─── Worker 并行执行 ───
                worker_results = await self._execute_workers(sub_tasks)

                for sub_task in sub_tasks:
                    self.completed_tasks.add(sub_task["task_id"])

                accumulated_results[phase_name] = worker_results

                await self.context.blackboard.set(
                    self._ns(phase_name),
                    worker_results,
                    producer="supervisor",
                )

                is_done = await self._check_progress_and_update_plan(
                    objective, worker_results, attempt, max_rounds
                )
                if not is_done:
                    # 读取 Supervisor 新创建的任务分配
                    sub_tasks = await self._read_task_assignments()

                phase.output = {
                    "worker_results": worker_results,
                    "is_done": is_done,
                }
                phase.status = PhaseStatus.COMPLETED
                self.notify_progress(result.phases, max_rounds)
                phase.completed_at = datetime.now(timezone.utc)

                if is_done:
                    if self._check_aborted():
                        phase.status = PhaseStatus.FAILED
                        phase.error = "Execution aborted"
                        phase.completed_at = datetime.now(timezone.utc)
                        result.status = ExecutionStatus.ABORTED
                        result.error = "Aborted after acceptable iteration"
                        break

                    # 合成最终结果
                    if self.crew.extras.get("do_synthesis", False):
                        synthesis = await self._synthesize(
                            objective, accumulated_results
                        )
                    else:
                        synthesis = ""

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
                logger.error(f"Supervisor-Worker iteration {attempt + 1} failed: {e}")
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
            elif self.crew.extras.get("do_synthesis", False):
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
            raise OrchestrationError(
                "No Supervisor Agent found. Supervisor-Worker requires "
                "a supervisor agent (role=supervisor)."
            )

        prompt = PromptLoader.render(
            "supervisor_worker",
            "supervisor_plan.j2",
            objective=objective,
            workers=[{"name": w} for w in self.worker_names],
            worker_count=len(self.worker_names),
        )

        from broca.loop_engine import ExecutionStatus as ES
        from broca.session import MessageProtocol

        trigger_message = MessageProtocol.create_user_message(content=prompt)
        exec_result = await supervisor_agent.run(
            trigger_message, from_agent=True, namespace=self.namespace
        )

        if exec_result.status != ES.COMPLETED:
            raise OrchestrationError(f"Supervisor Agent failed: {exec_result.error}")

    # ═══════════════════════════════════════════════
    # Phase B: Worker 并行执行
    # ═══════════════════════════════════════════════

    async def _read_task_assignments(self) -> List[Dict[str, str]]:
        """从黑板读取 Supervisor 写入的任务分配。"""
        assignments = await self.context.blackboard.get(self._ns("task_assignments"))
        if not assignments:
            raise OrchestrationError(
                "Supervisor completed but no task assignments found "
                "in blackboard key 'task_assignments'"
            )

        if isinstance(assignments, str):
            assignments = json.loads(assignments)

        sub_tasks = []
        for worker_name in self.worker_names:
            task_id = assignments.get(worker_name)
            if task_id and task_id not in self.completed_tasks:
                sub_tasks.append({"agent": worker_name, "task_id": task_id})

        if not sub_tasks:
            raise OrchestrationError(
                "Supervisor completed but no new task assignments found "
                "in blackboard key 'task_assignments'"
            )

        return sub_tasks

    async def _execute_workers(self, sub_tasks: List[Dict[str, str]]) -> Dict[str, str]:
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
        return await execute_agents_in_parallel(
            self.context, tasks, namespace=self.namespace
        )

    # ═══════════════════════════════════════════════
    # Combined: 质量检查 + 计划更新
    # ═══════════════════════════════════════════════

    async def _check_progress_and_update_plan(
        self,
        objective: str,
        worker_results: Dict[str, str],
        attempt: int,
        max_rounds: int,
    ) -> bool:
        """
        合并步骤：Supervisor (LLM) 一次性完成质量检查 和 计划更新。

        1. 评估 Worker 结果是否达标
        2. 若不达标，则创建新任务（plan update）并写入 task_assignments
        3. 返回 True（达标）/ False（需继续迭代）
        """
        supervisor_agent = self.supervisor
        if supervisor_agent is None:
            # 无 Supervisor 时简单检查错误
            return not any(r.startswith("Error:") for r in worker_results.values())

        prompt = PromptLoader.render(
            "supervisor_worker",
            "supervisor_check_and_plan.j2",
            objective=objective,
            progress_check_key=self.progress_check_key,
            worker_results=worker_results,
            workers=[{"name": w} for w in self.worker_names],
            worker_count=len(self.worker_names),
            attempt=attempt + 1,
            max_rounds=max_rounds,
        )

        from broca.loop_engine import ExecutionStatus as ES
        from broca.session import MessageProtocol

        trigger_message = MessageProtocol.create_user_message(content=prompt)
        exec_result = await supervisor_agent.run(
            trigger_message, from_agent=True, namespace=self.namespace
        )

        if exec_result.status != ES.COMPLETED:
            logger.error(
                f"Combined check & plan failed: {exec_result.error}, assuming acceptable"
            )
            raise OrchestrationError(exec_result.error)

        progress_tag = await self.blackboard.get(self._ns(self.progress_check_key))
        return str(progress_tag).lower() == "true"

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

        from broca.loop_engine import ExecutionStatus as ES
        from broca.session import MessageProtocol

        trigger_message = MessageProtocol.create_user_message(content=prompt)
        exec_result = await supervisor_agent.run(
            trigger_message, from_agent=True, namespace=self.namespace
        )

        if exec_result.status == ES.COMPLETED:
            return (
                supervisor_agent.context.get_latest_assistant_message()
                or "Synthesis completed (no output)"
            )
        else:
            logger.warning(
                f"Synthesis failed: {exec_result.error}, falling back to concatenation"
            )
            parts = []
            for iter_name, results in accumulated_results.items():
                parts.append(f"=== {iter_name} ===")
                for worker_name, output in results.items():
                    parts.append(f"[{worker_name}]:\n{output}")
            return "\n\n".join(parts)
