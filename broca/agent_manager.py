import os
import platform
from pathlib import Path

import yaml
from loguru import logger

from broca.agent import Agent, AgentConfig
from broca.llm import LLMClient
from broca.session import SessionManager

logger.add("agent.log", level="DEBUG")


class AgentFactory:
    _instance = None
    built_in_agent_config_dir = Path(__file__).parent.parent / "configs" / "agents"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AgentFactory, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            # Removed shared LLMClient - each agent will have its own instance
            self._session_agents = {}

    async def init_session_agents(
        self, session_id=None, workspace=None, provider=None, model=None
    ) -> list[Agent]:
        """
        初始化会话的 Agent

        Args:
            session_id: 可选的会话ID，如果提供则恢复该会话的 agents
            workspace: 工作空间路径
            provider: 可选的 LLM provider，会覆盖配置中的设置
            model: 可选的 LLM model，会覆盖配置中的设置
        """
        if session_id is not None:
            agents = await self.restore_agents_from_session(session_id)
            session_agents = {agent.name: agent for agent in agents}
            self._session_agents[session_id] = session_agents
        else:
            agent_configs = self._load_agent_configs(self.built_in_agent_config_dir)
            boostrap_config_dir = Path(os.getcwd()) / ".agents/agents"
            agent_configs.extend(self._load_agent_configs(boostrap_config_dir))
            session_manager = SessionManager()
            await session_manager.create_session(workspace=workspace)
            agents = []
            for config in agent_configs:
                agent = await self._create_agent(
                    config, session_manager, workspace, provider, model
                )
                agents.append(agent)
            session_agents = {agent.name: agent for agent in agents}
            self._session_agents[session_manager.session_id] = session_agents

        return agents

    async def _create_agent(
        self, agent_config, session_manager, workspace=None, provider=None, model=None
    ) -> Agent:
        """
        创建 Agent 实例

        Args:
            agent_config: agent 配置字典
            session_manager: session 管理器
            workspace: 可选的 workspace 路径
            provider: 可选的 LLM provider，会覆盖配置中的值
            model: 可选的 LLM model，会覆盖配置中的值
        """
        config = AgentConfig.from_config(agent_config)
        if workspace is not None:
            config.workspace = workspace
        if not config.workspace:
            config.workspace = os.getcwd()

        # 覆盖 LLM provider 和 model（如果提供了的话）
        if provider is not None:
            config.provider = provider
        if model is not None:
            config.model = model

        if config.environment is None:
            config.environment = self._init_environment(config)
        # Each agent gets its own LLMClient instance
        llm_client = LLMClient()
        agent = Agent(config, llm_client, session_manager)
        await session_manager.save_agent(agent)
        return agent

    async def restore_agents_from_session(self, session_id) -> list[Agent]:
        session_manager = SessionManager()
        await session_manager.load_session(session_id)
        db_agents = await session_manager.get_agents()
        agents = []
        for db_agent in db_agents:
            agent = await self.restore_agent(db_agent["agent_id"], session_manager)
            agents.append(agent)
        return agents

    async def restore_agent(self, agent_id, session_manager=None, session_id=None):
        if session_manager is None:
            session_manager = SessionManager()
            await session_manager.load_session(session_id)
        config = await session_manager.get_agent_config(agent_id)
        logger.info(f"Restoring agent from config: {config}, agent_id: {agent_id}")
        agent_config = AgentConfig.from_config(config)
        # Each agent gets its own LLMClient instance
        llm_client = LLMClient()
        agent = Agent(
            agent_config, llm_client, session_manager, agent_id=agent_id
        )
        await agent.restore_from_session(agent_id)
        if session_manager.session_id not in self._session_agents:
            self._session_agents[session_manager.session_id] = {}
        self._session_agents[session_manager.session_id][agent.name] = agent
        return agent

    def _init_environment(self, config: AgentConfig) -> str:
        return f"System: {platform.system()}\nWorkspace: {config.workspace}"

    def _load_agent_configs(self, config_dir):
        configs = []
        if not os.path.exists(config_dir):
            return configs
        for file in os.listdir(config_dir):
            if file.endswith(".md"):
                config_path = os.path.join(config_dir, file)
                config = self._load_agent_config(config_path)
                if config:
                    configs.append(config)
        return configs

    def _load_agent_config(self, config_path):
        with open(config_path, encoding="utf-8") as f:
            content = f.read()
            parts = content.split("---", 2)
            if len(parts) < 3 or len(parts[2].strip()) == 0:
                logger.error(f"Invalid format in {config_path}.")
                return {}
            try:
                header = parts[1].strip()
                config = yaml.safe_load(header)
                config["system_prompt_template"] = parts[2].strip()
                if "tools" in config and isinstance(config["tools"], str):
                    config["tools"] = [
                        part.strip() for part in config["tools"].split(",")
                    ]
                return config
            except yaml.YAMLError as e:
                logger.error(f"YAML parsing error in {config_path}: {e}")
                return {}

    def get_agent(self, session_id, agent_name) -> Agent | None:
        if session_id not in self._session_agents:
            return None
        return self._session_agents[session_id].get(agent_name)
