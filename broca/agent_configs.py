import json


class AgentConfig:
    def __init__(self):
        self.config_name = None
        self.name = None
        self.role = None
        self.role_description = None
        self.llm_config_name = "deepseek"
        self.log_file = "agent.log"
        self.system_prompt_template = None
        self.subagents = []
        self.tools = None
        self.skills = None
        self.server_url = "http://localhost:6868"
        self.interactive = True
        self.save_history = True
        self.environment = None
        self.workspace = ""
        self.boostrap_instractions = False

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
