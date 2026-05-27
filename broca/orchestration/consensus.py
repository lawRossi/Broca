"""
Consensus 共识拓扑编排器

多个 Agent 独立评估同一产物（代码/文档/方案），通过评分/投票达成共识。

拓扑特征：
- 多个 Reviewer 独立评估目标
- 支持 4 种聚合策略（average/majority/unanimous/weighted）
- 通过阈值可配置
- 分歧点标记（minority report）
"""

from __future__ import annotations

import asyncio
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
)

logger = get_logger(__name__)


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


class ConsensusOrchestrator(Orchestrator):
    """
    共识拓扑编排器

    多个 Reviewer 独立评估，按策略聚合达成共识。
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
            result.error = f"Unsupported strategy: '{strategy}'. Choose from: {self.STRATEGIES}"
            return result

        try:
            # Phase 1: 所有 Reviewer 独立评估
            phase1 = PhaseResult(
                name="independent_reviews",
                status=PhaseStatus.RUNNING,
                agents=[r["config"].name for r in self.reviewers],
                started_at=datetime.now(timezone.utc),
            )
            result.phases.append(phase1)

            reviews = await self._collect_reviews(review_target)
            await self.context.blackboard.set("reviews", [r.to_dict() for r in reviews])

            phase1.status = PhaseStatus.COMPLETED
            self.notify_progress(result.phases)
            phase1.output = {"reviews_count": len(reviews)}
            phase1.completed_at = datetime.now(timezone.utc)

            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.completed_at = datetime.now(timezone.utc)
                return result

            # Phase 2: 共识引擎聚合
            phase2 = PhaseResult(
                name="consensus_aggregation",
                status=PhaseStatus.RUNNING,
                agents=["consensus_engine"],
                started_at=datetime.now(timezone.utc),
            )
            result.phases.append(phase2)

            consensus = self._aggregate(reviews, strategy, threshold)
            await self.context.blackboard.set("consensus_result", consensus)

            phase2.status = PhaseStatus.COMPLETED
            self.notify_progress(result.phases)
            phase2.output = consensus
            phase2.completed_at = datetime.now(timezone.utc)

            result.status = ExecutionStatus.COMPLETED

        except Exception as e:
            logger.error(f"Consensus execution failed: {e}")
            result.status = ExecutionStatus.FAILED
            result.error = str(e)

        result.completed_at = datetime.now(timezone.utc)
        result.blackboard_snapshot = await self.context.blackboard.to_dict()
        result.final_output = {
            "review_target": review_target,
            "strategy": strategy,
            "threshold": threshold,
            "consensus": consensus if 'consensus' in dir() else None,
            "reviews": [r.to_dict() for r in reviews] if 'reviews' in dir() else [],
        }

        return result

    async def _collect_reviews(self, review_target: str) -> List[ReviewResult]:
        """收集所有 Reviewer 的独立评估"""

        async def review_single(reviewer: Dict[str, Any]) -> ReviewResult:
            agent = reviewer["agent"]
            agent_cfg = reviewer["config"]

            prompt = (
                f"Please review the following:\n\n{review_target}\n\n"
                f"Provide your evaluation as a JSON:\n"
                f'{{"score": <0.0-1.0>, "summary": "...", "issues": ["..."]}}\n'
                f"Score above 0.7 means passing."
            )

            try:
                from broca.session import MessageProtocol
                from broca.execution_engine import ExecutionStatus

                trigger_message = MessageProtocol.create_user_message(content=prompt)
                execution_result = await agent.run(trigger_message, from_agent=True)

                if execution_result.status == ExecutionStatus.COMPLETED:
                    response = agent.context.get_latest_assistant_message() or "{}"
                    import json
                    try:
                        data = json.loads(response)
                        score = float(data.get("score", 0.5))
                        return ReviewResult(
                            reviewer=agent_cfg.name,
                            score=score,
                            passed=score >= 0.7,
                            summary=data.get("summary", ""),
                            issues=data.get("issues", []),
                        )
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass

                return ReviewResult(
                    reviewer=agent_cfg.name,
                    score=0.5,
                    passed=False,
                    summary="Could not parse review response",
                    issues=["Review format error"],
                )
            except Exception as e:
                return ReviewResult(
                    reviewer=agent_cfg.name,
                    score=0.0,
                    passed=False,
                    summary=f"Error: {e}",
                    issues=[str(e)],
                )

        results = await asyncio.gather(*[review_single(r) for r in self.reviewers])
        return list(results)

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

        return {"strategy": strategy, "passed": False, "error": f"Unknown strategy: {strategy}"}

    def _find_minority_issues(self, reviews: List[ReviewResult]) -> List[str]:
        """找出分歧点"""
        all_issues = []
        for r in reviews:
            if not r.passed and r.issues:
                all_issues.append(f"[{r.reviewer}]: {'; '.join(r.issues)}")
        return all_issues
