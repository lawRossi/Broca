"""
Session Memory 管理器

负责会话笔记的自动维护，在后台使用子代理提取关键信息并更新笔记文件。
"""

import asyncio
import copy
from pathlib import Path
from typing import Optional

from broca.agent_manager import AgentFactory
from broca.execution_engine import ExecutionStatus
from broca.logging_config import get_logger
from broca.session import MessageProtocol
from broca.session_memory.memory_prompts import (
    build_extraction_user_prompt,
)
from broca.session_memory.memory_utils import (
    DEFAULT_CONFIG,
    SessionMemoryConfig,
    SessionMemoryState,
)

logger = get_logger(__name__)

# 默认模板（启动时写入文件）
DEFAULT_MEMORY_TEMPLATE = """# Session Title
_A short and distinctive 5-10 word descriptive title for the session._ (KEEP THIS LINE)

# Current State
_What is actively being worked on right now? Pending tasks not yet completed._ (KEEP THIS LINE)

# Task Specification
_What did the user ask to do? Design decisions and context._ (KEEP THIS LINE)

# Files and Functions
_Important files and their purposes._ (KEEP THIS LINE)

# Workflow
_Commands and their execution order._ (KEEP THIS LINE)

# Errors & Corrections
_Errors encountered and how they were fixed, what did the user correct/feedback?._ (KEEP THIS LINE)

# Project Documentation
_Important project components/modules and their purposes._ (KEEP THIS LINE)

# Learnings
_What has worked well? What has not?_ (KEEP THIS LINE)

# Key Results
_Specific outputs requested by the user._ (KEEP THIS LINE)

# Worklog
_Step by step actions taken. Very terse summary for each step_ (KEEP THIS LINE)
"""


class SessionMemoryManager:
    """Session Memory 管理器"""

    MEMORY_FILENAME = "session-memory.md"
    AGENT_ID_POSTFIX = "#session-memory-agent"

    def __init__(
        self,
        workspace: str,
        agent,
        config: Optional[SessionMemoryConfig] = None,
        task_timeout: int = 60,
    ):
        self.workspace = workspace
        self.agent = agent
        self.config = config or DEFAULT_CONFIG
        self.state = SessionMemoryState()
        self.task_timeout = task_timeout
        self._lock = asyncio.Lock()

        # 初始化时确保模板文件存在
        self._ensure_template_exists()

    @property
    def memory_path(self) -> str:
        """获取 memory 文件路径"""
        return str(
            Path(self.workspace)
            / ".broca"
            / self.agent.session_id
            / self.MEMORY_FILENAME
        )

    def read_session_memory_content(self) -> str:
        return Path(self.memory_path).read_text(encoding="utf-8").strip()

    def is_session_memory_empty(self) -> bool:
        content = self.read_session_memory_content()
        return content == "" or content == DEFAULT_MEMORY_TEMPLATE.strip()

    @property
    def last_message_index(self) -> int:
        """获取最后处理的消息索引"""
        return self.state.last_message_index

    @property
    def has_content(self) -> bool:
        """检查 session memory 是否有实际内容（非空模板）"""
        content = self.read_session_memory_content()
        return content != "" and content != DEFAULT_MEMORY_TEMPLATE.strip()

    def get_session_memory_content(self) -> str:
        """获取 session memory 内容"""
        return self.read_session_memory_content()

    def reset_last_message_index(self):
        """重置 last_message_index（索引校验不通过或截断成功后调用）"""
        self.state.last_message_index = 0
        self.state.initialized = False

    def _ensure_template_exists(self):
        """确保模板文件存在（启动时创建）"""
        memory_file = Path(self.memory_path)
        if not memory_file.exists():
            memory_file.parent.mkdir(parents=True, exist_ok=True)
            memory_file.write_text(DEFAULT_MEMORY_TEMPLATE.strip(), encoding="utf-8")
            logger.info(f"Created session memory template at {self.memory_path}")

    async def check_and_extract(self, context):
        """检查并触发 session memory 提取"""
        if self.state.extraction_in_progress:
            return

        if not self._should_extract(context):
            return

        # 异步执行提取，不阻塞主流程
        logger.info("start to extract session memory")
        await self.agent.communicator.send_agent_system_message(
            content="Extracting session memory", subscription=self.agent.session_id
        )
        original_content = self.read_session_memory_content()
        task = asyncio.create_task(self._extract(context))
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        try:
            await asyncio.wait_for(task, timeout=self.task_timeout)
        except Exception as e:
            logger.error(f"Session memory extraction failed: {e}")
            with open(self.memory_path, "w", encoding="utf-8") as f:
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
            self.state.last_message_index = current_msg_count
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
        user_prompt = build_extraction_user_prompt(
            memory_path=self.memory_path,
            current_content=self.read_session_memory_content(),
        )

        await self._run_extraction_subagent(
            user_prompt=user_prompt,
            context=context,
        )

    async def _run_extraction_subagent(self, user_prompt, context):
        """
        创建并运行提取子代理

        子代理拥有独立的 LLM 调用，可用的工具仅限于文件操作。
        """
        # 创建子代理配置
        agent_factory = AgentFactory()
        session_manager = self.agent.session_manager
        agent_id = session_manager.session_id + self.AGENT_ID_POSTFIX
        agent_config = await session_manager.get_agent_config(agent_id)
        if agent_config is None:
            agent_config = self.agent.config.to_dict()
            agent_config["name"] = "session-memory-agent"
            agent_config["role"] = "session_memory_manager"
            agent_config["tools"] = ["edit_file"]
            agent_config["track_session_momory"] = False
            agent_config["save_history"] = False
            agent_config["interactive"] = False

            sub_agent = await agent_factory.create_agent(
                agent_config=agent_config,
                session_manager=session_manager,
                agent_id=agent_id,
            )
        else:
            sub_agent = agent_factory.get_agent(
                session_manager.session_id, agent_config["name"]
            )
            if sub_agent is None:
                sub_agent = await agent_factory.restore_agent(agent_id, session_manager)
        if not sub_agent.running:
            task = asyncio.create_task(sub_agent.start())
            task.add_done_callback(lambda t, a=sub_agent: a.stop())
        sub_agent.context.history = copy.copy(context.history)
        trigger_message = MessageProtocol.create_user_message(
            content=user_prompt,
        )
        result = await sub_agent.run(trigger_message, from_agent=True)

        if result.status != ExecutionStatus.COMPLETED:
            logger.warning(
                f"Session memory sub-agent execution failed: {result.status}"
            )
            await self.agent.communicator.send_agent_system_message(
                content="Fail to extract session memory",
                subscription=self.agent.session_id,
            )
        else:
            logger.info("Session memory updated successfully via sub-agent")
            await self.agent.communicator.send_agent_system_message(
                content="Session memory updated successfully",
                subscription=self.agent.session_id,
            )
            self.state.last_message = context.history[-1]
            self.state.last_message_index = len(context.history)

    def increment_step(self):
        """增加 step 计数"""
        self.state.step_count += 1

    def reset(self):
        self.state.reset()
