"""
Composite 组合嵌套编排器

支持多种拓扑组合使用，例如宏观 Supervisor-Worker 中包含子 Pipeline/Broadcast 拓扑。
编排器递归组合子编排器，每个 Worker 本身可以是一个子 Crew。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from broca.logging_config import get_logger
from broca.orchestration.crew import (
    CrewConfig,
    OrchestratorType,
    SubCrewConfig,
)
from broca.orchestration.orchestrator import (
    CrewContext,
    ExecutionStatus,
    OrchestrationResult,
    Orchestrator,
    OrchestratorFactory,
    PhaseResult,
    PhaseStatus,
)

logger = get_logger(__name__)


class CompositeOrchestrator(Orchestrator):
    """
    组合嵌套编排器

    将主 Crew 和子 Crew 按不同拓扑组合执行。
    主 Crew 执行主流程，子 Crew 在特定步骤中使用不同拓扑。
    """

    def __init__(self, crew_config: CrewConfig, context: Optional[CrewContext] = None):
        super().__init__(crew_config, context)
        self.sub_crews = crew_config.sub_crews or []

    async def run(self) -> OrchestrationResult:
        """执行组合编排"""
        crew_id = self.crew.name
        result = OrchestrationResult(
            crew_id=crew_id,
            status=ExecutionStatus.RUNNING,
            phases=[],
        )

        logger.info(
            f"Composite orchestrator '{crew_id}' started with {len(self.sub_crews)} sub-crews"
        )

        try:
            # 根据主拓扑类型执行主流程
            main_type = self.crew.orchestrator.type

            if main_type == OrchestratorType.SUPERVISOR_WORKER:
                # 主流程：Supervisor-Worker，子流程在 Worker 中嵌套
                await self._run_supervisor_worker_with_sub_crews(result)

            elif main_type == OrchestratorType.PIPELINE:
                # 主流程：Pipeline，子流程在特定步骤中嵌套
                await self._run_pipeline_with_sub_crews(result)

            else:
                # 默认：直接执行子 Crew
                for i, sub_crew in enumerate(self.sub_crews):
                    if self._check_aborted():
                        result.status = ExecutionStatus.ABORTED
                        break

                    phase = PhaseResult(
                        name=f"sub_crew_{i + 1}: {sub_crew.name}",
                        status=PhaseStatus.RUNNING,
                        agents=[a.name for a in (sub_crew.agents or [])]
                        if sub_crew.agents
                        else [],
                        started_at=datetime.now(timezone.utc),
                    )
                    result.phases.append(phase)

                    try:
                        sub_result = await self._run_sub_crew(sub_crew)
                        await self.context.blackboard.set(
                            f"sub_crew_{sub_crew.name}",
                            sub_result.final_output,
                            producer="composite",
                        )

                        phase.status = PhaseStatus.COMPLETED
                        self.notify_progress(result.phases)
                        phase.output = sub_result.final_output
                        phase.completed_at = datetime.now(timezone.utc)
                    except Exception as e:
                        logger.error(f"Sub-crew '{sub_crew.name}' failed: {e}")
                        phase.status = PhaseStatus.FAILED
                        phase.error = str(e)
                        phase.completed_at = datetime.now(timezone.utc)

                        result.status = ExecutionStatus.FAILED
                        result.error = f"Sub-crew '{sub_crew.name}' failed: {e}"
                        break

            if result.status == ExecutionStatus.RUNNING:
                result.status = ExecutionStatus.COMPLETED

        except Exception as e:
            logger.error(f"Composite execution failed: {e}")
            result.status = ExecutionStatus.FAILED
            result.error = str(e)

        result.completed_at = datetime.now(timezone.utc)
        result.blackboard_snapshot = await self.context.blackboard.to_dict()
        result.final_output = {
            "main_type": self.crew.orchestrator.type.value,
            "sub_crews_executed": len(self.sub_crews),
            "phases_completed": sum(
                1 for p in result.phases if p.status == PhaseStatus.COMPLETED
            ),
        }

        return result

    async def _run_supervisor_worker_with_sub_crews(
        self, result: OrchestrationResult
    ) -> None:
        """以 Supervisor-Worker 为主流程，在 Worker 阶段嵌入子 Crew"""
        # 主流程阶段
        main_phase = PhaseResult(
            name="main_supervisor",
            status=PhaseStatus.RUNNING,
            agents=[a.name for a in self.crew.agents],
            started_at=datetime.now(timezone.utc),
        )
        result.phases.append(main_phase)

        # 执行子 Crew
        for i, sub_crew in enumerate(self.sub_crews):
            if self._check_aborted():
                return

            sub_phase = PhaseResult(
                name=f"sub_crew_{i + 1}: {sub_crew.name}",
                status=PhaseStatus.RUNNING,
                agents=[a.name for a in (sub_crew.agents or [])]
                if sub_crew.agents
                else [],
                started_at=datetime.now(timezone.utc),
            )
            result.phases.append(sub_phase)

            try:
                sub_result = await self._run_sub_crew(sub_crew)
                await self.context.blackboard.set(
                    f"sub_crew_{sub_crew.name}",
                    sub_result.final_output,
                    producer="composite",
                )
                sub_phase.status = PhaseStatus.COMPLETED
                self.notify_progress(result.phases)
                sub_phase.output = sub_result.final_output
                sub_phase.completed_at = datetime.now(timezone.utc)
            except Exception as e:
                sub_phase.status = PhaseStatus.FAILED
                sub_phase.error = str(e)
                sub_phase.completed_at = datetime.now(timezone.utc)
                raise

        self.notify_progress(result.phases)
        main_phase.status = PhaseStatus.COMPLETED
        main_phase.output = {"sub_crews_count": len(self.sub_crews)}
        main_phase.completed_at = datetime.now(timezone.utc)

    async def _run_pipeline_with_sub_crews(self, result: OrchestrationResult) -> None:
        """以 Pipeline 为主流程，在步骤中嵌入子 Crew"""
        for i, sub_crew in enumerate(self.sub_crews):
            if self._check_aborted():
                return

            phase = PhaseResult(
                name=f"pipeline_step_{i + 1}: {sub_crew.name}",
                status=PhaseStatus.RUNNING,
                agents=[a.name for a in (sub_crew.agents or [])]
                if sub_crew.agents
                else [],
                started_at=datetime.now(timezone.utc),
            )
            result.phases.append(phase)

            try:
                sub_result = await self._run_sub_crew(sub_crew)
                await self.context.blackboard.set(
                    f"pipeline_step_{sub_crew.name}",
                    sub_result.final_output,
                    producer="composite",
                )
                phase.status = PhaseStatus.COMPLETED
                self.notify_progress(result.phases)
                phase.output = sub_result.final_output
                phase.completed_at = datetime.now(timezone.utc)
            except Exception as e:
                phase.status = PhaseStatus.FAILED
                phase.error = str(e)
                phase.completed_at = datetime.now(timezone.utc)
                raise

    async def _run_sub_crew(self, sub_crew: SubCrewConfig) -> OrchestrationResult:
        """
        执行子 Crew

        为子 Crew 创建独立的 CrewConfig 和 Blackboard，
        然后通过 Factory 创建对应的编排器执行。
        """
        sub_config = CrewConfig(
            name=sub_crew.name,
            description=f"Sub-crew: {sub_crew.name}",
            orchestrator=sub_crew.orchestrator,
            agents=sub_crew.agents or [],
        )

        # 子 Crew 共享父 Crew 的 Blackboard
        sub_context = CrewContext(
            crew_config=sub_config,
            blackboard=self.context.blackboard,
            agent_factory=self.context.agent_factory,
            session_manager=self.context.session_manager,
        )

        # 从父上下文复制 Agent
        if sub_crew.agents:
            for agent_cfg in sub_crew.agents:
                agent = self.context.get_agent(agent_cfg.name)
                if agent:
                    sub_context.register_agent(agent_cfg.name, agent)

        # 如果是 Pipeline 且有 steps 定义，注入到 extras
        if sub_crew.orchestrator.type == OrchestratorType.PIPELINE and sub_crew.steps:
            sub_config.orchestrator.extras["steps"] = [
                s.to_dict() for s in sub_crew.steps
            ]

        orchestrator = OrchestratorFactory.create(sub_config, sub_context)
        return await orchestrator.run()
