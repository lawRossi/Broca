"""
GraphOrchestrator — 有向图编排基类

封装与节点类型无关的图遍历逻辑，供 PipelineOrchestrator 和 CompositeOrchestrator 继承。

提供的能力：
- 图遍历主循环（run → _run_main_loop）
- 路由选择（static / agent / static_then_agent）
- 并行执行 + 汇聚等待
- Human-in-the-loop
- 循环控制 + compile 校验
- 异常处理 + 进度回调
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from broca.logging_config import get_logger
from broca.orchestration.crew import CrewConfig
from broca.orchestration.graph_model import (
    Graph,
    GraphBuilder,
    Node,
    NodeType,
    Router,
)
from broca.orchestration.orchestrator import (
    CrewContext,
    ExecutionStatus,
    OrchestrationResult,
    OrchestrationStopRequest,
    Orchestrator,
    PhaseResult,
    PhaseStatus,
    check_blackboard_for_stop,
    evaluate_condition,
)
from broca.orchestration.prompt_loader import PromptLoader
from broca.session import MessageProtocol

logger = get_logger(__name__)


class GraphOrchestrator(Orchestrator, ABC):
    """
    有向图编排器基类

    子类只需实现 _execute_node()，根据节点类型分发执行逻辑。
    """

    MAX_TOTAL_STEPS = 200

    def __init__(self, crew_config: CrewConfig, context: Optional[CrewContext] = None):
        super().__init__(crew_config, context)
        self.graph = GraphBuilder.from_crew_config(crew_config) or Graph(
            nodes={
                "start": type(
                    "_", (), {"name": "start", "type": NodeType.TASK, "task": "Start"}
                )()
            },
            entry="start",
        )
        # 兼容：如果 GraphBuilder 返回 None，构造一个最小占位图
        if self.graph is None or "start" not in self.graph.nodes:
            from broca.orchestration.graph_model import Node as _Node

            self.graph = Graph(
                nodes={"start": _Node(name="start", type=NodeType.TASK, task="Start")},
                entry="start",
            )
        self._accumulated: Dict[str, Any] = {}
        self._visit_count: Dict[str, int] = {}
        self.namespace: str = crew_config.name

    # ═══════════════════════════════════════════════
    # 抽象方法
    # ═══════════════════════════════════════════════

    @abstractmethod
    async def _execute_node(
        self, node: Node, result: OrchestrationResult
    ) -> Optional[PhaseResult]:
        """子类实现：根据节点类型执行，返回 PhaseResult。"""
        ...

    # ═══════════════════════════════════════════════
    # 主执行流程
    # ═══════════════════════════════════════════════

    async def run(self) -> OrchestrationResult:
        result = self._init_result()
        if not result:
            return await self._finalize(
                await self._failed_result("Graph validation failed")
            )

        try:
            await self._run_main_loop(result)
        except OrchestrationStopRequest as stop_req:
            self._handle_stop_request(stop_req, result)
        except Exception as e:
            self._handle_execution_error(e, result)

        return await self._finalize(result)

    def _ns(self, key: str) -> str:
        """用命名空间修饰 key。Agent 通过工具写入的值都以 namespace 为前缀，
        编排器直接读写黑板时需使用此方法保持一致性。"""
        return f"{self.namespace}.{key}" if self.namespace else key

    def _init_result(self) -> Optional[OrchestrationResult]:
        self._accumulated = {}
        self._visit_count = {}

        errors = self.graph.compile()
        if errors:
            logger.error(f"Graph validation failed: {errors}")
            return None

        return OrchestrationResult(
            crew_id=self.crew.name,
            status=ExecutionStatus.RUNNING,
            phases=[],
        )

    async def _failed_result(self, error: str) -> OrchestrationResult:
        return OrchestrationResult(
            crew_id=self.crew.name,
            status=ExecutionStatus.FAILED,
            phases=[],
            error=error,
        )

    async def _run_main_loop(self, result: OrchestrationResult) -> None:
        current = self.graph.entry
        total_steps = 0

        while current and total_steps < self.MAX_TOTAL_STEPS:
            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.error = "Aborted during graph traversal"
                break

            total_steps += 1
            node = self.graph.nodes.get(current)
            if node is None:
                logger.error(f"Node '{current}' not found in graph")
                break

            if current != self.graph.entry:
                current = await self._execute_current_node(current, node, result)
                if current is None:
                    continue

            current = await self._advance_to_next(node, result)

    async def _execute_current_node(
        self, name: str, node: Node, result: OrchestrationResult
    ) -> Optional[str]:
        self._visit_count[name] = self._visit_count.get(name, 0) + 1

        if node.max_loop > 0 and self._visit_count[name] > node.max_loop:
            logger.warning(
                f"Node '{name}' exceeded max_loop ({node.max_loop}), terminating"
            )
            return None

        phase = await self._execute_node(node, result)
        if phase is None:
            return name
        return name

    async def _advance_to_next(
        self, node: Node, result: OrchestrationResult
    ) -> Optional[str]:
        targets = await self._route(node, result)

        if len(targets) == 0:
            return None
        elif len(targets) == 1:
            return targets[0]
        else:
            return await self._execute_parallel(targets, result)

    # ═══════════════════════════════════════════════
    # 异常处理
    # ═══════════════════════════════════════════════

    def _handle_stop_request(
        self, stop_req: OrchestrationStopRequest, result: OrchestrationResult
    ) -> None:
        logger.warning(f"Graph orchestrator stop requested: {stop_req}")
        result.status = ExecutionStatus.ABORTED
        result.error = str(stop_req)
        for phase in result.phases:
            if phase.status == PhaseStatus.RUNNING:
                phase.status = PhaseStatus.FAILED
                phase.error = str(stop_req)
                phase.completed_at = datetime.now(timezone.utc)

    def _handle_execution_error(
        self, error: Exception, result: OrchestrationResult
    ) -> None:
        logger.error(f"Graph orchestrator execution failed: {error}")
        if self._check_aborted():
            result.status = ExecutionStatus.ABORTED
            result.error = f"Aborted: {error}"
        else:
            result.status = ExecutionStatus.FAILED
            result.error = str(error)

    async def _finalize(self, result: OrchestrationResult) -> OrchestrationResult:
        if result.status == ExecutionStatus.RUNNING:
            result.status = ExecutionStatus.COMPLETED

        result.completed_at = datetime.now(timezone.utc)
        result.blackboard_snapshot = await self.context.blackboard.to_dict()
        result.final_output = {
            "graph_entry": self.graph.entry,
            "nodes_executed": list(self._visit_count.keys()),
            "phases_completed": sum(
                1 for p in result.phases if p.status == PhaseStatus.COMPLETED
            ),
            "phases_total": len(result.phases),
            "accumulated_keys": list(self._accumulated.keys()),
        }
        return result

    # ═══════════════════════════════════════════════
    # 节点执行辅助
    # ═══════════════════════════════════════════════

    def _node_agents(self, node: Node) -> List[str]:
        agents = []
        if node.agent:
            agents.append(node.agent)
        return agents

    def _estimate_total_phases(self) -> int:
        """估算总阶段数

        排除不执行的入口节点后，统计所有将被执行的节点数作为总阶段数估算值。

        注意：
        - 入口节点（entry）在 _run_main_loop 中被跳过执行，不计入
        - 循环/分支场景下实际 phase 数可能多于或少于估算值
          （循环产生更多、条件分支可能跳过某些节点）
        - 此估算值用于进度百分比计算，偏保守比偏乐观更好：
          偏保守时进度条不会在未完成时显示 100%
        """
        entry = self.graph.entry
        total = sum(1 for name in self.graph.nodes if name != entry)
        return max(total, 1)

    # ═══════════════════════════════════════════════
    # TASK 节点执行
    # ═══════════════════════════════════════════════

    async def _execute_task_node(self, node: Node) -> Optional[str]:
        if not node.agent:
            return None
        if not node.task:
            raise ValueError(f"Task node '{node.name}' requires 'task' field")

        agg_strategy = node.extras.get("aggregation_strategy")
        if agg_strategy:
            return await self._execute_aggregation(node, agg_strategy)

        previous_output = self._get_previous_output()
        task_context = self._build_task_context(
            task=node.task,
            context=node.context,
            previous_output=previous_output,
        )
        return await self._execute_agent(node.agent, task_context)

    def _build_task_context(
        self,
        task: str,
        context: Optional[str],
        previous_output: Any,
    ) -> str:
        return PromptLoader.render(
            "graph",
            "task_context.j2",
            task=task,
            context=context or "",
            accumulated=self._accumulated,
            previous_output=previous_output,
        )

    def _get_previous_output(self) -> Any:
        if not self._accumulated:
            return None
        last_key = list(self._accumulated.keys())[-1]
        last_val = self._accumulated[last_key]
        if isinstance(last_val, dict) and "output" in last_val:
            return last_val["output"]
        return last_val

    async def _execute_agent(self, agent_name: str, task_context: str) -> str:
        target_agent = self.context.get_agent(agent_name)
        if target_agent is None:
            raise ValueError(f"Agent '{agent_name}' not found in Crew context")

        full_task = PromptLoader.render(
            "graph",
            "execute_step.j2",
            task_context=task_context,
        )

        trigger_message = MessageProtocol.create_user_message(content=full_task)
        execution_result = await target_agent.run(
            trigger_message,
            from_agent=True,
            namespace=self.namespace,
        )

        from broca.loop_engine import ExecutionStatus as ExecStatus

        if execution_result.status == ExecStatus.COMPLETED:
            await check_blackboard_for_stop(self.context.blackboard)
            message = target_agent.context.get_latest_assistant_message() or ""
            return message or "Task completed (no output message)"
        elif execution_result.status == ExecStatus.ABORTED:
            raise RuntimeError("Execution was aborted by user")
        else:
            raise RuntimeError(f"Execution failed: {execution_result.error}")

    # ═══════════════════════════════════════════════
    # 汇聚节点执行
    # ═══════════════════════════════════════════════

    async def _execute_aggregation(self, node: Node, strategy: str) -> Any:
        sources = node.extras.get("sources")
        source_data: Dict[str, Any] = {}

        if sources:
            for src in sources:
                val = self._accumulated.get(src)
                if val is None:
                    val = await self.context.blackboard.get(self._ns(src))
                if val is not None:
                    source_data[src] = val
        else:
            for key, val in self._accumulated.items():
                if isinstance(val, str) and key != node.name:
                    source_data[key] = val

        if not source_data:
            logger.warning(f"Aggregation node '{node.name}': no source data found")
            return ""

        if strategy == "concat":
            parts = [f"[{name}]:\n{val}" for name, val in source_data.items()]
            return "\n\n".join(parts)
        elif strategy == "merge":
            return dict(source_data)
        elif strategy == "agent":
            if not node.agent:
                raise ValueError(
                    f"Aggregation node '{node.name}' needs 'agent' for agent strategy"
                )
            input_text = "\n\n".join(
                f"[{name}]:\n{val}" for name, val in source_data.items()
            )
            fan_in_prompt = PromptLoader.render(
                "graph",
                "fan_in_agent.j2",
                input_text=input_text,
                task=node.task
                or "Synthesize the above results into a coherent output.",
            )
            return await self._execute_agent(node.agent, fan_in_prompt)
        else:
            return "\n\n".join(str(v) for v in source_data.values())

    # ═══════════════════════════════════════════════
    # HUMAN 节点执行
    # ═══════════════════════════════════════════════

    async def _execute_human(self, node: Node) -> str:
        if not node.question:
            raise ValueError(f"Human node '{node.name}' missing 'question'")
        if not node.response_field:
            raise ValueError(f"Human node '{node.name}' missing 'response_field'")

        agent_name = None
        if node.router and node.router.evaluator:
            agent_name = node.router.evaluator

        if not agent_name:
            raise ValueError(
                f"Human node '{node.name}': no agent available to ask user. "
                f"Either set router.evaluator or register at least one agent."
            )

        context_str = ""
        if node.context:
            rendered_parts = []
            for key, value in node.context.items():
                val_str = str(value)
                for acc_key, acc_val in self._accumulated.items():
                    placeholder = f"{{{{ {acc_key} }}}}"
                    if placeholder in val_str:
                        val_str = val_str.replace(placeholder, str(acc_val)[:200])
                rendered_parts.append(f"  - {key}: {val_str}")
            if rendered_parts:
                context_str = "\n上下文信息：\n" + "\n".join(rendered_parts)

        options_text = ""
        for edge in node.edges:
            if edge.value is not None:
                label = str(edge.value)
            elif edge.field:
                label = edge.target
            else:
                continue
            desc = f" - {edge.description}" if edge.description else ""
            options_text += f"\n  {label}{desc}"

        user_prompt = PromptLoader.render(
            "graph",
            "human_node.j2",
            question=node.question,
            context_str=context_str,
            options_text=options_text,
        )
        target_agent = self.context.get_agent(agent_name)
        if target_agent is None:
            raise ValueError(f"Agent '{agent_name}' not found for human node")

        full_task = PromptLoader.render(
            "graph",
            "execute_step.j2",
            task_context=user_prompt,
        )

        trigger_message = MessageProtocol.create_user_message(content=full_task)
        execution_result = await target_agent.run(
            trigger_message, from_agent=True, namespace=self.namespace
        )

        from broca.loop_engine import ExecutionStatus as ExecStatus

        if execution_result.status != ExecStatus.COMPLETED:
            raise RuntimeError(
                f"Human node '{node.name}': agent execution failed: {execution_result.error}"
            )

        response = target_agent.context.get_latest_assistant_message() or ""

        await self.context.blackboard.set(
            self._ns(node.response_field),
            response,
            producer=f"human:{node.name}",
        )
        logger.info(f"Human node '{node.name}': response='{response[:100]}...'")
        return response

    # ═══════════════════════════════════════════════
    # 路由
    # ═══════════════════════════════════════════════

    async def _route(self, node: Node, result: OrchestrationResult) -> List[str]:
        if not node.edges:
            return []

        router = node.router
        if router is None:
            return [node.edges[0].target]

        if router.mode in ("static", "static_then_agent"):
            matched = await self._route_static(node)
            if matched:
                return matched

        if router.mode in ("agent", "static_then_agent"):
            selected = await self._route_agent(node, router)
            if selected:
                return selected

        for edge in reversed(node.edges):
            if edge.field is None:
                return [edge.target]

        return []

    async def _route_static(self, node: Node) -> List[str]:
        matched = []
        unconditional = None

        for edge in node.edges:
            if edge.field is None:
                unconditional = edge
                continue
            actual = await self.context.blackboard.get(self._ns(edge.field))
            if evaluate_condition(actual, edge.operator, edge.value):
                if edge.context:
                    for key, value in edge.context.items():
                        await self.context.blackboard.set(
                            self._ns(key), value, producer=f"route:{node.name}"
                        )
                matched.append(edge.target)

        if matched:
            return matched

        if unconditional:
            if unconditional.context:
                for key, value in unconditional.context.items():
                    await self.context.blackboard.set(
                        self._ns(key), value, producer=f"route:{node.name}"
                    )
            return [unconditional.target]

        return []

    async def _route_agent(self, node: Node, router: Router) -> List[str]:
        evaluator_name = router.evaluator
        if not evaluator_name:
            return []

        evaluator = self.context.get_agent(evaluator_name)
        if evaluator is None:
            logger.warning(f"Evaluator agent '{evaluator_name}' not found")
            return []

        options = "\n".join(
            f"  {e.target}  —  {e.description or '(no description)'}"
            for e in node.edges
        )
        bb_state = await self.context.blackboard.to_dict()

        prompt = PromptLoader.render(
            "graph",
            "agent_route.j2",
            prompt=router.prompt,
            blackboard_state=bb_state,
            options=options,
        )

        msg = MessageProtocol.create_user_message(content=prompt)
        exec_result = await evaluator.run(
            msg, from_agent=True, namespace=self.namespace
        )

        from broca.loop_engine import ExecutionStatus as ES

        if exec_result.status != ES.COMPLETED:
            logger.warning(f"Agent routing failed: {exec_result.error}")
            return []

        response = (evaluator.context.get_latest_assistant_message() or "").strip()
        selected = []
        for token in response.replace("，", ",").split(","):
            token = token.strip()
            for edge in node.edges:
                if edge.target == token:
                    selected.append(edge.target)
                    break
        return selected

    # ═══════════════════════════════════════════════
    # 并行执行 + 汇聚等待
    # ═══════════════════════════════════════════════

    async def _execute_parallel(
        self,
        targets: List[str],
        result: OrchestrationResult,
    ) -> Optional[str]:
        convergence = self._get_convergence_node(targets)

        async def run_branch(target: str) -> None:
            node = self.graph.nodes.get(target)
            if node is None:
                logger.warning(f"Branch target '{target}' not found")
                return

            self._visit_count[target] = self._visit_count.get(target, 0) + 1

            if node.max_loop > 0 and self._visit_count[target] > node.max_loop:
                logger.warning(
                    f"Branch '{target}' exceeded max_loop ({node.max_loop}), skipping"
                )
                return

            phase = await self._execute_node(node, result)
            if phase is None:
                return

            if node.edges:
                next_target = node.edges[0].target
                if convergence and next_target != convergence:
                    await self._execute_chain(next_target, result)

        await asyncio.gather(*[run_branch(t) for t in targets])
        return convergence

    async def _execute_chain(self, start: str, result: OrchestrationResult) -> None:
        current = start
        max_depth = 50
        depth = 0

        while current and depth < max_depth:
            if self._check_aborted():
                return

            depth += 1
            node = self.graph.nodes.get(current)
            if node is None:
                break

            convergence = self._get_convergence_node([start])
            if convergence and current == convergence:
                break

            self._visit_count[current] = self._visit_count.get(current, 0) + 1
            phase = await self._execute_node(node, result)
            if phase is None:
                return

            if node.edges:
                current = node.edges[0].target
            else:
                break

    def _get_convergence_node(self, targets: List[str]) -> Optional[str]:
        if len(targets) <= 1:
            return None

        successors = set()
        for target in targets:
            node = self.graph.nodes.get(target)
            if node and node.edges:
                successors.add(node.edges[0].target)
            else:
                successors.add(None)

        non_none = {s for s in successors if s is not None}
        if len(non_none) == 1:
            return non_none.pop()
        return None
