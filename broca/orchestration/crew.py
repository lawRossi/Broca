"""
Crew 定义模块

定义编排单元的核心数据结构：
- CrewConfig: 编排配置
- AgentRole: Agent 角色
- OrchestratorConfig: 编排器配置
- TaskDefinition: 任务定义
- BlackboardEntry: 黑板初始条目
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class OrchestratorType(str, Enum):
    """编排器拓扑类型枚举"""

    PIPELINE = "pipeline"
    SUPERVISOR_WORKER = "supervisor-worker"
    ROUND_TABLE = "round-table"
    BROADCAST = "broadcast"
    CONSENSUS = "consensus"
    COMPOSITE = "composite"


class AgentRole(str, Enum):
    """Agent 角色枚举"""

    SUPERVISOR = "supervisor"
    WORKER = "worker"
    MODERATOR = "moderator"
    PARTICIPANT = "participant"
    DISPATCHER = "dispatcher"
    AGGREGATOR = "aggregator"
    REVIEWER = "reviewer"
    ADJUDICATOR = "adjudicator"


@dataclass
class TaskDefinition:
    """任务定义（编排中单个 Agent 的任务描述）"""

    agent: str
    task: str
    context: Optional[str] = None
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "task": self.task,
            "context": self.context,
            "extras": self.extras,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskDefinition":
        return cls(
            agent=data["agent"],
            task=data["task"],
            context=data.get("context"),
            extras=data.get("extras", {}),
        )


@dataclass
class OrchestratorConfig:
    """编排器配置"""

    type: OrchestratorType
    max_rounds: int = 5
    strategy: Optional[str] = None
    threshold: float = 0.7
    weights: Dict[str, float] = field(default_factory=dict)
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "max_rounds": self.max_rounds,
            "strategy": self.strategy,
            "threshold": self.threshold,
            "weights": self.weights,
            "extras": self.extras,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrchestratorConfig":
        return cls(
            type=OrchestratorType(data["type"]),
            max_rounds=data.get("max_rounds", 5),
            strategy=data.get("strategy"),
            threshold=data.get("threshold", 0.7),
            weights=data.get("weights", {}),
            extras=data.get("extras", {}),
        )


@dataclass
class BlackboardEntry:
    """黑板初始条目"""

    key: str
    value: Any

    def to_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "value": self.value}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BlackboardEntry":
        return cls(key=data["key"], value=data["value"])


@dataclass
class SubCrewConfig:
    """子 Crew 配置（用于组合嵌套）"""

    name: str
    orchestrator: OrchestratorConfig
    steps: Optional[List[TaskDefinition]] = None
    agents: Optional[List["AgentRoleConfig"]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "name": self.name,
            "orchestrator": self.orchestrator.to_dict(),
        }
        if self.steps:
            result["steps"] = [s.to_dict() for s in self.steps]
        if self.agents:
            result["agents"] = [a.to_dict() for a in self.agents]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubCrewConfig":
        steps = None
        if "steps" in data:
            steps = [TaskDefinition.from_dict(s) for s in data["steps"]]

        agents = None
        if "agents" in data:
            agents = [AgentRoleConfig.from_dict(a) for a in data["agents"]]

        return cls(
            name=data["name"],
            orchestrator=OrchestratorConfig.from_dict(data["orchestrator"]),
            steps=steps,
            agents=agents,
        )


@dataclass
class AgentRoleConfig:
    """Agent 角色配置（YAML 中 agents 列表的每个元素）"""

    role: AgentRole
    name: str
    config: str
    use_history: bool = False
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role.value,
            "name": self.name,
            "config": self.config,
            "use_history": self.use_history,
            "extras": self.extras,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentRoleConfig":
        return cls(
            role=AgentRole(data["role"]),
            name=data["name"],
            config=data["config"],
            use_history=data.get("use_history", False),
            extras=data.get("extras", {}),
        )


@dataclass
class CrewConfig:
    """Crew 编排配置（对应 YAML 顶层结构）"""

    name: str
    description: str
    orchestrator: OrchestratorConfig
    agents: List[AgentRoleConfig]
    blackboard: Optional[Dict[str, Any]] = None
    sub_crews: Optional[List[SubCrewConfig]] = None
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "name": self.name,
            "description": self.description,
            "orchestrator": self.orchestrator.to_dict(),
            "agents": [a.to_dict() for a in self.agents],
        }
        if self.blackboard:
            result["blackboard"] = self.blackboard
        if self.sub_crews:
            result["sub_crews"] = [s.to_dict() for s in self.sub_crews]
        if self.extras:
            result["extras"] = self.extras
        return result

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CrewConfig":
        sub_crews = None
        if "sub_crews" in data:
            sub_crews = [SubCrewConfig.from_dict(s) for s in data["sub_crews"]]

        blackboard = None
        if "blackboard" in data:
            if (
                isinstance(data["blackboard"], dict)
                and "initial_entries" in data["blackboard"]
            ):
                blackboard = data["blackboard"]
            else:
                blackboard = data["blackboard"]

        orchestrator = None
        if "orchestrator" in data:
            orchestrator = OrchestratorConfig.from_dict(data["orchestrator"])

        agents = []
        if "agents" in data:
            agents = [AgentRoleConfig.from_dict(a) for a in data["agents"]]

        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            orchestrator=orchestrator,
            agents=agents,
            blackboard=blackboard,
            sub_crews=sub_crews,
            extras=data.get("extras", {}),
        )

    @classmethod
    def from_yaml(cls, yaml_content: str) -> "CrewConfig":
        """从 YAML 字符串解析 CrewConfig"""
        import yaml

        data = yaml.safe_load(yaml_content)
        if not data:
            raise ValueError("Empty YAML content")
        return cls.from_dict(data)

    @classmethod
    def from_yaml_file(cls, file_path: str) -> "CrewConfig":
        """从 YAML 文件解析 CrewConfig"""
        import yaml

        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data:
            raise ValueError(f"Empty YAML file: {file_path}")
        return cls.from_dict(data)


# ============================================================================
# YAML 校验器
# ============================================================================


class CrewConfigValidator:
    """Crew 配置校验器"""

    REQUIRED_FIELDS = ["name", "description", "orchestrator", "agents"]
    ORCHESTRATOR_REQUIRED = ["type"]

    @classmethod
    def validate(cls, config: CrewConfig) -> List[str]:
        """
        校验 CrewConfig，返回错误信息列表。
        如果校验通过，返回空列表。
        """
        errors = []

        # 基础字段
        if not config.name:
            errors.append("Crew name is required")
        if not config.description:
            errors.append("Crew description is required")
        if not config.orchestrator:
            errors.append("Orchestrator config is required")
            # 无法继续校验编排器相关字段
            return errors

            # 编排器配置（已在上面验证过，此处直接使用）
            # 拓扑特定校验
            if not config.orchestrator.type:
                errors.append("Orchestrator type is required")

        # Agent 配置
        if not config.agents:
            errors.append("At least one agent is required")
        else:
            for i, agent in enumerate(config.agents):
                if not agent.name:
                    errors.append(f"Agent at index {i}: name is required")
                if not agent.config:
                    errors.append(f"Agent '{agent.name or i}': config path is required")
                if not agent.role:
                    errors.append(f"Agent '{agent.name or i}': role is required")

                # 拓扑特定校验
                if config.orchestrator and config.orchestrator.type:
                    otype = config.orchestrator.type
                    if otype == OrchestratorType.PIPELINE:
                        if agent.role not in (AgentRole.WORKER, AgentRole.PARTICIPANT):
                            # Pipeline 允许 worker 或 participant
                            pass
                    elif otype == OrchestratorType.SUPERVISOR_WORKER:
                        if agent.role not in (AgentRole.SUPERVISOR, AgentRole.WORKER):
                            errors.append(
                                f"Supervisor-Worker: agent '{agent.name}' role must be 'supervisor' or 'worker'"
                            )
                        if agent.role == AgentRole.SUPERVISOR and i > 0:
                            errors.append(
                                f"Supervisor-Worker: supervisor '{agent.name}' should be the first agent"
                            )
                    elif otype == OrchestratorType.ROUND_TABLE:
                        if agent.role not in (
                            AgentRole.MODERATOR,
                            AgentRole.PARTICIPANT,
                        ):
                            errors.append(
                                f"Round-Table: agent '{agent.name}' role must be 'moderator' or 'participant'"
                            )
                    elif otype == OrchestratorType.BROADCAST:
                        if agent.role not in (
                            AgentRole.DISPATCHER,
                            AgentRole.AGGREGATOR,
                            AgentRole.WORKER,
                        ):
                            errors.append(
                                f"Broadcast: agent '{agent.name}' role must be 'dispatcher', 'aggregator', or 'worker'"
                            )
                    elif otype == OrchestratorType.CONSENSUS:
                        if agent.role not in (AgentRole.REVIEWER,):
                            errors.append(
                                f"Consensus: agent '{agent.name}' role must be 'reviewer'"
                            )

        return errors

    @classmethod
    def validate_yaml(cls, yaml_content: str) -> List[str]:
        """校验 YAML 字符串配置"""
        import yaml

        try:
            config = CrewConfig.from_yaml(yaml_content)
            return cls.validate(config)
        except yaml.YAMLError as e:
            return [f"YAML parsing error: {e}"]
        except Exception as e:
            return [f"Validation error: {e}"]

    @classmethod
    def validate_yaml_file(cls, file_path: str) -> List[str]:
        """校验 YAML 文件配置"""
        import yaml

        try:
            config = CrewConfig.from_yaml_file(file_path)
            return cls.validate(config)
        except yaml.YAMLError as e:
            return [f"YAML parsing error in {file_path}: {e}"]
        except FileNotFoundError:
            return [f"File not found: {file_path}"]
        except Exception as e:
            return [f"Validation error: {e}"]
