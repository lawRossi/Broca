"""Broca 核心配置加载模块。

配置来源（纯文件，不读取环境变量）:
  1. 显式指定的 config_path（由调用方传入）
  2. 项目 configs/configs.json
  3. ~/.broca/configs.json
  4. 代码默认值
"""

import json
import os
from pathlib import Path


# llm_config.json 中的保留键：存放全局默认 provider / model。
# 该键不是真实提供商，遍历时需跳过。
LLM_DEFAULT_KEY = "__default__"

# 内置兜底默认值：llm_config.json 未配置 __default__ 时使用
DEFAULT_LLM_PROVIDER = "deepseek"
DEFAULT_LLM_MODEL = "deepseek-v4-flash"


class ExecutionConfig:
    """执行引擎相关配置（loop_engine / llm / agent）"""

    def __init__(self):
        self.step_max_errors = 3  # LLM 最大重试次数
        self.llm_retry_delay = 5  # LLM 重试间隔（秒）
        self.tool_call_timeout = 120  # 普通工具执行超时（秒）
        self.assign_task_timeout = 1800  # assign_task 工具超时（秒）
        self.llm_timeout = 300  # LLM 流式请求超时（秒，也用于外层 wait_for）
        self.llm_first_chunk_timeout = 30  # LLM 首块超时（秒）
        self.dead_loop_window = 3  # 最近 N 步工具调用相同判定死循环
        self.message_queue_size = 3  # agent 消息队列大小
        self.permission_request_timeout = 90  # 权限请求等待超时（秒）
        self.agent_query_timeout = 300  # ask_user 用户问答等待超时（秒）
        self.tool_execution_mode = "parallel"  # 工具执行方式: "parallel" | "serial"
        self.max_parallel_tools = 10  # 并行模式下最大同时执行的工具数
        self.max_concurrent_runners = 10  # 最大并发 session runner 数
        # Session Runner 心跳（子进程 → Web 进程）
        # 发送间隔 5s、判定超时 45s（≈9 个周期）、巡检间隔 15s
        self.runner_heartbeat_interval = 5  # Runner 上报心跳间隔（秒）
        self.runner_heartbeat_timeout = 45  # 心跳超时判定阈值（秒）
        self.runner_heartbeat_check_interval = 15  # Manager 心跳巡检间隔（秒）

    @classmethod
    def from_config(cls, config):
        exec_config = cls()
        for key in list(config.keys()):
            if key not in exec_config.__dict__:
                del config[key]
        exec_config.__dict__.update(config)
        return exec_config


class StorageConfig:
    """文件上传存储配置（configs.json 的 storage 分组）"""

    def __init__(self):
        self.backend = ""  # "cloudflare" | "supabase" | ""
        # Cloudflare R2
        self.cloudflare_account_id = ""
        self.cloudflare_access_key_id = ""
        self.cloudflare_secret_access_key = ""
        self.cloudflare_bucket = "upload"
        self.cloudflare_public_url = ""
        # Supabase S3
        self.supabase_url = ""
        self.supabase_s3_access_key_id = ""
        self.supabase_s3_secret_access_key = ""
        self.supabase_bucket = "upload"

    @classmethod
    def from_config(cls, config):
        storage_config = cls()
        for key in list(config.keys()):
            if key not in storage_config.__dict__:
                del config[key]
        storage_config.__dict__.update(config)
        return storage_config


class SearchConfig:
    """搜索 API 配置（configs.json 的 search 分组）"""

    def __init__(self):
        self.tavily_api_key = ""
        self.anysearch_api_key = ""
        self.anysearch_api_base_url = "https://api.anysearch.com"
        self.default_search_provider = "tavily"   # "tavily" | "anysearch"
        self.default_fetch_provider = "anysearch"  # "anysearch" | "playwright"

    @classmethod
    def from_config(cls, config):
        search_config = cls()
        for key in list(config.keys()):
            if key not in search_config.__dict__:
                del config[key]
        search_config.__dict__.update(config)
        return search_config


# 需要 expanduser 的路径字段
_PATH_FIELDS = (
    "database_dir",
    "log_file",
    "log_dir",
    "llm_config_file",
    "agents_config_dir",
    "snapshot_home",
    "components_config",
)


