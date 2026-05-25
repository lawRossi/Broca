"""
Round-Table 圆桌拓扑编排器

多个 Agent 围绕议题进行多轮按序发言，可设 Moderator 控制节奏和终止条件。
Agent 通过共享讨论历史互相引用/反驳。

拓扑特征：
- Moderator 控制讨论节奏和终止条件
- 多轮按序发言（每轮每个参与者发言一次）
- 讨论历史注入（Agent 可引用/反驳上一轮观点）
- Moderator 判断是否达成结论
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
    PhaseResult,
    PhaseStatus,
)

logger = get_logger(__name__)


class RoundTableOrchestrator(Orchestrator):
    """
    圆桌拓扑编排器

    参与者围绕议题进行多轮讨论，Moderator 控制节奏和终止条件。
    """

    def __init__(self, crew_config: CrewConfig, context: Optional[CrewContext] = None):
        super().__init__(crew_config, context)

    @property
    def moderator(self) -> Optional[Any]:
        """获取 Moderator Agent"""
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.MODERATOR:
                return self.context.get_agent(agent_cfg.name)
        return None

    @property
    def participants(self) -> List[Dict[str, Any]]:
        """获取所有参与者（含角色配置扩展信息）"""
        participants = []
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.PARTICIPANT:
                agent = self.context.get_agent(agent_cfg.name)
                if agent:
                    participants.append({
                        "agent": agent,
                        "config": agent_cfg,
                    })
        return participants

    async def run(self) -> OrchestrationResult:
        """执行圆桌讨论"""
        crew_id = self.crew.name
        result = OrchestrationResult(
            crew_id=crew_id,
            status=ExecutionStatus.RUNNING,
            phases=[],
        )

        max_rounds = self.crew.orchestrator.max_rounds
        topic = await self.context.blackboard.get("topic", "")
        if not topic:
            result.status = ExecutionStatus.FAILED
            result.error = "No 'topic' found in Blackboard"
            return result

        discussion_history: List[Dict[str, Any]] = []
        concluded = False
        conclusion = None

        for round_num in range(1, max_rounds + 1):
            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                break

            phase_name = f"round_{round_num}"
            phase = PhaseResult(
                name=phase_name,
                status=PhaseStatus.RUNNING,
                agents=[a["config"].name for a in self.participants],
                started_at=datetime.now(timezone.utc),
            )
            result.phases.append(phase)

            logger.info(
                f"Round-Table round {round_num}/{max_rounds}: "
                f"topic='{topic[:50]}...'"
            )

            try:
                # 本轮讨论
                round_entries = []
                for participant in self.participants:
                    agent = participant["agent"]
                    agent_cfg = participant["config"]

                    # 构建讨论提示
                    prompt = self._build_discussion_prompt(
                        topic=topic,
                        history=discussion_history,
                        round_num=round_num,
                        agent_name=agent_cfg.name,
                        extras=agent_cfg.extras,
                    )

                    # 获取 Agent 发言
                    response = await self._get_agent_response(agent, prompt)
                    round_entries.append({
                        "agent": agent_cfg.name,
                        "content": response,
                        "extras": agent_cfg.extras,
                    })

                # 记录本轮讨论
                discussion_history.extend(round_entries)
                await self.context.blackboard.set(
                    f"round_{round_num}",
                    round_entries,
                    producer="round_table",
                )
                await self.context.blackboard.set(
                    "discussion_history",
                    discussion_history,
                    producer="round_table",
                )

                phase.output = {
                    "round": round_num,
                    "entries_count": len(round_entries),
                }
                phase.status = PhaseStatus.COMPLETED
                phase.completed_at = datetime.now(timezone.utc)

                # Moderator 评估是否达成结论
                if self.moderator:
                    verdict = await self._evaluate_by_moderator(
                        discussion_history, round_num, max_rounds
                    )
                    if verdict.get("should_conclude", False):
                        concluded = True
                        conclusion = verdict.get("summary", "Discussion concluded.")
                        break

            except Exception as e:
                logger.error(f"Round {round_num} failed: {e}")
                phase.status = PhaseStatus.FAILED
                phase.error = str(e)
                phase.completed_at = datetime.now(timezone.utc)

                if round_num == max_rounds:
                    result.status = ExecutionStatus.FAILED
                    result.error = f"Last round failed: {e}"
                    break
                else:
                    continue

        # 结果汇总
        if result.status == ExecutionStatus.RUNNING:
            result.status = ExecutionStatus.COMPLETED

        result.completed_at = datetime.now(timezone.utc)
        result.blackboard_snapshot = await self.context.blackboard.to_dict()
        result.final_output = {
            "topic": topic,
            "rounds_completed": sum(
                1 for p in result.phases if p.status == PhaseStatus.COMPLETED
            ),
            "concluded": concluded,
            "conclusion": conclusion,
            "discussion_history": discussion_history,
        }

        return result

    def _build_discussion_prompt(
        self,
        topic: str,
        history: List[Dict[str, Any]],
        round_num: int,
        agent_name: str,
        extras: Dict[str, Any],
    ) -> str:
        """构建 Agent 讨论提示"""
        parts = [f"## Discussion Topic\n{topic}\n"]

        if history:
            parts.append("## Previous Discussion\n")
            for entry in history[-10:]:  # 最多展示最近 10 条
                parts.append(f"[{entry['agent']}]: {entry['content'][:300]}")
            parts.append("")

        stance = extras.get("stance", "")
        if stance:
            parts.append(f"\n## Your Stance\nYou are arguing from the **{stance}** perspective.")

        parts.append(f"\n## Your Turn (Round {round_num})")
        parts.append("Please provide your perspective on the topic. "
                     "You can agree, disagree, or build upon previous speakers' points.")

        return "\n".join(parts)

    async def _get_agent_response(self, agent: Any, prompt: str) -> str:
        """获取 Agent 的讨论发言"""
        try:
            from broca.session import MessageProtocol
            from broca.execution_engine import ExecutionStatus

            trigger_message = MessageProtocol.create_user_message(content=prompt)
            execution_result = await agent.run(trigger_message, from_agent=True)

            if execution_result.status == ExecutionStatus.COMPLETED:
                return agent.context.get_latest_assistant_message() or "(no response)"
            else:
                return f"(error: {execution_result.error})"
        except Exception as e:
            logger.error(f"Agent response error: {e}")
            return f"(error: {e})"

    async def _evaluate_by_moderator(
        self,
        history: List[Dict[str, Any]],
        round_num: int,
        max_rounds: int,
    ) -> Dict[str, Any]:
        """Moderator 评估是否应结束讨论"""
        # 最后一轮自动结束
        if round_num >= max_rounds:
            return {"should_conclude": True, "summary": "Max rounds reached."}

        # 简化实现：由 Moderator Agent 判断
        moderator = self.moderator
        if moderator is None:
            # 无 Moderator 时，3 轮后自动结束
            return {
                "should_conclude": round_num >= 3,
                "summary": "Discussion completed." if round_num >= 3 else "",
            }

        prompt = (
            f"As moderator, evaluate the discussion so far.\n"
            f"Round {round_num} of {max_rounds}.\n"
            f"Total statements: {len(history)}.\n\n"
            f"Should we conclude the discussion? "
            f"Reply with a JSON: {{\"should_conclude\": true/false, \"summary\": \"...\"}}"
        )

        try:
            from broca.session import MessageProtocol
            from broca.execution_engine import ExecutionStatus

            trigger_message = MessageProtocol.create_user_message(content=prompt)
            execution_result = await moderator.run(trigger_message, from_agent=True)

            if execution_result.status == ExecutionStatus.COMPLETED:
                response = moderator.context.get_latest_assistant_message() or "{}"
                import json
                # Try to extract JSON from response
                try:
                    return json.loads(response)
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception:
            pass

        return {"should_conclude": round_num >= 3, "summary": "Discussion completed."}
