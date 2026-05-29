"""
Broadcast 广播拓扑编排器

同一任务分发给多个 Agent 独立处理（并行），最后聚合结果。

拓扑特征：
- Dispatcher Agent 将任务分解为并行子任务（通过 LLM）
- 并行执行所有子任务
- Aggregator Agent 汇总整合结果（通过 LLM）

vs Pipeline fan-out/fan-in:
- Broadcast = 完整顶层拓扑，Dispatcher/Aggregator 由 LLM 驱动
- Pipeline fan-out/fan-in = 流水线中的步骤原语，分支静态定义
"""

from __future__ import annotations

import json
import re
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
    execute_agents_in_parallel,
)
from broca.orchestration.prompt_loader import PromptLoader

logger = get_logger(__name__)


class BroadcastOrchestrator(Orchestrator):
    """
    广播拓扑编排器

    Dispatcher (LLM) 分解任务 → Worker 并行执行 → Aggregator (LLM) 汇总。
    三个角色均通过 Agent 调用 LLM 完成。
    """

    def __init__(self, crew_config: CrewConfig, context: Optional[CrewContext] = None):
        super().__init__(crew_config, context)

    @property
    def dispatcher(self) -> Optional[Any]:
        """获取 Dispatcher Agent（用于 LLM 分解任务）"""
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.DISPATCHER:
                return self.context.get_agent(agent_cfg.name)
        return None

    @property
    def aggregator(self) -> Optional[Any]:
        """获取 Aggregator Agent（用于 LLM 汇聚结果）"""
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.AGGREGATOR:
                return self.context.get_agent(agent_cfg.name)
        return None

    @property
    def workers(self) -> List[Dict[str, Any]]:
        """获取所有 Worker Agent"""
        workers = []
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.WORKER:
                agent = self.context.get_agent(agent_cfg.name)
                if agent:
                    workers.append({"agent": agent, "config": agent_cfg})
        return workers

    @property
    def worker_names(self) -> List[str]:
        return [w["config"].name for w in self.workers]

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

        worker_results: Dict[str, str] = {}

        try:
            # ═══════════════════════════════════════════
            # Phase 1: Dispatcher LLM 分解任务
            # ═══════════════════════════════════════════
            phase1 = PhaseResult(
                name="dispatch",
                status=PhaseStatus.RUNNING,
                agents=self._phase_agents(AgentRole.DISPATCHER),
                started_at=datetime.now(timezone.utc),
            )
            result.phases.append(phase1)

            sub_tasks = await self._dispatch(task)
            await self.context.blackboard.set(
                "sub_tasks", sub_tasks, producer="dispatcher"
            )

            phase1.status = PhaseStatus.COMPLETED
            self.notify_progress(result.phases, 3)
            phase1.output = {"sub_tasks_count": len(sub_tasks)}
            phase1.completed_at = datetime.now(timezone.utc)

            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.completed_at = datetime.now(timezone.utc)
                return result

            # ═══════════════════════════════════════════
            # Phase 2: Worker 并行执行
            # ═══════════════════════════════════════════
            phase2 = PhaseResult(
                name="parallel_execution",
                status=PhaseStatus.RUNNING,
                agents=self.worker_names,
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

            # ═══════════════════════════════════════════
            # Phase 3: Aggregator LLM 汇聚结果
            # ═══════════════════════════════════════════
            phase3 = PhaseResult(
                name="aggregation",
                status=PhaseStatus.RUNNING,
                agents=self._phase_agents(AgentRole.AGGREGATOR),
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

            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.error = "Aborted during aggregation"
            else:
                result.status = ExecutionStatus.COMPLETED

        except Exception as e:
            logger.error(f"Broadcast execution failed: {e}")
            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.error = "Aborted during broadcast execution"
            else:
                result.status = ExecutionStatus.FAILED
                result.error = str(e)

        result.completed_at = datetime.now(timezone.utc)
        result.blackboard_snapshot = await self.context.blackboard.to_dict()
        result.final_output = {
            "task": task,
            "worker_results": worker_results,
            "aggregated": aggregated if "aggregated" in dir() else None,
        }

        return result

    def _phase_agents(self, role: AgentRole) -> List[str]:
        """获取指定角色的 Agent 名称列表"""
        return [
            a_cfg.name
            for a_cfg in self.crew.agents
            if a_cfg.role == role
        ]

    # ═══════════════════════════════════════════════
    # Phase 1: Dispatcher LLM 分解任务
    # ═══════════════════════════════════════════════

    async def _dispatch(self, task: str) -> List[Dict[str, str]]:
        """
        由 Dispatcher Agent 调用 LLM 将任务分解为并行子任务。

        Dispatcher 接收原始任务 + Worker 列表，输出 JSON 格式的子任务分配。

        Returns:
            [{"agent": worker_name, "task": sub_task_desc}, ...]
        """
        dispatcher_agent = self.dispatcher
        if dispatcher_agent is None:
            logger.warning(
                "No Dispatcher Agent found, using static task distribution"
            )
            return self._static_dispatch(task)

        # 构建 Dispatcher 提示
        workers_info = [
            {
                "name": w["config"].name,
                "description": w["config"].extras.get(
                    "description",
                    w["config"].config.replace(".md", ""),
                ),
            }
            for w in self.workers
        ]

        prompt = PromptLoader.render(
            "broadcast",
            "dispatcher_prompt.j2",
            task=task,
            workers=workers_info,
            worker_count=len(self.workers),
        )

        # 调用 Dispatcher Agent (LLM)
        from broca.session import MessageProtocol
        from broca.execution_engine import ExecutionStatus as ES

        trigger_message = MessageProtocol.create_user_message(content=prompt)
        exec_result = await dispatcher_agent.run(trigger_message, from_agent=True)

        if exec_result.status != ES.COMPLETED:
            logger.warning(
                f"Dispatcher Agent failed: {exec_result.error}, "
                f"falling back to static dispatch"
            )
            return self._static_dispatch(task)

        response = dispatcher_agent.context.get_latest_assistant_message() or ""

        # 解析 JSON 输出
        sub_tasks = self._parse_json_list(response)
        if not sub_tasks:
            logger.warning(
                "Failed to parse Dispatcher output as JSON, "
                "falling back to static dispatch"
            )
            return self._static_dispatch(task)

        # 验证子任务格式
        valid_tasks = []
        for st in sub_tasks:
            if isinstance(st, dict) and "agent" in st and "task" in st:
                # 确保 agent 在 worker 列表中
                if st["agent"] in self.worker_names:
                    valid_tasks.append(st)

        if not valid_tasks:
            logger.warning(
                "No valid sub-tasks from Dispatcher, "
                "falling back to static dispatch"
            )
            return self._static_dispatch(task)

        return valid_tasks

    def _static_dispatch(self, task: str) -> List[Dict[str, str]]:
        """
        静态分发（兜底方案）：无 Dispatcher Agent 或 LLM 失败时使用。

        为每个 Worker 构建 "从你的独特角度分析" 的任务描述。
        """
        sub_tasks = []
        worker_count = max(len(self.workers), 1)

        for i, worker in enumerate(self.workers):
            task_desc = PromptLoader.render(
                "broadcast",
                "dispatch_task.j2",
                agent_name=worker["config"].name,
                task=task,
            )
            sub_tasks.append({
                "agent": worker["config"].name,
                "task": task_desc,
                "index": i,
            })

        return sub_tasks

    @staticmethod
    def _parse_json_list(text: str) -> Optional[List[Dict[str, str]]]:
        """
        从 LLM 响应中解析 JSON 数组。

        兼容 markdown 代码块、前后多余文本等情况。
        """
        # 尝试提取 ```json ... ``` 代码块
        m = re.search(
            r"```(?:json)?\s*\n?(\\[.*?\\])\s*\n?```",
            text, re.DOTALL,
        )
        if m:
            try:
                return json.loads(m.group(1))
            except (json.JSONDecodeError, TypeError):
                pass

        # 尝试提取 [...] 数组
        m = re.search(r"\[(?:[^\[\]]|\n)*\]", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except (json.JSONDecodeError, TypeError):
                pass

        # 直接尝试解析整个文本
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None

    # ═══════════════════════════════════════════════
    # Phase 2: Worker 并行执行
    # ═══════════════════════════════════════════════

    async def _execute_workers(
        self, sub_tasks: List[Dict[str, str]]
    ) -> Dict[str, str]:
        """
        并行执行所有 Worker 任务

        使用共享的 execute_agents_in_parallel 工具。
        """
        tasks = [(st["agent"], st["task"]) for st in sub_tasks]
        return await execute_agents_in_parallel(self.context, tasks)

    # ═══════════════════════════════════════════════
    # Phase 3: Aggregator LLM 汇聚结果
    # ═══════════════════════════════════════════════

    async def _aggregate(
        self, task: str, worker_results: Dict[str, str]
    ) -> str:
        """
        由 Aggregator Agent 调用 LLM 汇聚所有 Worker 结果。

        Aggregator 接收原始任务 + 所有 Worker 输出，生成综合报告。
        """
        aggregator_agent = self.aggregator
        if aggregator_agent is None:
            logger.warning(
                "No Aggregator Agent found, using simple concatenation"
            )
            parts = [
                f"[{name}]:\n{result}"
                for name, result in worker_results.items()
            ]
            return "\n\n".join(parts)

        prompt = PromptLoader.render(
            "broadcast",
            "aggregator_prompt.j2",
            task=task,
            worker_results=worker_results,
        )

        from broca.session import MessageProtocol
        from broca.execution_engine import ExecutionStatus as ES

        trigger_message = MessageProtocol.create_user_message(content=prompt)
        exec_result = await aggregator_agent.run(trigger_message, from_agent=True)

        if exec_result.status == ES.COMPLETED:
            return (
                aggregator_agent.context.get_latest_assistant_message()
                or "Aggregation completed (no output)"
            )
        else:
            logger.warning(
                f"Aggregator Agent failed: {exec_result.error}, "
                f"falling back to concatenation"
            )
            parts = [
                f"[{name}]:\n{result}"
                for name, result in worker_results.items()
            ]
            return "\n\n".join(parts)
