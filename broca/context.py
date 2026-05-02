import json
from pathlib import Path
from typing import Optional, Union

from jinja2 import Template
from litellm import Message

from broca.agent_configs import AgentConfig
from broca.logging_config import get_logger
from broca.session import MessageType, SessionManager
from broca.skill_manager import SkillManager
from broca.utils import scan_content_security

# 记忆存储路径和分隔符（与 broca/tools/memory.py 保持一致）
MEMORY_DIR = Path(".broca") / "memories"
MEMORY_ENTRY_DELIMITER = "\n§\n"
MEMORY_CHAR_LIMIT = 2200
USER_CHAR_LIMIT = 1375

logger = get_logger(__name__)


class Context:
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", ".agents/AGENTS.md", ".agents/SOUL.md"]
    STALE_TOOL_RESULT_PLACEHOLDER = "[Expired tool result has been cleared]"

    def __init__(
        self, agent_config: AgentConfig, session_manager: SessionManager, **kwargs
    ):
        self.agent_config = agent_config
        self.session_manager = session_manager
        self.system_prompt_kwargs = kwargs
        self.system_prompt = self._build_system_prompt()
        self._init_history()

    def _init_history(self) -> None:
        self._history: list = []
        self._message_db_ids: list = []  # 与 _history 一一对应，存储数据库 message_id
        self._history.append({"role": "system", "content": self.system_prompt})
        self._message_db_ids.append(None)  # system prompt 没有数据库记录

    @property
    def history(self):
        return self._history

    @history.setter
    def history(self, value):
        self._history = value

    def get_message_db_id(self, index: int) -> Optional[str]:
        """获取指定索引消息的数据库 message_id"""
        if 0 <= index < len(self._message_db_ids):
            return self._message_db_ids[index]
        return None

    def set_message_db_id(self, index: int, db_id: str):
        """设置指定索引消息的数据库 message_id"""
        if 0 <= index < len(self._message_db_ids):
            self._message_db_ids[index] = db_id

    def mark_message_as_expired(self, index: int) -> Optional[str]:
        """
        标记 context 中指定索引的消息为过期。

        Returns:
            对应的数据库 message_id，可用于更新数据库
        """
        db_id = self.get_message_db_id(index)
        if db_id:
            # 替换 context 中的 content 为占位符
            if index < len(self._history):
                msg = self._history[index]
                if msg.get("role") == "tool":
                    msg["content"] = self.STALE_TOOL_RESULT_PLACEHOLDER
            return db_id
        return None

    def _build_system_prompt(self) -> str:
        config = self.agent_config
        kwargs = self.system_prompt_kwargs
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
        session_memory = self._load_session_memory()
        if session_memory:
            kwargs["session_memory"] = session_memory
        memory_content, user_content = self._load_memory_store()
        if memory_content:
            kwargs["memory_content"] = memory_content
        if user_content:
            kwargs["user_content"] = user_content
        return Template(prompt_template).render(**kwargs).strip()

    def _format_skills(self, skills: dict[str, dict]) -> str:
        skills_str = ""
        for name, skill in skills.items():
            skills_str += f"{name}: {skill['description']}\n"
        return skills_str.strip()

    def _load_session_memory(self) -> str:
        workspace = self.agent_config.workspace
        session_id = self.session_manager.session_id
        session_memeory_path = (
            Path(workspace) / ".broca" / session_id / "session-memory.md"
        )
        if session_memeory_path.exists():
            return session_memeory_path.read_text(encoding="utf-8").strip()
        return ""

    def _load_memory_store(self) -> tuple[str, str]:
        """
        加载持久化记忆存储（MEMORY.md 和 USER.md），
        格式化为 system prompt 可注入的文本块。

        Returns:
            (memory_block, user_block): 格式化后的记忆文本块，无内容时返回空字符串
        """
        mem_dir = MEMORY_DIR
        if not mem_dir.exists():
            return "", ""

        memory_entries = Context._read_memory_file(mem_dir / "MEMORY.md")
        user_entries = Context._read_memory_file(mem_dir / "USER.md")

        memory_block = Context._format_memory_block(
            "memory", memory_entries, MEMORY_CHAR_LIMIT
        )
        user_block = Context._format_memory_block("user", user_entries, USER_CHAR_LIMIT)
        return memory_block, user_block

    @staticmethod
    def _read_memory_file(path: Path) -> list[str]:
        """读取记忆文件并拆分为条目列表"""
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, IOError):
            return []
        if not raw.strip():
            return []
        entries = [e.strip() for e in raw.split(MEMORY_ENTRY_DELIMITER)]
        return [e for e in entries if e]

    @staticmethod
    def _format_memory_block(target: str, entries: list[str], char_limit: int) -> str:
        """将记忆条目格式化为 system prompt 文本块"""
        if not entries:
            return ""

        content = MEMORY_ENTRY_DELIMITER.join(entries)
        current = len(content)
        pct = min(100, int((current / char_limit) * 100)) if char_limit > 0 else 0

        if target == "user":
            header = (
                f"USER PROFILE (who the user is) "
                f"[{pct}% — {current:,}/{char_limit:,} chars]"
            )
        else:
            header = (
                f"MEMORY (your personal notes) "
                f"[{pct}% — {current:,}/{char_limit:,} chars]"
            )
        separator = "═" * 46
        return f"{separator}\n{header}\n{separator}\n{content}"

    def _load_bootstrap_files(self, workspace: str) -> str | None:
        boostrap_content = ""
        for file in self.BOOTSTRAP_FILES:
            file_path = Path(workspace) / file
            if file_path.exists() and file_path.is_file():
                text = file_path.read_text()
                if text.strip():
                    # 安全扫描：防止提示注入
                    scan_error = scan_content_security(text)
                    if scan_error:
                        logger.warning(f"安全阻断：文件 {file} 被跳过，{scan_error}")
                        continue
                    boostrap_content += f"## Instrunction from {file}\n\n{text}\n\n"

        return boostrap_content.strip()

    async def add_message(
        self, message: Union[dict, Message], db_message_id: Optional[str] = None
    ):
        """
        添加消息到 context

        Args:
            message: 消息内容
            db_message_id: 对应的数据库 message_id（可选）
        """
        self._history.append(message)
        self._message_db_ids.append(db_message_id)

    async def build_history_from_session(
        self, agent_id: str, rebuild_system_prompt: bool = False
    ) -> None:
        if rebuild_system_prompt:
            self.system_prompt = self._build_system_prompt()

        self._init_history()

        messages = await self.session_manager.get_messages(agent_id)
        for message in messages:
            if message.message_type in [
                MessageType.USER_MESSAGE,
                MessageType.AGENT_RESPONSE,
                MessageType.TOOL_CALL,
            ]:
                # 策略B：被 session memory 截断的消息 → 跳过
                if message.is_truncated:
                    continue

                content = message.data.get("content")
                if content is None:
                    continue
                if message.message_type == MessageType.TOOL_CALL:
                    message_content = self.format_tool_call_result(message)
                else:
                    message_content = json.loads(content)

                if message_content["role"] != "user":
                    await self.add_message(
                        Message.parse_obj(message_content),
                        db_message_id=message.message_id,
                    )
                else:
                    await self.add_message(
                        message_content,
                        db_message_id=message.message_id,
                    )

    def format_tool_call_result(self, message) -> dict:
        message_content = json.loads(message.data.get("content"))
        if message.is_expired:
            message_content["content"] = self.STALE_TOOL_RESULT_PLACEHOLDER
        message_content["meta"] = {
            "tool_name": message.data.get("tool_name", ""),
            "arguments": message.data.get("arguments", {}),
            "status": message.data.get("status", ""),
        }
        return message_content

    def get_latest_assistant_message(self) -> str | None:
        if not self._history:
            return None
        message = self._history[-1]
        if message["role"] == "assistant":
            return message["content"]

        return None

    async def truncate_last_assistant_message_with_tool_calls(
        self, turn_id=None, agent_id=None
    ):
        """
        Truncate the last assistant message with tool_calls from context and database.

        This method checks if the last message in context is an assistant message
        with tool_calls, and if so:
        1. Removes it from context
        2. Checks if it was persisted to database
        3. If persisted, removes it from database

        Args:
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
            if turn_id and agent_id:
                await self._delete_last_persisted_assistant_message(turn_id, agent_id)
            else:
                logger.debug(
                    "No session_manager, turn_id or agent_id, skipping database cleanup"
                )

        except Exception as e:
            logger.error(f"Error truncating last assistant message: {e}")

    async def _delete_last_persisted_assistant_message(self, turn_id, agent_id):
        """
        Delete the last persisted assistant message from database.

        This method finds the last assistant message with AGENT_RESPONSE type
        for the current turn and agent, and deletes it from database.
        """
        from broca.logging_config import get_logger

        logger = get_logger(__name__)

        try:
            # Get message service
            message_service = self.session_manager.message_service

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
