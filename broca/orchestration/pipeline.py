"""
Pipeline 流水线拓扑编排器

多个 Agent 按顺序依次执行，前一个 Agent 的输出作为后一个 Agent 上下文的一部分。
支持步骤定义、步骤间数据传递、结果累加、错误中断处理。

增强功能（v2）：
- Fan-out (扇出): 一个步骤并行分发到多个 Agent 执行
- Fan-in (扇入): 多个分支结果汇聚合并
- Condition (条件分支): 基于黑板值判断选择不同路径
- Switch (多路分支): 多值匹配选择分支

拓扑特征：
- 有序步骤列表（支持 5 种步骤类型）
- 前一步输出自动注入下一步上下文
- 结果累加和最终汇总
- 某步骤失败可选终止整个流水线
- 向后兼容：纯 agent/task 列表视为 task 类型
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from broca.logging_config import get_logger
from broca.orchestration.crew import (
    AgentRole,
    CrewConfig,
    SubCrewConfig,
)
from broca.orchestration.orchestrator import (
    CrewContext,
    ExecutionStatus,
    OrchestrationResult,
    Orchestrator,
    OrchestratorFactory,
    OrchestrationStopRequest,
    PhaseResult,
    PhaseStatus,
    check_blackboard_for_stop,
)
from broca.orchestration.prompt_loader import PromptLoader
from broca.session import MessageProtocol

logger = get_logger(__name__)


# ============================================================================
# Pipeline 步骤类型定义
# ============================================================================


class PipelineStepType(str, Enum):
    """流水线步骤类型"""

    TASK = "task"
    """单 Agent 任务（原有模式）"""
    FAN_OUT = "fan-out"
    """扇出：并行分发到多个 Agent"""
    FAN_IN = "fan-in"
    """扇入：汇聚多个分支结果"""
    CONDITION = "condition"
    """条件分支：基于条件判断选择路径"""
    SWITCH = "switch"
    """多路分支：多值匹配选择路径"""


@dataclass
class BranchDefinition:
    """分支定义（fan-out / condition / switch 的子步骤）

    支持两种执行模式：
    - Agent 模式: 指定 agent + task，由单个 Agent 执行
    - Crew 模式: 指定 crew，运行一个子编排器
    """

    name: str
    """分支名称"""
    agent: Optional[str] = None
    """执行 Agent（Agent 模式）"""
    task: Optional[str] = None
    """任务描述（Agent 模式）"""
    context: Optional[str] = None
    """额外上下文（Agent 模式）"""
    crew: Optional[SubCrewConfig] = None
    """子 Crew 配置（Crew 模式）"""

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"name": self.name}
        if self.agent:
            result["agent"] = self.agent
            result["task"] = self.task or ""
            if self.context:
                result["context"] = self.context
        if self.crew:
            result["crew"] = self.crew.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BranchDefinition":
        crew_data = data.get("crew")
        if crew_data:
            return cls(
                name=data["name"],
                crew=SubCrewConfig.from_dict(crew_data),
            )
        return cls(
            name=data["name"],
            agent=data.get("agent"),
            task=data.get("task", ""),
            context=data.get("context"),
        )


@dataclass
class PipelineStep:
    """
    流水线步骤定义

    支持 5 种步骤类型，不同类型使用不同字段组合。
    兼容旧格式：纯 dict（无 type 字段）视为 TASK 类型。
    """

    # === 通用字段 ===
    type: PipelineStepType = PipelineStepType.TASK
    """步骤类型"""
    name: Optional[str] = None
    """步骤名称（用于日志和黑板标识，省略则自动生成）"""

    # === TASK 类型字段 ===
    agent: Optional[str] = None
    """目标 Agent 名称"""
    task: Optional[str] = None
    """任务描述"""
    context: Optional[str] = None
    """额外上下文"""

    # === FAN-OUT / CONDITION / SWITCH 共用字段 ===
    branches: Optional[List[BranchDefinition]] = None
    """子分支列表"""

    # === FAN-IN 字段 ===
    aggregator: Optional[str] = None
    """汇聚 Agent 名称"""
    aggregation_strategy: str = "concat"
    """汇聚策略: concat(拼接) | merge(合并) | agent(由 Agent 自行汇聚)"""
    sources: Optional[List[str]] = None
    """待汇聚的分支名称列表（留空则汇聚前一步所有输出）"""

    # === CONDITION 字段 ===
    condition_field: Optional[str] = None
    """黑板中用于条件判断的字段路径（静态比较模式使用）"""
    condition_operator: str = "eq"
    """比较运算符: eq | ne | gt | gte | lt | lte | contains | startswith | endswith（静态比较模式使用）"""
    condition_value: Any = None
    """比较目标值（静态比较模式使用）"""
    evaluator: Optional[str] = None
    """评估 Agent 名称（Agent 评估模式使用）。指定后由该 Agent 根据 evaluation_prompt 判断走哪个分支"""
    evaluation_prompt: Optional[str] = None
    """评估指令（Agent 评估模式使用）。Agent 根据此指令和当前黑板上下文决定走哪个分支"""

    # === SWITCH 字段 ===
    switch_field: Optional[str] = None
    """黑板中用于匹配的字段路径"""
    default_branch: Optional[str] = None
    """无匹配时的默认分支名称"""

    # === 额外信息 ===
    extras: Dict[str, Any] = field(default_factory=dict)

    # ── 序列化 ──

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"type": self.type.value}

        if self.name:
            result["name"] = self.name

        # TASK 字段
        if self.agent:
            result["agent"] = self.agent
        if self.task:
            result["task"] = self.task
        if self.context:
            result["context"] = self.context

        # 分支
        if self.branches:
            result["branches"] = [b.to_dict() for b in self.branches]

        # FAN-IN
        if self.type == PipelineStepType.FAN_IN:
            if self.aggregator:
                result["aggregator"] = self.aggregator
            result["aggregation_strategy"] = self.aggregation_strategy
            if self.sources:
                result["sources"] = self.sources

        # CONDITION
        if self.type == PipelineStepType.CONDITION:
            if self.evaluator:
                result["evaluator"] = self.evaluator
                if self.evaluation_prompt:
                    result["evaluation_prompt"] = self.evaluation_prompt
            else:
                # 静态比较模式
                if self.condition_field:
                    result["condition_field"] = self.condition_field
                result["condition_operator"] = self.condition_operator
                result["condition_value"] = self.condition_value
            if self.default_branch:
                result["default_branch"] = self.default_branch

        # SWITCH
        if self.type == PipelineStepType.SWITCH:
            if self.evaluator:
                result["evaluator"] = self.evaluator
                if self.evaluation_prompt:
                    result["evaluation_prompt"] = self.evaluation_prompt
            else:
                if self.switch_field:
                    result["switch_field"] = self.switch_field
            if self.default_branch:
                result["default_branch"] = self.default_branch

        if self.extras:
            result["extras"] = self.extras

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineStep":
        # 兼容旧格式：无 type 字段视为 TASK
        step_type = PipelineStepType(data.get("type", "task"))

        if step_type == PipelineStepType.TASK:
            return cls(
                type=step_type,
                name=data.get("name"),
                agent=data.get("agent"),
                task=data.get("task"),
                context=data.get("context"),
                extras=data.get("extras", {}),
            )

        branches = None
        if "branches" in data:
            branches = [BranchDefinition.from_dict(b) for b in data["branches"]]

        if step_type == PipelineStepType.FAN_OUT:
            return cls(
                type=step_type,
                name=data.get("name"),
                branches=branches,
                extras=data.get("extras", {}),
            )

        if step_type == PipelineStepType.FAN_IN:
            return cls(
                type=step_type,
                name=data.get("name"),
                branches=branches,
                aggregator=data.get("aggregator"),
                aggregation_strategy=data.get("aggregation_strategy", "concat"),
                sources=data.get("sources"),
                extras=data.get("extras", {}),
            )

        if step_type == PipelineStepType.CONDITION:
            # Agent 评估模式 vs 静态比较模式
            evaluator = data.get("evaluator")
            if evaluator:
                return cls(
                    type=step_type,
                    name=data.get("name"),
                    branches=branches,
                    evaluator=evaluator,
                    evaluation_prompt=data.get("evaluation_prompt"),
                    default_branch=data.get("default_branch"),
                    extras=data.get("extras", {}),
                )
            return cls(
                type=step_type,
                name=data.get("name"),
                branches=branches,
                condition_field=data.get("condition_field"),
                condition_operator=data.get("condition_operator", "eq"),
                condition_value=data.get("condition_value"),
                default_branch=data.get("default_branch"),
                extras=data.get("extras", {}),
            )

        if step_type == PipelineStepType.SWITCH:
            evaluator = data.get("evaluator")
            if evaluator:
                return cls(
                    type=step_type,
                    name=data.get("name"),
                    branches=branches,
                    evaluator=evaluator,
                    evaluation_prompt=data.get("evaluation_prompt"),
                    default_branch=data.get("default_branch"),
                    extras=data.get("extras", {}),
                )
            return cls(
                type=step_type,
                name=data.get("name"),
                branches=branches,
                switch_field=data.get("switch_field"),
                default_branch=data.get("default_branch"),
                extras=data.get("extras", {}),
            )

        raise ValueError(f"Unknown PipelineStepType: {step_type}")


# ============================================================================
# 条件表达式求值
# ============================================================================


def _evaluate_condition(
    actual_value: Any,
    operator: str,
    target_value: Any,
) -> bool:
    """
    求值条件表达式

    Args:
        actual_value: 实际值（从黑板读取）
        operator: 比较运算符
        target_value: 目标值

    Returns:
        是否满足条件
    """
    ops = {
        "eq": lambda a, b: a == b,
        "ne": lambda a, b: a != b,
        "gt": lambda a, b: (a is not None and b is not None) and a > b,
        "gte": lambda a, b: (a is not None and b is not None) and a >= b,
        "lt": lambda a, b: (a is not None and b is not None) and a < b,
        "lte": lambda a, b: (a is not None and b is not None) and a <= b,
        "contains": lambda a, b: b in (a or ""),
        "startswith": lambda a, b: str(a or "").startswith(str(b)),
        "endswith": lambda a, b: str(a or "").endswith(str(b)),
    }

    op_fn = ops.get(operator)
    if op_fn is None:
        logger.warning(f"Unknown condition operator '{operator}', falling back to eq")
        return ops["eq"](actual_value, target_value)

    try:
        return bool(op_fn(actual_value, target_value))
    except (TypeError, ValueError) as e:
        logger.warning(f"Condition evaluation error ({operator}): {e}")
        return False


def _match_switch(
    actual_value: Any,
    branches: List[BranchDefinition],
    default_branch: Optional[str] = None,
) -> Optional[str]:
    """
    匹配 switch 分支

    按 branches 顺序匹配，返回第一个 name == actual_value 的分支。

    Returns:
        匹配的分支名称，无匹配返回 default_branch
    """
    str_value = str(actual_value) if actual_value is not None else ""
    for branch in (branches or []):
        if branch.name == str_value:
            return branch.name
    return default_branch


# ============================================================================
# 编排器
# ============================================================================


class PipelineOrchestrator(Orchestrator):
    """
    流水线拓扑编排器（增强版）

    支持 5 种步骤类型：
    - task:      单 Agent 顺序执行（原有）
    - fan-out:   并行分发到多个 Agent
    - fan-in:    汇聚多个分支结果
    - condition: 条件判断选择分支
    - switch:    多值匹配选择分支
    """

    def __init__(self, crew_config: CrewConfig, context: Optional[CrewContext] = None):
        super().__init__(crew_config, context)
        self.steps = self._resolve_steps()

    def _resolve_steps(self) -> List[PipelineStep]:
        """
        解析步骤定义

        优先级：
        1. orchestrate.extras.steps（显式 PipelineStep 定义）
        2. agents 列表（按 role=worker 顺序，兼容旧配置）
        """
        steps_data = self.crew.orchestrator.extras.get("steps", [])
        if steps_data:
            return [
                PipelineStep.from_dict(s) if isinstance(s, dict) else s
                for s in steps_data
            ]

        # 回退：按 agents 列表中的 worker 顺序（兼容旧配置）
        steps = []
        for agent_cfg in self.crew.agents:
            if agent_cfg.role in (AgentRole.WORKER, AgentRole.PARTICIPANT):
                steps.append(
                    PipelineStep(
                        type=PipelineStepType.TASK,
                        agent=agent_cfg.name,
                        task=f"Execute your role as {agent_cfg.name}",
                    )
                )
        return steps

    # ── 步骤名称辅助 ──

    def _step_name(self, step: PipelineStep, index: int) -> str:
        """获取步骤显示名称"""
        if step.name:
            return step.name
        if step.type == PipelineStepType.TASK:
            return f"step_{index + 1}: {step.agent or 'unknown'}"
        return f"step_{index + 1}: {step.type.value}"

    # ── 主执行流程 ──

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

        accumulated_context: Dict[str, Any] = {}

        for i, step in enumerate(self.steps):
            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                break

            phase_name = self._step_name(step, i)
            phase = PhaseResult(
                name=phase_name,
                status=PhaseStatus.RUNNING,
                agents=self._step_agents(step),
                started_at=datetime.now(timezone.utc),
            )
            result.phases.append(phase)

            logger.info(
                f"Pipeline [{phase_name}] type={step.type.value}, "
                f"branches={len(step.branches) if step.branches else 1}"
            )

            try:
                # 根据步骤类型分发执行
                step_output = await self._dispatch_step(step, i, accumulated_context)

                # 检查中止
                if self._check_aborted():
                    phase.status = PhaseStatus.FAILED
                    phase.error = "Execution aborted"
                    phase.completed_at = datetime.now(timezone.utc)
                    result.status = ExecutionStatus.ABORTED
                    result.error = f"Aborted after step {i + 1} ('{phase_name}')"
                    break

                # 记录结果
                if step_output is not None:
                    accumulated_context[phase_name] = step_output

                phase.status = PhaseStatus.COMPLETED
                self.notify_progress(result.phases, len(self.steps))
                phase.output = {"output": step_output}
                phase.completed_at = datetime.now(timezone.utc)

                # 结果写入黑板
                await self.context.blackboard.set(
                    f"pipeline.step_{i + 1}",
                    {
                        "name": phase_name,
                        "type": step.type.value,
                        "output": step_output,
                    },
                    producer="pipeline_orchestrator",
                )

            except OrchestrationStopRequest as stop_req:
                logger.warning(
                    f"Pipeline step {i + 1} ('{phase_name}') requested stop: "
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
                logger.error(f"Pipeline step {i + 1} ('{phase_name}') failed: {e}")
                phase.status = PhaseStatus.FAILED
                phase.error = str(e)
                phase.completed_at = datetime.now(timezone.utc)

                if self._check_aborted():
                    result.status = ExecutionStatus.ABORTED
                    result.error = f"Aborted during step {i + 1} ('{phase_name}')"
                else:
                    result.status = ExecutionStatus.FAILED
                    result.error = f"Step {i + 1} ('{phase_name}') failed: {e}"
                break

        # 最终状态
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

    def _step_agents(self, step: PipelineStep) -> List[str]:
        """获取步骤涉及的所有 Agent 名称（用于 phase 记录）"""
        if step.type == PipelineStepType.TASK and step.agent:
            return [step.agent]
        if step.branches:
            return [b.agent for b in step.branches]
        if step.type == PipelineStepType.FAN_IN and step.aggregator:
            return [step.aggregator]
        return []

    # ── 步骤分发 ──

    async def _dispatch_step(
        self,
        step: PipelineStep,
        index: int,
        accumulated: Dict[str, Any],
    ) -> Any:
        """根据步骤类型分发到对应的执行方法"""
        dispatch_map = {
            PipelineStepType.TASK: self._execute_task,
            PipelineStepType.FAN_OUT: self._execute_fan_out,
            PipelineStepType.FAN_IN: self._execute_fan_in,
            PipelineStepType.CONDITION: self._execute_condition,
            PipelineStepType.SWITCH: self._execute_switch,
        }

        executor = dispatch_map.get(step.type)
        if executor is None:
            raise ValueError(f"Unsupported step type: {step.type}")

        return await executor(step, index, accumulated)

    # ═══════════════════════════════════════════════
    # TASK 类型
    # ═══════════════════════════════════════════════

    async def _execute_task(
        self,
        step: PipelineStep,
        index: int,
        accumulated: Dict[str, Any],
    ) -> Optional[str]:
        """执行单个 Agent 任务（原有逻辑）"""
        if not step.agent:
            raise ValueError("TASK step requires 'agent' field")
        if not step.task:
            raise ValueError("TASK step requires 'task' field")

        # 取前一步输出作为 previous_output
        previous_output = self._get_previous_output(accumulated)

        task_context = self._build_task_context(
            task=step.task,
            context=step.context,
            accumulated=accumulated,
            previous_output=previous_output,
        )

        return await self._execute_agent(step.agent, task_context)

    def _build_task_context(
        self,
        task: str,
        context: Optional[str],
        accumulated: Dict[str, Any],
        previous_output: Any,
    ) -> str:
        """构建步骤执行的任务上下文"""
        return PromptLoader.render(
            "pipeline",
            "task_context.j2",
            task=task,
            context=context,
            accumulated=accumulated,
            previous_output=previous_output,
        )

    def _get_previous_output(self, accumulated: Dict[str, Any]) -> Any:
        """从累加结果中提取前一步的输出"""
        if not accumulated:
            return None
        # 取最后一个条目的 output
        last_key = list(accumulated.keys())[-1]
        last_val = accumulated[last_key]
        if isinstance(last_val, dict) and "output" in last_val:
            return last_val["output"]
        return last_val

    async def _execute_agent(self, agent_name: str, task_context: str) -> str:
        """
        向指定 Agent 下发任务并返回执行结果

        Args:
            agent_name: Agent 名称
            task_context: 任务描述上下文

        Returns:
            Agent 执行结果文本

        Raises:
            ValueError: Agent 不存在
            RuntimeError: 执行失败或被中止
        """
        target_agent = self.context.get_agent(agent_name)
        if target_agent is None:
            raise ValueError(f"Agent '{agent_name}' not found in Crew context")

        full_task = PromptLoader.render(
            "pipeline",
            "execute_step.j2",
            task_context=task_context,
        )

        trigger_message = MessageProtocol.create_user_message(content=full_task)
        execution_result = await target_agent.run(trigger_message, from_agent=True)

        from broca.execution_engine import ExecutionStatus as ExecStatus

        if execution_result.status == ExecStatus.COMPLETED:
            # 检查黑板中是否有停止编排信号
            await check_blackboard_for_stop(self.context.blackboard)
            message = target_agent.context.get_latest_assistant_message() or ""
            return message or "Task completed (no output message)"
        elif execution_result.status == ExecStatus.ABORTED:
            raise RuntimeError("Execution was aborted by user")
        else:
            raise RuntimeError(f"Execution failed: {execution_result.error}")

    # ═══════════════════════════════════════════════
    # FAN-OUT 类型
    # ═══════════════════════════════════════════════

    async def _execute_fan_out(
        self,
        step: PipelineStep,
        index: int,
        accumulated: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        扇出执行：并行分发到多个 Agent

        Returns:
            {branch_name: branch_output, ...}
        """
        if not step.branches:
            raise ValueError("FAN-OUT step requires 'branches' list")

        previous_output = self._get_previous_output(accumulated)

        from broca.orchestration.orchestrator import execute_agents_in_parallel

        # 区分 Agent 分支和 Crew 分支
        agent_branches = [b for b in step.branches if not b.crew]
        crew_branches = [b for b in step.branches if b.crew]

        result_dict: Dict[str, Any] = {}

        # Agent 分支：通过共享并行执行器
        if agent_branches:
            tasks = []
            for branch in agent_branches:
                branch_context = PromptLoader.render(
                    "pipeline",
                    "fan_out_branch.j2",
                    branch_name=branch.name,
                    task=branch.task,
                    context=branch.context,
                    previous_output=previous_output,
                    accumulated=accumulated,
                )
                tasks.append((branch.agent, branch_context))
            agent_results = await execute_agents_in_parallel(self.context, tasks)
            result_dict.update(agent_results)

        # Crew 分支：通过子编排器并行执行
        if crew_branches:
            async def run_crew_branch(branch: BranchDefinition) -> tuple:
                try:
                    output = await self._execute_branch_crew(branch)
                    return (branch.name, output)
                except Exception as e:
                    logger.error(f"Crew branch '{branch.name}' failed: {e}")
                    return (branch.name, f"Error: {e}")

            crew_results = await asyncio.gather(
                *[run_crew_branch(b) for b in crew_branches]
            )
            result_dict.update(dict(crew_results))

        # 记录到黑板
        for branch_name, output in result_dict.items():
            await self.context.blackboard.set(
                f"pipeline.fan_out.{step.name or f'step_{index + 1}'}.{branch_name}",
                output,
                producer="pipeline_orchestrator",
            )

        return result_dict

    # ═══════════════════════════════════════════════
    # FAN-IN 类型
    # ═══════════════════════════════════════════════

    async def _execute_fan_in(
        self,
        step: PipelineStep,
        index: int,
        accumulated: Dict[str, Any],
    ) -> Any:
        """
        扇入执行：汇聚多个分支结果

        aggregation_strategy:
        - concat: 将所有结果拼接为一个字符串
        - merge:  合并为一个 dict
        - agent:  由指定的 aggregator Agent 自行汇聚

        Returns:
            汇聚后的结果
        """
        # 确定要汇聚的数据源
        sources = step.sources  # branch name 列表
        source_data: Dict[str, Any] = {}

        if sources:
            # 从黑板读取指定分支的结果
            for src in sources:
                val = await self.context.blackboard.get(
                    f"pipeline.fan_out.{src}"
                )
                if val is None:
                    # 也尝试从 accumulated 查找
                    val = accumulated.get(src)
                if val is not None:
                    source_data[src] = val
        else:
            # 从 accumulated 中取上一轮 fan-out 的结果
            for key, val in reversed(list(accumulated.items())):
                if isinstance(val, dict) and not any(
                    isinstance(v, dict) and "output" in v for v in val.values()
                ):
                    source_data = val
                    break

        if not source_data:
            logger.warning(
                f"FAN-IN step '{self._step_name(step, index)}': "
                f"no source data found, using empty dict"
            )

        strategy = step.aggregation_strategy

        if strategy == "concat":
            parts = []
            for src_name, src_val in source_data.items():
                parts.append(f"[{src_name}]:\n{src_val}")
            return "\n\n".join(parts)

        elif strategy == "merge":
            return dict(source_data)

        elif strategy == "agent":
            if not step.aggregator:
                raise ValueError(
                    "FAN-IN with 'agent' strategy requires 'aggregator' field"
                )
            # 由指定 Agent 汇聚
            input_text = "\n\n".join(
                f"[{name}]:\n{val}" for name, val in source_data.items()
            )
            fan_in_prompt = PromptLoader.render(
                "pipeline",
                "fan_in_agent.j2",
                input_text=input_text,
                task=step.task or "Synthesize the above results into a coherent output.",
            )
            return await self._execute_agent(step.aggregator, fan_in_prompt)

        else:
            logger.warning(
                f"Unknown aggregation strategy '{strategy}', falling back to concat"
            )
            return "\n\n".join(str(v) for v in source_data.values())

    # ═══════════════════════════════════════════════
    # CONDITION 类型
    # ═══════════════════════════════════════════════

    async def _execute_condition(
        self,
        step: PipelineStep,
        index: int,
        accumulated: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        条件分支执行

        支持两种模式：
        1. Agent 评估模式（推荐）: 指定 evaluator Agent，由 LLM 根据 evaluation_prompt 判断走哪个分支
        2. 静态比较模式: 从黑板读取 condition_field，用 condition_operator 与 condition_value 比较

        Returns:
            {"branch": branch_name, "output": branch_output}
        """
        if not step.branches or len(step.branches) < 1:
            raise ValueError("CONDITION step requires at least 1 branch")

        # ── Agent 评估模式 ──
        if step.evaluator:
            return await self._execute_condition_by_agent(step, index, accumulated)

        # ── 静态比较模式 ──
        actual_value = None
        if step.condition_field:
            actual_value = await self.context.blackboard.get(step.condition_field)
            if actual_value is None:
                actual_value = accumulated.get(step.condition_field)

        logger.info(
            f"CONDITION evaluating: field='{step.condition_field}', "
            f"actual={actual_value}, operator={step.condition_operator}, "
            f"target={step.condition_value}"
        )

        matched = _evaluate_condition(
            actual_value, step.condition_operator, step.condition_value
        )

        selected_branch = self._pick_branch(step, matched)

        if selected_branch is None:
            logger.warning(
                f"CONDITION step '{self._step_name(step, index)}': "
                f"no branch matched, skipping"
            )
            return {"branch": None, "output": None, "matched": matched}

        output = await self._execute_selected_branch(selected_branch, accumulated)

        result = {
            "branch": selected_branch.name,
            "output": output,
            "matched": matched,
            "condition": {
                "mode": "static",
                "field": step.condition_field,
                "operator": step.condition_operator,
                "expected": step.condition_value,
                "actual": actual_value,
            },
        }

        await self.context.blackboard.set(
            f"pipeline.condition.{step.name or f'step_{index + 1}'}",
            result,
            producer="pipeline_orchestrator",
        )

        return result

    async def _execute_condition_by_agent(
        self,
        step: PipelineStep,
        index: int,
        accumulated: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Agent 评估模式：由指定的 evaluator Agent 根据当前上下文判断走哪个分支。
        """
        evaluator_agent = self.context.get_agent(step.evaluator)
        if evaluator_agent is None:
            logger.warning(
                f"Evaluator Agent '{step.evaluator}' not found, "
                f"falling back to default branch"
            )
            selected_branch = self._pick_branch(step, matched=False)
            if selected_branch is None:
                return {"branch": None, "output": None, "error": "evaluator not found"}
            output = await self._execute_selected_branch(selected_branch, accumulated)
            return {"branch": selected_branch.name, "output": output}

        # 构建评估提示，包含当前黑板状态和累加结果
        blackboard_snapshot = await self.context.blackboard.to_dict()
        prompt = PromptLoader.render(
            "pipeline",
            "condition_eval.j2",
            evaluation_prompt=step.evaluation_prompt or "",
            branches=[{"name": b.name, "task": b.task} for b in (step.branches or [])],
            blackboard_snapshot=blackboard_snapshot,
            accumulated=accumulated,
        )

        eval_prompt_display = step.evaluation_prompt or "(default)"
        logger.info(
            f"CONDITION (agent) evaluator='{step.evaluator}', "
            f"prompt='{eval_prompt_display}'"
        )

        # 调用 evaluator Agent 做判断
        from broca.session import MessageProtocol
        from broca.execution_engine import ExecutionStatus as ES

        trigger_message = MessageProtocol.create_user_message(content=prompt)
        exec_result = await evaluator_agent.run(trigger_message, from_agent=True)

        branch_name = None
        if exec_result.status == ES.COMPLETED:
            response = evaluator_agent.context.get_latest_assistant_message() or ""
            # 从响应中提取分支名（按顺序匹配）
            for b in (step.branches or []):
                if b.name in response:
                    branch_name = b.name
                    break

        if branch_name is None:
            logger.warning(
                f"Evaluator Agent didn't return a valid branch name, "
                f"falling back to default"
            )
            selected_branch = self._pick_branch(step, matched=False)
            if selected_branch is None:
                return {"branch": None, "output": None, "error": "no branch selected"}
        else:
            selected_branch = None
            for b in (step.branches or []):
                if b.name == branch_name:
                    selected_branch = b
                    break

        if selected_branch is None:
            return {"branch": None, "output": None, "error": "branch not found"}

        output = await self._execute_selected_branch(selected_branch, accumulated)

        result = {
            "branch": selected_branch.name,
            "output": output,
            "condition": {
                "mode": "agent",
                "evaluator": step.evaluator,
                "prompt": step.evaluation_prompt,
            },
        }

        await self.context.blackboard.set(
            f"pipeline.condition.{step.name or f'step_{index + 1}'}",
            result,
            producer="pipeline_orchestrator",
        )

        return result

    def _pick_branch(
        self,
        step: PipelineStep,
        matched: bool,
    ) -> Optional[BranchDefinition]:
        """
        根据匹配结果选择分支。
        - matched=True → 第一个分支
        - matched=False → 第二个分支（如有）
        - 都不满足 → default_branch
        """
        if matched and step.branches:
            return step.branches[0]
        if not matched and step.branches and len(step.branches) > 1:
            return step.branches[1]
        if step.default_branch:
            for b in (step.branches or []):
                if b.name == step.default_branch:
                    return b
        return None

    async def _execute_selected_branch(
        self,
        branch: BranchDefinition,
        accumulated: Dict[str, Any],
    ) -> str:
        """执行选中的分支（支持 Agent 模式或 Crew 模式）"""
        if branch.crew:
            return await self._execute_branch_crew(branch)
        previous_output = self._get_previous_output(accumulated)
        branch_context = PromptLoader.render(
            "pipeline",
            "fan_out_branch.j2",
            branch_name=branch.name,
            task=branch.task,
            context=branch.context,
            previous_output=previous_output,
            accumulated=accumulated,
        )
        return await self._execute_agent(branch.agent, branch_context)

    async def _execute_branch_crew(self, branch: BranchDefinition) -> str:
        """以子 Crew 模式执行分支"""
        crew = branch.crew
        sub_config = CrewConfig(
            name=crew.name or branch.name,
            description=f"Branch: {branch.name}",
            orchestrator=crew.orchestrator,
            agents=crew.agents or [],
        )
        sub_context = CrewContext(
            crew_config=sub_config,
            blackboard=self.context.blackboard,
            agent_factory=self.context.agent_factory,
            session_manager=self.context.session_manager,
        )
        if crew.agents:
            for agent_cfg in crew.agents:
                agent = self.context.get_agent(agent_cfg.name)
                if agent:
                    sub_context.register_agent(agent_cfg.name, agent)
        if (
            crew.orchestrator.type == OrchestratorType.PIPELINE
            and crew.steps
        ):
            sub_config.orchestrator.extras["steps"] = [
                s.to_dict() for s in crew.steps
            ]

        orchestrator = OrchestratorFactory.create(sub_config, sub_context)
        sub_result = await orchestrator.run()

        result = sub_result.final_output or {}
        return str(result)

    # ═══════════════════════════════════════════════
    # SWITCH 类型
    # ═══════════════════════════════════════════════

    async def _execute_switch(
        self,
        step: PipelineStep,
        index: int,
        accumulated: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        多路分支执行

        从黑板读取 switch_field 的值，与各分支名称匹配，
        执行匹配的分支。

        Returns:
            {"branch": branch_name, "output": branch_output}
        """
        if not step.branches or len(step.branches) < 1:
            raise ValueError("SWITCH step requires at least 1 branch")

        # ── Agent 评估模式 ──
        if step.evaluator:
            return await self._execute_condition_by_agent(step, index, accumulated)

        # ── 静态匹配模式 ──
        actual_value = None
        if step.switch_field:
            actual_value = await self.context.blackboard.get(step.switch_field)
            if actual_value is None:
                actual_value = accumulated.get(step.switch_field)

        logger.info(
            f"SWITCH matching: field='{step.switch_field}', "
            f"actual={actual_value}, branches={[b.name for b in step.branches]}"
        )

        matched_name = _match_switch(
            actual_value, step.branches, step.default_branch
        )

        selected_branch: Optional[BranchDefinition] = None
        for b in (step.branches or []):
            if b.name == matched_name:
                selected_branch = b
                break

        if selected_branch is None:
            logger.warning(
                f"SWITCH step '{self._step_name(step, index)}': "
                f"no branch matched and no default, skipping"
            )
            return {"branch": None, "output": None, "matched_value": actual_value}

        output = await self._execute_selected_branch(selected_branch, accumulated)

        result = {
            "branch": selected_branch.name,
            "output": output,
            "matched_value": actual_value,
            "condition": {"mode": "static", "field": step.switch_field},
        }

        await self.context.blackboard.set(
            f"pipeline.switch.{step.name or f'step_{index + 1}'}",
            result,
            producer="pipeline_orchestrator",
        )

        return result
