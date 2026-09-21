"""
上下文压缩器（Context Compressor）

实现一种压缩策略：
- Session Memory 截断（Session Memory Truncation）

根据设计文档 docs/context-compression-design.md 实现。
"""

from __future__ import annotations

import copy
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
        检查 context token 数并触发压缩（统一"提取 + 压缩"流程）。

        在 execute_step 完成后由 loop_engine 调用。当 force=True 时（手动
        /compact），跳过 token 阈值检查直接执行压缩。

        流程：
        1. 校验存在 session_memory_manager；
        2. token 阈值检查（force 时跳过）；
        3. 计算保留边界 keep_pivot（保留最近 N 步，不跨 turn）；
        4. 调用 session_memory_manager 提取记忆（用被压缩的旧消息更新 snapshot）；
        5. 提取成功 → 截断压缩（标记截断、frozen、reset、重建 context）。

        Args:
            context: Context 实例
            execution_engine: ExecutionEngine 实例（用于获取 session_manager）
            agent: Agent
            force: 是否强制压缩（跳过 token 阈值检查）

        Returns:
            CompressionStats: 压缩统计信息
        """
        self.stats.reset()

        session_memory_manager = agent.session_memory_manager
        if not session_memory_manager:
            logger.info("Session Memory：无 session_memory_manager，跳过压缩")
            return self.stats

        compact_config: ContextCompactConfig = agent.config.compact_config

        # 获取 context token 数（优先用 LLM 返回的真实值）
        total_tokens = self._get_total_tokens(context, agent)

        # token 阈值检查
        if not force:
            effective_threshold = self._get_effective_threshold(
                compact_config.session_trunc_threshold,
                compact_config.session_trunc_percentage,
                agent,
            )
            if total_tokens <= effective_threshold:
                return self.stats

        await self._do_session_memory_compress(
            context=context,
            execution_engine=execution_engine,
            agent=agent,
            total_tokens=total_tokens,
        )

        return self.stats

    def _estimate_context_tokens(self, context) -> int:
        """
        估算 context 的总 token 数。

        涵盖 content、reasoning_content, tool_calls，使用约 3 字符/token 的粗略换算。
        """
        total_chars = 0
        for msg in context.history:
            if isinstance(msg, dict):
                total_chars += len([msg["content"]])
            elif hasattr(msg, "content"):
                # litellm.Message 对象：统计 content + reasoning_content + tool_calls
                total_chars += len(str(msg.content or ""))
                rc = getattr(msg, "reasoning_content", None)
                if rc:
                    total_chars += len(str(rc))
                tc = getattr(msg, "tool_calls", None)
                if tc:
                    total_chars += len(
                        json.dumps(tc, ensure_ascii=False, default=str)
                    )
        return total_chars // 3

    def _get_total_tokens(self, context, agent) -> int:
        """
        获取 context 的总 token 数。

        优先使用 LLM 调用返回的真实值（agent.last_context_length），
        再加上最后一次 LLM 调用后新增的 tool result 消息的估算值。
        取不到真实值时回退到全量字符估算。
        """
        last_ctx = getattr(agent, "last_context_length", None)
        if last_ctx is None:
            return self._estimate_context_tokens(context)
        tool_result_tokens = self._estimate_recent_tool_result_tokens(context)
        return last_ctx + tool_result_tokens

    @staticmethod
    def _estimate_recent_tool_result_tokens(context) -> int:
        """
        估算最近一次 LLM 调用后新增的 tool result 消息的 token 数。

        从 context.history 末尾向前扫描，累计 role == "tool" 的消息字符数，
        遇到非 tool 消息即停止（即最后一条 assistant 消息）。
        """
        total_chars = 0
        for msg in reversed(context.history):
            role = (
                msg.get("role") if isinstance(msg, dict)
                else getattr(msg, "role", None)
            )
            if role == "tool":
                content = (
                    msg.get("content", "") if isinstance(msg, dict)
                    else (msg.content or "")
                )
                total_chars += len(str(content))
            else:
                break
        return total_chars // 3

    # ========================================================================
    # Session Memory 压缩（统一"提取 + 压缩"）
    # ========================================================================

    async def _do_session_memory_compress(
        self,
        context,
        execution_engine,
        agent,
        total_tokens,
    ):
        """
        统一"提取 + 压缩"流程。

        1. 通过 manager 计算保留边界 keep_pivot（保留最近 N 步，不跨 turn）；
        2. 调用 manager 提取记忆（用被压缩的旧消息 context.history[:keep_index]
           更新 snapshot 文件）；
        3. 提取成功 → 截断压缩：
           - 标记被截断的消息到数据库
           - 将 snapshot 冻结为 frozen memory
           - 重建 context（保留截断点之后的消息）
           - 重置 SessionMemoryManager
        """
        session_memory_manager = agent.session_memory_manager
        compact_config = agent.config.compact_config
        keep_steps = getattr(compact_config, "keep_steps", 5)

        # 1. 计算保留边界（复用 manager 的 pivot 计算）
        keep_from_message_id, keep_index = (
            await session_memory_manager.compute_keep_pivot(context, keep_steps)
        )
        if not keep_from_message_id or keep_index is None:
            logger.info("Session Memory：无法计算保留边界 pivot，跳过压缩")
            return

        logger.info(
            f"Session Memory：开始压缩 (tokens={total_tokens}, "
            f"keep_steps={keep_steps})"
        )

        # 2. 提取记忆（用被压缩的旧消息，最新几步不写入记忆避免丢信息）
        old_history = copy.copy(context.history[:keep_index])
        extraction_ok = await session_memory_manager.extract(context, old_history)
        if not extraction_ok:
            logger.info("Session Memory：记忆提取失败，跳过压缩")
            return

        # 3. 截断压缩
        session_manager = execution_engine.session_manager
        count = await session_manager.mark_messages_before_as_truncated(
            agent.agent_id, keep_from_message_id
        )
        self.stats.truncated_count = count
        session_memory_manager.frozen_session_memory()
        session_memory_manager.reset()
        await context.build_history_from_session(
            agent.agent_id, rebuild_system_prompt=True
        )

        logger.info(
            f"Session Memory：Session memory 压缩完成，"
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
