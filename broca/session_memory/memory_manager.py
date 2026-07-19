"""
Session Memory 管理器

负责会话笔记的自动维护，在后台使用子代理提取关键信息并更新笔记文件。
"""

import asyncio
import copy
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from broca.agent_configs import SessionMemoryConfig
from broca.agent_manager import AgentFactory
from broca.context import Context
from broca.loop_engine import ExecutionStatus
from broca.logging_config import get_logger
from broca.session import MessageProtocol
from broca.session_memory.memory_prompts import (
    DEFAULT_MEMORY_TEMPLATE,
    build_extraction_user_prompt,
)

logger = get_logger(__name__)


@dataclass
class SessionMemoryState:
    """Session Memory 状态"""

    initialized: bool = False
    last_message_id: str = ""
    last_message_index: int = 0
    last_step_count: int = 0
    step_count: int = 0
    extraction_in_progress: bool = False

    def reset(self):
        """重置状态"""
        self.initialized = False
        self.last_message_id = ""
        self.last_message_index = 0
        self.last_step_count = 0
        self.step_count = 0
        self.extraction_in_progress = False


class SessionMemoryManager:
    """Session Memory 管理器"""

    FROSEN_MEMORY_FILENAME = "session-memory.md"
    SNAPSHOT_MEMORY_FILENAME = "session-memory_latest.md"
    AGENT_ID_POSTFIX = "#session-memory-agent"

    def __init__(
        self,
        workspace: str,
        agent,
        config: SessionMemoryConfig,
        task_timeout: int = 120,
    ):
        self.workspace = workspace
        self.agent = agent
        self.config = config
        self.state = SessionMemoryState()
        self.task_timeout = task_timeout
        self._lock = asyncio.Lock()

        # 初始化时确保模板文件存在
        self._ensure_template_exists()

    @property
    def snapshot_memory_path(self) -> str:
        """获取 memory 文件路径"""
        return str(
            Path(self.workspace)
            / ".broca"
            / self.agent.session_id
            / self.SNAPSHOT_MEMORY_FILENAME
        )

    @property
    def memory_path(self) -> str:
        """获取 memory 文件路径"""
        return str(
            Path(self.workspace)
            / ".broca"
            / self.agent.session_id
            / self.FROSEN_MEMORY_FILENAME
        )

    def is_session_memory_empty(self) -> bool:
        content = Path(self.snapshot_memory_path).read_text(encoding="utf-8").strip()
        return content == "" or content == DEFAULT_MEMORY_TEMPLATE.strip()

    def frosen_session_memory(self):
        shutil.copyfile(self.snapshot_memory_path, self.memory_path)

    def _read_session_memory_content(self):
        return Path(self.snapshot_memory_path).read_text(encoding="utf-8").strip()

    @property
    def last_message_id(self) -> str:
        """获取最后处理的消息 ID"""
        return self.state.last_message_id

    @property
    def last_message_index(self) -> int:
        """获取最后处理的消息索引"""
        return self.state.last_message_index

    def reset_last_message_index(self):
        """重置 last_message_index（索引校验不通过或截断成功后调用）"""
        self.state.last_message_index = 0
        self.state.initialized = False

    def _ensure_template_exists(self):
        """确保模板文件存在（启动时创建）"""
        memory_file = Path(self.snapshot_memory_path)
        if not memory_file.exists():
            memory_file.parent.mkdir(parents=True, exist_ok=True)
            memory_file.write_text(DEFAULT_MEMORY_TEMPLATE.strip(), encoding="utf-8")
            logger.info(f"Created session memory template at {memory_file}")

    async def check_and_extract(self, context):
        """检查并触发 session memory 提取"""
        if self.state.extraction_in_progress:
            return

        if not self._should_extract(context):
            return

        # 异步执行提取，不阻塞主流程
        logger.info("start to extract session memory")
        try:
            await self.agent.communicator.send_agent_system_message(
                content="Extracting session memory", subscription=self.agent.session_id
            )
            original_content = self._read_session_memory_content()
            task = asyncio.create_task(self._extract(context))
            task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None
            )
            await asyncio.wait_for(task, timeout=self.task_timeout)
        except Exception as e:
            logger.error(f"Session memory extraction failed: {e}")
            with open(self.snapshot_memory_path, "w", encoding="utf-8") as f:
                f.write(original_content)

    def _should_extract(self, context) -> bool:
        """判断是否应该提取"""
        messages = context.history
        current_msg_count = len(messages)

        # 初始化阈值检查
        if not self.state.initialized:
            if current_msg_count >= self.config.minimum_messages_to_init:
                self.state.initialized = True
            else:
                return False

        # 检查消息增长
        msg_growth = current_msg_count - self.state.last_message_index
        has_met_msg_threshold = (
            msg_growth >= self.config.minimum_messages_between_update
        )

        # 检查 step 增长
        step_growth = self.state.step_count - self.state.last_step_count
        has_met_step_threshold = step_growth >= self.config.steps_between_updates

        # 检查最后一条 assistant 消息是否有 tool_calls
        last_msg = messages[-1] if messages else None
        has_tool_calls = last_msg and (
            last_msg.get("role") == "tool" or last_msg.get("tool_calls")
        )

        should_extract = (
            has_met_msg_threshold and has_met_step_threshold and not has_tool_calls
        )

        if should_extract:
            self.state.last_step_count = self.state.step_count

        return should_extract

    async def _extract(self, context):
        """执行提取（通过子代理）"""
        async with self._lock:
            if self.state.extraction_in_progress:
                return

            self.state.extraction_in_progress = True
            try:
                await self._do_extract(context)
            except Exception as e:
                logger.error(f"Session memory extraction failed: {e}")
            finally:
                self.state.extraction_in_progress = False

    async def _do_extract(self, context):
        """实际提取逻辑——创建子代理执行"""
        current_content = self._read_session_memory_content()
        user_prompt = build_extraction_user_prompt(
            memory_path=self.snapshot_memory_path,
            current_content=current_content,
        )

        await self._run_extraction_subagent(
            user_prompt=user_prompt, context=context, current_content=current_content
        )

    async def _run_extraction_subagent(
        self, user_prompt: str, context: Context, current_content: str
    ):
        """
        创建并运行提取子代理

        子代理拥有独立的 LLM 调用，可用的工具仅限于文件操作。
        """
        # 创建子代理配置
        start = time.time()
        agent_factory = AgentFactory()
        session_manager = self.agent.session_manager
        agent_id = session_manager.session_id + self.AGENT_ID_POSTFIX
        agent_config = await session_manager.get_agent_config(agent_id)
        if agent_config is None:
            agent_config = self.agent.config.to_dict()
            agent_config["name"] = "session-memory-agent"
            agent_config["role"] = "session_memory_manager"
            agent_config["track_session_momory"] = False
            agent_config["enable_context_compression"] = False
            agent_config["save_history"] = False
            agent_config["interactive"] = False

            sub_agent = await agent_factory.create_agent(
                agent_config=agent_config,
                session_manager=session_manager,
                agent_id=agent_id,
            )
        else:
            sub_agent = agent_factory.get_agent(  # type: ignore[assignment]
                session_manager.session_id, agent_config["name"]
            )
            if sub_agent is None:
                sub_agent = await agent_factory.restore_agent(agent_id, session_manager)
        if not sub_agent.running:
            task = asyncio.create_task(sub_agent.start())
            task.add_done_callback(lambda t, a=sub_agent: a.stop())  # type: ignore[misc]
        sub_agent.context.history = copy.copy(context.history)
        trigger_message = MessageProtocol.create_user_message(
            content=user_prompt,
        )
        result = await sub_agent.run(
            trigger_message, from_agent=True, allowed_tools=["edit_file"]
        )

        if result.status != ExecutionStatus.COMPLETED:
            logger.warning(
                f"Session memory sub-agent execution failed: {result.status}"
            )
            await self.agent.communicator.send_agent_system_message(
                content="Fail to extract session memory",
                subscription=self.agent.session_id,
            )
            with open(self.snapshot_memory_path, "w", encoding="utf-8") as f:
                f.write(current_content)
        else:
            end = time.time()
            logger.info("Session memory updated successfully via sub-agent")
            time_used = int(end - start)
            await self.agent.communicator.send_agent_system_message(
                content=f"Session memory updated successfully in {time_used} seconds",
                subscription=self.agent.session_id,
            )
            self.state.last_message_index = len(context.history) - 1
            db_id = context.get_message_db_id(self.state.last_message_index)
            if db_id is not None:
                self.state.last_message_id = db_id

    def increment_step(self):
        """增加 step 计数"""
        self.state.step_count += 1

    def reset(self):
        self.state.reset()
