"""
Composite 组合嵌套编排器

基于有向图的组合编排，节点可以是 TASK（单 Agent）、HUMAN（人在环路）或 CREW（子编排）。
图遍历逻辑继承自 GraphOrchestrator。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from broca.logging_config import get_logger
from broca.orchestration.crew import (
    CrewConfig,
    SubCrewConfig,
)
from broca.orchestration.graph_model import Node, NodeType
from broca.orchestration.graph_orchestrator import GraphOrchestrator
from broca.orchestration.orchestrator import (
    CrewContext,
    ExecutionStatus,
    OrchestrationResult,
    OrchestrationStopRequest,
    OrchestratorFactory,
    PhaseResult,
    PhaseStatus,
)

logger = get_logger(__name__)


class CompositeOrchestrator(GraphOrchestrator):
    """
    组合嵌套编排器

    节点类型：
    - TASK:  单 Agent 任务（复用基类 _execute_task_node）
    - HUMAN: 人在环路（复用基类 _execute_human）
    - CREW:  子编排（由本类 _execute_crew_node 处理）
    """

    def __init__(self, crew_config: CrewConfig, context: Optional[CrewContext] = None):
        super().__init__(crew_config, context)
        self.sub_crews = crew_config.sub_crews or []

    # ═══════════════════════════════════════════════
    # 节点执行分发
    # ═══════════════════════════════════════════════

    async def _execute_node(
        self, node: Node, result: OrchestrationResult
    ) -> Optional[PhaseResult]:
        phase_name = f"composite_{self.name}_{node.name}"
        phase = PhaseResult(
            name=phase_name,
            status=PhaseStatus.RUNNING,
            agents=self._node_agents(node),
            started_at=datetime.now(timezone.utc),
        )
        result.phases.append(phase)

        logger.info(f"Composite executing node: '{node.name}' (type={node.type.value})")

        try:
            if node.type == NodeType.CREW:
                output = await self._execute_crew_node(node)
            elif node.type == NodeType.HUMAN:
                output = await self._execute_human(node)
            else:
                output = await self._execute_task_node(node)

            if self._check_aborted():
                phase.status = PhaseStatus.FAILED
                phase.error = "Execution aborted"
                phase.completed_at = datetime.now(timezone.utc)
                return None

            if output is not None:
                self._accumulated[node.name] = output

            phase.status = PhaseStatus.COMPLETED
            phase.output = {"output": output}
            phase.completed_at = datetime.now(timezone.utc)

            await self.context.blackboard.set(
                self._ns(node.name),
                {"name": node.name, "type": node.type.value, "output": output},
                producer="composite_orchestrator",
            )

            self.notify_progress(result.phases, self._estimate_total_phases())
            return phase

        except OrchestrationStopRequest:
            raise
        except Exception as e:
            logger.error(f"Node '{node.name}' execution failed: {e}")
            phase.status = PhaseStatus.FAILED
            phase.error = str(e)
            phase.completed_at = datetime.now(timezone.utc)
            raise

    def _node_agents(self, node: Node) -> List[str]:
        agents = []
        if node.agent:
            agents.append(node.agent)
        if node.type == NodeType.CREW:
            sub = self._resolve_sub_crew(node.crew_ref or "")
            if sub and sub.agents:
                agents.extend(a.name for a in sub.agents)
        return agents

    # ═══════════════════════════════════════════════
    # CREW 节点执行
    # ═══════════════════════════════════════════════

    async def _execute_crew_node(self, node: Node) -> Any:
        """执行子 Crew 节点，返回子编排的最终输出。"""
        if not node.crew_ref:
            raise ValueError(f"CREW node '{node.name}' missing 'crew_ref'")

        sub_crew = self._resolve_sub_crew(node.crew_ref)
        if not sub_crew:
            raise ValueError(
                f"CREW node '{node.name}': sub-crew '{node.crew_ref}' not found"
            )

        # 构建子 Crew 配置
        sub_config = CrewConfig(
            name=sub_crew.name,
            description=f"Sub-crew: {sub_crew.name}",
            orchestrator=sub_crew.orchestrator,
            agents=sub_crew.agents or [],
        )

        # 共享黑板，设定子命名空间
        sub_namespace = f"sub_crew.{sub_crew.name}"
        sub_context = CrewContext(
            crew_config=sub_config,
            blackboard=self.context.blackboard,
            agent_factory=self.context.agent_factory,
            session_manager=self.context.session_manager,
        )

        # 注册 Agent（共享父编排的 Agent 实例）
        if sub_crew.agents:
            for agent_cfg in sub_crew.agents:
                agent = self.context.get_agent(agent_cfg.name)
                if agent:
                    sub_context.register_agent(agent_cfg.name, agent)

        # 创建子编排器并设置命名空间
        sub_orch = OrchestratorFactory.create(sub_config, sub_context)
        sub_orch.namespace = sub_namespace

        # 传递输入上下文（写入子命名空间）
        if node.context:
            for key, value in node.context.items():
                await self.context.blackboard.set(
                    f"{sub_namespace}.input.{key}",
                    value,
                    producer=f"composite:{node.name}",
                )

        # 执行子编排
        sub_result = await sub_orch.run()

        if sub_result.status == ExecutionStatus.ABORTED:
            await self.abort()
            raise RuntimeError(
                f"Sub-crew '{sub_crew.name}' aborted: {sub_result.error}"
            )

        if sub_result.status == ExecutionStatus.FAILED:
            raise RuntimeError(f"Sub-crew '{sub_crew.name}' failed: {sub_result.error}")

        return sub_result.final_output

    def _resolve_sub_crew(self, name: str) -> Optional[SubCrewConfig]:
        """按名称查找子 Crew 配置。"""
        for sc in self.sub_crews:
            if sc.name == name:
                return sc
        return None
