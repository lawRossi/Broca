"""
Composite 组合嵌套编排器

支持多种拓扑组合使用，例如宏观 Supervisor-Worker 中包含子 Pipeline/Broadcast 拓扑。
编排器递归组合子编排器，每个 Worker 本身可以是一个子 Crew。

子 Crew 的停止信号（orchestration.stop）会自动传播到父编排器。
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
    OrchestrationStopRequest,
    PhaseResult,
    PhaseStatus,
    check_blackboard_for_stop,
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
            f"Composite orchestrator '{crew_id}' started "
            f"with {len(self.sub_crews)} sub-crews"
        )

        try:
            main_type = self.crew.orchestrator.type

            if main_type == OrchestratorType.SUPERVISOR_WORKER:
                await self._run_supervisor_worker_with_sub_crews(result)
            elif main_type == OrchestratorType.PIPELINE:
                await self._run_pipeline_with_sub_crews(result)
            else:
                await self._run_default(result)

            if result.status == ExecutionStatus.RUNNING:
                if self._check_aborted():
                    result.status = ExecutionStatus.ABORTED
                    result.error = "Aborted after all sub-crews completed"
                else:
                    result.status = ExecutionStatus.COMPLETED

        except OrchestrationStopRequest as stop_req:
            logger.warning(f"Composite stop requested: {stop_req}")
            await self.abort()
            result.status = ExecutionStatus.ABORTED
            result.error = str(stop_req)
            for phase in result.phases:
                if phase.status == PhaseStatus.RUNNING:
                    phase.status = PhaseStatus.FAILED
                    phase.error = str(stop_req)
                    phase.completed_at = datetime.now(timezone.utc)

        except Exception as e:
            logger.error(f"Composite execution failed: {e}")
            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.error = "Aborted during composite execution"
            else:
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

    # ── 子 Crew 执行与结果检查 ──

    async def _run_and_check_sub_crew(
        self, sub_crew: SubCrewConfig, phase: PhaseResult
    ) -> Optional[OrchestrationResult]:
        """
        执行子 Crew 并检查停止信号。

        Returns:
            子 Crew 的执行结果，或 None（需要终止）

        Raises:
            OrchestrationStopRequest: 子 Crew 或黑板要求停止
        """
        sub_result = await self._run_sub_crew(sub_crew)

        # 子 Crew 自身 abort 了 → 传播到 Composite 层面
        if sub_result.status == ExecutionStatus.ABORTED:
            await self.abort()
            phase.status = PhaseStatus.FAILED
            phase.error = sub_result.error or "Sub-crew aborted"
            phase.completed_at = datetime.now(timezone.utc)
            return None

        # 检查黑板是否有停止信号（子 Crew 内部的 Agent 写入的）
        await check_blackboard_for_stop(self.context.blackboard)

        # 记录结果
        await self.context.blackboard.set(
            f"sub_crew_{sub_crew.name}",
            sub_result.final_output,
            producer="composite",
        )

        phase.status = PhaseStatus.COMPLETED
        phase.output = sub_result.final_output
        phase.completed_at = datetime.now(timezone.utc)
        return sub_result

    # ── 执行拓扑 ──

    async def _run_default(self, result: OrchestrationResult) -> None:
        """默认：直接顺序执行所有子 Crew"""
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
                sub_result = await self._run_and_check_sub_crew(sub_crew, phase)
                if sub_result is None:
                    # 子 Crew 要求停止
                    result.status = ExecutionStatus.ABORTED
                    result.error = (
                        f"Aborted after sub-crew '{sub_crew.name}'"
                    )
                    break

                self.notify_progress(result.phases, len(self.sub_crews))

            except OrchestrationStopRequest:
                result.status = ExecutionStatus.ABORTED
                result.error = f"Stop during sub-crew '{sub_crew.name}'"
                break

            except Exception as e:
                logger.error(f"Sub-crew '{sub_crew.name}' failed: {e}")
                phase.status = PhaseStatus.FAILED
                phase.error = str(e)
                phase.completed_at = datetime.now(timezone.utc)

                if self._check_aborted():
                    result.status = ExecutionStatus.ABORTED
                    result.error = (
                        f"Aborted during sub-crew '{sub_crew.name}'"
                    )
                else:
                    result.status = ExecutionStatus.FAILED
                    result.error = f"Sub-crew '{sub_crew.name}' failed: {e}"
                break

    async def _run_supervisor_worker_with_sub_crews(
        self, result: OrchestrationResult
    ) -> None:
        """Supervisor-Worker 主流程，Worker 阶段嵌入子 Crew"""
        main_phase = PhaseResult(
            name="main_supervisor",
            status=PhaseStatus.RUNNING,
            agents=[a.name for a in self.crew.agents],
            started_at=datetime.now(timezone.utc),
        )
        result.phases.append(main_phase)

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
                sub_result = await self._run_and_check_sub_crew(sub_crew, sub_phase)
                if sub_result is None:
                    result.status = ExecutionStatus.ABORTED
                    result.error = (
                        f"Aborted after sub-crew '{sub_crew.name}'"
                    )
                    return

                self.notify_progress(result.phases, len(self.sub_crews))

            except OrchestrationStopRequest:
                result.status = ExecutionStatus.ABORTED
                result.error = f"Stop during sub-crew '{sub_crew.name}'"
                return

            except Exception as e:
                sub_phase.status = PhaseStatus.FAILED
                sub_phase.error = str(e)
                sub_phase.completed_at = datetime.now(timezone.utc)
                raise

        self.notify_progress(result.phases, len(self.sub_crews))
        main_phase.status = PhaseStatus.COMPLETED
        main_phase.output = {"sub_crews_count": len(self.sub_crews)}
        main_phase.completed_at = datetime.now(timezone.utc)

    async def _run_pipeline_with_sub_crews(
        self, result: OrchestrationResult
    ) -> None:
        """Pipeline 主流程，步骤中嵌入子 Crew"""
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
                sub_result = await self._run_and_check_sub_crew(sub_crew, phase)
                if sub_result is None:
                    result.status = ExecutionStatus.ABORTED
                    result.error = (
                        f"Aborted after step '{sub_crew.name}'"
                    )
                    return

                self.notify_progress(result.phases, len(self.sub_crews))

            except OrchestrationStopRequest:
                result.status = ExecutionStatus.ABORTED
                result.error = f"Stop during step '{sub_crew.name}'"
                return

            except Exception as e:
                phase.status = PhaseStatus.FAILED
                phase.error = str(e)
                phase.completed_at = datetime.now(timezone.utc)
                raise

    async def _run_sub_crew(self, sub_crew: SubCrewConfig) -> OrchestrationResult:
        """
        执行子 Crew。

        创建子 CrewConfig，通过 Factory 创建对应编排器执行。
        子 Crew 共享父 Crew 的黑板，子 Crew 内部 Agent 写入的
        orchestration.stop 信号可被父编排器检测到。
        """
        sub_config = CrewConfig(
            name=sub_crew.name,
            description=f"Sub-crew: {sub_crew.name}",
            orchestrator=sub_crew.orchestrator,
            agents=sub_crew.agents or [],
        )

        sub_context = CrewContext(
            crew_config=sub_config,
            blackboard=self.context.blackboard,
            agent_factory=self.context.agent_factory,
            session_manager=self.context.session_manager,
        )

        if sub_crew.agents:
            for agent_cfg in sub_crew.agents:
                agent = self.context.get_agent(agent_cfg.name)
                if agent:
                    sub_context.register_agent(agent_cfg.name, agent)

        if (
            sub_crew.orchestrator.type == OrchestratorType.PIPELINE
            and sub_crew.steps
        ):
            sub_config.orchestrator.extras["steps"] = [
                s.to_dict() for s in sub_crew.steps
            ]

        orchestrator = OrchestratorFactory.create(sub_config, sub_context)
        return await orchestrator.run()
