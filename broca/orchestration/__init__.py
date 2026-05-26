"""
Broca Orchestration Module

多 Agent 编排系统，支持多种协作拓扑：
- Pipeline: 流水线顺序执行
- Supervisor-Worker: 主管-工人层级执行
- Round-Table: 圆桌多轮讨论
- Broadcast: 广播并行分发
- Consensus: 共识评估聚合
- Composite: 组合嵌套
"""

from broca.orchestration.crew import (
    AgentRole,
    CrewConfig,
    OrchestratorConfig,
    OrchestratorType,
    TaskDefinition,
    BlackboardEntry,
)

__all__ = [
    "AgentRole",
    "CrewConfig",
    "OrchestratorConfig",
    "OrchestratorType",
    "TaskDefinition",
    "BlackboardEntry",
]
