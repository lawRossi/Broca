import json
from dataclasses import asdict, dataclass


@dataclass
class SessionMemoryConfig:
    """Session Memory 配置"""

    minimum_messages_to_init: int = 50
    minimum_messages_between_update: int = 20
    steps_between_updates: int = 10


DEFAULT_SESSION_MEMORY_CONFIG = SessionMemoryConfig()


@dataclass
class ContextCompactConfig:
    """上下文压缩全局配置"""

    # 策略A：过期工具结果清理
    enable_stale_tool_cleanup: bool = True
    stale_tool_cleanup_token_threshold: int = 30000  # 触发清理的 token 阈值
    min_stale_messages: int = 20  # 超过多少条消息视为过期
    min_recent_tool_results_to_keep: int = 5  # 至少保留最近几条工具结果
    min_stale_tokens: int = 5000

    # 策略B：Session Memory 截断
    enable_session_memory_truncation: bool = True
    session_memory_truncation_token_threshold: int = 200000  # 触发截断的 token 阈值


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
        self.mcp_configs = None
        self.server_url = "http://localhost:6868"
        self.interactive = True
        self.save_history = True
        self.environment = None
        self.workspace = ""
        self.track_session_momory = False
        self.session_memory_config = DEFAULT_SESSION_MEMORY_CONFIG
        self.enable_context_compression = False
        self.compact_config = DEFAULT_COMPACT_CONFIG

    @classmethod
    def from_config(cls, config):
        agent_config = cls()
        for key in list(config.keys()):
            if key not in agent_config.__dict__:
                continue
            if key == "session_memory_config":
                if isinstance(config[key], dict):
                    agent_config.session_memory_config = SessionMemoryConfig(
                        **config[key]
                    )
                elif isinstance(config[key], SessionMemoryConfig):
                    agent_config.session_memory_config = config[key]
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
        data["session_memory_config"] = asdict(self.session_memory_config)
        data["compact_config"] = asdict(self.compact_config)
        return json.dumps(data, ensure_ascii=False, indent=4)

    def to_dict(self) -> dict:
        return dict(self.__dict__)
