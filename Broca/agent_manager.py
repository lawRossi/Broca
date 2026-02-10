import os
import platform

from Broca.agent import AgentConfig, SocketIOAgent
from Broca.agent_configs import main_agent_config, sub_agent_config
from Broca.llm import LLMClient
from Broca.session import SessionManager


class AgentFactory:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AgentFactory, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self.llm_client = LLMClient()

    def get_agent(self, name: str, **kwargs):
        if name == "main_agent":
            return self._create_main_agent(**kwargs)
        elif name == "sub_agent":
            return self._create_subagent(**kwargs)
        else:
            raise ValueError(f"Unknown agent type: {name}")

    async def _create_main_agent(self, session_id=None) -> SocketIOAgent:
        config = AgentConfig.from_config(main_agent_config)
        session_manager = SessionManager()
        if session_id is not None:
            await session_manager.load_session(session_id)
        else:
            await session_manager.create_session()
        if config.environment is None:
            config.environment = self._init_environment()
        return SocketIOAgent(config, self.llm_client, session_manager)

    def _create_subagent(self, role=None):
        config = AgentConfig.from_config(sub_agent_config)
        if config.environment is None:
            config.environment = self._init_environment()
        config.role = role
        if role == "requirment analyzer":
            role_description = "You are an expert requirement analyzer. Your task is to dig the requirements from the user by applying your skills."
            skills = ["Requirement Analyzer"]
        elif role == "frontend developer":
            skills = ["frontend-design"]
            role_description = "You are a frontend developer. Your task is to design and implement the frontend for the user's requirements."
        else:
            skills = []
            role_description = "You are a backend developer. Your task is to design and implement the backend for the user's requirements."
        config.skills = skills
        config.role_description = role_description
        return SocketIOAgent(config, self.llm_client)

    def _init_environment(self):
        return f"System: {platform.system()}\nWorkspace: {os.getcwd()}"
