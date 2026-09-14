import json
from dataclasses import asdict, dataclass

from broca.configs import ExecutionConfig


@dataclass
class PersistentMemoryConfig:
    """持久化记忆提取配置"""

    auto_extract: bool = False
    minimum_messages_to_init: int = 50
    minimum_messages_between_update: int = 30
    steps_between_updates: int = 20
    freshness_warning_days: int = 7


DEFAULT_PERSISTENT_MEMORY_CONFIG = PersistentMemoryConfig()


@dataclass
class ContextCompactConfig:
    """上下文压缩全局配置"""

    # Session Memory 截断
    session_trunc_threshold: int = 250000  # 触发截断的 token 阈值
    session_trunc_percentage: float = 0.5  # 上下文窗口百分比
    keep_steps: int = 5  # 截断时保留的最近 step 数（当前 turn 未结束时）


DEFAULT_COMPACT_CONFIG = ContextCompactConfig()


class AgentConfig:
    def __init__(self):
        self.config_name = None
        self.name = None
        self.role = None
        self.role_description = None
        self.provider = "deepseek"
        self.model = "deepseek-v4-flash"
        self.system_prompt_template = None
        self.tools = None
        self.skills = None
        self.mcp_servers = None
        self.server_url = "http://localhost:6868"
        self.interactive = True
        self.save_history = True
        self.environment = None
        self.workspace = ""
        self.persistent_memory_config = DEFAULT_PERSISTENT_MEMORY_CONFIG
        self.enable_context_compression = False
        self.compact_config = DEFAULT_COMPACT_CONFIG
        self.execution_config = ExecutionConfig()

    @classmethod
    def from_config(cls, config):
        agent_config = cls()
        for key in list(config.keys()):
            if key not in agent_config.__dict__:
                continue
            if key == "persistent_memory_config":
                if isinstance(config[key], dict):
                    agent_config.persistent_memory_config = PersistentMemoryConfig(
                        **config[key]
                    )
                elif isinstance(config[key], PersistentMemoryConfig):
                    agent_config.persistent_memory_config = config[key]
            elif key == "compact_config":
                if isinstance(config[key], dict):
                    agent_config.compact_config = ContextCompactConfig(**config[key])
                elif isinstance(config[key], ContextCompactConfig):
                    agent_config.compact_config = config[key]
            else:
                setattr(agent_config, key, config[key])

        return agent_config

    def to_json(self) -> str:
        data = self.to_dict()
        data["persistent_memory_config"] = asdict(self.persistent_memory_config)
        data["compact_config"] = asdict(self.compact_config)
        return json.dumps(data, ensure_ascii=False, indent=4)

    def to_dict(self) -> dict:
        # execution_config 是全局配置，不随 agent 配置持久化/序列化
        data = dict(self.__dict__)
        data.pop("execution_config", None)
        return data
