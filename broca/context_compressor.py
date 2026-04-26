"""
上下文压缩器（Context Compressor）

实现两种压缩策略：
- 策略A：清理过期工具调用结果（Stale Tool Result Cleanup）
- 策略B：Session Memory 截断（Session Memory Truncation）

根据设计文档 docs/context-compression-design.md 实现。
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Template

from broca.agent_configs import ContextCompactConfig, DEFAULT_COMPACT_CONFIG
from broca.logging_config import get_logger
from broca.session import MessageType, MessageService

logger = get_logger(__name__)

# 只读工具列表（不在列表中的工具视为写操作）
_READONLY_TOOLS = {
    "read_file",
    "glob",
    "grep",
    "list_dir",
    "tree_dir",
    "web_fetch",
    "web_search",
    "ask_user",
    "task_management",
    "todo_management",
    "cron",
}


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

    def __init__(
        self,
        config: Optional[ContextCompactConfig] = None,
        message_service: Optional[MessageService] = None,
    ):
        self.config = config or DEFAULT_COMPACT_CONFIG
        self.message_service = message_service
        self.stats = CompressionStats()

        # 防抖记录
        self._last_stale_cleanup_step: int = 0
        self._last_sm_truncation_step: int = 0

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
        self,
        context,
        execution_engine,
        session_memory_manager=None,
        agent_config=None,
    ) -> CompressionStats:
        """
        检查 context token 数并触发压缩。

        在 execute_step 完成后调用。

        Args:
            context: Context 实例
            execution_engine: ExecutionEngine 实例（用于获取 step 信息和写操作）
            session_memory_manager: 可选的 SessionMemoryManager 实例
            agent_config: 可选的 AgentConfig 实例

        Returns:
            CompressionStats: 压缩统计信息
        """
        self.stats.reset()

        compact_config = self.get_effective_config(agent_config) if agent_config else self.config

        # 估算 context 总 token 数
        total_tokens = self._estimate_context_tokens(context)

        # 策略A：清理过期工具调用结果
        if compact_config.enable_stale_tool_cleanup:
            if total_tokens > compact_config.stale_tool_cleanup_token_threshold:
                current_step = self._get_current_step(execution_engine)
                if self._check_debounce(
                    current_step,
                    self._last_stale_cleanup_step,
                    compact_config.stale_tool_cleanup_debounce_steps,
                ):
                    await self._cleanup_stale_tool_results(
                        context=context,
                        execution_engine=execution_engine,
                        config=compact_config,
                        current_step=current_step,
                    )
                    self._last_stale_cleanup_step = current_step

        # 策略B：Session Memory 截断
        if compact_config.enable_session_memory_truncation:
            if total_tokens > compact_config.session_memory_truncation_token_threshold:
                current_step = self._get_current_step(execution_engine)
                if self._check_debounce(
                    current_step,
                    self._last_sm_truncation_step,
                    compact_config.session_memory_truncation_debounce_steps,
                ):
                    await self._try_session_memory_truncation(
                        context=context,
                        execution_engine=execution_engine,
                        session_memory_manager=session_memory_manager,
                        config=compact_config,
                        current_step=current_step,
                    )
                    self._last_sm_truncation_step = current_step

        return self.stats

    def _estimate_context_tokens(self, context) -> int:
        """
        估算 context 的总 token 数。

        使用简单的字符数估算（约 4 字符/token）。
        """
        total_chars = 0
        for msg in context.history:
            if isinstance(msg, dict):
                content = msg.get("content", "")
                if content:
                    total_chars += len(str(content))
            elif hasattr(msg, "content"):
                total_chars += len(str(msg.content))
        # 粗略估算：约 4 字符/token
        return total_chars // 4

    def _get_current_step(self, execution_engine) -> int:
        """获取当前 step 数"""
        if hasattr(execution_engine, "session_memory_manager") and execution_engine.session_memory_manager:
            return execution_engine.session_memory_manager.state.step_count
        return 0

    def _check_debounce(self, current_step: int, last_step: int, debounce_steps: int) -> bool:
        """检查防抖间隔是否满足"""
        return (current_step - last_step) >= debounce_steps

    # ========================================================================
    # 策略A：清理过期工具调用结果
    # ========================================================================

    async def _cleanup_stale_tool_results(
        self,
        context,
        execution_engine,
        config: ContextCompactConfig,
        current_step: int,
    ):
        """
        清理过期的工具调用结果。

        检测写操作关联和时间因素，将过期的工具结果替换为占位符。
        """
        # 获取当前 step 中的写操作涉及的文件路径
        write_file_paths = self._get_write_file_paths(execution_engine)

        history = context.history
        current_time = time.time()

        # 记录需要标记为过期的消息索引和对应的数据库 ID
        expired_indices = []

        # 从后往前遍历，保留最近的 N 条工具结果
        recent_tool_count = 0
        min_recent = config.min_recent_tool_results_to_keep
        history_len = len(history)

        for i in range(len(history) - 1, -1, -1):
            msg = history[i]
            if not isinstance(msg, dict):
                continue
            if msg.get("role") != "tool":
                continue

            # 保留最近的 N 条工具调用结果
            if recent_tool_count < min_recent:
                recent_tool_count += 1
                continue

            # 检查是否过期
            if self._is_tool_result_stale(
                msg=msg,
                index=i,
                history_len=history_len,
                write_file_paths=write_file_paths,
                config=config,
                current_step=current_step,
                current_time=current_time,
            ):
                expired_indices.append(i)

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
            logger.info(
                f"策略A：标记了 {self.stats.expired_count} 条工具结果为过期"
            )

    def _get_write_file_paths(self, execution_engine) -> List[str]:
        """
        获取当前 step 中写操作涉及的文件路径。

        从 execution_engine 的 tool_mapping 和当前 step 的 tool_calls 中提取。
        """
        paths = []
        # 检查 execution_engine 是否有记录当前 step 的写操作文件路径
        if hasattr(execution_engine, "_step_write_file_paths"):
            paths = execution_engine._step_write_file_paths or []
        return paths

    def _is_tool_result_stale(
        self,
        msg: dict,
        index: int,
        history_len: int,
        write_file_paths: List[str],
        config: ContextCompactConfig,
        current_step: int,
        current_time: float,
    ) -> bool:
        """
        判断工具调用结果是否过期。

        满足任一条件即视为过期：
        1. 写操作关联：该工具结果关联的文件被写操作修改
        2. Step 年龄：超过 max_stale_steps
        3. 消息序列年龄：超过 max_stale_messages
        4. 绝对时间：超过 max_stale_seconds
        """
        # 1. 写操作关联检测
        if write_file_paths:
            tool_name = msg.get("tool_name", "")
            if self._has_write_operation_affecting(tool_name, msg, write_file_paths):
                return True

        # 2. Step 年龄检测
        msg_step = self._get_msg_step(msg)
        if msg_step is not None and (current_step - msg_step) > config.max_stale_steps:
            return True

        # 3. 消息序列年龄检测
        # 该消息之后（含自身）还有多少条消息
        # index 是正向索引，history[0] 是 system prompt
        # history_len - index 表示从该消息到末尾的消息数量
        # 如果这个数量超过 max_stale_messages，说明该消息已被后续大量消息覆盖
        messages_after = history_len - index
        if messages_after > config.max_stale_messages:
            return True

        # 4. 绝对时间检测
        msg_time = self._get_msg_timestamp(msg)
        if msg_time is not None and (current_time - msg_time) > config.max_stale_seconds:
            return True

        return False

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

    def _has_write_operation_affecting(
        self, tool_name: str, msg: dict, write_file_paths: List[str]
    ) -> bool:
        """
        检查写操作是否影响该工具调用结果。

        根据工具类型和写操作文件路径判断。
        """
        # 如果没有写操作文件路径，无法判断
        if not write_file_paths:
            return False

        # 如果工具是只读的，但写操作可能影响其结果
        if tool_name in ("read_file",):
            # read_file 的结果如果文件被修改则过期
            return True

        if tool_name in ("grep",):
            # grep 的结果如果文件被修改则过期
            return True

        if tool_name in ("glob", "list_dir", "tree_dir"):
            # 文件列表操作，任何写操作都可能改变文件列表
            return True

        if tool_name in ("web_fetch", "web_search"):
            # 网络操作不受本地写操作影响
            return False

        return False

    async def _update_expired_in_db(self):
        """批量更新数据库中的 is_expired 字段"""
        if not self.message_service or not self.stats.expired_message_ids:
            return

        for msg_id in self.stats.expired_message_ids:
            try:
                await self.message_service.update_message(
                    msg_id, {"is_expired": True}
                )
            except Exception as e:
                logger.error(f"Failed to update message {msg_id} as expired: {e}")

    # ========================================================================
    # 策略B：Session Memory 截断
    # ========================================================================

    async def _try_session_memory_truncation(
        self,
        context,
        execution_engine,
        session_memory_manager,
        config: ContextCompactConfig,
        current_step: int,
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
        if not session_memory_manager:
            logger.info("策略B：无 session_memory_manager，跳过截断")
            return

        # 校验一：Session memory 内容非空
        if not session_memory_manager.has_content:
            logger.info("策略B：Session memory 内容为空，跳过截断")
            return

        # 校验二：last_message_index 与 context 对齐
        last_index = session_memory_manager.last_message_index
        if last_index > 0:
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
            session_memory_manager=session_memory_manager,
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

        return True

    async def _do_session_memory_truncation(
        self,
        context,
        execution_engine,
        session_memory_manager,
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
        last_index = session_memory_manager.last_message_index

        # 获取需要标记为截断的消息 ID 列表
        truncated_ids = context.get_truncated_message_ids(last_index)

        # 获取 session memory 内容
        session_memory_content = session_memory_manager.get_session_memory_content()

        # 将 session memory 注入到 system prompt
        self._inject_session_memory_to_system_prompt(
            context, session_memory_content
        )

        # 重建 context：保留 system prompt 和截断点之后的消息
        new_history = [context.history[0]]  # system prompt（已注入 session memory）
        new_db_ids = [context._message_db_ids[0]]  # system prompt 的 db id

        # 保留截断点之后的消息
        for i in range(last_index, len(context.history)):
            new_history.append(context.history[i])
            new_db_ids.append(context._message_db_ids[i])

        context._history = new_history
        context._message_db_ids = new_db_ids

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

        # 重置 SessionMemoryManager
        session_memory_manager.reset_last_message_index()

        logger.info(
            f"策略B：Session memory 截断完成，"
            f"截断了 {self.stats.truncated_count} 条消息，"
            f"context 从 {len(new_history) + last_index} 条减少到 {len(new_history)} 条"
        )

    def _inject_session_memory_to_system_prompt(
        self, context, session_memory_content: str
    ):
        """
        将 session memory 内容注入到 system prompt 中。

        在 system prompt 末尾追加 session memory 部分。
        """
        if not session_memory_content:
            return

        # 获取当前的 system prompt
        system_prompt = context.history[0]
        if not isinstance(system_prompt, dict):
            return

        current_content = system_prompt.get("content", "")

        # 检查是否已注入过 session memory
        if "## Session Memory" in current_content:
            # 替换已有的 session memory 部分
            import re
            pattern = r"(## Session Memory\n\n)[\s\S]*?(?=\n## |\Z)"
            replacement = f"## Session Memory\n\n{session_memory_content}\n\n"
            new_content = re.sub(pattern, replacement, current_content)
        else:
            # 追加 session memory 到末尾
            new_content = current_content + f"\n\n## Session Memory\n\n{session_memory_content}"

        context.history[0]["content"] = new_content
