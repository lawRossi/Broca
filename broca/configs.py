"""Broca 核心配置加载模块。

配置来源（纯文件，不读取环境变量）:
  1. 显式指定的 config_path（由调用方传入）
  2. 项目 configs/configs.json
  3. ~/.broca/configs.json
  4. 代码默认值
"""

import json
import os
import threading
from dataclasses import dataclass, fields
from pathlib import Path

def _get_logger():
    """惰性获取 logger，避免 configs 被 logging_config lazy import 时死锁。"""
    from broca.logging_config import get_logger

    return get_logger(__name__)


# llm_config.json 中的保留键：存放全局默认 provider / model。
# 该键不是真实提供商，遍历时需跳过。
LLM_DEFAULT_KEY = "__default__"

# 内置兜底默认值：llm_config.json 未配置 __default__ 时使用
DEFAULT_LLM_PROVIDER = "deepseek"
DEFAULT_LLM_MODEL = "deepseek-v4-flash"


@dataclass
class ExecutionConfig:
    """执行引擎相关配置（loop_engine / llm / agent）"""

    step_max_errors: int = 3  # LLM 最大重试次数
    llm_retry_delay: int = 5  # LLM 重试间隔（秒）
    tool_call_timeout: int = 120  # 普通工具执行超时（秒）
    assign_task_timeout: int = 1800  # assign_task 工具超时（秒）
    llm_timeout: int = 300  # LLM 流式请求超时（秒，也用于外层 wait_for）
    llm_first_chunk_timeout: int = 30  # LLM 首块超时（秒）
    dead_loop_window: int = 3  # 最近 N 步工具调用相同判定死循环
    message_queue_size: int = 3  # agent 消息队列大小
    permission_request_timeout: int = 90  # 权限请求等待超时（秒）
    agent_query_timeout: int = 300  # ask_user 用户问答等待超时（秒）
    tool_execution_mode: str = "parallel"  # 工具执行方式: "parallel" | "serial"
    execution_mode: str = "non_blocking"  # 执行模式: "blocking" | "non_blocking"
    max_parallel_tools: int = 10  # 并行模式下最大同时执行的工具数
    max_concurrent_runners: int = 10  # 最大并发 session runner 数
    # Session Runner 心跳（子进程 → Web 进程）
    # 发送间隔 5s、判定超时 45s（≈9 个周期）、巡检间隔 15s
    runner_heartbeat_interval: int = 5  # Runner 上报心跳间隔（秒）
    runner_heartbeat_timeout: int = 45  # 心跳超时判定阈值（秒）
    runner_heartbeat_check_interval: int = 15  # Manager 心跳巡检间隔（秒）
    # IPC 单线程多路复用（Task 4.2）：一个 ipc-poller 线程轮询所有连接。
    # 心跳状态落库的最小间隔（秒）：时间维度聚合，避免每轮巡检都写库
    runner_status_persist_interval: int = 60
    # 每个 session 的 IPC 消息队列上限（背压，Task 4.4）
    runner_ipc_queue_size: int = 1000
    # Per-session runner 日志目录 GC 保留天数
    runner_log_gc_days: int = 30
    # Per-session runner 日志目录 GC 轮询间隔（秒）
    runner_log_gc_interval: int = 3600

    @classmethod
    def from_config(cls, config: dict) -> "ExecutionConfig":
        """从 dict 创建/更新实例，过滤未知字段（就地修改 config dict）。"""
        instance = cls()
        known = {f.name for f in fields(cls)}
        for key in list(config.keys()):
            if key not in known:
                del config[key]
        for key, value in config.items():
            setattr(instance, key, value)
        return instance


@dataclass
class StorageConfig:
    """文件上传存储配置（configs.json 的 storage 分组）"""

    backend: str = ""  # "cloudflare" | "supabase" | ""
    # Cloudflare R2
    cloudflare_account_id: str = ""
    cloudflare_access_key_id: str = ""
    cloudflare_secret_access_key: str = ""
    cloudflare_bucket: str = "upload"
    cloudflare_public_url: str = ""
    # Supabase S3
    supabase_url: str = ""
    supabase_s3_access_key_id: str = ""
    supabase_s3_secret_access_key: str = ""
    supabase_bucket: str = "upload"

    @classmethod
    def from_config(cls, config: dict) -> "StorageConfig":
        """从 dict 创建/更新实例，过滤未知字段（就地修改 config dict）。"""
        instance = cls()
        known = {f.name for f in fields(cls)}
        for key in list(config.keys()):
            if key not in known:
                del config[key]
        for key, value in config.items():
            setattr(instance, key, value)
        return instance


