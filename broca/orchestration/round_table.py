"""
Round-Table 圆桌拓扑编排器

多个 Agent 围绕议题进行多轮发言，可设 Moderator 控制节奏和终止条件。
Agent 通过共享讨论历史互相引用/反驳。

可选阶段：
- 主持人开场语（moderator_opening）
- 主持人结束语（moderator_closing）

发言顺序（speaker_order）：
- fixed:    每轮固定顺序（默认）
- random:   每轮随机打乱
- moderator:由 Moderator Agent 决定每轮顺序
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from broca.errors import OrchestrationError
from broca.logging_config import get_logger
from broca.orchestration.crew import AgentRole, CrewConfig
from broca.orchestration.orchestrator import (
    CrewContext,
    ExecutionStatus,
    OrchestrationResult,
    OrchestrationStopRequest,
    Orchestrator,
    PhaseResult,
    PhaseStatus,
)
from broca.orchestration.prompt_loader import PromptLoader

logger = get_logger(__name__)


class RoundTableOrchestrator(Orchestrator):
    """
    圆桌拓扑编排器

    参与者围绕议题进行多轮发言，支持三种发言顺序和可选的主持人开场/结束语。
    """

    # 发言顺序模式
    ORDER_FIXED = "fixed"
    ORDER_RANDOM = "random"
    ORDER_MODERATOR = "moderator"

    SPEAKER_ORDER_KEY = "speaker_order"

    def __init__(self, crew_config: CrewConfig, context: Optional[CrewContext] = None):
        super().__init__(crew_config, context)
        self.namespace = crew_config.name
        extras = self.crew.orchestrator.extras
        self.speaker_order = extras.get("speaker_order", self.ORDER_FIXED)
        self.moderator_opening = extras.get("moderator_opening", False)
        self.moderator_closing = extras.get("moderator_closing", False)
        self.rounds_config = extras.get("rounds", None)
        self.total_rounds = self.crew.orchestrator.max_rounds
        if self.moderator_opening:
            self.total_rounds += 1
        if self.moderator_closing:
            self.total_rounds += 1

    def _ns(self, key: str) -> str:
        return f"{self.namespace}.{key}" if self.namespace else key

    @property
    def moderator(self) -> Optional[Any]:
        """获取 Moderator Agent"""
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.MODERATOR:
                return self.context.get_agent(agent_cfg.name)
        return None

    @property
    def participants(self) -> List[Dict[str, Any]]:
        """获取所有参与者"""
        participants = []
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.PARTICIPANT:
                agent = self.context.get_agent(agent_cfg.name)
                if agent:
                    participants.append({"agent": agent, "config": agent_cfg})
        return participants

    @property
    def participant_names(self) -> List[str]:
        return [p["config"].name for p in self.participants]

    # ── 发言顺序 ──

    async def _get_moderator_order(
        self, round_num: int, order_rule: str | None = None
    ) -> List[str]:
        """
        Moderator Agent 决定本轮发言顺序。
        """
        moderator_agent = self.moderator
        if moderator_agent is None:
            return self.participant_names

        prompt = PromptLoader.render(
            "round_table",
            "moderator_order.j2",
            topic=await self.context.blackboard.get(self._ns("topic"), ""),
            participants=self.participant_names,
            round_num=round_num,
            order_rule=order_rule,
        )

        try:
            from broca.loop_engine import ExecutionStatus as ES
            from broca.session import MessageProtocol

            trigger_message = MessageProtocol.create_user_message(content=prompt)
            exec_result = await moderator_agent.run(
                trigger_message, from_agent=True, namespace=self.namespace
            )

            if exec_result.status == ES.COMPLETED:
                speaker_order = await self.blackboard.get(
                    self._ns(self.SPEAKER_ORDER_KEY), []
                )
                if not isinstance(speaker_order, list):
                    speaker_order = json.loads(speaker_order)
                return speaker_order
        except Exception as e:
            logger.warning(f"Moderator order failed: {e}")

        return []

    async def _resolve_round_speakers(
        self, round_num: int = 1, round_config: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        根据 round 配置解析本轮发言人列表及顺序。

        round_config 支持字段：
        - speakers: [name, ...]  按 agent 名称指定发言人和顺序
        - roles: [role, ...]     按角色筛选发言人
        - order: fixed | random | moderator
          fixed:    保持列表顺序
          random:   随机打乱
        - order_rule: 发言顺序的规则，用于 Moderator Agent 决定

        Returns:
            Agent 名称列表（按发言顺序）
        """
        speakers = None
        roles = None
        order = self.speaker_order
        order_rule = None
        if round_config:
            speakers = round_config.get("speakers")
            roles = round_config.get("roles")
            order = round_config.get("order", order)
            order_rule = round_config.get("order_rule")

        # 确定候选人
        candidates: List[str] = []
        if speakers:
            for name in speakers:
                if name in self.participant_names:
                    candidates.append(name)
                else:
                    raise OrchestrationError(f"Participant '{name}' not found")
        elif roles:
            role_set = set(roles)
            for p in self.participants:
                if p["config"].role.value in role_set:
                    candidates.append(p["config"].name)
        else:
            candidates = list(self.participant_names)

        if order == "random":
            random.shuffle(candidates)
        elif order == "moderator" and self.moderator:
            candidates = await self._get_moderator_order(round_num, order_rule)

        return candidates

    # ── 主执行流程 ──

    async def run(self) -> OrchestrationResult:
        """执行圆桌讨论"""
        crew_id = self.crew.name
        result = OrchestrationResult(
            crew_id=crew_id,
            status=ExecutionStatus.RUNNING,
            phases=[],
        )

        max_rounds = self.crew.orchestrator.max_rounds
        topic = await self.context.blackboard.get(self._ns("topic"), "")
        if not topic:
            result.status = ExecutionStatus.FAILED
            result.error = "No 'topic' found in Blackboard"
            return result

        discussion_history: List[Dict[str, Any]] = []
        concluded = False
        conclusion = None

        try:
            # ═══════════════════════════════════════════
            # Opening: Moderator 开场语
            # ═══════════════════════════════════════════
            if self.moderator_opening and self.moderator:
                opening_phase = PhaseResult(
                    name="opening",
                    status=PhaseStatus.RUNNING,
                    agents=[self.moderator_name()],
                    started_at=datetime.now(timezone.utc),
                )
                result.phases.append(opening_phase)

                opening = await self._moderator_speak(
                    "moderator_opening.j2",
                    topic=topic,
                    participants=self.participant_names,
                    max_rounds=max_rounds,
                )
                discussion_history.append(
                    {
                        "agent": self.moderator_name(),
                        "content": opening,
                        "round": 0,
                        "type": "opening",
                    }
                )
                self.blackboard.set(self._ns("opening"), opening)
                opening_phase.status = PhaseStatus.COMPLETED
                opening_phase.output = {"statement": opening}
                opening_phase.completed_at = datetime.now(timezone.utc)
                self.notify_progress(result.phases, self.total_rounds)

            # ═══════════════════════════════════════════
            # Discussion Rounds
            # ═══════════════════════════════════════════
            for round_idx in range(max_rounds):
                if self._check_aborted():
                    result.status = ExecutionStatus.ABORTED
                    break

                round_config = (
                    self.rounds_config[round_idx] if self.rounds_config else None
                )
                round_num = round_idx + 1
                phase_name = f"round_{round_num}"
                if round_config:
                    phase_name = round_config.get("name", phase_name)

                # 解析本轮发言人和顺序
                order = await self._resolve_round_speakers(round_num, round_config)
                if not order:
                    logger.error(f"Round {round_num} has no speakers")
                    raise OrchestrationError("Round table error")

                phase = PhaseResult(
                    name=phase_name,
                    status=PhaseStatus.RUNNING,
                    agents=order,
                    started_at=datetime.now(timezone.utc),
                )
                result.phases.append(phase)

                logger.info(
                    f"Round-Table round {round_num}: "
                    f"topic='{topic[:50]}...', speakers={order}"
                )

                round_entries = await self._run_round(
                    round_num=round_num,
                    order=order,
                    topic=topic,
                    discussion_history=discussion_history,
                    phase=phase,
                    result=result,
                )

                if result.status == ExecutionStatus.ABORTED:
                    break

                discussion_history.extend(round_entries)
                await self.context.blackboard.set(
                    self._ns("discussion_history"),
                    discussion_history,
                    producer="round_table",
                )

                phase.status = PhaseStatus.COMPLETED
                self.notify_progress(result.phases, self.total_rounds)
                phase.output = {
                    "round": round_num,
                    "entries_count": len(round_entries),
                    "speaker_order": order,
                }
                phase.completed_at = datetime.now(timezone.utc)

                # Moderator 评估是否结束
                # if self.moderator:
                #     verdict = await self._evaluate_by_moderator(
                #         discussion_history, round_num, max_rounds
                #     )
                #     if verdict.get("should_conclude", False):
                #         concluded = True
                #         conclusion = verdict.get("summary", "Discussion concluded.")
                #         break

            # ═══════════════════════════════════════════
            # Closing: Moderator 结束语
            # ═══════════════════════════════════════════
            if (
                self.moderator_closing
                and self.moderator
                and result.status != ExecutionStatus.ABORTED
            ):
                closing_phase = PhaseResult(
                    name="closing",
                    status=PhaseStatus.RUNNING,
                    agents=[self.moderator_name()],
                    started_at=datetime.now(timezone.utc),
                )
                result.phases.append(closing_phase)

                closing = await self._moderator_speak(
                    "moderator_closing.j2",
                    topic=topic,
                    rounds_completed=sum(
                        1
                        for p in result.phases
                        if p.status == PhaseStatus.COMPLETED
                        and p.name.startswith("round_")
                    ),
                )
                discussion_history.append(
                    {
                        "agent": self.moderator_name(),
                        "content": closing,
                        "round": max_rounds + 1,
                        "type": "closing",
                    }
                )
                closing_phase.status = PhaseStatus.COMPLETED
                closing_phase.output = {"statement": closing}
                closing_phase.completed_at = datetime.now(timezone.utc)
                self.notify_progress(result.phases, self.total_rounds)

        except OrchestrationStopRequest as stop_req:
            logger.warning(f"Round-Table stop requested: {stop_req}")
            await self.abort()
            result.status = ExecutionStatus.ABORTED
            result.error = str(stop_req)
            for phase in result.phases:
                if phase.status == PhaseStatus.RUNNING:
                    phase.status = PhaseStatus.FAILED
                    phase.error = str(stop_req)
                    phase.completed_at = datetime.now(timezone.utc)

        except Exception as e:
            logger.error(f"Round-Table execution failed: {e}")
            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.error = "Aborted during discussion"
            else:
                result.status = ExecutionStatus.FAILED
                result.error = str(e)

        # 结果汇总
        if result.status == ExecutionStatus.RUNNING:
            if self._check_aborted():
                result.status = ExecutionStatus.ABORTED
                result.error = "Aborted during discussion"
            else:
                result.status = ExecutionStatus.COMPLETED

        result.completed_at = datetime.now(timezone.utc)
        result.blackboard_snapshot = await self.context.blackboard.to_dict()
        result.final_output = {
            "topic": topic,
            "speaker_order_mode": self.speaker_order,
            "moderator_opening": self.moderator_opening,
            "moderator_closing": self.moderator_closing,
            "rounds_completed": sum(
                1
                for p in result.phases
                if p.status == PhaseStatus.COMPLETED and p.name.startswith("round_")
            ),
            "concluded": concluded,
            "conclusion": conclusion,
            "discussion_history": discussion_history,
        }

        return result

    # ── 辅助方法 ──

    async def _run_round(
        self,
        round_num: int,
        order: List[str],
        topic: str,
        discussion_history: List[Dict[str, Any]],
        phase: PhaseResult,
        result: OrchestrationResult,
    ) -> List[Dict[str, Any]]:
        """执行一轮发言，返回本轮发言记录列表"""
        round_entries = []
        for agent_name in order:
            if self._check_aborted():
                phase.status = PhaseStatus.FAILED
                phase.error = "Execution aborted during round"
                phase.completed_at = datetime.now(timezone.utc)
                result.status = ExecutionStatus.ABORTED
                break

            participant = None
            for p in self.participants:
                if p["config"].name == agent_name:
                    participant = p
                    break
            if participant is None:
                continue

            agent = participant["agent"]
            agent_cfg = participant["config"]

            prompt = self._build_discussion_prompt(
                topic=topic,
                round_num=round_num,
                agent_name=agent_cfg.name,
                extras=agent_cfg.extras,
                order_info=order,
            )

            response = await self._get_agent_response(agent, prompt)
            round_entries.append(
                {
                    "agent": agent_cfg.name,
                    "content": response,
                    "round": round_num,
                    "extras": agent_cfg.extras,
                }
            )

            await self.context.blackboard.set(
                self._ns(f"round_{round_num}_{agent_cfg.name}"),
                response,
                producer="round_table",
            )
        return round_entries

    def moderator_name(self) -> str:
        for agent_cfg in self.crew.agents:
            if agent_cfg.role == AgentRole.MODERATOR:
                return agent_cfg.name
        return "moderator"

    async def _moderator_speak(self, template: str, **kwargs) -> str:
        """Moderator 发言（开场/结束语）"""
        moderator_agent = self.moderator
        if moderator_agent is None:
            return ""

        prompt = PromptLoader.render("round_table", template, **kwargs)

        from broca.loop_engine import ExecutionStatus as ES
        from broca.session import MessageProtocol

        trigger_message = MessageProtocol.create_user_message(content=prompt)
        exec_result = await moderator_agent.run(
            trigger_message, from_agent=True, namespace=self.namespace
        )

        if exec_result.status == ES.COMPLETED:
            return (
                moderator_agent.context.get_latest_assistant_message()
                or "(no response)"
            )
        return f"(error: {exec_result.error})"

    def _build_discussion_prompt(
        self,
        topic: str,
        round_num: int,
        agent_name: str,
        extras: Dict[str, Any],
        order_info: List[str],
    ) -> str:
        """构建 Agent 讨论提示"""
        return PromptLoader.render(
            "round_table",
            "discussion_prompt.j2",
            topic=topic,
            round_num=round_num,
            stance=extras.get("stance", ""),
            speaker_order_info=" → ".join(order_info),
        )

    async def _get_agent_response(self, agent: Any, prompt: str) -> str:
        """获取 Agent 的讨论发言"""
        try:
            from broca.loop_engine import ExecutionStatus
            from broca.session import MessageProtocol

            trigger_message = MessageProtocol.create_user_message(content=prompt)
            execution_result = await agent.run(
                trigger_message, from_agent=True, namespace=self.namespace
            )

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
        if round_num >= max_rounds:
            return {"should_conclude": True, "summary": "Max rounds reached."}

        moderator = self.moderator
        if moderator is None:
            return {
                "should_conclude": round_num >= 3,
                "summary": "Discussion completed." if round_num >= 3 else "",
            }

        prompt = PromptLoader.render(
            "round_table",
            "moderator_evaluation.j2",
            round_num=round_num,
            max_rounds=max_rounds,
            statements_count=len(history),
        )

        try:
            from broca.loop_engine import ExecutionStatus
            from broca.session import MessageProtocol

            trigger_message = MessageProtocol.create_user_message(content=prompt)
            exec_result = await moderator.run(
                trigger_message, from_agent=True, namespace=self.namespace
            )

            if exec_result.status == ExecutionStatus.COMPLETED:
                response = moderator.context.get_latest_assistant_message() or ""
                result = self._extract_json(response)
                if result is not None:
                    return result
        except Exception:
            pass

        return {"should_conclude": round_num >= 3, "summary": "Discussion completed."}
