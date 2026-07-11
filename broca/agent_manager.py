import asyncio
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

import yaml

from broca.agent import Agent, AgentConfig
from broca.llm import LLMClient
from broca.logging_config import get_logger
from broca.session import SessionManager
from broca.tools.tool_manager import ToolManager

logger = get_logger(__name__)


class AgentFactory:
    _instance = None

    def _resolve_agent_config_dir(self) -> str:
        """获取 Agent 配置目录，优先级: 环境变量 > ~/.broca > 包默认"""
        # 1. 环境变量
        env_dir = os.getenv("BROCA_AGENTS_CONFIG_DIR")
        if env_dir:
            return env_dir
        # 2. ~/.broca/configs/agents/
        user_dir = str(Path.home() / ".broca" / "configs" / "agents")
        if os.path.isdir(user_dir):
            return user_dir
        # 3. 包内默认路径（editable 安装时指向项目，非 editable 时指向 site-packages）
        return str(Path(__file__).parent.parent / "configs" / "agents")

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
        self,
        session_id=None,
        workspace=None,
        provider=None,
        model=None,
        category="normal",
    ) -> tuple[list[Agent], Optional[str]]:
        """
        初始化会话的 Agent

        Args:
            session_id: 可选的会话ID，如果提供则恢复该会话的 agents
            workspace: 工作空间路径
            provider: 可选的 LLM provider，会覆盖配置中的设置
            model: 可选的 LLM model，会覆盖配置中的设置
            category: 会话分类（normal/agent-orchestration）

        Returns:
            (agents, session_id) 元组
            agents: Agent 列表
            session_id: 会话 ID（新建或恢复的）

        normal 分类：加载内置 Agent 配置（main_agent/sub_agent/explorer）
        agent-orchestration 分类：不加载内置 Agent，只从 workspace 加载自定义 Agent
        """
        if session_id is not None:
            agents = await self.restore_agents_from_session(session_id)
            session_agents = {agent.name: agent for agent in agents}
            self._session_agents[session_id] = session_agents
            return agents, session_id
        else:
            session_manager = SessionManager()
            await session_manager.create_session(workspace=workspace)
            new_session_id = session_manager.session_id

            if category == "agent-orchestration":
                agents = await self._init_agent_orchestration_agents(
                    session_manager, workspace, provider, model
                )
            else:
                agents = await self._init_normal_session_agents(
                    session_manager, workspace, provider, model
                )

            return agents, new_session_id

    async def _init_normal_session_agents(
        self, session_manager, workspace=None, provider=None, model=None
    ) -> list[Agent]:
        """初始化普通会话的 Agent（内置 + 自定义）"""
        agent_configs = self._load_agent_configs(self._resolve_agent_config_dir())
        boostrap_config_dir = Path(os.getcwd()) / ".agents/agents"
        agent_configs.extend(self._load_agent_configs(boostrap_config_dir))

        agents = []
        for config in agent_configs:
            agent = await self.create_agent(
                config, session_manager, workspace, provider, model
            )
            agents.append(agent)
        return agents

    async def _init_agent_orchestration_agents(
        self, session_manager, workspace=None, provider=None, model=None
    ) -> list[Agent]:
        """
        初始化 Agent 编排会话的 Agent

        从 workspace 的 .broca/agents/ 目录加载自定义 Agent 配置。
        如果没有自定义 Agent，则返回空列表（编排器会动态创建 Agent）。
        """
        agents = []

        if not workspace:
            logger.info(
                "Agent-orchestration session has no workspace, skipping custom agent loading"
            )
            return agents

        # 从 workspace/.broca/agents/ 加载自定义 Agent 配置
        custom_agents_dir = Path(workspace) / ".agents" / "agents"
        if custom_agents_dir.exists():
            custom_configs = self._load_agent_configs(str(custom_agents_dir))
            for config in custom_configs:
                agent = await self.create_agent(
                    config, session_manager, workspace, provider, model
                )
                agents.append(agent)
            logger.info(f"Loaded {len(agents)} custom agents from {custom_agents_dir}")
        else:
            logger.info(f"No custom agents directory found at {custom_agents_dir}")

        return agents

    async def create_agent(
        self,
        agent_config,
        session_manager,
        workspace=None,
        provider=None,
        model=None,
        agent_id: str = None,
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

        # Initialize ToolManager (loads custom tools + MCP servers).
        # Idempotent: only happens once across all agents in this process.
        await ToolManager().init(config.workspace)

        # 覆盖 LLM provider 和 model（如果提供了的话）
        if provider is not None:
            config.provider = provider
        if model is not None:
            config.model = model

        if config.environment is None:
            config.environment = self._init_environment(config)
        # Each agent gets its own LLMClient instance
        llm_client = LLMClient()
        agent = await Agent.create(
            config, llm_client, session_manager, agent_id=agent_id
        )
        await session_manager.save_agent(agent)
        if session_manager.session_id not in self._session_agents:
            self._session_agents[session_manager.session_id] = {}
        self._session_agents[session_manager.session_id][agent.name] = agent
        self.dump_agent_config_cache(config, session_manager.session_id)

        return agent

    def _get_agent_config_cache_path(self, workspace, session_id, agent_name):
        cache_path = (
            Path(workspace) / ".broca" / session_id / "agents" / f"{agent_name}.json"
        )
        return cache_path

    def dump_agent_config_cache(self, agent_config, session_id):
        cache_path = self._get_agent_config_cache_path(
            agent_config.workspace, session_id, agent_config.name
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            f.write(agent_config.to_json())

    def load_cached_agent_config(self, workspace, session_id, agent_name):
        cache_path = self._get_agent_config_cache_path(
            workspace, session_id, agent_name
        )
        if cache_path.exists():
            with open(cache_path, "r") as f:
                return json.load(f)
        return None

    async def restore_agents_from_session(self, session_id) -> list[Agent]:
        session_manager = SessionManager()
        await session_manager.load_session(session_id)
        db_agents = await session_manager.get_agents()

        agents = await asyncio.gather(
            *[
                self.restore_agent(db_agent["agent_id"], session_manager)
                for db_agent in db_agents
            ]
        )

        return agents

    async def restore_agent(
        self, agent_id, session_manager=None, session_id=None
    ) -> Agent:
        if session_manager is None:
            session_manager = SessionManager()
            await session_manager.load_session(session_id)

        config = await session_manager.get_agent_config(agent_id)
        cached_config = self.load_cached_agent_config(
            config["workspace"], session_manager.session_id, config["name"]
        )
        if cached_config:
            un_modifiable_fields = ["name", "workspace", "environment"]
            for field in un_modifiable_fields:
                del cached_config[field]
            config.update(cached_config)
        logger.debug(f"Restoring agent from config: {config}, agent_id: {agent_id}")
        agent_config = AgentConfig.from_config(config)

        # Ensure ToolManager is initialized (idempotent — safe to call on restore)
        await ToolManager().init(agent_config.workspace)

        llm_client = LLMClient()
        agent = await Agent.create(
            agent_config, llm_client, session_manager, agent_id=agent_id
        )
        await agent.restore_from_session(agent_id)
        if session_manager.session_id not in self._session_agents:
            self._session_agents[session_manager.session_id] = {}
        self._session_agents[session_manager.session_id][agent.name] = agent

        return agent

    def _init_environment(self, config: AgentConfig) -> str:
        lines = [
            f"System: {platform.system()}",
            f"Workspace: {config.workspace}",
        ]

        # --- Python environment ---
        active_ver, active_path = self._detect_active_python()
        lines.append(f"Your default Python: {active_ver} ({active_path})")

        sys_ver, sys_path = self._detect_system_python(active_path)
        if sys_path:
            lines.append(f"System Python: {sys_ver} ({sys_path})")
        else:
            lines.append("System Python: (not found outside current environment)")

        venvs = self._detect_workspace_venvs(config.workspace)
        if venvs:
            lines.append("Workspace Python virtual environments:")
            for name, ver in venvs:
                ver_info = f" ({ver})" if ver else ""
                lines.append(f"  - {name}{ver_info}")
        else:
            lines.append("Wrokspace Python virtual environments: (none detected)")

        return "\n".join(lines)

    @staticmethod
    def _detect_active_python() -> tuple[str, str]:
        """Detect the currently active Python environment."""
        ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        return ver, sys.executable

    @staticmethod
    def _get_python_version(python_path: str) -> str:
        """Run `python --version` and return the version string."""
        try:
            result = subprocess.run(
                [python_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return (result.stdout or result.stderr).strip()
        except Exception:
            return ""

    @staticmethod
    def _detect_system_python(active_path: str) -> tuple[str, str]:
        """Detect system-global Python, skipping the current active one.

        Returns (version_string, path) or ("", "") if not found.
        """
        real_active = os.path.realpath(active_path)
        candidates: list[str] = []

        # 1. Well-known system paths (Linux / macOS)
        candidates.extend(
            [
                "/usr/bin/python3",
                "/usr/bin/python",
                "/usr/local/bin/python3",
                "/usr/local/bin/python",
                "/opt/homebrew/bin/python3",
                "/opt/homebrew/bin/python",
            ]
        )

        # 2. `which -a` (Linux/macOS) / `where` (Windows): discover all PATH entries
        for exe_name in ("python3", "python"):
            try:
                cmd = (
                    ["where", exe_name]
                    if platform.system() == "Windows"
                    else ["which", "-a", exe_name]
                )
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for p in result.stdout.strip().split("\n"):
                        p = p.strip()
                        if p and p not in candidates:
                            candidates.append(p)
            except Exception:
                continue

        # 3. Windows: common installation directories
        if platform.system() == "Windows":
            for drive in ("C:", "D:"):
                for ver_dir in sorted(Path(drive).glob("Python3*"), reverse=True):
                    py_exe = str(ver_dir / "python.exe")
                    if py_exe not in candidates:
                        candidates.append(py_exe)

        # Try each candidate, skip duplicates and the active interpreter
        seen_real = set()
        for candidate in candidates:
            if not os.path.exists(candidate):
                continue
            try:
                real_candidate = os.path.realpath(candidate)
            except Exception:
                continue
            if real_candidate in seen_real:
                continue
            seen_real.add(real_candidate)
            if real_candidate == real_active:
                continue
            ver = AgentFactory._get_python_version(candidate)
            if ver:
                return ver, candidate

        return "", ""

    @staticmethod
    def _detect_workspace_venvs(workspace: str) -> list[tuple[str, str]]:
        """Scan workspace for common Python virtual environment directories.

        Returns list of (directory_name, version_string).
        """
        venv_dirs: list[tuple[str, str]] = []
        ws_path = Path(workspace) if workspace else None
        if not ws_path or not ws_path.is_dir():
            return venv_dirs

        for candidate in ("venv", ".venv", "env", ".env", "virtualenv"):
            venv_path = ws_path / candidate
            if not venv_path.is_dir():
                continue

            # Linux/macOS: bin/python or bin/python3
            bin_dir = venv_path / "bin"
            bin_python = bin_dir / "python"
            bin_python3 = bin_dir / "python3"
            # Windows: Scripts/python.exe
            scripts_dir = venv_path / "Scripts"
            scripts_python = scripts_dir / "python.exe"

            if bin_python.exists():
                venv_py = str(bin_python)
            elif bin_python3.exists():
                venv_py = str(bin_python3)
            elif scripts_python.exists():
                venv_py = str(scripts_python)
            else:
                continue

            ver = AgentFactory._get_python_version(venv_py)
            venv_dirs.append((candidate, ver))

        return venv_dirs

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
