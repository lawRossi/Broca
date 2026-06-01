"""
Composite 组合嵌套编排器

支持多种拓扑组合使用，例如宏观 Supervisor-Worker 中包含子 Pipeline/Broadcast 拓扑。
编排器递归组合子编排器，每个 Worker 本身可以是一个子 Crew。

子 Crew 的停止信号（orchestration.stop）会自动传播到父编排器。
"""

from __future__ import annotations

import asyncio
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
    OrchestrationStopRequest,
    Orchestrator,
    OrchestratorFactory,
    PhaseResult,
    PhaseStatus,
    check_blackboard_for_stop,
    evaluate_condition,
)
from broca.orchestration.prompt_loader import PromptLoader
from broca.session import MessageProtocol

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
                await self._run_sequential(result, phase_template="pipeline_step_{i+1}: {name}")
            elif main_type == OrchestratorType.BRANCH:
                await self._run_branch(result)
            elif main_type == OrchestratorType.CONSENSUS:
                await self._run_consensus(result)
            else:
                await self._run_sequential(result, phase_template="sub_crew_{i+1}: {name}")

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

    async def _run_sequential(
        self,
        result: OrchestrationResult,
        phase_template: str = "step_{i+1}: {name}",
    ) -> None:
        """顺序执行所有子 Crew，支持 on_result 条件跳转（流程图循环）

        Args:
            result: 编排结果对象
            phase_template: Phase 名称模板，支持 {i}（执行序号）、{name}（子 Crew 名）
        """
        if not self.sub_crews:
            return

        # 建立名称→索引映射
        name_to_index = {sc.name: idx for idx, sc in enumerate(self.sub_crews)}
        visit_count = {sc.name: 0 for sc in self.sub_crews}
        step_counter = 0
        i = 0

        while i < len(self.sub_crews):
            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.error = "Aborted during sequential execution"
                return

            sub_crew = self.sub_crews[i]
            visit_count[sub_crew.name] += 1
            step_counter += 1

            # 防无限循环
            if sub_crew.on_result and sub_crew.on_result.max_iterations > 0:
                if visit_count[sub_crew.name] > sub_crew.on_result.max_iterations:
                    logger.warning(
                        f"Sub-crew '{sub_crew.name}' exceeded max_iterations "
                        f"({sub_crew.on_result.max_iterations}), stopping loop"
                    )
                    i += 1
                    continue

            phase_name = phase_template.format(
                i=step_counter, name=sub_crew.name
            )
            phase = PhaseResult(
                name=phase_name,
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
                    result.error = f"Aborted after sub-crew '{sub_crew.name}'"
                    return

                self.notify_progress(result.phases, len(self.sub_crews))

                # ── on_result 条件跳转 ──
                if sub_crew.on_result:
                    oc = sub_crew.on_result
                    actual_value = await self.context.blackboard.get(
                        oc.condition_field
                    )
                    matched = evaluate_condition(
                        actual_value, oc.condition_operator, oc.condition_value
                    )

                    logger.info(
                        f"on_result for '{sub_crew.name}': "
                        f"field='{oc.condition_field}', actual={actual_value}, "
                        f"matched={matched}, "
                        f"goto={oc.goto if matched else oc.else_goto}"
                    )

                    if matched and oc.goto and oc.goto in name_to_index:
                        # 写入跳转上下文
                        if oc.goto_context:
                            for key, value in oc.goto_context.items():
                                await self.context.blackboard.set(
                                    key, value, producer=f"goto:{sub_crew.name}"
                                )
                        i = name_to_index[oc.goto]
                        continue
                    elif not matched and oc.else_goto and oc.else_goto in name_to_index:
                        # 写入跳转上下文
                        if oc.else_goto_context:
                            for key, value in oc.else_goto_context.items():
                                await self.context.blackboard.set(
                                    key, value, producer=f"goto:{sub_crew.name}"
                                )
                        i = name_to_index[oc.else_goto]
                        continue

            except OrchestrationStopRequest:
                result.status = ExecutionStatus.ABORTED
                result.error = f"Stop during sub-crew '{sub_crew.name}'"
                return

            except Exception as e:
                logger.error(f"Sub-crew '{sub_crew.name}' failed: {e}")
                phase.status = PhaseStatus.FAILED
                phase.error = str(e)
                phase.completed_at = datetime.now(timezone.utc)
                raise

            i += 1

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

    # ── Branch 拓扑 ──

    async def _run_branch(self, result: OrchestrationResult) -> None:
        """
        分支拓扑执行。

        支持三种模式，通过 orchestrator.extras.mode 指定：
        - fan-out:    所有 sub_crews 并行执行 + 可选 aggregator 汇聚
        - condition:  基于黑板值条件判断，选择 sub_crews 中的一个执行
        - switch:     基于黑板值多路匹配，选择 sub_crews 中的一个执行

        condition/switch 通过 extras.branches 映射到 sub_crews 名称：
          {branch_name: sub_crew_name}
        """
        extras = self.crew.orchestrator.extras
        mode = extras.get("mode", "fan-out")

        if mode == "fan-out":
            await self._run_branch_fan_out(result, extras)
        elif mode == "condition":
            await self._run_branch_condition(result, extras)
        elif mode == "switch":
            await self._run_branch_switch(result, extras)
        else:
            raise ValueError(f"Unsupported branch mode: {mode}")

    # ── Fan-out ──

    async def _run_branch_fan_out(
        self, result: OrchestrationResult, extras: Dict[str, Any]
    ) -> None:
        """Fan-out: 所有 sub_crews 并行执行 + 可选 aggregator 汇聚"""
        if not self.sub_crews:
            return

        phases = []
        for sub_crew in self.sub_crews:
            phase = PhaseResult(
                name=f"branch: {sub_crew.name}",
                status=PhaseStatus.RUNNING,
                agents=[a.name for a in (sub_crew.agents or [])]
                if sub_crew.agents
                else [],
                started_at=datetime.now(timezone.utc),
            )
            phases.append(phase)
            result.phases.append(phase)

        async def run_one(sub_crew: SubCrewConfig, phase: PhaseResult) -> bool:
            try:
                sub_result = await self._run_and_check_sub_crew(sub_crew, phase)
                if sub_result is None:
                    return False
                return True
            except OrchestrationStopRequest:
                return False
            except Exception as e:
                logger.error(f"Branch sub-crew '{sub_crew.name}' failed: {e}")
                phase.status = PhaseStatus.FAILED
                phase.error = str(e)
                phase.completed_at = datetime.now(timezone.utc)
                return False

        par_results = await asyncio.gather(*[
            run_one(sc, ph) for sc, ph in zip(self.sub_crews, phases)
        ])

        self.notify_progress(result.phases, len(self.sub_crews))

        if not all(par_results):
            await self.abort()
            result.status = ExecutionStatus.ABORTED
            failed = [
                s.name for s, ok in zip(self.sub_crews, par_results) if not ok
            ]
            result.error = f"One or more branch sub-crews failed/aborted: {failed}"
            return

        # 可选聚合
        aggregator_name = extras.get("aggregator")
        if aggregator_name:
            await self._run_aggregator(result, aggregator_name, extras)

    # ── Condition ──

    async def _run_branch_condition(
        self, result: OrchestrationResult, extras: Dict[str, Any]
    ) -> None:
        """Condition: 基于黑板值条件判断，选择一个子 Crew 执行

        extras.branches: {branch_name: sub_crew_name} 名称映射
        """
        branches_data = extras.get("branches", {})
        if not branches_data:
            raise ValueError("CONDITION branch requires 'branches' in extras")

        condition_field = extras.get("condition_field")
        condition_operator = extras.get("condition_operator", "eq")
        condition_value = extras.get("condition_value")

        # 读取黑板值
        actual_value = None
        if condition_field:
            actual_value = await self.context.blackboard.get(condition_field)

        logger.info(
            f"CONDITION branch evaluating: field='{condition_field}', "
            f"actual={actual_value}, operator={condition_operator}, "
            f"target={condition_value}"
        )

        # 条件判断
        matched = evaluate_condition(
            actual_value, condition_operator, condition_value
        )

        # 选择分支：matched=True → 第一个分支, matched=False → 第二个分支(如有)
        branch_names = list(branches_data.keys())
        selected_branch_name = branch_names[0] if matched else (
            branch_names[1] if len(branch_names) > 1 else None
        )

        if selected_branch_name is None:
            logger.warning("CONDITION branch: no branch matched, skipping")
            return

        # 通过名称引用 sub_crews
        sub_crew_name = branches_data[selected_branch_name]
        sub_crew = next(
            (sc for sc in self.sub_crews if sc.name == sub_crew_name), None
        )
        if sub_crew is None:
            raise ValueError(
                f"CONDITION branch references unknown sub_crew "
                f"'{sub_crew_name}'"
            )

        phase = PhaseResult(
            name=f"condition: {selected_branch_name}",
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
                result.error = f"Aborted during condition branch '{selected_branch_name}'"
                return
            self.notify_progress(result.phases, 1)
        except OrchestrationStopRequest:
            result.status = ExecutionStatus.ABORTED
            result.error = f"Stop during condition branch '{selected_branch_name}'"
        except Exception as e:
            logger.error(f"Condition branch '{selected_branch_name}' failed: {e}")
            phase.status = PhaseStatus.FAILED
            phase.error = str(e)
            phase.completed_at = datetime.now(timezone.utc)
            raise

    # ── Switch ──

    async def _run_branch_switch(
        self, result: OrchestrationResult, extras: Dict[str, Any]
    ) -> None:
        """Switch: 基于黑板值多路匹配，选择一个子 Crew 执行

        extras.branches: {branch_name: sub_crew_name} 名称映射
        """
        branches_data = extras.get("branches", {})
        if not branches_data:
            raise ValueError("SWITCH branch requires 'branches' in extras")

        switch_field = extras.get("switch_field")
        default_branch = extras.get("default_branch")

        # 读取黑板值
        actual_value = None
        if switch_field:
            actual_value = await self.context.blackboard.get(switch_field)

        str_value = str(actual_value) if actual_value is not None else ""
        selected_branch_name = str_value if str_value in branches_data else default_branch

        logger.info(
            f"SWITCH branch matching: field='{switch_field}', "
            f"actual={actual_value}, selected={selected_branch_name}"
        )

        if selected_branch_name is None or selected_branch_name not in branches_data:
            logger.warning(
                f"SWITCH branch: no match for '{actual_value}', skipping"
            )
            return

        # 通过名称引用 sub_crews
        sub_crew_name = branches_data[selected_branch_name]
        sub_crew = next(
            (sc for sc in self.sub_crews if sc.name == sub_crew_name), None
        )
        if sub_crew is None:
            raise ValueError(
                f"SWITCH branch references unknown sub_crew "
                f"'{sub_crew_name}'"
            )

        phase = PhaseResult(
            name=f"switch: {selected_branch_name}",
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
                result.error = f"Aborted during switch branch '{selected_branch_name}'"
                return
            self.notify_progress(result.phases, 1)
        except OrchestrationStopRequest:
            result.status = ExecutionStatus.ABORTED
            result.error = f"Stop during switch branch '{selected_branch_name}'"
        except Exception as e:
            logger.error(f"Switch branch '{selected_branch_name}' failed: {e}")
            phase.status = PhaseStatus.FAILED
            phase.error = str(e)
            phase.completed_at = datetime.now(timezone.utc)
            raise

    # ── Consensus 拓扑 ──

    async def _run_consensus(self, result: OrchestrationResult) -> None:
        """
        共识拓扑执行。

        所有 sub_crews 并行执行后，按策略汇聚结果达成共识。
        配置位于 orchestrator.extras：
        - strategy: average | majority | unanimous | weighted
        - threshold: 通过阈值 (0.0 ~ 1.0)
        - weights: {sub_crew_name: weight} (weighted 策略用)
        - adjudicator: 可选，LLM 综合评议 Agent 名称
        - adjudicator_prompt: 可选，评议指令
        """
        if not self.sub_crews:
            return

        extras = self.crew.orchestrator.extras
        strategy = extras.get("strategy", "average")
        threshold = extras.get("threshold", 0.7)
        weights = extras.get("weights", {})

        # ── Phase 1: 并行执行所有 sub_crews ──
        phase1 = PhaseResult(
            name="consensus_execution",
            status=PhaseStatus.RUNNING,
            agents=[sc.name for sc in self.sub_crews],
            started_at=datetime.now(timezone.utc),
        )
        result.phases.append(phase1)

        phases = []
        for sub_crew in self.sub_crews:
            phase = PhaseResult(
                name=f"consensus: {sub_crew.name}",
                status=PhaseStatus.RUNNING,
                agents=[a.name for a in (sub_crew.agents or [])]
                if sub_crew.agents
                else [],
                started_at=datetime.now(timezone.utc),
            )
            phases.append(phase)
            result.phases.append(phase)

        async def run_one(sub_crew: SubCrewConfig, phase: PhaseResult) -> bool:
            try:
                sub_result = await self._run_and_check_sub_crew(sub_crew, phase)
                return sub_result is not None
            except OrchestrationStopRequest:
                return False
            except Exception as e:
                logger.error(f"Consensus sub-crew '{sub_crew.name}' failed: {e}")
                phase.status = PhaseStatus.FAILED
                phase.error = str(e)
                phase.completed_at = datetime.now(timezone.utc)
                return False

        par_results = await asyncio.gather(*[
            run_one(sc, ph) for sc, ph in zip(self.sub_crews, phases)
        ])
        self.notify_progress(result.phases, len(self.sub_crews) + 1)

        phase1.status = PhaseStatus.COMPLETED
        phase1.completed_at = datetime.now(timezone.utc)

        if not all(par_results):
            await self.abort()
            result.status = ExecutionStatus.ABORTED
            failed = [
                s.name for s, ok in zip(self.sub_crews, par_results) if not ok
            ]
            result.error = f"One or more consensus sub-crews failed: {failed}"
            return

        # ── Phase 2: 共识汇聚 ──
        phase2 = PhaseResult(
            name="consensus_aggregation",
            status=PhaseStatus.RUNNING,
            agents=["consensus_engine"],
            started_at=datetime.now(timezone.utc),
        )
        result.phases.append(phase2)

        consensus = await self._run_consensus_aggregate(
            strategy, threshold, weights
        )

        await self.context.blackboard.set(
            "consensus_result", consensus, producer="composite_consensus"
        )

        phase2.status = PhaseStatus.COMPLETED
        phase2.output = consensus
        phase2.completed_at = datetime.now(timezone.utc)
        self.notify_progress(result.phases, len(self.sub_crews) + 1)

        # ── Phase 3: 可选 Adjudicator LLM 综合评议 ──
        adjudicator_name = extras.get("adjudicator")
        if adjudicator_name:
            await self._run_consensus_adjudication(
                result, adjudicator_name, extras, consensus
            )

    async def _run_consensus_aggregate(
        self,
        strategy: str,
        threshold: float,
        weights: Dict[str, float],
    ) -> Dict[str, Any]:
        """共识汇聚：收集 sub_crew 结果并按策略聚合"""
        reviews_data = []
        for sub_crew in self.sub_crews:
            output = await self.context.blackboard.get(
                f"sub_crew_{sub_crew.name}"
            )
            passed = output is not None
            score = 1.0 if passed else 0.0
            reviews_data.append({
                "name": sub_crew.name,
                "score": score,
                "passed": passed,
                "output": output,
            })

        if not reviews_data:
            return {"strategy": strategy, "passed": False, "error": "No results"}

        if strategy == "average":
            scores = [r["score"] for r in reviews_data]
            avg = sum(scores) / len(scores)
            return {
                "strategy": strategy,
                "average_score": round(avg, 3),
                "passed": avg >= threshold,
                "threshold": threshold,
                "sub_crew_scores": {r["name"]: r["score"] for r in reviews_data},
                "details": {r["name"]: r["output"] for r in reviews_data if r["output"]},
            }

        elif strategy == "majority":
            passed_count = sum(1 for r in reviews_data if r["passed"])
            return {
                "strategy": strategy,
                "passed_count": passed_count,
                "total": len(reviews_data),
                "passed": passed_count > len(reviews_data) / 2,
                "threshold": threshold,
                "sub_crew_scores": {r["name"]: r["score"] for r in reviews_data},
            }

        elif strategy == "unanimous":
            all_passed = all(r["passed"] for r in reviews_data)
            return {
                "strategy": strategy,
                "passed": all_passed,
                "threshold": threshold,
                "sub_crew_scores": {r["name"]: r["score"] for r in reviews_data},
            }

        elif strategy == "weighted":
            total_weight = sum(weights.get(r["name"], 1.0) for r in reviews_data)
            if total_weight == 0:
                total_weight = 1.0
            weighted_score = sum(
                r["score"] * weights.get(r["name"], 1.0) for r in reviews_data
            ) / total_weight
            return {
                "strategy": strategy,
                "weighted_score": round(weighted_score, 3),
                "passed": weighted_score >= threshold,
                "threshold": threshold,
                "weights": weights,
                "sub_crew_scores": {r["name"]: r["score"] for r in reviews_data},
            }

        return {
            "strategy": strategy,
            "passed": False,
            "error": f"Unknown strategy: {strategy}",
        }

    async def _run_consensus_adjudication(
        self,
        result: OrchestrationResult,
        adjudicator_name: str,
        extras: Dict[str, Any],
        consensus: Dict[str, Any],
    ) -> None:
        """Adjudicator LLM 综合评议"""
        agent = self.context.get_agent(adjudicator_name)
        if agent is None:
            logger.warning(
                f"Adjudicator '{adjudicator_name}' not found, skipping"
            )
            return

        phase = PhaseResult(
            name="consensus_adjudication",
            status=PhaseStatus.RUNNING,
            agents=[adjudicator_name],
            started_at=datetime.now(timezone.utc),
        )
        result.phases.append(phase)

        # 收集各 sub_crew 的输出
        sub_results = {}
        for sub_crew in self.sub_crews:
            val = await self.context.blackboard.get(
                f"sub_crew_{sub_crew.name}"
            )
            if val:
                sub_results[sub_crew.name] = val

        adjudicator_prompt = extras.get(
            "adjudicator_prompt",
            "Review the outputs from all sub-crews and provide a final synthesis.",
        )

        prompt = PromptLoader.render(
            "composite",
            "aggregator_prompt.j2",
            prompt=adjudicator_prompt,
            results=sub_results,
        )

        from broca.execution_engine import ExecutionStatus as ES

        trigger_message = MessageProtocol.create_user_message(content=prompt)
        exec_result = await agent.run(trigger_message, from_agent=True)

        if exec_result.status == ES.COMPLETED:
            synthesis = agent.context.get_latest_assistant_message() or ""
            phase.status = PhaseStatus.COMPLETED
            phase.output = {"synthesis": synthesis}
            await self.context.blackboard.set(
                "consensus_synthesis", synthesis, producer="adjudicator"
            )
        else:
            logger.warning(f"Adjudicator failed: {exec_result.error}")
            phase.status = PhaseStatus.FAILED
            phase.error = exec_result.error

        phase.completed_at = datetime.now(timezone.utc)
        self.notify_progress(result.phases, len(self.sub_crews) + 1)

    async def _run_aggregator(
        self,
        result: OrchestrationResult,
        aggregator_name: str,
        extras: dict,
    ) -> None:
        """执行扇入汇聚"""
        # 收集所有子 Crew 的结果
        sub_results = {}
        for sub_crew in self.sub_crews:
            val = await self.context.blackboard.get(
                f"sub_crew_{sub_crew.name}"
            )
            if val:
                sub_results[sub_crew.name] = val

        agg_prompt = extras.get(
            "aggregator_prompt",
            "Synthesize the results from all sub-crews.",
        )

        agg_phase = PhaseResult(
            name="aggregation",
            status=PhaseStatus.RUNNING,
            agents=[aggregator_name],
            started_at=datetime.now(timezone.utc),
        )
        result.phases.append(agg_phase)

        agent = self.context.get_agent(aggregator_name)
        if agent is None:
            logger.warning(f"Aggregator '{aggregator_name}' not found, skipping")
            agg_phase.status = PhaseStatus.FAILED
            agg_phase.completed_at = datetime.now(timezone.utc)
            return

        prompt = PromptLoader.render(
            "composite",
            "aggregator_prompt.j2",
            prompt=agg_prompt,
            results=sub_results,
        )

        from broca.execution_engine import ExecutionStatus as ES

        trigger_message = MessageProtocol.create_user_message(content=prompt)
        exec_result = await agent.run(trigger_message, from_agent=True)

        if exec_result.status == ES.COMPLETED:
            output = agent.context.get_latest_assistant_message() or ""
            agg_phase.status = PhaseStatus.COMPLETED
            agg_phase.output = {"aggregated": output}
        else:
            logger.warning(f"Aggregator failed: {exec_result.error}")
            agg_phase.status = PhaseStatus.FAILED
            agg_phase.error = exec_result.error
        agg_phase.completed_at = datetime.now(timezone.utc)
        self.notify_progress(result.phases, len(self.sub_crews))

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
