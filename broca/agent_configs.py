import json
from dataclasses import dataclass


@dataclass
class ContextCompactConfig:
    """上下文压缩全局配置"""

    # 策略A：过期工具结果清理
    enable_stale_tool_cleanup: bool = True
    stale_tool_cleanup_token_threshold: int = 30_000  # 触发清理的 token 阈值
    min_stale_messages: int = 20  # 超过多少条消息视为过期
    min_recent_tool_results_to_keep: int = 5  # 至少保留最近几条工具结果
    min_stale_tokens: int = 5000

    # 策略B：Session Memory 截断
    enable_session_memory_truncation: bool = True
    session_memory_truncation_token_threshold: int = 100_000  # 触发截断的 token 阈值


DEFAULT_COMPACT_CONFIG = ContextCompactConfig()


class AgentConfig:
    def __init__(self):
        self.config_name = None
        self.name = None
        self.role = None
        self.role_description = None
        self.provider = "openrouter"
        self.model = "glm"
        self.system_prompt_template = None
        self.tools = None
        self.skills = None
        self.server_url = "http://localhost:6868"
        self.interactive = True
        self.save_history = True
        self.environment = None
        self.track_session_momory = False
        self.workspace = ""
        self.enable_context_compression = False
        self.compact_config = {}

    @classmethod
    def from_config(cls, config):
        agent_config = cls()
        for key in list(config.keys()):
            if key not in agent_config.__dict__:
                del config[key]
        agent_config.__dict__.update(config)
        return agent_config

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False)

    def to_dict(self) -> dict:
        return dict(self.__dict__)
