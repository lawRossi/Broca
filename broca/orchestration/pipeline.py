"""
Pipeline 流水线拓扑编排器

有向图编排的简化版，仅包含 PipelineOrchestrator。
图遍历逻辑继承自 GraphOrchestrator。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from broca.logging_config import get_logger
from broca.orchestration.graph_model import Node, NodeType
from broca.orchestration.graph_orchestrator import GraphOrchestrator
from broca.orchestration.orchestrator import (
    OrchestrationResult,
    OrchestrationStopRequest,
    PhaseResult,
    PhaseStatus,
)

logger = get_logger(__name__)


class PipelineOrchestrator(GraphOrchestrator):
    """
    流水线拓扑编排器

    节点类型：TASK（单 Agent 任务）、HUMAN（人在环路）
    图遍历逻辑继承自 GraphOrchestrator。
    """

    async def _execute_node(
        self, node: Node, result: OrchestrationResult
    ) -> Optional[PhaseResult]:
        phase_name = f"pipeline_{self.name}_{node.name}"
        phase = PhaseResult(
            name=phase_name,
            status=PhaseStatus.RUNNING,
            agents=self._node_agents(node),
            started_at=datetime.now(timezone.utc),
        )
        result.phases.append(phase)

        logger.info(f"Pipeline executing node: '{node.name}' (type={node.type.value})")

        try:
            output: str | None
            if node.type == NodeType.HUMAN:
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
                producer="pipeline_orchestrator",
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
