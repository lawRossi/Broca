import json
import os
from pathlib import Path


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

    @classmethod
    def from_config(cls, config):
        exec_config = cls()
        for key in list(config.keys()):
            if key not in exec_config.__dict__:
                del config[key]
        exec_config.__dict__.update(config)
        return exec_config


class BrocaConfig:
    def __init__(self):
        self.database_dir = None
        self.log_file = None
        self.log_level = "INFO"
        self.llm_config_file = None
        self.socket_server_url = None
        self.api_server_url = None
        self.execution = ExecutionConfig()

    @classmethod
    def from_config(cls, config):
        agent_config = cls()
        for key in list(config.keys()):
            if key not in agent_config.__dict__:
                del config[key]
            elif key == "execution" and isinstance(config[key], dict):
                agent_config.execution = ExecutionConfig.from_config(config[key])
                config[key] = agent_config.execution
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
