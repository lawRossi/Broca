import json
import os
from pathlib import Path


class BrocaConfig:
    def __init__(self):
        self.database_dir = None
        self.log_file = None
        self.log_level = "INFO"
        self.llm_config_file = None

    @classmethod
    def from_config(cls, config):
        agent_config = cls()
        for key in list(config.keys()):
            if key not in agent_config.__dict__:
                del config[key]
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
