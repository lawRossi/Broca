"""
上下文压缩器（Context Compressor）

实现一种压缩策略：
- Session Memory 截断（Session Memory Truncation）

根据设计文档 docs/context-compression-design.md 实现。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from broca.agent import Agent
    from broca.context import Context

from broca.agent_configs import ContextCompactConfig
from broca.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class CompressionStats:
    """压缩统计信息"""

    truncated_count: int = 0
    truncated_message_ids: List[str] = field(default_factory=list)

    def reset(self):
        self.truncated_count = 0
        self.truncated_message_ids = []


class ContextCompressor:
    """
    上下文压缩器

    负责检查 context token 数，触发 session memory 截断。
    """

    def __init__(self):
        self.stats = CompressionStats()
        self._llm_config: Optional[dict] = None

    def _get_llm_config(self) -> dict:
        """加载并缓存 LLM 配置"""
        if self._llm_config is None:
            config_path: str | Path = os.getenv("BROCA_LLM_CONFIG") or ""
            if not config_path:
                config_path = (
                    Path(__file__).parent.parent / "configs" / "llm_config.json"
                )
            with open(config_path) as f:
                self._llm_config = json.load(f)
        return self._llm_config

    def _get_effective_threshold(
        self, absolute_threshold: int, percentage: float, agent: "Agent"
    ) -> int:
        """
        计算有效触发阈值。

        有效阈值 = min(绝对阈值, context_window * percentage)

        Args:
            absolute_threshold: 配置文件中的绝对 token 阈值
            percentage: 上下文窗口百分比（自动钳位到 [0.05, 1.0]）
            agent: Agent 实例（用于获取 provider 和 model）

        Returns:
            较小的有效阈值
        """
        percentage = max(0.05, min(1.0, percentage))

        llm_config = self._get_llm_config()
        provider = agent.config.provider
        model = agent.config.model

        # 尝试从 LLM 配置中获取模型对应的 context_window
        if provider in llm_config and "models" in llm_config[provider]:
            if model in llm_config[provider]["models"]:
                meta = llm_config[provider]["models"][model].get("meta", {})
                context_window = meta.get("context_window")
                if context_window is not None:
                    percentage_threshold = int(context_window * percentage)
                    return min(absolute_threshold, percentage_threshold)

        # 如果取不到 context_window，回退使用绝对阈值
        return absolute_threshold

    async def check_and_compress(
        self, context, execution_engine, agent: "Agent", force: bool = False
    ) -> CompressionStats:
        """
        检查 context token 数并触发压缩。

        在 execute_step 完成后调用。当 force=True 时，跳过 token 阈值检查直接执行压缩。

        Args:
            context: Context 实例
            execution_engine: ExecutionEngine 实例（用于获取 step 信息和写操作）
            agent: Agent
            force: 是否强制压缩（跳过 token 阈值检查）

        Returns:
            CompressionStats: 压缩统计信息
        """
        self.stats.reset()

        compact_config: ContextCompactConfig = agent.config.compact_config

        # 估算 context 总 token 数
        total_tokens = self._estimate_context_tokens(context)

        # Session Memory 截断
        if compact_config.enable_session_memory_truncation:
            if force:
                await self._try_session_memory_truncation(
                    context=context,
                    execution_engine=execution_engine,
                    agent=agent,
                    config=compact_config,
                )
            else:
                effective_threshold = self._get_effective_threshold(
                    compact_config.session_trunc_threshold,
                    compact_config.session_trunc_percentage,
                    agent,
                )
                if total_tokens > effective_threshold:
                    await self._try_session_memory_truncation(
                        context=context,
                        execution_engine=execution_engine,
                        agent=agent,
                        config=compact_config,
                    )

        return self.stats

    def _estimate_context_tokens(self, context) -> int:
        """
        估算 context 的总 token 数。

        使用简单的字符数估算（约 3 字符/token）。
        """
        total_chars = 0
        for msg in context.history:
            if isinstance(msg, dict):
                content = msg.get("content", "")
                if content:
                    total_chars += len(str(content))
            elif hasattr(msg, "content"):
                total_chars += len(str(msg.content))
        # 粗略估算：约 3 字符/token
        return total_chars // 3

    # ========================================================================
    # Session Memory 截断
    # ========================================================================

    async def _try_session_memory_truncation(
        self,
        context,
        execution_engine,
        agent,
        config: ContextCompactConfig,
    ):
        """
        尝试使用 session memory 做截断。

        流程：
        1. 安全校验（内容非空 + 索引对齐）
        2. 确定截断边界
        3. 将 session memory 注入 system prompt
        4. 重建 context
        5. 标记被截断的消息到数据库
        6. 重置 SessionMemoryManager
        """
        session_memory_manager = agent.session_memory_manager

        if not session_memory_manager:
            logger.info("Session Memory：无 session_memory_manager，跳过截断")
            return

        # 校验一：Session memory 内容非空
        if session_memory_manager.is_session_memory_empty():
            logger.info("Session Memory：session_memory 内容为空，跳过截断")
            return

        # 校验二：last_message_index 与 context 对齐
        last_index = session_memory_manager.last_message_index
        if last_index == 0:
            return

        if not self._validate_index_alignment(context, session_memory_manager):
            logger.warning(
                f"Session Memory：last_message_index ({last_index}) 与 context 不对齐，"
                "重置并跳过截断"
            )
            session_memory_manager.reset_last_message_index()
            return

        # 校验通过，执行截断
        await self._do_session_memory_truncation(
            context=context,
            execution_engine=execution_engine,
            agent=agent,
            config=config,
        )

    def _validate_index_alignment(self, context, session_memory_manager) -> bool:
        """验证 last_message_index 与当前 context 对齐"""
        last_index = session_memory_manager.state.last_message_index
        history = context.history

        # 索引越界检查
        if last_index >= len(history):
            return False

        # 通过 context 的 message_id 映射获取该消息的数据库 ID
        msg_db_id = context.get_message_db_id(last_index)

        if not msg_db_id:
            return False

        return msg_db_id == session_memory_manager.last_message_id

    async def _do_session_memory_truncation(
        self,
        context,
        execution_engine,
        agent,
        config: ContextCompactConfig,
    ):
        """
        执行 session memory 截断。

        1. 获取 session memory 内容
        2. 注入到 system prompt
        3. 重建 context（保留截断点之后的消息）
        4. 标记被截断的消息到数据库
        5. 重置 SessionMemoryManager
        """
        session_memory_manager = agent.session_memory_manager
        pivot_message_id = session_memory_manager.last_message_id

        # 标记被截断的消息到数据库
        session_manager = execution_engine.session_manager
        count = await session_manager.mark_messages_as_truncated(
            agent.agent_id, pivot_message_id
        )
        self.stats.truncated_count = count
        session_memory_manager.frosen_session_memory()
        session_memory_manager.reset()
        context.build_history_from_session(agent.agent_id, rebuild_system_prompt=True)

        logger.info(
            f"Session Memory：Session memory 截断完成，"
            f"截断了 {self.stats.truncated_count} 条消息"
        )

    def get_pre_loaded_skills(self, context: Context, last_index: int):
        pre_loaded_skills = []
        for msg in context.history[last_index:]:
            if msg.get("role") == "tool":
                tool_name = msg.get("meta").get("tool_name")
                status = msg.get("meta").get("status")
                if tool_name == "load_skill" and status == "success":
                    arguments = msg.get("meta").get("arguments")
                    pre_loaded_skills.append(arguments.get("skill_name"))

        return pre_loaded_skills
