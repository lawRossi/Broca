"""
上下文压缩器（Context Compressor）

实现 ContextCompressor ABC 的默认实现 ``SessionMemoryCompressor``，
合并了原 ``ContextCompressor`` 和 ``SessionMemoryManager`` 的职责：
- Token 监控 + 阈值检查
- 保留边界 (pivot) 计算
- 记忆提取（通过子代理）
- 截断 + 冻结 + context 重建
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from broca.components.protocols import CompressorContext
    from broca.context import Context

from broca.agent_configs import ContextCompactConfig
from broca.components.context_compressor import ContextCompressor
from broca.logging_config import get_logger
from broca.session_memory.memory_prompts import (
    DEFAULT_MEMORY_TEMPLATE,
    build_extraction_user_prompt,
)

logger = get_logger(__name__)

# Backward-compat alias: old code does `from broca.context_compressor import ContextCompressor`.
# The name now refers to the concrete ``SessionMemoryCompressor``.
# Phase 4 will migrate all call sites to the ABC from ``broca.components``.


@dataclass
class CompressionStats:
    """压缩统计信息"""

    truncated_count: int = 0
    truncated_message_ids: List[str] = field(default_factory=list)

    def reset(self):
        self.truncated_count = 0
        self.truncated_message_ids = []


@dataclass
class SessionMemoryState:
    """Session Memory 状态"""

    extraction_in_progress: bool = False

    def reset(self):
        self.extraction_in_progress = False


class SessionMemoryCompressor(ContextCompressor):
    """Default ``ContextCompressor`` implementation.

    Merges the responsibilities of the former concrete
    ``ContextCompressor`` and ``SessionMemoryManager`` into a single
    component that operates on a ``CompressorContext`` protocol
    (no direct ``Agent`` reference).

    Lifecycle::

        compressor = registry.get(ContextCompressor, scope_key=agent_id)
        await compressor.initialize(agent_ref, session_manager, config)
        stats = await compressor.check_and_compress(context, cc_ctx)
    """

    FROZEN_MEMORY_FILENAME = "session-memory.md"
    SNAPSHOT_MEMORY_FILENAME = "session-memory_latest.md"
    AGENT_ID_POSTFIX = "#session-memory-agent"

    # ------------------------------------------------------------------
    # Constructor & lifecycle
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self.stats = CompressionStats()
        self.state = SessionMemoryState()
        self._llm_config: Optional[dict] = None
        self._lock = asyncio.Lock()
        self.task_timeout: int = 120
        # Populated by initialize()
        self._agent_id: str = ""
        self._session_id: str = ""
        self._workspace: str = ""
        self._config = None  # full AgentConfig (for sub-agent creation)
        self._initialized = False

    async def initialize(
        self,
        agent_ref,
        session_manager,
        config,
    ) -> None:
        """Inject runtime dependencies.

        Args:
            agent_ref: Object conforming to ``AgentReference`` protocol
                (provides ``agent_id``, ``session_id``; optionally ``workspace``).
            session_manager: ``SessionManager`` instance.
            config: ``AgentConfig`` instance (full config, for sub-agent
                creation and ``compact_config`` access).
        """
        # Idempotency
        if self._initialized and self._agent_id == getattr(
            agent_ref, "agent_id", None
        ):
            return

        self._agent_id = agent_ref.agent_id
        self._session_id = agent_ref.session_id
        self._workspace = getattr(agent_ref, "workspace", None) or ""
        self._config = config
        self._initialized = True

        self._ensure_template_exists()

    # ------------------------------------------------------------------
    # Path management (from SessionMemoryManager)
    # ------------------------------------------------------------------

    @property
    def _agent_memory_dir(self) -> Path:
        """agent 级记忆目录"""
        return (
            Path(self._workspace)
            / ".broca"
            / (self._session_id or "")
            / (self._agent_id or "")
        )

    @property
    def snapshot_memory_path(self) -> str:
        """获取 memory 文件路径"""
        return str(self._agent_memory_dir / self.SNAPSHOT_MEMORY_FILENAME)

    @property
    def memory_path(self) -> str:
        """获取 memory 文件路径"""
        return str(self._agent_memory_dir / self.FROZEN_MEMORY_FILENAME)

    def is_session_memory_empty(self) -> bool:
        try:
            content = Path(self.snapshot_memory_path).read_text(
                encoding="utf-8"
            ).strip()
        except FileNotFoundError:
            logger.warning(
                f"Session memory snapshot not found: {self.snapshot_memory_path}"
            )
            return True
        return content == "" or content == DEFAULT_MEMORY_TEMPLATE.strip()

    def _ensure_template_exists(self):
        """确保模板文件存在（启动时创建）"""
        memory_file = Path(self.snapshot_memory_path)
        if not memory_file.exists():
            memory_file.parent.mkdir(parents=True, exist_ok=True)
            memory_file.write_text(
                DEFAULT_MEMORY_TEMPLATE.strip(), encoding="utf-8"
            )
            logger.info(f"Created session memory template at {memory_file}")

    # ------------------------------------------------------------------
    # ABC methods
    # ------------------------------------------------------------------

    async def check_and_compress(
        self,
        context,
        compressor_context: "CompressorContext",
        force: bool = False,
    ) -> CompressionStats:
        """Check context token count and trigger compression.

        Pipeline: token check → pivot → extract → truncate → freeze → rebuild.
        When ``force=True`` (e.g. ``/compact``), the threshold check is
        skipped.
        """
        self.stats.reset()

        compact_config: ContextCompactConfig = compressor_context.compact_config

        # Token threshold check (skipped when force=True)
        if not force:
            total_tokens = self._get_total_tokens(
                context, compressor_context
            )
            effective_threshold = self._get_effective_threshold(
                compact_config.session_trunc_threshold,
                compact_config.session_trunc_percentage,
                compressor_context,
            )
            if total_tokens <= effective_threshold:
                return self.stats
        else:
            total_tokens = self._get_total_tokens(context, compressor_context)

        await self._do_session_memory_compress(
            context=context,
            compressor_context=compressor_context,
            total_tokens=total_tokens,
        )

        return self.stats

    def reset_session_memory(self) -> None:
        """Clear the current agent's session memory files."""
        self.state.reset()
        # Delete snapshot + frozen files
        for path in (self.snapshot_memory_path, self.memory_path):
            try:
                p = Path(path)
                if p.exists():
                    p.unlink()
                    logger.info(f"Deleted session memory file: {path}")
            except OSError as e:
                logger.error(f"Failed to delete {path}: {e}")

    # ------------------------------------------------------------------
    # Non-abstract convenience method
    # ------------------------------------------------------------------

    async def force_compress(self, context, compressor_context) -> CompressionStats:
        """Convenience: equivalent to ``check_and_compress(force=True)``."""
        return await self.check_and_compress(
            context, compressor_context, force=True
        )

    # ==================================================================
    # Internal: token estimation
    # ==================================================================

    def _get_llm_config(self) -> dict:
        """加载并缓存 LLM 配置"""
        if self._llm_config is None:
            from broca.configs import resolve_llm_config_path
            config_path = resolve_llm_config_path()
            with open(config_path) as f:
                self._llm_config = json.load(f)
        return self._llm_config

    def _get_effective_threshold(
        self,
        absolute_threshold: int,
        percentage: float,
        compressor_context: "CompressorContext",
    ) -> int:
        """计算有效触发阈值。

        有效阈值 = min(绝对阈值, context_window * percentage)
        """
        percentage = max(0.05, min(1.0, percentage))

        llm_config = self._get_llm_config()
        provider = compressor_context.provider
        model = compressor_context.model

        if provider in llm_config and "models" in llm_config[provider]:
            if model in llm_config[provider]["models"]:
                meta = llm_config[provider]["models"][model].get("meta", {})
                context_window = meta.get("context_window")
                if context_window is not None:
                    percentage_threshold = int(context_window * percentage)
                    return min(absolute_threshold, percentage_threshold)

        return absolute_threshold

    def _get_total_tokens(
        self, context, compressor_context: "CompressorContext"
    ) -> int:
        """获取 context 的总 token 数。

        优先使用 LLM 调用返回的真实值 (``compressor_context.last_context_length``)。
        """
        last_ctx = compressor_context.last_context_length
        if last_ctx is None:
            return self._estimate_context_tokens(context)
        tool_result_tokens = self._estimate_recent_tool_result_tokens(context)
        return last_ctx + tool_result_tokens

    def _estimate_context_tokens(self, context) -> int:
        """估算 context 的总 token 数 (~3 chars/token)."""
        total_chars = 0
        for msg in context.history:
            if isinstance(msg, dict):
                total_chars += len(msg.get("content") or "")
            elif hasattr(msg, "content"):
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

    @staticmethod
    def _estimate_recent_tool_result_tokens(context) -> int:
        """估算最近一次 LLM 调用后新增的 tool result 消息的 token 数。"""
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

    # ==================================================================
    # Internal: session memory compression pipeline
    # ==================================================================

    async def _do_session_memory_compress(
        self,
        context,
        compressor_context: "CompressorContext",
        total_tokens: int,
    ):
        """统一"提取 + 压缩"流程。"""
        compact_config = compressor_context.compact_config
        keep_steps = getattr(compact_config, "keep_steps", 5)

        # 1. Compute keep pivot
        keep_from_message_id, keep_index = (
            await self._compute_keep_pivot(
                context, keep_steps, compressor_context
            )
        )
        if not keep_from_message_id or keep_index is None:
            logger.info("Session Memory: 无法计算保留边界 pivot，跳过压缩")
            return

        logger.info(
            f"Session Memory: 开始压缩 (tokens={total_tokens}, "
            f"keep_steps={keep_steps})"
        )

        # 2. Extract memory (use old messages)
        old_history = copy.copy(context.history[:keep_index])
        extraction_ok = await self._extract(
            old_history, compressor_context
        )
        if not extraction_ok:
            logger.info("Session Memory: 记忆提取失败，跳过压缩")
            return

        # 3. Truncate + freeze + rebuild
        session_manager = compressor_context.session_manager
        count = await session_manager.mark_messages_before_as_truncated(
            self._agent_id, keep_from_message_id
        )
        self.stats.truncated_count = count
        self._frozen_session_memory()
        self.state.reset()
        await context.build_history_from_session(
            self._agent_id, rebuild_system_prompt=True
        )

        logger.info(
            f"Session Memory: 压缩完成，截断了 {self.stats.truncated_count} 条消息"
        )

    # ==================================================================
    # Pivot calculation (from SessionMemoryManager.compute_keep_pivot)
    # ==================================================================

    async def _compute_keep_pivot(
        self,
        context,
        keep_steps: int,
        compressor_context: "CompressorContext",
    ):
        """计算保留边界。

        通过 DB 消息序列计算：一个 assistant message 为一个 step，
        遇到 user message 即停止（不跨 turn）。

        Returns:
            (keep_from_message_id, keep_index) or (None, None)
        """
        from broca.session import MessageType

        session_manager = compressor_context.session_manager
        agent_id = self._agent_id

        messages = await session_manager.get_messages(agent_id=agent_id)
        if not messages:
            return None, None

        # Find current turn start: most recent real USER_MESSAGE
        current_turn_start = None
        for i, m in enumerate(messages):
            if m.message_type == MessageType.USER_MESSAGE:
                if m.data and m.data.get("tool_injected"):
                    continue
                current_turn_start = i
        if current_turn_start is None:
            return None, None

        # Scan backwards from latest message
        keep_from_message_id = None
        step_count = 0
        for i in range(len(messages) - 1, current_turn_start - 1, -1):
            m = messages[i]
            if m.message_type == MessageType.TURN_END:
                keep_from_message_id = m.message_id
                break
            if m.message_type == MessageType.AGENT_RESPONSE:
                step_count += 1
                if step_count == keep_steps:
                    keep_from_message_id = m.message_id
                    break

        if keep_from_message_id is None:
            keep_from_message_id = messages[current_turn_start].message_id

        # Map to context.history index
        keep_index = self._resolve_context_index(context, keep_from_message_id)
        if keep_index is None:
            keep_index = self._resolve_context_index_by_order(
                context, messages, keep_from_message_id
            )
        if keep_index is None:
            return None, None

        return keep_from_message_id, keep_index

    def _resolve_context_index(self, context, message_id):
        """在 context 中根据 message_id 找到对应索引（仅精确匹配）"""
        db_ids = getattr(context, "_message_db_ids", None)
        if not db_ids:
            logger.warning(
                "_resolve_context_index: context 无 _message_db_ids，无法定位"
            )
            return None
        for idx, db_id in enumerate(db_ids):
            if db_id == message_id:
                return idx
        return None

    def _resolve_context_index_by_order(self, context, messages, message_id):
        """按 DB 顺序解析 keep_index。"""
        db_ids = getattr(context, "_message_db_ids", None)
        if not db_ids:
            logger.warning(
                "_resolve_context_index_by_order: context 无 _message_db_ids"
            )
            return None

        db_position = {m.message_id: i for i, m in enumerate(messages)}
        target_pos = db_position.get(message_id)
        if target_pos is None:
            logger.warning(
                f"_resolve_context_index_by_order: 消息 {message_id} 不在 DB 序列中"
            )
            return None

        for idx, db_id in enumerate(db_ids):
            pos = db_position.get(db_id) if db_id is not None else None
            if pos is not None and pos >= target_pos:
                return idx
        return len(db_ids)

    # ==================================================================
    # Memory extraction (from SessionMemoryManager)
    # ==================================================================

    async def _extract(
        self,
        old_history,
        compressor_context: "CompressorContext",
    ) -> bool:
        """执行记忆提取（通过子代理）。"""
        async with self._lock:
            if self.state.extraction_in_progress:
                return False

            self.state.extraction_in_progress = True
            original_content = None
            try:
                original_content = self._read_session_memory_content()
                await compressor_context.communicator.send_agent_system_message(
                    content="Extracting session memory",
                    subscription=self._session_id,
                )
                success = await self._do_extract(
                    old_history, compressor_context
                )
                if not success:
                    if original_content is not None:
                        with open(
                            self.snapshot_memory_path, "w", encoding="utf-8"
                        ) as f:
                            f.write(original_content)
                return success
            except Exception as e:
                logger.error(f"Session memory extraction failed: {e}")
                if original_content is not None:
                    with open(
                        self.snapshot_memory_path, "w", encoding="utf-8"
                    ) as f:
                        f.write(original_content)
                return False
            finally:
                self.state.extraction_in_progress = False

    def _read_session_memory_content(self) -> str:
        return Path(self.snapshot_memory_path).read_text(encoding="utf-8").strip()

    def _frozen_session_memory(self):
        """将 snapshot 冻结为 frozen memory"""
        try:
            shutil.copyfile(self.snapshot_memory_path, self.memory_path)
        except FileNotFoundError:
            logger.error(
                f"Cannot freeze session memory: snapshot not found "
                f"{self.snapshot_memory_path}"
            )
            raise
        except OSError as e:
            logger.error(
                f"Failed to freeze session memory "
                f"({self.snapshot_memory_path} → {self.memory_path}): {e}"
            )
            raise

    async def _do_extract(self, old_history, compressor_context) -> bool:
        """实际提取逻辑——创建子代理执行"""
        current_content = self._read_session_memory_content()
        user_prompt = build_extraction_user_prompt(
            memory_path=self.snapshot_memory_path
        )

        return await self._run_extraction_subagent(
            user_prompt=user_prompt,
            old_history=old_history,
            current_content=current_content,
            compressor_context=compressor_context,
        )

    async def _run_extraction_subagent(
        self,
        user_prompt: str,
        old_history,
        current_content: str,
        compressor_context: "CompressorContext",
    ) -> bool:
        """创建并运行提取子代理。"""
        from broca.components import ComponentRegistry
        from broca.components.agent_factory import AgentFactory as AgentFactoryABC
        from broca.loop_engine import ExecutionStatus
        from broca.session import MessageProtocol

        start = time.time()
        agent_factory = ComponentRegistry.get_instance().get(AgentFactoryABC)
        session_manager = compressor_context.session_manager
        agent_id = session_manager.session_id + self.AGENT_ID_POSTFIX
        agent_config = await session_manager.get_agent_config(agent_id)
        if agent_config is None:
            agent_config = self._config.to_dict()
            agent_config["name"] = "session-memory-agent"
            agent_config["role"] = "session_memory_manager"
            agent_config["enable_context_compression"] = False
            agent_config["save_history"] = False

            sub_agent = await agent_factory.create_agent(
                agent_config=agent_config,
                session_manager=session_manager,
                agent_id=agent_id,
            )
        else:
            agent_config["provider"] = compressor_context.provider
            agent_config["model"] = compressor_context.model
            sub_agent = agent_factory.get_agent(  # type: ignore[assignment]
                session_manager.session_id, agent_config["name"]
            )
            if sub_agent is None:
                sub_agent = await agent_factory.restore_agent(
                    agent_id, session_manager
                )
            sub_agent.config.provider = compressor_context.provider
            sub_agent.config.model = compressor_context.model

        if not sub_agent.running:
            task = asyncio.create_task(sub_agent.start())
            task.add_done_callback(
                lambda t, a=sub_agent: a.stop()
            )  # type: ignore[misc]

        sub_agent.context.history = copy.copy(old_history)
        trigger_message = MessageProtocol.create_user_message(
            content=user_prompt,
        )
        result = await sub_agent.run(
            trigger_message, from_agent=True, allowed_tools=["write_file"],
            max_steps=2,
        )

        if result.status != ExecutionStatus.COMPLETED:
            logger.warning(
                f"Session memory sub-agent execution failed: {result.status}"
            )
            await compressor_context.communicator.send_agent_system_message(
                content="Fail to extract session memory",
                subscription=self._session_id,
            )
            return False

        # Verify file was actually modified
        try:
            new_content = Path(self.snapshot_memory_path).read_text(
                encoding="utf-8"
            ).strip()
        except (FileNotFoundError, OSError) as e:
            logger.error(
                f"Failed to verify session memory file after extraction: {e}"
            )
            return False

        if new_content == current_content.strip():
            logger.warning(
                "Session memory sub-agent completed but file unchanged, "
                "treating as failure to prevent data loss"
            )
            await compressor_context.communicator.send_agent_system_message(
                content="Session memory extraction produced no changes",
                subscription=self._session_id,
            )
            return False

        end = time.time()
        logger.info("Session memory updated successfully via sub-agent")
        time_used = int(end - start)
        await compressor_context.communicator.send_agent_system_message(
            content=f"Session memory updated successfully in {time_used} seconds",
            subscription=self._session_id,
        )
        return True

    # ==================================================================
    # Utility (retained for backward compat)
    # ==================================================================

    def get_pre_loaded_skills(self, context, last_index: int):
        pre_loaded_skills = []
        for msg in context.history[last_index:]:
            if msg.get("role") == "tool":
                tool_name = msg.get("meta").get("tool_name")
                status = msg.get("meta").get("status")
                if tool_name == "load_skill" and status == "success":
                    arguments = msg.get("meta").get("arguments")
                    pre_loaded_skills.append(arguments.get("skill_name"))
        return pre_loaded_skills


# Backward-compat alias (Phase 4 will remove this)
ContextCompressor = SessionMemoryCompressor
