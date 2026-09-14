"""
Session Memory 管理器

负责会话笔记的自动维护，在后台使用子代理提取关键信息并更新笔记文件。

触发方式（统一"提取 + 压缩"流程）：
- 由 loop_engine 在 step 完成后调用 check_and_extract()
- 当 context token 数超过有效阈值时，先执行记忆提取，再执行截断压缩
- 保留最近 keep_steps 个 step（不跨 turn），更早的消息被压缩进 session memory
"""

import asyncio
import copy
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from broca.agent_manager import AgentFactory
from broca.context_compressor import ContextCompressor
from broca.loop_engine import ExecutionStatus
from broca.logging_config import get_logger
from broca.session import MessageProtocol, MessageType
from broca.session_memory.memory_prompts import (
    DEFAULT_MEMORY_TEMPLATE,
    build_extraction_user_prompt,
)

logger = get_logger(__name__)


@dataclass
class SessionMemoryState:
    """Session Memory 状态"""

    extraction_in_progress: bool = False

    def reset(self):
        """重置状态"""
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
        config,
        task_timeout: int = 120,
    ):
        # config 为 ContextCompactConfig
        self.workspace = workspace
        self.agent = agent
        self.config = config
        self.state = SessionMemoryState()
        self.task_timeout = task_timeout
        self._lock = asyncio.Lock()

        # 初始化时确保模板文件存在
        self._ensure_template_exists()

    @property
    def _agent_memory_dir(self) -> Path:
        """agent 级记忆目录"""
        return (
            Path(self.workspace)
            / ".broca"
            / (self.agent.session_id or "")
            / (self.agent.agent_id or "")
        )

    @property
    def snapshot_memory_path(self) -> str:
        """获取 memory 文件路径"""
        return str(self._agent_memory_dir / self.SNAPSHOT_MEMORY_FILENAME)

    @property
    def memory_path(self) -> str:
        """获取 memory 文件路径"""
        return str(self._agent_memory_dir / self.FROSEN_MEMORY_FILENAME)

    def is_session_memory_empty(self) -> bool:
        content = Path(self.snapshot_memory_path).read_text(encoding="utf-8").strip()
        return content == "" or content == DEFAULT_MEMORY_TEMPLATE.strip()

    def frosen_session_memory(self):
        shutil.copyfile(self.snapshot_memory_path, self.memory_path)

    def _read_session_memory_content(self):
        return Path(self.snapshot_memory_path).read_text(encoding="utf-8").strip()

    def _ensure_template_exists(self):
        """确保模板文件存在（启动时创建）"""
        memory_file = Path(self.snapshot_memory_path)
        if not memory_file.exists():
            memory_file.parent.mkdir(parents=True, exist_ok=True)
            memory_file.write_text(DEFAULT_MEMORY_TEMPLATE.strip(), encoding="utf-8")
            logger.info(f"Created session memory template at {memory_file}")

    # ========================================================================
    # token 阈值计算（复用 ContextCompressor）
    # ========================================================================

    def _estimate_context_tokens(self, context) -> int:
        return ContextCompressor()._estimate_context_tokens(context)

    def _get_effective_threshold(self) -> int:
        compressor = ContextCompressor()
        return compressor._get_effective_threshold(
            self.config.session_trunc_threshold,
            self.config.session_trunc_percentage,
            self.agent,
        )

    # ========================================================================
    # 统一触发：提取 + 压缩
    # ========================================================================

    async def check_and_extract(self, context, engine=None):
        """
        统一触发"提取 + 压缩"流程：

        1. 若提取进行中 → 返回；
        2. 计算有效 token 阈值；若 context token 数 ≤ 阈值 → 返回；
        3. 计算保留边界 keep_pivot（保留当前 turn 内最近 keep_steps 个 step），
           得到 keep_from_message_id 与对应的 context 索引 keep_index；
        4. 用 context.history[:keep_index]（被压缩的旧消息）作为子代理上下文，
           执行记忆提取（写 snapshot 文件）；
        5. 提取成功 → 截断压缩（标记截断、frozen、reset、重建 context）。
        """
        if self.state.extraction_in_progress:
            return

        # 1/2. token 阈值检查
        total_tokens = self._estimate_context_tokens(context)
        effective_threshold = self._get_effective_threshold()
        if total_tokens <= effective_threshold:
            return

        # 3. 计算保留边界
        keep_steps = getattr(self.config, "keep_steps", 5)
        keep_from_message_id, keep_index = await self._compute_keep_pivot(
            context, keep_steps
        )
        if not keep_from_message_id or keep_index is None:
            logger.info("Session Memory：无法计算保留边界 pivot，跳过截断")
            return

        logger.info(
            f"start to extract session memory (tokens={total_tokens}, "
            f"threshold={effective_threshold}, keep_steps={keep_steps})"
        )

        # 被压缩的旧消息（最新几步不写入记忆，避免丢信息）
        old_history = copy.copy(context.history[:keep_index])

        try:
            await self.agent.communicator.send_agent_system_message(
                content="Extracting session memory", subscription=self.agent.session_id
            )
            original_content = self._read_session_memory_content()
            success = await self._extract_and_compress(
                context=context,
                old_history=old_history,
                keep_from_message_id=keep_from_message_id,
            )
            if not success:
                with open(self.snapshot_memory_path, "w", encoding="utf-8") as f:
                    f.write(original_content)
        except Exception as e:
            logger.error(f"Session memory extraction failed: {e}")
            with open(self.snapshot_memory_path, "w", encoding="utf-8") as f:
                f.write(original_content)

    async def _extract_and_compress(
        self, context, old_history, keep_from_message_id
    ) -> bool:
        """
        执行提取，提取成功后执行截断压缩。

        Returns:
            是否提取成功（压缩仅在提取成功后执行）
        """
        async with self._lock:
            if self.state.extraction_in_progress:
                return False

            self.state.extraction_in_progress = True
            try:
                success = await self._do_extract(context, old_history)
                if not success:
                    return False

                await self._do_compress(context, keep_from_message_id)
                return True
            except Exception as e:
                logger.error(f"Session memory extraction/compression failed: {e}")
                return False
            finally:
                self.state.extraction_in_progress = False

    async def _do_compress(self, context, keep_from_message_id):
        """提取成功后执行截断压缩"""
        agent_id = self.agent.agent_id
        session_manager = self.agent.session_manager

        # 标记被压缩的旧消息为截断
        count = await session_manager.mark_messages_before_as_truncated(
            agent_id, keep_from_message_id
        )
        logger.info(
            f"Session Memory：截断完成，标记了 {count} 条消息为 truncated"
        )

        # snapshot -> frozen
        self.frosen_session_memory()
        self.reset()
        # 重建 context（system prompt + 保留的最近消息）
        await context.build_history_from_session(
            agent_id, rebuild_system_prompt=True
        )

    # ========================================================================
    # 保留边界 pivot 计算
    # ========================================================================

    async def _compute_keep_pivot(self, context, keep_steps: int):
        """
        计算保留边界。

        通过 agent 的 DB 消息序列计算：一个 assistant message 为一个 step，
        遇到 user message 即停止（不跨 turn）。

        Returns:
            (keep_from_message_id, keep_index)（无法计算时返回 (None, None)）
        """
        session_manager = self.agent.session_manager
        agent_id = self.agent.agent_id

        messages = await session_manager.get_messages(agent_id=agent_id)
        if not messages:
            return None, None

        # 找到当前（进行中）turn 的起点：最近一条 USER_MESSAGE
        current_turn_start = None
        for i, m in enumerate(messages):
            if m.message_type == MessageType.USER_MESSAGE:
                current_turn_start = i
        if current_turn_start is None:
            return None, None

        # 从最新消息向前扫描，统计 assistant step，遇到 user message 停止
        keep_from_message_id = None
        step_count = 0
        for i in range(len(messages) - 1, current_turn_start - 1, -1):
            m = messages[i]
            if m.message_type == MessageType.AGENT_RESPONSE:
                step_count += 1
                if step_count == keep_steps:
                    keep_from_message_id = m.message_id
                    break

        if keep_from_message_id is None:
            # 当前 turn 的 step 数 ≤ keep_steps → 保留整个当前 turn
            keep_from_message_id = messages[current_turn_start].message_id

        # 将 keep_from_message_id 映射到 context.history 索引
        keep_index = self._resolve_context_index(context, keep_from_message_id)
        if keep_index is None:
            return None, None

        return keep_from_message_id, keep_index

    def _resolve_context_index(self, context, message_id):
        """在 context 中根据 message_id 找到对应索引"""
        db_ids = getattr(context, "_message_db_ids", None)
        if not db_ids:
            return None
        for idx, db_id in enumerate(db_ids):
            if not db_id:
                continue
            if db_id == message_id or db_id.endswith(str(message_id)):
                return idx
        return None

    # ========================================================================
    # 提取（通过子代理）
    # ========================================================================

    async def _do_extract(self, context, old_history) -> bool:
        """实际提取逻辑——创建子代理执行"""
        current_content = self._read_session_memory_content()
        user_prompt = build_extraction_user_prompt(
            memory_path=self.snapshot_memory_path,
            current_content=current_content,
        )

        return await self._run_extraction_subagent(
            user_prompt=user_prompt,
            old_history=old_history,
            current_content=current_content,
        )

    async def _run_extraction_subagent(
        self, user_prompt: str, old_history, current_content: str
    ) -> bool:
        """
        创建并运行提取子代理

        子代理拥有独立的 LLM 调用，可用的工具仅限于文件操作。
        子代理只看到被压缩的旧消息（old_history），最新几步不写入记忆。
        """
        start = time.time()
        agent_factory = AgentFactory()
        session_manager = self.agent.session_manager
        agent_id = session_manager.session_id + self.AGENT_ID_POSTFIX
        agent_config = await session_manager.get_agent_config(agent_id)
        if agent_config is None:
            agent_config = self.agent.config.to_dict()
            agent_config["name"] = "session-memory-agent"
            agent_config["role"] = "session_memory_manager"
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
        sub_agent.context.history = copy.copy(old_history)
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
            return False
        else:
            end = time.time()
            logger.info("Session memory updated successfully via sub-agent")
            time_used = int(end - start)
            await self.agent.communicator.send_agent_system_message(
                content=f"Session memory updated successfully in {time_used} seconds",
                subscription=self.agent.session_id,
            )
            return True

    def reset(self):
        self.state.reset()
