import json
from pathlib import Path
from typing import Union

from jinja2 import Template
from litellm import Message

from broca.agent_configs import AgentConfig
from broca.logging_config import get_logger
from broca.session import MessageType, SessionManager
from broca.skill_manager import SkillManager

logger = get_logger(__name__)


class Context:
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", ".agents/AGENTS.md", ".agents/SOUL.md"]

    def __init__(self, agent_config: AgentConfig, **kwargs):
        self.system_prompt = self._build_system_prompt(agent_config, **kwargs)
        self._history: list = []
        self._history.append({"role": "system", "content": self.system_prompt})

    @property
    def history(self):
        return self._history

    @history.setter
    def history(self, value):
        self._history = value

    def _build_system_prompt(self, config: AgentConfig, **kwargs) -> str:
        prompt_template = config.system_prompt_template
        if config.environment:
            kwargs["environment"] = config.environment
        if config.role_description:
            kwargs["role_description"] = config.role_description
        skill_manager = SkillManager()
        skills = skill_manager.get_skills(config.workspace, skill_names=config.skills)
        kwargs["skills"] = self._format_skills(skills)
        boostrap_content = self._load_bootstrap_files(config.workspace)
        if boostrap_content:
            kwargs["bootstrap_content"] = boostrap_content
        return Template(prompt_template).render(**kwargs).strip()

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
                    boostrap_content += f"## Instrunction from {file}\n\n{text}\n\n"

        return boostrap_content.strip()

    async def add_message(self, message: Union[dict, Message]):
        self._history.append(message)

    async def build_history_from_session(
        self, session_manager: SessionManager, agent_id: str, rebuild=False
    ) -> None:
        self._history: list = []
        self._history.append({"role": "system", "content": self.system_prompt})
        messages = await session_manager.get_messages(agent_id)
        for message in messages:
            if message.message_type in [
                MessageType.USER_MESSAGE,
                MessageType.AGENT_RESPONSE,
                MessageType.TOOL_CALL,
            ]:
                # 获取content，现在content在data字段中
                content = message.data.get("content")
                if content is None:
                    continue
                message_content = json.loads(content)
                if message_content["role"] != "user":
                    await self.add_message(Message.parse_obj(message_content))
                else:
                    await self.add_message(message_content)

    def get_latest_assistant_message(self) -> str | None:
        if not self._history:
            return None
        message = self._history[-1]
        if message["role"] == "assistant":
            return message["content"]

        return None

    async def truncate_last_assistant_message_with_tool_calls(
        self, session_manager=None, turn_id=None, agent_id=None
    ):
        """
        Truncate the last assistant message with tool_calls from context and database.

        This method checks if the last message in context is an assistant message
        with tool_calls, and if so:
        1. Removes it from context
        2. Checks if it was persisted to database (if session_manager provided)
        3. If persisted, removes it from database

        Args:
            session_manager: Optional session manager for database operations
            turn_id: Optional turn ID for database lookup
            agent_id: Optional agent ID for database lookup
        """
        try:
            # Check if context has messages
            if not self._history:
                logger.debug("Context history is empty, nothing to truncate")
                return

            # Get the last message from context
            last_message = self._history[-1]

            # Check if it's an assistant message with tool_calls
            if last_message.get("role") != "assistant":
                logger.debug("Last message is not from assistant, skipping truncation")
                return

            if not last_message.get("tool_calls"):
                logger.debug(
                    "Last assistant message has no tool_calls, skipping truncation"
                )
                return

            # Log the message being truncated
            message_content = last_message.get("content", "")
            truncated_preview = (
                message_content[:100] + "..."
                if len(message_content) > 100
                else message_content
            )
            logger.info(
                f"Truncating last assistant message with tool_calls: {truncated_preview}"
            )

            # Remove the message from context
            self._history.pop()
            logger.debug("Removed message from context")

            # Check if the message was persisted to database
            if session_manager and turn_id and agent_id:
                await self._delete_last_persisted_assistant_message(
                    session_manager, turn_id, agent_id
                )
            else:
                logger.debug(
                    "No session_manager, turn_id or agent_id, skipping database cleanup"
                )

        except Exception as e:
            logger.error(f"Error truncating last assistant message: {e}")

    async def _delete_last_persisted_assistant_message(
        self, session_manager, turn_id, agent_id
    ):
        """
        Delete the last persisted assistant message from database.

        This method finds the last assistant message with AGENT_RESPONSE type
        for the current turn and agent, and deletes it from database.
        """
        from broca.logging_config import get_logger

        logger = get_logger(__name__)

        try:
            # Get message service
            message_service = session_manager.message_service

            # Get messages for the current turn and agent
            messages = await message_service.get_batch(
                filters={
                    "turn_id": turn_id,
                    "agent_id": agent_id,
                    "message_type": "AGENT_RESPONSE",
                },
                order_by="sequence_number desc",
                limit=1,
            )

            if not messages:
                logger.debug("No persisted assistant messages found for current turn")
                return

            # Get the last message
            last_persisted_message = messages[0]

            # Check if it's an assistant message
            if last_persisted_message.role != "assistant":
                logger.debug("Last persisted message is not from assistant")
                return

            # Check if it has tool_calls in its data
            message_data = last_persisted_message.data
            if message_data:
                # Try to parse the content to check for tool_calls
                content = message_data.get("content")
                if content:
                    try:
                        parsed_content = json.loads(content)
                        # LLMMessage的tool_calls字段可能在根级别
                        if not parsed_content.get("tool_calls"):
                            logger.debug(
                                "Last persisted assistant message has no tool_calls"
                            )
                            return
                    except Exception as parse_error:
                        logger.debug(f"Could not parse message content: {parse_error}")
                        # If we can't parse, we should still delete it to be safe
                        # since we already removed it from context

            # Delete the message from database
            message_id = last_persisted_message.message_id
            deleted = await message_service.delete(message_id)

            if deleted:
                logger.info(
                    f"Deleted persisted assistant message from database: {message_id}"
                )
            else:
                logger.warning(
                    f"Failed to delete persisted assistant message: {message_id}"
                )

        except Exception as e:
            logger.error(f"Error deleting last persisted assistant message: {e}")
