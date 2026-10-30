import json
import os
from pathlib import Path


# llm_config.json 中的保留键：存放全局默认 provider / model。
# 该键不是真实提供商，遍历时需跳过。
LLM_DEFAULT_KEY = "__default__"

# 内置兜底默认值：llm_config.json 未配置 __default__ 时使用
DEFAULT_LLM_PROVIDER = "deepseek"
DEFAULT_LLM_MODEL = "deepseek-v4-flash"


def _resolve_llm_config_path() -> Path:
    """解析 llm_config.json 路径，与 broca.llm.LLMClient 保持一致：
    BROCA_LLM_CONFIG 环境变量 > 项目默认 configs/llm_config.json。
    保证解析出的默认 provider/model 与 LLMClient 实际读取的文件相同。
    """
    env_path = os.getenv("BROCA_LLM_CONFIG")
    if env_path:
        return Path(env_path)
    return Path(__file__).parent.parent / "configs" / "llm_config.json"


def get_llm_defaults() -> tuple[str, str]:
    """读取 llm_config.json 的 __default__ 条目，返回 (provider, model)。

    未配置或读取失败时回退到内置默认值。永不抛异常。
    """
    provider = DEFAULT_LLM_PROVIDER
    model = DEFAULT_LLM_MODEL
    try:
        path = _resolve_llm_config_path()
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


class BrocaConfig:
    def __init__(self):
        self.database_dir = None
        self.log_file = None
        self.log_level = "INFO"
        self.llm_config_file = None
        self.socket_server_url = None
        self.api_server_url = None
        self.execution = ExecutionConfig()
        self.storage = StorageConfig()
        self.search = SearchConfig()

    @classmethod
    def from_config(cls, config):
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
        return agent_config


def _load_config_file(config_file: Path) -> BrocaConfig | None:
    """尝试从文件加载配置，如果文件不存在或 JSON 解析失败则返回 None"""
    try:
        if config_file.exists():
            with open(config_file) as f:
                return BrocaConfig.from_config(json.load(f))
    except (json.JSONDecodeError, OSError) as e:
        import logging
        logging.getLogger(__name__).warning(
            f"Failed to load config from {config_file}: {e}"
        )
    return None


def get_configs() -> BrocaConfig:
    """
    读取配置，优先级:
      1. BROCA_CONFIG 环境变量指定的路径
      2. ~/.broca/configs.json
      3. 项目默认 configs/configs.json
    """
    # 1. 环境变量
    env_path = os.getenv("BROCA_CONFIG")
    if env_path:
        config = _load_config_file(Path(env_path))
        if config is not None:
            return config

    # 2. 用户配置 ~/.broca/configs.json
    config = _load_config_file(Path.home() / ".broca" / "configs.json")
    if config is not None:
        return config

    # 3. 项目默认配置
    config = _load_config_file(Path(__file__).parent.parent / "configs" / "configs.json")
    if config is not None:
        return config

    # 4. 都不存在时返回默认值
    return BrocaConfig()
