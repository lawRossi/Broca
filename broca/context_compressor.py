"""
上下文压缩器（Context Compressor）

实现两种压缩策略：
- 策略A：清理过期工具调用结果（Stale Tool Result Cleanup）
- 策略B：Session Memory 截断（Session Memory Truncation）

根据设计文档 docs/context-compression-design.md 实现。
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

from broca.agent_configs import DEFAULT_COMPACT_CONFIG, ContextCompactConfig
from broca.context import Context
from broca.logging_config import get_logger
from broca.session import MessageService
from broca.tools.tool_manager import ToolManager

logger = get_logger(__name__)


@dataclass
class CompressionStats:
    """压缩统计信息"""

    expired_count: int = 0
    truncated_count: int = 0
    expired_message_ids: List[str] = field(default_factory=list)
    truncated_message_ids: List[str] = field(default_factory=list)

    def reset(self):
        self.expired_count = 0
        self.truncated_count = 0
        self.expired_message_ids = []
        self.truncated_message_ids = []


class ContextCompressor:
    """
    上下文压缩器

    负责检查 context token 数，触发过期工具结果清理和 session memory 截断。
    """

    EXCLUSIVE_TOOLS = ["load_skill"]

    def __init__(
        self,
        config: Optional[ContextCompactConfig] = None,
        message_service: Optional[MessageService] = None,
    ):
        self.config = config or DEFAULT_COMPACT_CONFIG
        self.message_service = message_service
        self.stats = CompressionStats()

    def get_effective_config(self, agent_config) -> ContextCompactConfig:
        """获取有效的压缩配置（支持 agent 级别覆盖）"""
        if not agent_config.enable_context_compression:
            return ContextCompactConfig(
                enable_stale_tool_cleanup=False,
                enable_session_memory_truncation=False,
            )

        if agent_config.compact_config:
            merged = {**self.config.__dict__, **agent_config.compact_config}
            return ContextCompactConfig(**merged)

        return self.config

    async def check_and_compress(
        self, context, execution_engine, agent: "Agent"
    ) -> CompressionStats:
        """
        检查 context token 数并触发压缩。

        在 execute_step 完成后调用。

        Args:
            context: Context 实例
            execution_engine: ExecutionEngine 实例（用于获取 step 信息和写操作）
            agent: Agent

        Returns:
            CompressionStats: 压缩统计信息
        """
        self.stats.reset()

        compact_config = self.get_effective_config(agent.config)

        # 估算 context 总 token 数
        total_tokens = self._estimate_context_tokens(context)

        # 策略A：清理过期工具调用结果
        if compact_config.enable_stale_tool_cleanup:
            if total_tokens > compact_config.stale_tool_cleanup_token_threshold:
                await self._cleanup_stale_tool_results(
                    context=context,
                    execution_engine=execution_engine,
                    config=compact_config,
                )

        # 策略B：Session Memory 截断
        if compact_config.enable_session_memory_truncation:
            if total_tokens > compact_config.session_memory_truncation_token_threshold:
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
    # 策略A：清理过期工具调用结果
    # ========================================================================

    async def _cleanup_stale_tool_results(
        self, context, execution_engine, config: ContextCompactConfig
    ):
        """
        清理过期的工具调用结果。

        检测写操作关联和时间因素，将过期的工具结果替换为占位符。
        """
        history = context.history

        # 从后往前遍历，保留最近的 N 条工具结果
        recent_tool_count = 0
        stop_index = 0
        for i in range(len(history) - 1, -1, -1):
            msg = history[i]
            if not isinstance(msg, dict):
                continue
            if msg.get("role") != "tool":
                continue

            recent_tool_count += 1
            if recent_tool_count == config.min_recent_tool_results_to_keep:
                stop_index = i
                break

        expired_indices = self._get_expired_indices(context, stop_index, config)

        if not self._check_stale_content_threshold(context, config, expired_indices):
            return

        # 标记过期
        for index in expired_indices:
            db_id = context.mark_message_as_expired(index)
            if db_id:
                self.stats.expired_message_ids.append(db_id)
                self.stats.expired_count += 1

        # 更新数据库
        if self.message_service and self.stats.expired_message_ids:
            await self._update_expired_in_db()

        if self.stats.expired_count > 0:
            logger.info(f"策略A：标记了 {self.stats.expired_count} 条工具结果为过期")

    def _get_expired_indices(self, context, stop_index, config: ContextCompactConfig):
        expired_indices = []
        prev_tool_call_results: dict = defaultdict(list)
        history = context.history
        history_len = len(history)
        for i in range(0, stop_index):
            msg = history[i]

            if msg.get("role") != "tool":
                continue

            if self._is_tool_result_cleared(msg):
                continue

            tool_name = msg.get("meta").get("tool_name")
            if (
                tool_name not in self.EXCLUSIVE_TOOLS
                and history_len - i > config.min_stale_messages
            ):
                expired_indices.append(i)
                continue
            arguments = msg.get("meta").get("arguments")
            for idx, prev_arguments in prev_tool_call_results.get(tool_name, []):
                if idx in expired_indices:
                    continue
                if tool_name in ToolManager.MODIFY_TOOLS:
                    if arguments.get("path") == prev_arguments.get("path"):
                        expired_indices.append(idx)
                        continue
                elif arguments == prev_arguments:
                    expired_indices.append(idx)
                    continue

            prev_tool_call_results[tool_name].append((i, arguments))

        return expired_indices

    def _check_stale_content_threshold(
        self, context, config: ContextCompactConfig, expired_indices: list[int]
    ):
        total_chars = 0
        for index in expired_indices:
            msg = context.history[index]
            if isinstance(msg, dict):
                content = msg.get("content", "")
                if content:
                    total_chars += len(str(content))
            elif hasattr(msg, "content"):
                total_chars += len(str(msg.content))

        tokens_count = total_chars // 3
        return tokens_count >= config.min_stale_tokens

    def _is_tool_result_cleared(self, msg: dict) -> bool:
        """
        判断工具调用结果是否被清除。
        """
        return msg.get("content") == Context.STALE_TOOL_RESULT_PLACEHOLDER

    def _get_msg_step(self, msg: dict) -> Optional[int]:
        """
        从工具调用消息中提取 step 号。

        工具结果消息在 context 中存储为 dict，格式如：
        {"role": "tool", "tool_call_id": "...", "content": "..."}

        如果消息包含 _meta 字段（由 _cleanup_stale_tool_results 在标记时附加），
        则从中提取 step 号。否则返回 None。
        """
        meta = msg.get("_meta")
        if isinstance(meta, dict):
            return meta.get("step")
        return None

    def _get_msg_timestamp(self, msg: dict) -> Optional[float]:
        """
        从工具调用消息中提取时间戳。

        如果消息包含 _meta 字段，则从中提取时间戳。
        否则返回 None。
        """
        meta = msg.get("_meta")
        if isinstance(meta, dict):
            ts = meta.get("timestamp")
            if ts is not None:
                return float(ts)
        return None

    async def _update_expired_in_db(self):
        """批量更新数据库中的 is_expired 字段"""
        if not self.message_service or not self.stats.expired_message_ids:
            return

        for msg_id in self.stats.expired_message_ids:
            try:
                await self.message_service.update_message(msg_id, {"is_expired": True})
            except Exception as e:
                logger.error(f"Failed to update message {msg_id} as expired: {e}")

    # ========================================================================
    # 策略B：Session Memory 截断
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
            logger.info("策略B：无 session_memory_manager，跳过截断")
            return

        # 校验一：Session memory 内容非空
        if session_memory_manager.is_session_memory_empty():
            logger.info("策略B：session_memory 内容为空，跳过截断")
            return

        # 校验二：last_message_index 与 context 对齐
        last_index = session_memory_manager.last_message_index
        if last_index == 0:
            return

        if not self._validate_index_alignment(context, session_memory_manager):
            logger.warning(
                f"策略B：last_message_index ({last_index}) 与 context 不对齐，"
                "重置并跳过截断"
            )
            session_memory_manager.reset_last_message_index()
            return

        # 校验通过，执行截断
        await self._do_session_memory_truncation(
            context=context,
            execution_engine=execution_engine,
            agent=agnet,
            config=config,
        )

    def _validate_index_alignment(self, context, session_memory_manager) -> bool:
        """验证 last_message_index 与当前 context 对齐"""
        last_index = session_memory_manager.last_message_index
        history = context.history

        # 索引越界检查
        if last_index >= len(history):
            return False

        # 通过 context 的 message_id 映射获取该消息的数据库 ID
        msg_db_id = context.get_message_db_id(last_index)

        # 如果没有对应的数据库 ID，说明该消息不是从数据库加载的 → 无效
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
        last_index = session_memory_manager.last_message_index

        # 获取需要标记为截断的消息 ID 列表
        truncated_ids = context.get_truncated_message_ids(last_index)

        # 标记被截断的消息到数据库
        if self.message_service and truncated_ids:
            for msg_id in truncated_ids:
                try:
                    await self.message_service.update_message(
                        msg_id, {"is_truncated": True}
                    )
                except Exception as e:
                    logger.error(f"Failed to update message {msg_id} as truncated: {e}")

            self.stats.truncated_message_ids = truncated_ids
            self.stats.truncated_count = len(truncated_ids)

        session_memory_manager.frosen_session_memory()
        session_memory_manager.reset()
        context.build_history_from_session(agent.agent_id, rebuild_system_prompt=True)

        logger.info(
            f"策略B：Session memory 截断完成，"
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
