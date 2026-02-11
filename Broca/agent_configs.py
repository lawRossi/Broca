import json

from Broca.prompts import main_agent_base, subagent_base


class AgentConfig:
    def __init__(self):
        self.config_name = None
        self.role_description = None
        self.llm_config_name = "deepseek"
        self.log_file = "agent.log"
        self.system_prompt_template = None
        self.subagents = []
        self.tools = None
        self.skills = None
        self.server_url = "http://localhost:8001"
        self.interactive = True
        self.save_history = True
        self.environment = None
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


main_agent_config = {
    "config_name": "main_agent",
    "llm_config_name": "deepseek",
    "system_prompt_template": main_agent_base,
    "subagents": [],
    # "subagents": ["requirment analyzer", "frontend developer", "backend developer"],
    "tools": [
        "edit_file",
        "read_file",
        "write_file",
        "list_dir",
        "execute_code",
        "load_skill",
    ],
    "skills": ["planning-with-files"],
    "interactive": True,
    "save_history": True,
    "environment": None,
    "verbose": True,
}


sub_agent_config = {
    "llm_config_name": "deepseek",
    "system_prompt_template": subagent_base,
    "tools": ["execute_code", "load_skill"],
    "skills": [],
    "interactive": True,
    "save_history": False,
    "environment": None,
    "verbose": True,
}
