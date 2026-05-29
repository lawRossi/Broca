"""
Pipeline 流水线拓扑编排器

多个 Agent 按顺序依次执行，前一个 Agent 的输出作为后一个 Agent 上下文的一部分。
支持步骤定义、步骤间数据传递、结果累加、错误中断处理。

拓扑特征：
- 有序步骤列表（每个步骤指定 Agent + 任务描述）
- 前一步输出自动注入下一步上下文
- 结果累加和最终汇总
- 某步骤失败可选终止整个流水线
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from broca.logging_config import get_logger
from broca.orchestration.crew import (
    AgentRole,
    CrewConfig,
    TaskDefinition,
)
from broca.orchestration.orchestrator import (
    CrewContext,
    ExecutionStatus,
    OrchestrationResult,
    Orchestrator,
    PhaseResult,
    PhaseStatus,
)
from broca.orchestration.prompt_loader import PromptLoader
from broca.session import MessageProtocol

logger = get_logger(__name__)


class PipelineOrchestrator(Orchestrator):
    """
    流水线拓扑编排器

    按预定义的步骤列表，依次将任务委派给对应的 Agent。
    每个步骤的输出被收集到累加结果中，并作为上下文传递给下一步。
    """

    def __init__(self, crew_config: CrewConfig, context: Optional[CrewContext] = None):
        super().__init__(crew_config, context)
        # 从 extras 或 agents 配置中提取步骤定义
        self.steps = self._resolve_steps()

    def _resolve_steps(self) -> List[TaskDefinition]:
        """
        解析步骤定义

        优先级：
        1. orchestrate.extras.steps（显式步骤定义）
        2. agents 列表（按 role=worker 顺序）
        """
        # 尝试从 extras.steps 读取
        steps_data = self.crew.orchestrator.extras.get("steps", [])
        if steps_data:
            return [
                TaskDefinition.from_dict(s) if isinstance(s, dict) else s
                for s in steps_data
            ]

        # 回退：按 agents 列表中的 worker 顺序
        steps = []
        for agent_cfg in self.crew.agents:
            if agent_cfg.role in (AgentRole.WORKER, AgentRole.PARTICIPANT):
                steps.append(
                    TaskDefinition(
                        agent=agent_cfg.name,
                        task=f"Execute your role as {agent_cfg.name}",
                    )
                )
        return steps

    async def run(self) -> OrchestrationResult:
        """执行流水线编排"""
        crew_id = self.crew.name
        result = OrchestrationResult(
            crew_id=crew_id,
            status=ExecutionStatus.RUNNING,
            phases=[],
        )

        if not self.steps:
            result.status = ExecutionStatus.FAILED
            result.error = "No steps defined for Pipeline"
            return result

        accumulated_context = {}
        previous_output = None

        for i, step in enumerate(self.steps):
            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                break

            phase_name = f"step_{i + 1}: {step.agent}"
            phase = PhaseResult(
                name=phase_name,
                status=PhaseStatus.RUNNING,
                agents=[step.agent],
                started_at=datetime.now(timezone.utc),
            )
            result.phases.append(phase)

            logger.info(
                f"Pipeline step {i + 1}/{len(self.steps)}: "
                f"agent='{step.agent}', task='{step.task[:50]}...'"
            )

            try:
                # 构建任务上下文（包含累加结果和前一步输出）
                task_context = self._build_task_context(
                    step=step,
                    accumulated=accumulated_context,
                    previous_output=previous_output,
                )

                # 执行任务
                step_output = await self._execute_step(step, task_context)

                # 如果编排已被中止，即使步骤成功也要停止执行
                if self._check_aborted():
                    phase.status = PhaseStatus.FAILED
                    phase.error = "Execution aborted"
                    phase.completed_at = datetime.now(timezone.utc)
                    result.status = ExecutionStatus.ABORTED
                    result.error = f"Aborted after step {i + 1} ('{step.agent}')"
                    break

                # 记录结果
                previous_output = step_output
                if step_output:
                    accumulated_context[step.agent] = step_output

                phase.status = PhaseStatus.COMPLETED
                self.notify_progress(result.phases, len(self.steps))
                phase.output = {"output": step_output}
                phase.completed_at = datetime.now(timezone.utc)

                # 将阶段性结果写入黑板
                await self.context.blackboard.set(
                    f"pipeline.step_{i + 1}",
                    {"agent": step.agent, "output": step_output},
                    producer="pipeline_orchestrator",
                )

            except Exception as e:
                logger.error(f"Pipeline step {i + 1} failed: {e}")
                phase.status = PhaseStatus.FAILED
                phase.error = str(e)
                phase.completed_at = datetime.now(timezone.utc)

                # 如果编排已被中止，按中止处理而非失败
                if self._check_aborted():
                    result.status = ExecutionStatus.ABORTED
                    result.error = f"Aborted during step {i + 1} ('{step.agent}')"
                else:
                    result.status = ExecutionStatus.FAILED
                    result.error = f"Step {i + 1} ('{step.agent}') failed: {e}"
                break

        # 最终汇总 — 循环结束后再次检查中止标志（防止最后一步完成后才被中止的情况）
        if result.status == ExecutionStatus.RUNNING:
            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.error = "Execution aborted after all steps completed"
            else:
                result.status = ExecutionStatus.COMPLETED

        result.completed_at = datetime.now(timezone.utc)
        result.blackboard_snapshot = await self.context.blackboard.to_dict()
        result.final_output = {
            "steps_completed": sum(
                1 for p in result.phases if p.status == PhaseStatus.COMPLETED
            ),
            "steps_total": len(self.steps),
            "accumulated": accumulated_context,
        }

        return result

    def _build_task_context(
        self,
        step: TaskDefinition,
        accumulated: Dict[str, Any],
        previous_output: Any,
    ) -> str:
        """构建步骤执行的任务上下文"""
        return PromptLoader.render(
            "pipeline",
            "task_context.j2",
            task=step.task,
            context=step.context,
            accumulated=accumulated,
            previous_output=previous_output,
        )

    async def _execute_step(
        self,
        step: TaskDefinition,
        task_context: str,
    ) -> Optional[str]:
        """
        执行单个步骤

        通过 assign_task 将任务委派给目标 Agent。
        """
        target_agent = self.context.get_agent(step.agent)
        if target_agent is None:
            raise ValueError(f"Agent '{step.agent}' not found in Crew context")

        # 构建完整的任务描述
        full_task = PromptLoader.render(
            "pipeline",
            "execute_step.j2",
            task_context=task_context,
        )

        trigger_message = MessageProtocol.create_user_message(content=full_task)
        execution_result = await target_agent.run(trigger_message, from_agent=True)

        from broca.execution_engine import ExecutionStatus

        if execution_result.status == ExecutionStatus.COMPLETED:
            message = target_agent.context.get_latest_assistant_message()
            return message or "Task completed (no output message)"
        elif execution_result.status == ExecutionStatus.ABORTED:
            raise RuntimeError("Execution was aborted by user")
        else:
            raise RuntimeError(f"Execution failed: {execution_result.error}")
