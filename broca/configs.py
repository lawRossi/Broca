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
        config_file = Path(env_path)
        if config_file.exists():
            with open(config_file) as f:
                return BrocaConfig.from_config(json.load(f))

    # 2. 用户配置 ~/.broca/configs.json
    user_config = Path.home() / ".broca" / "configs.json"
    if user_config.exists():
        with open(user_config) as f:
            return BrocaConfig.from_config(json.load(f))

    # 3. 项目默认配置
    project_config = Path(__file__).parent.parent / "configs" / "configs.json"
    if project_config.exists():
        with open(project_config) as f:
            return BrocaConfig.from_config(json.load(f))

    # 4. 都不存在时返回默认值
    return BrocaConfig()
