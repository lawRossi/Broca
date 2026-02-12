import json
from pathlib import Path
from typing import Union

from jinja2 import Template
from litellm import Message

from broca.agent_configs import AgentConfig
from broca.session import MessageRole, MessageType, SessionManager
from broca.skill_manager import SkillManager


class Context:
    BOOTSTRAP_FILES = ["AGENTS.md"]

    def __init__(self, agent_config: AgentConfig, **kwargs):
        self._history: list = []
        self.initialize(agent_config, **kwargs)

    @property
    def history(self):
        return self._history

    def initialize(self, agent_config: AgentConfig, **kwargs):
        self.system_prompt = self._build_system_prompt(agent_config, **kwargs)
        self._history.append({"role": "system", "content": self.system_prompt})

    def _build_system_prompt(self, config: AgentConfig, **kwargs) -> str:
        prompt_template = config.system_prompt_template
        if config.environment:
            kwargs["environment"] = config.environment
        kwargs["subagents"] = "\n".join(config.subagents)
        if config.role_description:
            kwargs["role_description"] = config.role_description
        skill_manager = SkillManager()
        skills = skill_manager.get_skills(skill_names=config.skills)
        kwargs["skills"] = self._format_skills(skills)
        boostrap_content = self._load_bootstrap_files(config.workspace)
        if boostrap_content:
            kwargs["bootstrap_content"] = boostrap_content
        return Template(prompt_template).render(**kwargs)

    def _format_skills(self, skills: dict[str, dict]) -> str:
        skills_str = ""
        for name, skill in skills.items():
            skills_str += f"{name}: {skill['description']}\n"
        return skills_str.strip()

    def _load_bootstrap_files(self, workspace: str) -> str | None:
        boostrap_content = ""
        for file in self.BOOTSTRAP_FILES:
            file_path = Path(workspace) / file
            if file_path.exists() and file_path.is_file():
                text = file_path.read_text()
                if text.strip():
                    boostrap_content += f"### Guidelines from {file}\n\n{text}\n\n"

        return boostrap_content

    async def add_message(self, message: Union[dict, Message]):
        self._history.append(message)

    async def build_history_from_session(
        self, session_manager: SessionManager, agent_id: str
    ) -> None:
        messages = await session_manager.get_messages(agent_id)
        for message in messages:
            if message.role in [
                MessageRole.USER,
                MessageRole.ASSISTANT,
                MessageRole.SYSTEM,
                MessageRole.TOOL,
            ] and message.message_type in [MessageType.TEXT, MessageType.TOOL_RESULT]:
                message_content = json.loads(message.content)
                await self.add_message(Message.parse_obj(message_content))