class BrocaConfig:
    """Broca 核心配置。所有值从 configs.json 文件加载。"""

    def __init__(self):
        # 路径
        self.database_dir: str | None = None
        self.log_file: str | None = None
        self.log_dir: str = os.path.expanduser("~/.broca/logs")
        self.llm_config_file: str | None = None
        self.agents_config_dir: str = os.path.expanduser("~/.broca/configs/agents")
        self.snapshot_home: str = os.path.expanduser("~/.broca/snapshots")
        self.components_config: str = ""
        # 配置源
        self.config_source_path: str | None = None
        # 服务
        self.log_level: str = "INFO"
        self.socket_server_url: str | None = None
        self.api_server_url: str | None = None
        # 子配置
        self.execution = ExecutionConfig()
        self.storage = StorageConfig()
        self.search = SearchConfig()

    @classmethod
    def from_config(cls, config: dict) -> "BrocaConfig":
        agent_config = cls()
        for key in list(config.keys()):
            if key not in agent_config.__dict__:
                del config[key]
            elif key == "execution" and isinstance(config[key], dict):
                agent_config.execution = ExecutionConfig.from_config(config[key])
                config[key] = agent_config.execution
            elif key == "storage" and isinstance(config[key], dict):
                agent_config.storage = StorageConfig.from_config(config[key])
                config[key] = agent_config.storage
            elif key == "search" and isinstance(config[key], dict):
                agent_config.search = SearchConfig.from_config(config[key])
                config[key] = agent_config.search
        agent_config.__dict__.update(config)
        # Expand ~ in path fields
        for path_key in _PATH_FIELDS:
            val = agent_config.__dict__.get(path_key)
            if isinstance(val, str) and val.startswith("~"):
                agent_config.__dict__[path_key] = os.path.expanduser(val)
        return agent_config


def _load_config_file(config_file: Path) -> BrocaConfig | None:
    """尝试从文件加载配置，如果文件不存在或 JSON 解析失败则返回 None。

    相对路径字段会基于配置文件所在目录解析为绝对路径。
    """
    try:
        if config_file.exists():
            with open(config_file) as f:
                config = BrocaConfig.from_config(json.load(f))
            # 将相对路径解析为基于配置文件目录的绝对路径
            base_dir = config_file.parent
            for path_key in _PATH_FIELDS:
                val = getattr(config, path_key, None)
                if val and not Path(val).is_absolute() and not val.startswith("~"):
                    resolved = (base_dir / val).resolve().as_posix()
                    setattr(config, path_key, resolved)
            # 记录配置源路径
            config.config_source_path = str(config_file.resolve())
            return config
    except (json.JSONDecodeError, OSError) as e:
        import logging
        logging.getLogger(__name__).warning(
            f"Failed to load config from {config_file}: {e}"
        )
    return None


# 模块级单例缓存
_config_instance: BrocaConfig | None = None


def get_configs(config_path: str | Path | None = None, *, enforce_production: bool = False) -> BrocaConfig:
    """
    读取配置（纯文件驱动，不读取环境变量）。

    优先级:
      1. config_path 参数（显式指定）
      2. 项目 configs/configs.json
      3. ~/.broca/configs.json
      4. 代码默认值

    Args:
        config_path: 显式指定配置文件路径。为 None 时走默认发现逻辑。
        enforce_production: 若为 True，log_level=DEBUG 强制降为 INFO（生产安全护栏）。
    """
    global _config_instance

    # 如果传了显式路径，加载并更新缓存
    if config_path is not None:
        config = _load_config_file(Path(config_path).expanduser())
        if config is not None:
            _config_instance = config
    else:
        # 使用缓存（避免重复 IO）
        if _config_instance is not None:
            config = _config_instance
        else:
            project_config = Path(__file__).parent.parent / "configs" / "configs.json"
            user_config = Path.home() / ".broca" / "configs.json"

            config = _load_config_file(project_config)
            if config is None:
                config = _load_config_file(user_config)

            if config is None:
                config = BrocaConfig()

            _config_instance = config

    if config is None:
        config = BrocaConfig()

    # 生产环境安全护栏: log_level=DEBUG 强制降为 INFO
    if enforce_production and config.log_level == "DEBUG":
        import logging
        logging.getLogger(__name__).warning(
            "enforce_production: log_level=DEBUG 已强制降为 INFO"
        )
        config.log_level = "INFO"

    return config


def reset_configs_cache() -> None:
    """重置配置缓存（测试用）"""
    global _config_instance
    _config_instance = None


def resolve_llm_config_path() -> Path:
    """解析 llm_config.json 路径。

    优先级: configs.json 的 llm_config_file > 项目默认 configs/llm_config.json
    """
    configs = get_configs()
    if configs.llm_config_file:
        return Path(configs.llm_config_file).expanduser()
    return Path(__file__).parent.parent / "configs" / "llm_config.json"


def get_llm_defaults() -> tuple[str, str]:
    """读取 llm_config.json 的 __default__ 条目，返回 (provider, model)。

    未配置或读取失败时回退到内置默认值。永不抛异常。
    """
    provider = DEFAULT_LLM_PROVIDER
    model = DEFAULT_LLM_MODEL
    try:
        path = resolve_llm_config_path()
        if path.exists():
            with open(path) as f:
                config = json.load(f)
            default = config.get(LLM_DEFAULT_KEY)
            if isinstance(default, dict):
                p = default.get("provider")
                m = default.get("model")
                if isinstance(p, str) and p.strip():
                    provider = p
                if isinstance(m, str) and m.strip():
                    model = m
    except Exception:
        # 读取失败时静默回退到内置默认值
        pass
    return provider, model
