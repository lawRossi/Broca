"""
PersistentMemoryManager — 持久化记忆提取管理器

管理基于独立子 Agent 的记忆提取，支持自动提取（轮次结束时按阈值触发）
和 on-demand 提取（通过 memory 工具触发）。
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from pathlib import Path
from typing import Optional

from broca.agent_configs import PersistentMemoryConfig
from broca.agent_manager import AgentFactory
from broca.context import Context
from broca.loop_engine import ExecutionStatus
from broca.session import MessageProtocol

from .prompts import build_extraction_prompt
from .state import PersistentMemoryState
from .store import MemoryStore

logger = logging.getLogger(__name__)

# 子 Agent 允许的工具白名单
ALLOWED_TOOLS = [
    "read_file",
    "glob",
    "grep",
    "list_dir",
    "tree_dir",
    "edit_file",
    "write_file",
    "load_skill",
]

AGENT_ID_POSTFIX = "#persistent-memory-agent"


class PersistentMemoryManager:
    """
    持久化记忆提取管理器。

    提供两种提取方式：
    1. 自动提取（check_and_extract）：每轮结束后触发，检查消息/步数阈值
    2. On-demand 提取（trigger_extraction）：被 memory 工具调用，跳过阈值检查
    """

    def __init__(
        self,
        workspace: str,
        agent,
        config: PersistentMemoryConfig,
        task_timeout: int = 120,
    ):
        self.workspace = workspace
        self.agent = agent
        self.config = config
        self.state = PersistentMemoryState()
        self.task_timeout = task_timeout
        self._lock = asyncio.Lock()

        self._store = MemoryStore(
            memory_dir=Path(workspace) / ".broca" / "memories",
            freshness_warning_days=config.freshness_warning_days,
        )

    # ────────────────────────────────────────
    # 公共方法
    # ────────────────────────────────────────

    def increment_step(self):
        """每步调用，递增 step 计数器（用于自动提取节流）"""
        self.state.step_count += 1

    async def check_and_extract(self, context: Context):
        """
        自动提取入口——在轮次结束时调用。

        检查消息数/步数阈值，满足条件且无提取进行中时触发子 Agent。
        """
        if self.state.extraction_in_progress:
            return

        if not self._should_extract(context):
            return

        logger.info("Persistent memory auto-extraction triggered")
        await self._trigger_internal(context, hint=None)

    async def trigger_extraction(self, context: Context, hint: Optional[str] = None):
        """
        On-demand 提取入口——被 memory 工具调用。

        跳过阈值检查，直接触发提取。

        Args:
            context: 当前对话上下文
            hint: 可选提示，引导子 Agent 关注特定内容
        """
        if self.state.extraction_in_progress:
            logger.info("Extraction already in progress, skipping on-demand trigger")
            return

        logger.info(f"Persistent memory on-demand extraction triggered (hint: {hint})")
        await self._trigger_internal(context, hint=hint)

    # ────────────────────────────────────────
    # 内部方法
    # ────────────────────────────────────────

    def _should_extract(self, context: Context) -> bool:
        """
        判断是否应该触发自动提取。

        条件：
        1. 消息数达到初始化阈值
        2. 消息增长达到更新阈值
        3. step 增长达到步数阈值
        4. 最后一条消息不是 tool_call 结果
        """
        messages = context.history
        current_msg_count = len(messages)

        # 初始化阈值
        if not self.state.initialized:
            if current_msg_count >= self.config.minimum_messages_to_init:
                self.state.initialized = True
            else:
                return False

        # 消息增长阈值
        msg_growth = current_msg_count - self.state.last_message_index
        has_met_msg_threshold = (
            msg_growth >= self.config.minimum_messages_between_update
        )

        # step 增长阈值
        step_growth = self.state.step_count - self.state.last_step_count
        has_met_step_threshold = step_growth >= self.config.steps_between_updates

        # 最后一条不是 tool_call
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

    async def _trigger_internal(self, context: Context, hint: Optional[str]):
        """内部触发逻辑：异步执行提取，不阻塞主流程"""
        self.state.extraction_in_progress = True
        try:
            task = asyncio.create_task(self._run_extraction(context, hint))
            await asyncio.wait_for(task, timeout=self.task_timeout)
        except asyncio.TimeoutError:
            logger.warning("Persistent memory extraction timed out")
        except Exception as e:
            logger.error(f"Persistent memory extraction failed: {e}")
        finally:
            self.state.extraction_in_progress = False

    async def _run_extraction(self, context: Context, hint: Optional[str]):
        """
        执行提取操作。

        1. 备份当前 MEMORY.md
        2. 读取现有索引
        3. 构建提取 prompt
        4. 创建子 Agent 并执行
        5. 失败时回滚
        6. 成功时通知
        """
        async with self._lock:
            if not self.state.extraction_in_progress:
                return

            try:
                await self._do_extract(context, hint)
            except Exception as e:
                logger.error(f"Extraction failed: {e}")

    async def _do_extract(self, context: Context, hint: Optional[str]):
        """实际提取逻辑"""
        # 1. 读取当前索引内容作为备份和注入
        index_content = ""
        if self._store.index_path.exists():
            index_content = self._store._read_file(self._store.index_path)
        backup_content = index_content

        # 2. 构建提取 prompt
        user_prompt = build_extraction_prompt(
            existing_index_content=index_content,
            hint=hint,
        )

        # 3. 执行子 Agent 提取
        success = await self._run_extraction_subagent(
            user_prompt=user_prompt,
            context=context,
            backup_content=backup_content,
        )

        # 4. 通知结果
        if success:
            await self.agent.communicator.send_agent_system_message(
                content="Persistent memory updated successfully",
                subscription=self.agent.session_id,
            )
            self.state.last_message_index = len(context.history) - 1
        else:
            # 回滚
            if backup_content:
                self._store._write_file(self._store.index_path, backup_content)
            await self.agent.communicator.send_agent_system_message(
                content="Persistent memory extraction failed, changes rolled back",
                subscription=self.agent.session_id,
            )

    async def _run_extraction_subagent(
        self,
        user_prompt: str,
        context: Context,
        backup_content: str,
    ) -> bool:
        """
        创建并运行提取子 Agent。

        子 Agent 拥有独立的 LLM 调用，可用的工具限于 ALLOWED_TOOLS。
        """
        start = time.time()
        agent_factory = AgentFactory()
        session_manager = self.agent.session_manager
        agent_id = session_manager.session_id + AGENT_ID_POSTFIX

        # 获取或创建子 Agent 配置
        agent_config = await session_manager.get_agent_config(agent_id)
        if agent_config is None:
            agent_config = self.agent.config.to_dict()
            agent_config["name"] = "persistent-memory-agent"
            agent_config["role"] = "persistent_memory_manager"
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
            sub_agent = agent_factory.get_agent(
                session_manager.session_id, agent_config["name"]
            )
            if sub_agent is None:
                sub_agent = await agent_factory.restore_agent(agent_id, session_manager)

        # 确保子 Agent 在运行
        if not sub_agent.running:
            task = asyncio.create_task(sub_agent.start())
            task.add_done_callback(lambda t, a=sub_agent: a.stop())

        # Fork 当前上下文，去掉末尾带 tool_calls 的 assistant 消息
        history = copy.copy(context.history)
        if history:
            last = history[-1]
            role = (
                last.get("role")
                if isinstance(last, dict)
                else getattr(last, "role", None)
            )
            tool_calls = (
                last.get("tool_calls")
                if isinstance(last, dict)
                else getattr(last, "tool_calls", None)
            )
            if role == "assistant" and tool_calls:
                history = history[:-1]
        sub_agent.context.history = history

        # 触发提取
        trigger_message = MessageProtocol.create_user_message(content=user_prompt)
        result = await sub_agent.run(
            trigger_message,
            from_agent=True,
            allowed_tools=ALLOWED_TOOLS,
        )

        elapsed = int(time.time() - start)

        if result.status != ExecutionStatus.COMPLETED:
            logger.warning(
                f"Persistent memory sub-agent execution failed: "
                f"{result.status} after {elapsed}s"
            )
            return False

        logger.info(f"Persistent memory extraction completed in {elapsed}s")
        return True

    def reset(self):
        """重置状态"""
        self.state.reset()
