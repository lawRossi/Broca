"""
Orchestrator 基类模块

定义编排器的通用抽象接口和工厂方法。
- Orchestrator 抽象基类
- OrchestrationResult 结果模型
- OrchestratorFactory 工厂方法
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from broca.logging_config import get_logger
from broca.orchestration.blackboard import Blackboard
from broca.orchestration.crew import (
    CrewConfig,
    OrchestratorType,
)
from broca.session import MessageProtocol
from broca.tools.end_execution import STOP_ORCHESTRATION_MARKER

logger = get_logger(__name__)


class ExecutionStatus(str, Enum):
    """编排执行状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class PhaseStatus(str, Enum):
    """阶段执行状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PhaseResult:
    """阶段执行结果"""

    name: str
    status: PhaseStatus
    agents: List[str]
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "agents": self.agents,
            "output": self.output,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
        }


@dataclass
class OrchestrationResult:
    """编排执行结果"""

    crew_id: str
    status: ExecutionStatus
    phases: List[PhaseResult] = field(default_factory=list)
    blackboard_snapshot: Optional[Dict[str, Any]] = None
    final_output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "crew_id": self.crew_id,
            "status": self.status.value,
            "phases": [p.to_dict() for p in self.phases],
            "blackboard_snapshot": self.blackboard_snapshot,
            "final_output": self.final_output,
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
        }

    @property
    def is_success(self) -> bool:
        return self.status == ExecutionStatus.COMPLETED

    @property
    def current_phase(self) -> Optional[str]:
        for phase in self.phases:
            if phase.status == PhaseStatus.RUNNING:
                return phase.name
        return None

    @property
    def progress(self) -> float:
        if not self.phases:
            return 0.0
        completed = sum(1 for p in self.phases if p.status == PhaseStatus.COMPLETED)
        return completed / len(self.phases)


class CrewContext:
    """
    Crew 执行上下文

    包含编排执行过程中所需的内部引用。
    """

    def __init__(
        self,
        crew_config: CrewConfig,
        blackboard: Blackboard,
        agent_factory: Any = None,
        session_manager: Any = None,
    ):
        self.crew_config = crew_config
        self.blackboard = blackboard
        self.agent_factory = agent_factory
        self.session_manager = session_manager
        self._agents: Dict[str, Any] = {}

    def register_agent(self, name: str, agent: Any) -> None:
        """注册 Agent 实例"""
        self._agents[name] = agent

    def get_agent(self, name: str) -> Any:
        """获取 Agent 实例"""
        return self._agents.get(name)

    def get_agents_by_role(self, role: str) -> List[Any]:
        """按角色获取 Agent 实例列表"""
        return [
            agent
            for agent_config, agent in zip(
                self.crew_config.agents, self._agents.values()
            )
            if agent_config.role.value == role
        ]

    @property
    def all_agents(self) -> Dict[str, Any]:
        return dict(self._agents)

    async def initialize_agents(self) -> None:
        """
        初始化所有 Agent 实例。

        通过 AgentFactory 创建 Agent，注入 Blackboard 上下文。
        """
        if not self.agent_factory:
            logger.warning("No agent_factory provided, skipping agent initialization")
            return

        for agent_cfg in self.crew_config.agents:
            # 加载 Agent 配置
            config_path = agent_cfg.config
            # TODO: 从配置路径加载 Agent，通过 agent_factory 创建
            logger.info(f"Would initialize agent: {agent_cfg.name} from {config_path}")
            # self.register_agent(agent_cfg.name, agent)


class Orchestrator(ABC):
    """
    编排器抽象基类

    所有拓扑编排器继承此类，实现 run() 方法。
    """

    def __init__(self, crew_config: CrewConfig, context: Optional[CrewContext] = None):
        self.crew = crew_config
        self.context = context or CrewContext(
            crew_config=crew_config,
            blackboard=Blackboard(),
        )
        self._aborted = False
        self._result: Optional[OrchestrationResult] = None
        # 进度回调（由 CrewOrchestratorRunner 设置，阶段完成时推送实时进度）
        self.progress_callback = None

    def notify_progress(self, phases: List[Any], total: int) -> None:
        """阶段完成时回调，推送实时进度（由子编排器在阶段完成后调用）

        Args:
            phases: 当前已完成的阶段列表
            total: 预期总阶段数（用于正确计算进度百分比）
        """
        if self.progress_callback:
            self.progress_callback(phases, total)

    @property
    def name(self) -> str:
        return self.crew.name

    @property
    def orchestrator_type(self) -> OrchestratorType:
        return self.crew.orchestrator.type

    @abstractmethod
    async def run(self) -> OrchestrationResult:
        """
        执行编排

        Returns:
            OrchestrationResult 编排执行结果
        """
        pass

    async def abort(self) -> None:
        """中止编排执行"""
        self._aborted = True
        logger.info(f"Orchestrator '{self.name}' aborted")

    @property
    def is_aborted(self) -> bool:
        return self._aborted

    def _check_aborted(self) -> bool:
        """检查是否被中止，并返回中止状态"""
        if self._aborted:
            logger.info(f"Orchestrator '{self.name}' execution aborted")
        return self._aborted


# ============================================================================
# OrchestrationStopRequest — Agent 请求停止编排
# ============================================================================


class OrchestrationStopRequest(Exception):
    """
    Agent 通过 end_execution 工具请求停止编排时抛出的异常。

    编排器的 run() 方法应当捕获此异常并调用 self.abort() 来优雅终止。
    """

    def __init__(self, agent_name: str, reason: str):
        self.agent_name = agent_name
        self.reason = reason
        super().__init__(f"Orchestration stop requested by '{agent_name}': {reason}")


def check_agent_output_for_stop(
    agent_name: str,
    output: str,
) -> None:
    """
    检查 Agent 输出中是否包含编排停止标记。

    如果包含，抛出 OrchestrationStopRequest 异常。
    此函数供 _execute_agent、fan-out、Broadcast 等调用处使用。

    Args:
        agent_name: Agent 名称（用于异常信息）
        output: Agent 的输出文本

    Raises:
        OrchestrationStopRequest: 如果输出包含停止标记
    """
    if STOP_ORCHESTRATION_MARKER in output:
        # 提取原因
        reason = output.split(STOP_ORCHESTRATION_MARKER, 1)[-1].strip().strip(": ")
        raise OrchestrationStopRequest(agent_name, reason)


# ============================================================================
# 共享并行执行工具
# ============================================================================


async def execute_agents_in_parallel(
    context: CrewContext,
    tasks: List[Tuple[str, str]],
) -> Dict[str, str]:
    """
    并行执行多个 Agent 任务（共享工具，供 fan-out / Broadcast 共用）

    对每个 (agent_name, task_prompt) 创建用户消息并调用 agent.run()，
    所有任务通过 asyncio.gather 并行执行。

    Args:
        context: Crew 上下文（通过 get_agent 获取 Agent 实例）
        tasks: (agent_name, task_prompt) 列表

    Returns:
        {agent_name: output} 字典，每个 Agent 的输出或错误信息
    """

    async def _execute_one(agent_name: str, prompt: str) -> Tuple[str, str]:
        agent = context.get_agent(agent_name)
        if agent is None:
            logger.warning(f"Agent '{agent_name}' not found, skipping")
            return (agent_name, f"Error: Agent '{agent_name}' not found")

        try:
            trigger_message = MessageProtocol.create_user_message(content=prompt)
            execution_result = await agent.run(trigger_message, from_agent=True)

            from broca.execution_engine import ExecutionStatus as ES

            if execution_result.status == ES.COMPLETED:
                message = agent.context.get_latest_assistant_message()
                # 检查是否请求停止编排
                output = message or "(no output)"
                check_agent_output_for_stop(agent_name, output)
                return (agent_name, output)
            elif execution_result.status == ES.ABORTED:
                return (agent_name, "Error: Execution aborted by user")
            else:
                return (agent_name, f"Error: {execution_result.error}")
        except OrchestrationStopRequest:
            raise
        except Exception as e:
            logger.error(f"Agent '{agent_name}' execution error: {e}")
            return (agent_name, f"Error: {e}")

    results = await asyncio.gather(
        *[_execute_one(agent, prompt) for agent, prompt in tasks]
    )
    return dict(results)


class OrchestratorFactory:
    """
    编排器工厂

    根据 OrchestratorType 创建对应的编排器实例。
    """

    _ORCHESTRATOR_MAP = {
        OrchestratorType.PIPELINE: (
            "broca.orchestration.pipeline",
            "PipelineOrchestrator",
        ),
        OrchestratorType.SUPERVISOR_WORKER: (
            "broca.orchestration.supervisor_worker",
            "SupervisorWorkerOrchestrator",
        ),
        OrchestratorType.ROUND_TABLE: (
            "broca.orchestration.round_table",
            "RoundTableOrchestrator",
        ),
        OrchestratorType.BROADCAST: (
            "broca.orchestration.broadcast",
            "BroadcastOrchestrator",
        ),
        OrchestratorType.CONSENSUS: (
            "broca.orchestration.consensus",
            "ConsensusOrchestrator",
        ),
        OrchestratorType.COMPOSITE: (
            "broca.orchestration.composite",
            "CompositeOrchestrator",
        ),
    }

    @staticmethod
    def create(
        crew_config: CrewConfig,
        context: Optional[CrewContext] = None,
    ) -> Orchestrator:
        """
        根据 CrewConfig 创建编排器实例

        Args:
            crew_config: Crew 编排配置
            context: 可选的 Crew 执行上下文

        Returns:
            Orchestrator 实例

        Raises:
            ValueError: 不支持的编排器类型
        """
        otype = crew_config.orchestrator.type

        mapping = OrchestratorFactory._ORCHESTRATOR_MAP
        if otype not in mapping:
            raise ValueError(f"Unsupported orchestrator type: {otype}")

        module_path, class_name = mapping[otype]
        try:
            import importlib

            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            return cls(crew_config, context)
        except (ImportError, AttributeError) as e:
            raise ImportError(
                f"Orchestrator module for '{otype.value}' not yet implemented. "
                f"Please implement {module_path}.{class_name}. Error: {e}"
            )
