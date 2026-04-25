import json


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
