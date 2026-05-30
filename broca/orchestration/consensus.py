"""
Consensus 共识拓扑编排器

多个 Agent 独立评估同一产物（代码/文档/方案），通过评分/投票达成共识。

拓扑特征：
- 多个 Reviewer 独立评估（通过 write_blackboard 记录结果）
- 支持 4 种聚合策略（average/majority/unanimous/weighted）
- 可选 Adjudicator Agent 进行 LLM 综合评议
- 通过阈值可配置
- 分歧点标记（minority report）
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from broca.logging_config import get_logger
from broca.orchestration.crew import AgentRole, CrewConfig
from broca.orchestration.orchestrator import (
    CrewContext,
    ExecutionStatus,
    OrchestrationResult,
    Orchestrator,
    OrchestrationStopRequest,
    PhaseResult,
    PhaseStatus,
    execute_agents_in_parallel,
)
from broca.orchestration.prompt_loader import PromptLoader

logger = get_logger(__name__)

# 黑板 key 约定
REVIEWS_PREFIX = "reviews."


class ReviewResult:
    """单个 Reviewer 的评估结果"""

    def __init__(
        self,
        reviewer: str,
        score: float,
        passed: bool,
        summary: str,
        issues: Optional[List[str]] = None,
    ):
        self.reviewer = reviewer
        self.score = score
        self.passed = passed
        self.summary = summary
        self.issues = issues or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reviewer": self.reviewer,
            "score": self.score,
            "passed": self.passed,
            "summary": self.summary,
            "issues": self.issues,
        }

    @classmethod
    def from_blackboard(cls, reviewer: str, data: dict) -> "ReviewResult":
        """从黑板数据构建 ReviewResult"""
        score = float(data.get("score", 0.5))
        threshold = float(data.get("threshold", 0.7))
        return cls(
            reviewer=reviewer,
            score=score,
            passed=score >= threshold,
            summary=data.get("summary", ""),
            issues=data.get("issues", []),
        )


class ConsensusOrchestrator(Orchestrator):
    """
    共识拓扑编排器

    多个 Reviewer 独立评估（通过 write_blackboard 记录），
    按策略聚合，可选 Adjudicator LLM 综合评议。
    """

    STRATEGIES = ["average", "majority", "unanimous", "weighted"]

    def __init__(self, crew_config: CrewConfig, context: Optional[CrewContext] = None):
        super().__init__(crew_config, context)

    @property
    def reviewers(self) -> List[Dict[str, Any]]:
        """获取所有 Reviewer"""
        reviewers = []
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.REVIEWER:
                agent = self.context.get_agent(agent_cfg.name)
                if agent:
                    reviewers.append({"agent": agent, "config": agent_cfg})
        return reviewers

    @property
    def reviewer_names(self) -> List[str]:
        return [r["config"].name for r in self.reviewers]

    @property
    def adjudicator(self) -> Optional[Any]:
        """获取 Adjudicator Agent（用于 LLM 综合评议）"""
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.ADJUDICATOR:
                return self.context.get_agent(agent_cfg.name)
        return None

    async def run(self) -> OrchestrationResult:
        """执行共识编排"""
        crew_id = self.crew.name
        result = OrchestrationResult(
            crew_id=crew_id,
            status=ExecutionStatus.RUNNING,
            phases=[],
        )

        review_target = await self.context.blackboard.get("review_target", "")
        if not review_target:
            result.status = ExecutionStatus.FAILED
            result.error = "No 'review_target' found in Blackboard"
            return result

        strategy = self.crew.orchestrator.strategy or "average"
        threshold = self.crew.orchestrator.threshold or 0.7

        if strategy not in self.STRATEGIES:
            result.status = ExecutionStatus.FAILED
            result.error = (
                f"Unsupported strategy: '{strategy}'. "
                f"Choose from: {self.STRATEGIES}"
            )
            return result

        try:
            # ═══════════════════════════════════════════
            # Phase 1: Reviewer 独立评估
            # ═══════════════════════════════════════════
            phase1 = PhaseResult(
                name="independent_reviews",
                status=PhaseStatus.RUNNING,
                agents=self.reviewer_names,
                started_at=datetime.now(timezone.utc),
            )
            result.phases.append(phase1)

            await self._collect_reviews(review_target, threshold)

            # 从黑板读取 reviews
            reviews = await self._read_reviews(threshold)

            phase1.status = PhaseStatus.COMPLETED
            self.notify_progress(result.phases, 3)
            phase1.output = {"reviews_count": len(reviews)}
            phase1.completed_at = datetime.now(timezone.utc)

            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.completed_at = datetime.now(timezone.utc)
                return result

            # ═══════════════════════════════════════════
            # Phase 2: 共识引擎聚合
            # ═══════════════════════════════════════════
            phase2 = PhaseResult(
                name="consensus_aggregation",
                status=PhaseStatus.RUNNING,
                agents=["consensus_engine"],
                started_at=datetime.now(timezone.utc),
            )
            result.phases.append(phase2)

            consensus = self._aggregate(reviews, strategy, threshold)
            await self.context.blackboard.set(
                "consensus_result", consensus, producer="consensus_engine"
            )

            phase2.status = PhaseStatus.COMPLETED
            self.notify_progress(result.phases, 3)
            phase2.output = consensus
            phase2.completed_at = datetime.now(timezone.utc)

            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.error = "Aborted during consensus aggregation"
                result.completed_at = datetime.now(timezone.utc)
                return result

            # ═══════════════════════════════════════════
            # Phase 3: Adjudicator LLM 综合评议（可选）
            # ═══════════════════════════════════════════
            if self.adjudicator:
                phase3 = PhaseResult(
                    name="adjudication",
                    status=PhaseStatus.RUNNING,
                    agents=[self._adjudicator_name()],
                    started_at=datetime.now(timezone.utc),
                )
                result.phases.append(phase3)

                synthesis = await self._adjudicate(
                    review_target, reviews, strategy, threshold, consensus
                )
                consensus["synthesis"] = synthesis
                await self.context.blackboard.set(
                    "consensus_synthesis", synthesis, producer="adjudicator"
                )

                phase3.status = PhaseStatus.COMPLETED
                self.notify_progress(result.phases, 3)
                phase3.output = {"synthesis": synthesis}
                phase3.completed_at = datetime.now(timezone.utc)

            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.error = "Aborted during adjudication"
            else:
                result.status = ExecutionStatus.COMPLETED

        except OrchestrationStopRequest as stop_req:
            logger.warning(f"Consensus stop requested: {stop_req}")
            await self.abort()
            result.status = ExecutionStatus.ABORTED
            result.error = str(stop_req)
            for phase in result.phases:
                if phase.status == PhaseStatus.RUNNING:
                    phase.status = PhaseStatus.FAILED
                    phase.error = str(stop_req)
                    phase.completed_at = datetime.now(timezone.utc)

        except Exception as e:
            logger.error(f"Consensus execution failed: {e}")
            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.error = "Aborted during consensus execution"
            else:
                result.status = ExecutionStatus.FAILED
                result.error = str(e)

        result.completed_at = datetime.now(timezone.utc)
        result.blackboard_snapshot = await self.context.blackboard.to_dict()
        result.final_output = {
            "review_target": review_target,
            "strategy": strategy,
            "threshold": threshold,
            "consensus": consensus if "consensus" in dir() else None,
            "reviews": [r.to_dict() for r in reviews] if "reviews" in dir() else [],
        }

        return result

    # ═══════════════════════════════════════════════
    # Phase 1: Reviewer 独立评估
    # ═══════════════════════════════════════════════

    async def _collect_reviews(
        self, review_target: str, threshold: float
    ) -> None:
        """
        所有 Reviewer 并行评估，通过 write_blackboard 记录结果到黑板。
        """
        tasks = []
        for reviewer in self.reviewers:
            prompt = PromptLoader.render(
                "consensus",
                "review_prompt.j2",
                review_target=review_target,
                threshold=threshold,
                agent_name=reviewer["config"].name,
            )
            tasks.append((reviewer["config"].name, prompt))

        await execute_agents_in_parallel(self.context, tasks)

    async def _read_reviews(self, threshold: float) -> List[ReviewResult]:
        """从黑板读取所有 Reviewer 的评估结果"""
        reviews = []
        for reviewer_name in self.reviewer_names:
            data = await self.context.blackboard.get(
                f"{REVIEWS_PREFIX}{reviewer_name}"
            )
            if data and isinstance(data, dict):
                data["threshold"] = threshold
                reviews.append(ReviewResult.from_blackboard(reviewer_name, data))
            else:
                logger.warning(
                    f"No review found for '{reviewer_name}' in blackboard"
                )
        return reviews

    # ═══════════════════════════════════════════════
    # Phase 2: 共识引擎聚合
    # ═══════════════════════════════════════════════

    def _aggregate(
        self,
        reviews: List[ReviewResult],
        strategy: str,
        threshold: float,
    ) -> Dict[str, Any]:
        """按策略聚合评分"""
        if not reviews:
            return {"strategy": strategy, "passed": False, "error": "No reviews"}

        if strategy == "average":
            scores = [r.score for r in reviews]
            avg_score = sum(scores) / len(scores)
            return {
                "strategy": strategy,
                "average_score": round(avg_score, 3),
                "passed": avg_score >= threshold,
                "threshold": threshold,
                "scores": {r.reviewer: r.score for r in reviews},
                "minority_issues": self._find_minority_issues(reviews),
            }

        elif strategy == "majority":
            passed_count = sum(1 for r in reviews if r.passed)
            return {
                "strategy": strategy,
                "passed_count": passed_count,
                "total": len(reviews),
                "passed": passed_count > len(reviews) / 2,
                "threshold": threshold,
                "scores": {r.reviewer: r.score for r in reviews},
                "minority_issues": self._find_minority_issues(reviews),
            }

        elif strategy == "unanimous":
            all_passed = all(r.passed for r in reviews)
            return {
                "strategy": strategy,
                "passed": all_passed,
                "threshold": threshold,
                "scores": {r.reviewer: r.score for r in reviews},
                "minority_issues": self._find_minority_issues(reviews),
            }

        elif strategy == "weighted":
            weights = self.crew.orchestrator.weights or {}
            total_weight = sum(weights.get(r.reviewer, 1.0) for r in reviews)
            if total_weight == 0:
                total_weight = 1.0
            weighted_score = sum(
                r.score * weights.get(r.reviewer, 1.0) for r in reviews
            ) / total_weight
            return {
                "strategy": strategy,
                "weighted_score": round(weighted_score, 3),
                "passed": weighted_score >= threshold,
                "threshold": threshold,
                "weights": weights,
                "scores": {r.reviewer: r.score for r in reviews},
                "minority_issues": self._find_minority_issues(reviews),
            }

        return {
            "strategy": strategy,
            "passed": False,
            "error": f"Unknown strategy: {strategy}",
        }

    def _find_minority_issues(self, reviews: List[ReviewResult]) -> List[str]:
        """找出分歧点"""
        all_issues = []
        for r in reviews:
            if not r.passed and r.issues:
                all_issues.append(f"[{r.reviewer}]: {'; '.join(r.issues)}")
        return all_issues

    # ═══════════════════════════════════════════════
    # Phase 3: Adjudicator LLM 综合评议（可选）
    # ═══════════════════════════════════════════════

    def _adjudicator_name(self) -> str:
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.ADJUDICATOR:
                return agent_cfg.name
        return "adjudicator"

    async def _adjudicate(
        self,
        review_target: str,
        reviews: List[ReviewResult],
        strategy: str,
        threshold: float,
        consensus: Dict[str, Any],
    ) -> str:
        """Adjudicator Agent LLM 综合评议"""
        adjudicator_agent = self.adjudicator
        if adjudicator_agent is None:
            return ""

        prompt = PromptLoader.render(
            "consensus",
            "adjudicator_prompt.j2",
            review_target=review_target,
            strategy=strategy,
            threshold=threshold,
            passed=consensus.get("passed", False),
            reviews=[r.to_dict() for r in reviews],
            **consensus,
        )

        from broca.session import MessageProtocol
        from broca.execution_engine import ExecutionStatus as ES

        trigger_message = MessageProtocol.create_user_message(content=prompt)
        exec_result = await adjudicator_agent.run(trigger_message, from_agent=True)

        if exec_result.status == ES.COMPLETED:
            return (
                adjudicator_agent.context.get_latest_assistant_message()
                or "Adjudication completed (no output)"
            )
        else:
            logger.warning(
                f"Adjudicator failed: {exec_result.error}, skipping synthesis"
            )
            return ""
