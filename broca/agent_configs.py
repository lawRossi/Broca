import json
from dataclasses import asdict, dataclass, fields

from broca.configs import ExecutionConfig, get_llm_defaults


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
    keep_steps: int = 8  # 截断时保留的最近 step 数（当前 turn 未结束时）


DEFAULT_COMPACT_CONFIG = ContextCompactConfig()


@dataclass
class CommunicationPolicy:
    """Agent 间通信策略配置。

    核心机制（ACL / task 存在性校验 / 回复保障 / request 超时+环检测）始终生效。
    （可选增强——每 turn 通信预算、notify/delegate 可选环检测——按用户要求本期不实现，
    故此处不含 enable_* 开关与预算参数。）
    """

    # --- 核心：ACL（始终生效） ---
    allowed_targets: list[str] | None = None  # None = 不限制
    allowed_modes: list[str] | None = None  # None = 所有模式
    # --- 核心：request 超时（始终生效，对齐 agent_query_timeout） ---
    request_timeout: float = 300.0
    max_chain_depth: int = 3  # request 环检测用


def _parse_communication_policy(data: dict) -> CommunicationPolicy:
    """Build a CommunicationPolicy from a dict, ignoring unknown keys."""
    allowed = {f.name for f in fields(CommunicationPolicy)}
    return CommunicationPolicy(**{k: v for k, v in data.items() if k in allowed})


class AgentConfig:
    """Per-agent configuration.

    Notable field: ``communication_policy`` (a
    :class:`~broca.agent_configs.CommunicationPolicy`) configures agent-to-agent
    communication:

    - ``allowed_targets`` / ``allowed_modes`` — static ACL (core, always on).
    - ``request_timeout`` — how long a ``request`` blocks for a reply before
      raising ``AgentCommunicationError(reason="request_timeout")`` (core).
    - ``max_chain_depth`` — request forced cycle detection depth guard
      (core, always on; deadlock prevention).

    Optional enhancements (per-turn budget, notify/delegate optional chain
    detection) are intentionally not implemented in this iteration.
    """

    def __init__(self):
        self.config_name = None
        self.name = None
        self.role = None
        self.role_description = None
        # 默认 provider/model 取自 llm_config.json 的 __default__ 条目（可在 LLM 配置页配置），
        # 未配置时回退到内置默认值；agent 配置或显式参数可覆盖此默认。
        self.provider, self.model = get_llm_defaults()
        self.system_prompt_template = None
        self.tools = None
        self.skills = None
        self.skill_loading_mode = "eager"  # "eager" (default) | "lazy"
        self.mcp_servers = None
        self.server_url = "http://localhost:6666"  # fallback，生产环境由 configs.json 的 socket_server_url 覆盖
        self.interactive = True
        self.save_history = True
        self.environment = None
        self.workspace = ""
        self.persistent_memory_config = DEFAULT_PERSISTENT_MEMORY_CONFIG
        self.enable_context_compression = False
        self.enable_snapshot_tracking = True  # 是否跟踪文件快照（undo/redo 时恢复文件）
        self.bash_security_check = True  # 是否对 bash 命令做安全代码检查（默认开启）
        self.tool_execution_mode: str | None = None  # 工具执行方式（None=使用全局配置）
        self.max_parallel_tools: int | None = None  # 最大并行工具数（None=使用全局配置）
        self.compact_config = DEFAULT_COMPACT_CONFIG
        self.communication_policy = CommunicationPolicy()
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
            elif key == "communication_policy":
                if isinstance(config[key], dict):
                    agent_config.communication_policy = _parse_communication_policy(
                        config[key]
                    )
                elif isinstance(config[key], CommunicationPolicy):
                    agent_config.communication_policy = config[key]
            else:
                setattr(agent_config, key, config[key])

        return agent_config

    def to_json(self) -> str:
        data = self.to_dict()
        data["persistent_memory_config"] = asdict(self.persistent_memory_config)
        data["compact_config"] = asdict(self.compact_config)
        data["communication_policy"] = asdict(self.communication_policy)
        return json.dumps(data, ensure_ascii=False, indent=4)

    def to_dict(self) -> dict:
        # execution_config 是全局配置，不随 agent 配置持久化/序列化
        data = dict(self.__dict__)
        data.pop("execution_config", None)
        return data
