import os
import platform

from loguru import logger

from broca.agent import AgentConfig, SocketIOAgent
from broca.agent_configs import main_agent_config, sub_agent_config
from broca.llm import LLMClient
from broca.session import SessionManager

logger.add("agent.log", level="DEBUG")


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

    async def _create_main_agent(
        self, session_id=None, workspace=None
    ) -> SocketIOAgent:
        if session_id is not None:
            return await self.restore_agent_from_session(session_id)
        config = AgentConfig.from_config(main_agent_config)
        if workspace is not None:
            config.workspace = workspace
        if not config.workspace:
            config.workspace = os.getcwd()
        session_manager = SessionManager()
        await session_manager.create_session()
        if config.environment is None:
            config.environment = self._init_environment(config)
        agent = SocketIOAgent(config, self.llm_client, session_manager)
        await session_manager.save_agent(agent)
        return agent

    async def restore_agent_from_session(self, session_id) -> SocketIOAgent:
        session_manager = SessionManager()
        await session_manager.load_session(session_id)
        agents = await session_manager.get_agents()
        agent_id = agents[0]["agent_id"]
        config = await session_manager.get_agent_config(agent_id)
        logger.info(f"Restoring agent from config: {config}, agent_id: {agent_id}")
        agent_config = AgentConfig.from_config(config)
        agent = SocketIOAgent(
            agent_config, self.llm_client, session_manager, agent_id=agent_id
        )
        await agent.restore_from_session(agent_id)
        return agent

    def _create_subagent(self, role=None):
        config = AgentConfig.from_config(sub_agent_config)
        if config.environment is None:
            config.environment = self._init_environment(config)
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

    def _init_environment(self, config: AgentConfig) -> str:
        return f"System: {platform.system()}\nWorkspace: {config.workspace}"
