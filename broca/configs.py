import json
from pathlib import Path


class BrocaConfig:
    def __init__(self):
        self.database_dir = None
        self.log_file = None
        self.log_level = "INFO"

    @classmethod
    def from_config(cls, config):
        agent_config = cls()
        for key in list(config.keys()):
            if key not in agent_config.__dict__:
                del config[key]
        agent_config.__dict__.update(config)
        return agent_config


def get_configs():
    config_file = Path(__file__).parent.parent / "configs" / "configs.json"
    with open(config_file) as f:
        configs = json.load(f)

    return BrocaConfig.from_config(configs)