@dataclass
class SearchConfig:
    """搜索 API 配置（configs.json 的 search 分组）"""

    tavily_api_key: str = ""
    anysearch_api_key: str = ""
    anysearch_api_base_url: str = "https://api.anysearch.com"
    default_search_provider: str = "tavily"   # "tavily" | "anysearch"
    default_fetch_provider: str = "anysearch"  # "anysearch" | "playwright"

    @classmethod
    def from_config(cls, config: dict) -> "SearchConfig":
        """从 dict 创建/更新实例，过滤未知字段（就地修改 config dict）。"""
        instance = cls()
        known = {f.name for f in fields(cls)}
        for key in list(config.keys()):
            if key not in known:
                del config[key]
        for key, value in config.items():
            setattr(instance, key, value)
        return instance


# 需要 expanduser 的路径字段
_PATH_FIELDS = (
    "database_dir",
    "log_file",
    "log_dir",
    "llm_config_file",
    "decision_config_file",
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
        self.decision_config_file: str | None = None
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
        _get_logger().warning(f"Failed to load config from {config_file}: {e}")
    return None


# ---------------------------------------------------------------------------
# 统一路径解析（所有模块共用此函数，不再各自实现回退链）
# ---------------------------------------------------------------------------

# 项目根目录（broca/configs.py 的上一级的上一级 = 项目根）
# editable 安装 / 源码运行时 → 项目源码目录；pip install 后 → site-packages
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

def _default_search_paths() -> tuple[Path, ...]:
    """默认发现链（按优先级排列）。

    动态计算以支持测试中 patch HOME 后路径正确更新。
    """
    home = Path.home()
    return (
        _PROJECT_ROOT / "configs" / "configs.json",
        home / ".broca" / "configs" / "configs.json",
        home / ".broca" / "configs.json",
    )


def resolve_configs_path(
    explicit_path: str | Path | None = None,
    base_dir: str | Path | None = None,
) -> Path | None:
    """统一的 configs.json 路径解析入口。

    所有需要定位 configs.json 的模块（broca 核心 / Web 后端 / TUI）
    都应调用此函数，而非各自硬编码回退链。

    Args:
        explicit_path: 显式指定的路径（来自 BROCA_CONFIG / 参数）。
                       相对路径以 base_dir 为基准解析；绝对路径 / ~ 路径直接 expanduser。
                       为 None / 空字符串时走默认发现链。
        base_dir: 相对路径的锚定目录。未提供时相对路径直接 expanduser
                  （退化为基于 CWD，不推荐）。

    Returns:
        解析后的绝对 Path。显式路径不存在时仍返回（调用方可自行 .exists() 检查）；
        默认发现链找不到任何文件时返回 None。
    """
    # --- 显式路径 ---
    if explicit_path is not None:
        raw = str(explicit_path).strip()
        if not raw:
            explicit_path = None  # 空字符串视为未提供
        else:
            path = Path(raw).expanduser()
            if not path.is_absolute() and base_dir is not None:
                path = (Path(base_dir).expanduser() / path).resolve()
            return path

    # --- 默认发现链 ---
    for candidate in _default_search_paths():
        if candidate.exists():
            return candidate

    return None


def _get_default_search_paths() -> tuple[Path, ...]:
    """暴露默认搜索链（测试 / 诊断用）。"""
    return _default_search_paths()


# ---------------------------------------------------------------------------
# 模块级单例缓存
# ---------------------------------------------------------------------------
_config_instance: BrocaConfig | None = None
_config_lock = threading.Lock()


def get_configs(config_path: str | Path | None = None, *, enforce_production: bool = False) -> BrocaConfig:
    """
    读取配置（纯文件驱动，不读取环境变量）。

    路径解析委托给 ``resolve_configs_path()``。

    优先级:
      1. config_path 参数（显式指定）
      2. 项目 configs/configs.json
      3. ~/.broca/configs/configs.json
      4. ~/.broca/configs.json
      5. 代码默认值

    Args:
        config_path: 显式指定配置文件路径。为 None 时走默认发现逻辑。
        enforce_production: 若为 True，log_level=DEBUG 强制降为 INFO（生产安全护栏）。
    """
    global _config_instance

    resolved = resolve_configs_path(config_path) if config_path is not None else None

    if resolved is not None:
        # 显式路径：加载并更新缓存（加锁防止并发初始化）
        with _config_lock:
            config = _load_config_file(resolved)
            if config is not None:
                _config_instance = config
    else:
        # 快速路径：缓存已存在且无需 enforce_production 变换
        if not enforce_production and _config_instance is not None:
            return _config_instance
        with _config_lock:
            # double-check after acquiring lock
            if not enforce_production and _config_instance is not None:
                config = _config_instance
            elif _config_instance is not None:
                config = _config_instance
            else:
                # 通过统一函数发现默认路径
                default_path = resolve_configs_path()
                if default_path is not None:
                    config = _load_config_file(default_path)
                else:
                    config = None

                if config is None:
                    config = BrocaConfig()

                _config_instance = config

    if config is None:
        config = BrocaConfig()

    # 生产环境安全护栏: log_level=DEBUG 强制降为 INFO
    if enforce_production and config.log_level == "DEBUG":
        _get_logger().warning("enforce_production: log_level=DEBUG 已强制降为 INFO")
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
