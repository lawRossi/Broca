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

    @property
    def blackboard(self) -> Blackboard:
        return self.context.blackboard

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


# 黑板约定 key：Agent 向此 key 写入停止信号来请求终止编排
STOP_ORCHESTRATION_KEY = "orchestration.stop"


class OrchestrationStopRequest(Exception):
    """
    Agent 通过黑板约定请求停止编排时抛出的异常。

    编排器在 Agent 执行完毕后检查黑板 key `orchestration.stop`，
    如果存在则抛出此异常，由 run() 捕获后调用 self.abort() 优雅终止。
    """

    def __init__(self, agent_name: str, reason: str):
        self.agent_name = agent_name
        self.reason = reason
        super().__init__(f"Orchestration stop requested by '{agent_name}': {reason}")


async def check_blackboard_for_stop(blackboard) -> None:
    """
    检查黑板中是否有编排停止信号。

    所有编排模式的 run() 方法应当在每个 Agent 执行完毕后调用此函数。
    如果黑板中存在 `orchestration.stop` key，则抛出 OrchestrationStopRequest。

    Args:
        blackboard: Blackboard 实例

    Raises:
        OrchestrationStopRequest: 如果黑板中存在停止信号
    """
    stop_signal = await blackboard.get(STOP_ORCHESTRATION_KEY)
    if stop_signal is not None:
        agent_name = stop_signal.get("agent", "unknown")
        reason = stop_signal.get("reason", "No reason")
        # 清除信号，防止重复触发
        await blackboard.delete(STOP_ORCHESTRATION_KEY, producer="orchestrator")
        raise OrchestrationStopRequest(agent_name, reason)


# ============================================================================
# 共享并行执行工具
# ============================================================================


async def execute_agents_in_parallel(
    context: CrewContext,
    tasks: List[Tuple[str, str]],
    namespace: Optional[str] = None,
) -> Dict[str, str]:
    """
    并行执行多个 Agent 任务（共享工具，供 fan-out / Broadcast 共用）

    对每个 (agent_name, task_prompt) 创建用户消息并调用 agent.run()，
    所有任务通过 asyncio.gather 并行执行。

    Args:
        context: Crew 上下文（通过 get_agent 获取 Agent 实例）
        tasks: (agent_name, task_prompt) 列表
        namespace: 可选命名空间，传递给 agent.run() 以便工具正确读写黑板

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
            execution_result = await agent.run(
                trigger_message, from_agent=True, namespace=namespace
            )

            from broca.loop_engine import ExecutionStatus as ES

            if execution_result.status == ES.COMPLETED:
                message = agent.context.get_latest_assistant_message()
                # 检查黑板中是否有停止编排信号
                await check_blackboard_for_stop(context.blackboard)
                return (agent_name, message or "(no output)")
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


# ============================================================================
# 条件表达式求值（Pipeline condition 和 Composite branch 共用）
# ============================================================================


def evaluate_condition(
    actual_value: Any,
    operator: str,
    target_value: Any,
) -> bool:
    """
    求值条件表达式

    Args:
        actual_value: 实际值（从黑板读取）
        operator: 比较运算符 (eq, ne, gt, gte, lt, lte, contains, startswith, endswith)
        target_value: 目标值

    Returns:
        是否满足条件
    """
    ops = {
        "eq": lambda a, b: a == b,
        "ne": lambda a, b: a != b,
        "gt": lambda a, b: (a is not None and b is not None) and a > b,
        "gte": lambda a, b: (a is not None and b is not None) and a >= b,
        "lt": lambda a, b: (a is not None and b is not None) and a < b,
        "lte": lambda a, b: (a is not None and b is not None) and a <= b,
        "contains": lambda a, b: b in (a or ""),
        "startswith": lambda a, b: str(a or "").startswith(str(b)),
        "endswith": lambda a, b: str(a or "").endswith(str(b)),
    }

    op_fn = ops.get(operator)
    if op_fn is None:
        logger.warning(f"Unknown condition operator '{operator}', falling back to eq")
        return ops["eq"](actual_value, target_value)

    try:
        return bool(op_fn(actual_value, target_value))
    except (TypeError, ValueError) as e:
        logger.warning(f"Condition evaluation error ({operator}): {e}")
        return False


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
