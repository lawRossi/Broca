"""
SessionRevert 服务

提供撤销/重做功能，管理会话级别的操作回滚。
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from broca.errors import SessionError
from broca.logging_config import get_logger
from broca.session.database import db_manager
from broca.session.models import Message, MessageType
from broca.session.service import get_message_service
from broca.session.session_manager import SessionManager
from broca.components.snapshot_manager import SnapshotManager
from broca.components.revert_service import RevertServiceABC

logger = get_logger(__name__)


class SessionRevertService(RevertServiceABC):
    """会话撤销服务"""

    def __init__(
        self,
        session_manager: SessionManager,
        snapshot_manager: SnapshotManager,
        workspace_path: str,
        enable_snapshot_tracking: bool = True,
    ):
        """
        初始化会话撤销服务

        Args:
            session_manager: 会话管理器
            snapshot_manager: 快照管理器（SnapshotManager 接口实例）
            workspace_path: 工作空间路径
            enable_snapshot_tracking: 是否启用快照跟踪。
                False 时 undo/redo 仅标记消息，不执行文件恢复。
        """
        self.session_manager = session_manager
        self._sm: SnapshotManager = snapshot_manager
        self.workspace_path = workspace_path
        self.enable_snapshot_tracking = enable_snapshot_tracking
        self.undo_stack: List[dict] = []  # undo 栈，支持多级撤销

    def can_undo(self, session_id: str) -> bool:
        """是否可以撤销（undo_stack 非空）"""
        return len(self.undo_stack) > 0

    def can_redo(self, session_id: str) -> bool:
        """是否可以重做（当前实现中 redo 依赖 undo_stack 栈顶，
        因此 can_redo 等同于 can_undo）"""
        return len(self.undo_stack) > 0

    async def undo(
        self,
        session_id: str,
        agent_id: str,
        target_message_id: Optional[str] = None,
        level: str = "step",
    ) -> Dict[str, Any]:
        """
        执行撤销操作

        Args:
            session_id: 会话ID
            agent_id: Agent ID
            target_message_id: 目标消息ID（可选）
            level: 撤销级别，"turn" 或 "step"

        Returns:
            撤销结果
        """
        logger.info(f"Undo: {session_id}, {agent_id}, {target_message_id}, {level}")

        # 验证会话状态
        session = await self.session_manager.get_session(session_id)
        if not session:
            raise SessionError(f"会话不存在: {session_id}")

        msg_svc = get_message_service()

        # 未指定 target_message_id 时，通过 SQL 定位最后一条 AGENT_RESPONSE
        if not target_message_id:
            target_message_id = await msg_svc.get_last_agent_response_id(agent_id)

        if not target_message_id:
            return {
                "success": False,
                "error": "No target message found",
                "patches_reverted": 0,
            }

        # 通过 SQL 查找 pivot message_id
        pivot_message_id = await msg_svc.find_pivot_message_id(
            agent_id, target_message_id, level
        )

        if not pivot_message_id:
            return {
                "success": False,
                "error": "No pivot message found",
                "patches_reverted": 0,
            }

        logger.info(f"pivot_message_id: {pivot_message_id}")

        # 仅加载 pivot 之后的消息（用于收集 patches）
        messages_from_pivot = await msg_svc.get_messages_from_pivot(
            agent_id, pivot_message_id
        )

        # 收集 patches（仅从 pivot 之后的 STEP_END 消息）
        patches_to_revert = []
        collecting = False
        for msg in messages_from_pivot:
            if msg.message_id == pivot_message_id:
                collecting = True
                continue
            if collecting:
                if msg.message_type == MessageType.STEP_END:
                    patch = msg.data.get("patch")
                    if patch:
                        patches_to_revert.append(patch)

        logger.info(f"patches_to_revert: {patches_to_revert}")

        # 捕获当前快照（用于重做）+ 反向应用 patch
        # 全程持锁（acquire_lock 底层 fcntl.flock 是同步阻塞调用，
        # 必须用 to_thread 包装避免阻塞事件循环）
        diff_content = ""
        diff_summary = {}
        if patches_to_revert and self.enable_snapshot_tracking:
            await asyncio.to_thread(self._sm.acquire_lock)
            try:
                current_snapshot_hash = await self._sm.track(self.workspace_path)
                await self._sm.restore_patches(patches_to_revert)
                diff_content = await self._calculate_diff_for_patches(current_snapshot_hash)
                diff_summary = self._sm.get_diff_summary(diff_content)
            finally:
                await asyncio.to_thread(self._sm.release_lock)
        else:
            current_snapshot_hash = ""

        # 通过 SQL 标记相关消息为已撤销
        message_ids_to_revert = await self._mark_messages_as_reverted_sql(
            agent_id, pivot_message_id
        )

        # 保存撤销记录
        undo_meta_info = self._create_undo_meta_info(
            session_id,
            agent_id,
            level,
            pivot_message_id,
            current_snapshot_hash,
            diff_content,
            diff_summary,
            patches_to_revert,
            message_ids_to_revert,
        )
        self.undo_stack.append(undo_meta_info)

        return {
            "success": True,
            "diff_summary": diff_summary,
            "patches_reverted": len(patches_to_revert),
        }

    async def redo(self, session_id: str, agent_id: str) -> Dict[str, Any]:
        """
        执行重做操作

        Args:
            session_id: 会话ID
            agent_id: Agent ID

        Returns:
            重做结果
        """
        # 验证会话状态
        session = await self.session_manager.get_session(session_id)
        if not session:
            raise SessionError(f"会话不存在: {session_id}")

        # 从 undo 栈顶获取最新的撤销记录
        if not self.undo_stack:
            return {"success": False, "message": "没有可重做的操作"}

        undo_meta_info = self.undo_stack[-1]

        # 从撤销记录中恢复快照（仅在启用快照跟踪且有 patches 时执行文件恢复）
        # 全程持锁，确保 restore + orphan cleanup 原子性
        snapshot_hash = undo_meta_info.get("snapshot_hash", "")
        if undo_meta_info["patches"] and snapshot_hash and self.enable_snapshot_tracking:
            await asyncio.to_thread(self._sm.acquire_lock)
            try:
                await self._sm.restore(snapshot_hash)

                # 清理孤儿文件：遍历 undo patch 中出现过的文件，
                # 如果 restore 后它们变为未跟踪状态，说明在目标 tree 中已被删除
                orphan_candidates = set()
                for patch in undo_meta_info["patches"]:
                    for f in patch.get("files", []):
                        orphan_candidates.add(f)

                if orphan_candidates:
                    untracked_files = await self._sm.get_untracked_files()
                    orphan_files = orphan_candidates & untracked_files
                    for file_path in orphan_files:
                        full_path = Path(self.workspace_path) / file_path
                        if full_path.exists():
                            logger.info(f"删除孤儿文件: {file_path}")
                            full_path.unlink()
            finally:
                await asyncio.to_thread(self._sm.release_lock)

        # 标记相关消息为已重做
        await self._mark_messages_as_redone(agent_id, undo_meta_info)

        # 弹出 undo 栈（redo 后该记录即失效）
        self.undo_stack.pop()

        logger.info("redo成功")
        return {"success": True}

    def _find_last_target_message(self, messages: List[Message]) -> Optional[str]:
        """在未指定 target_message_id 时，找到最后一条有意义的消息作为撤销目标。

        优先级：AGENT_RESPONSE > TOOL_CALL > 最后一条消息
        """
        for msg in reversed(messages):
            if msg.message_type == MessageType.AGENT_RESPONSE:
                return msg.message_id
        # 没有 AGENT_RESPONSE，回退到最后一条消息
        if messages:
            return messages[-1].message_id
        return None

    async def _collect_patches_to_message(
        self, messages: List[Message], target_message_id: Optional[str], level: str
    ) -> Tuple[list[dict[str, Any]], Optional[str]]:
        """收集到指定消息的所有patch"""
        patches = []
        pivot_message_id = None

        # 找到目标消息
        target_message = None
        for msg in reversed(messages):
            if msg.message_id == target_message_id:
                target_message = msg
                break

        if not target_message:
            logger.info(f"找不到目标消息: {target_message_id}")
            return [], None

        # 根据level确定pivot message
        pivot_message = None
        if level == "turn":
            # 找到对应的TURN_START消息作为pivot
            turn_id = target_message.turn_id
            for msg in reversed(messages):
                if (
                    msg.message_type == MessageType.TURN_START
                    and msg.turn_id == turn_id
                ):
                    pivot_message = msg
                    pivot_message_id = pivot_message.message_id
                    break
            # Fallback: 未找到 TURN_START 时（无快照模式），用目标消息自身作为 pivot
            if not pivot_message:
                pivot_message = target_message
                pivot_message_id = pivot_message.message_id
        else:
            step_id = target_message.data.get("step_id")
            if step_id:
                for msg in reversed(messages):
                    if (
                        msg.message_type == MessageType.STEP_START
                        and msg.data.get("step_id") == step_id
                    ):
                        pivot_message = msg
                        pivot_message_id = pivot_message.message_id
                        break
            # Fallback: 未找到 STEP_START（无快照模式下不存在 STEP_START 消息），
            # 用目标消息自身作为 pivot → undo 仅标记消息，不做文件恢复
            if not pivot_message:
                pivot_message = target_message
                pivot_message_id = pivot_message.message_id

        # 收集pivot message往后的所有patch
        collecting = False
        for msg in messages:
            if msg.message_id == pivot_message.message_id:
                collecting = True
                continue

            if collecting:
                if msg.message_type == MessageType.STEP_END:
                    patch = msg.data.get("patch")
                    if patch:
                        patches.append(patch)

        return patches, pivot_message_id

    async def _calculate_diff_for_patches(self, from_hash: str) -> str:
        """计算patch的差异"""
        current_hash = await self._sm.track(self.workspace_path)

        return await self._sm.calculate_diff(from_hash, current_hash)

    def _create_undo_meta_info(
        self,
        session_id: str,
        agent_id: str,
        level: str,
        pivot_message_id: Optional[str],
        snapshot_hash: str,
        diff_content: str,
        diff_summary: Dict[str, Any],
        patches: List[dict[str, Any]] = [],
        message_ids_to_revert: Optional[set] = None,
    ) -> dict:
        """创建撤销消息"""
        message = {
            "command": "undo",
            "level": level,
            "session_id": session_id,
            "agent_id": agent_id,
            "snapshot_hash": snapshot_hash,
            "diff": diff_content,
            "diff_summary": diff_summary,
            "pivot_message_id": pivot_message_id,
            "timestamp": datetime.now().isoformat(),
            "patches": patches,
            "message_ids_to_revert": list(message_ids_to_revert) if message_ids_to_revert else [],
        }
        return message

    async def _mark_messages_as_reverted(
        self, messages: List[Message], pivot_message_id: str | None
    ) -> set[str]:
        """标记消息和关联轮次为已撤销，返回被标记的消息ID集合

        轮次标记规则：仅当该轮次中所有消息都被撤销时，才标记轮次为已撤销。
        """
        # 按 turn 分组所有消息
        turn_message_map: dict[str, set[str]] = {}
        for msg in messages:
            if msg.turn_id:
                if msg.turn_id not in turn_message_map:
                    turn_message_map[msg.turn_id] = set()
                turn_message_map[msg.turn_id].add(msg.message_id)

        # 收集从 pivot 开始需要撤销的消息
        message_ids_to_revert = set()
        collecting = False
        for msg in messages:
            if msg.message_id == pivot_message_id:
                message_ids_to_revert.add(msg.message_id)
                collecting = True
                continue
            if collecting:
                message_ids_to_revert.add(msg.message_id)

        logger.debug(f"标记消息为已撤销: {message_ids_to_revert}")

        # 更新消息状态
        if message_ids_to_revert:
            await self.session_manager.batch_update_messages(
                list(message_ids_to_revert), reverted=True
            )

        # 标记轮次：仅当该轮次的所有消息都被撤销时才标记
        turn_ids_to_revert = set()
        for turn_id, msg_ids in turn_message_map.items():
            if msg_ids.issubset(message_ids_to_revert):
                turn_ids_to_revert.add(turn_id)

        if turn_ids_to_revert:
            logger.debug(f"标记轮次为已撤销（全部消息已撤销）: {turn_ids_to_revert}")
            await self.session_manager.batch_update_turns(
                list(turn_ids_to_revert), reverted=True
            )

        return message_ids_to_revert

    async def _mark_messages_as_reverted_sql(
        self, agent_id: str, pivot_message_id: str
    ) -> set:
        """通过 SQL 标记消息和关联轮次为已撤销（不加载全量消息）

        轮次标记规则：仅当该轮次中所有消息都在 revert 集合中时，才标记轮次。
        """
        msg_svc = get_message_service()

        # 通过 SQL 获取 pivot 之后的 message_ids 和 turn_ids
        result = await msg_svc.get_message_ids_from_pivot(agent_id, pivot_message_id)
        message_ids_to_revert = result.get("message_ids", set()) if isinstance(result, dict) else result
        turn_ids_from_pivot = result.get("turn_ids", set()) if isinstance(result, dict) else set()

        logger.debug(f"标记消息为已撤销: {len(message_ids_to_revert)} messages")

        # 更新消息状态
        if message_ids_to_revert:
            await self.session_manager.batch_update_messages(
                list(message_ids_to_revert), reverted=True
            )

        # 标记轮次：仅当该 turn 的所有消息都在 revert 集合中时才标记
        # （step-level undo 的 pivot 可能在 turn 中间，此时该 turn 还有未 revert 的消息）
        if turn_ids_from_pivot and message_ids_to_revert:
            async with db_manager.get_session() as session:
                # 查找这些 turn 中仍有未 revert 消息的 turn
                partial_rows = (
                    await session.execute(
                        select(Message.turn_id)
                        .where(Message.agent_id == agent_id)
                        .where(Message.turn_id.in_(list(turn_ids_from_pivot)))
                        .where(Message.message_id.not_in(list(message_ids_to_revert)))
                        .distinct()
                    )
                ).scalars().all()
                partial_turns = {tid for tid in partial_rows if tid}

            # 排除部分 revert 的 turn，仅标记完全 revert 的 turn
            turn_ids_to_mark = turn_ids_from_pivot - partial_turns
            if turn_ids_to_mark:
                logger.debug(f"标记轮次为已撤销（全部消息已撤销）: {turn_ids_to_mark}")
                if partial_turns:
                    logger.debug(f"跳过部分撤销的轮次: {partial_turns}")
                await self.session_manager.batch_update_turns(
                    list(turn_ids_to_mark), reverted=True
            )
        elif turn_ids_from_pivot and not message_ids_to_revert:
            # 边界情况：没有消息需要 revert 但有 turn_ids（不应发生，防御性处理）
            logger.warning(f"turn_ids 非空但 message_ids 为空，跳过 turn 标记: {turn_ids_from_pivot}")

        return message_ids_to_revert

    async def _mark_messages_as_redone(
        self, agent_id: str, undo_meta_info: dict
    ) -> None:
        """标记消息和轮次为已重做（SQL 化，不全量加载）

        只恢复本次 undo 时被撤销的消息，不影响 undo 之后产生的新消息。
        """
        message_ids_to_restore = set(undo_meta_info.get("message_ids_to_revert", []))
        if not message_ids_to_restore:
            return

        # 通过 SQL 查询这些 message_ids 对应的 turn_ids
        msg_svc = get_message_service()
        turn_ids_to_restore = await self._get_turn_ids_for_messages(
            agent_id, message_ids_to_restore
        )

        # 恢复消息
        await self.session_manager.batch_update_messages(
            list(message_ids_to_restore), reverted=False
        )

        # 恢复轮次
        if turn_ids_to_restore:
            logger.debug(f"标记轮次为已重做: {turn_ids_to_restore}")
            await self.session_manager.batch_update_turns(
                list(turn_ids_to_restore), reverted=False
            )

    async def _get_turn_ids_for_messages(
        self, agent_id: str, message_ids: set
    ) -> set:
        """通过 SQL 获取指定 message_ids 对应的 turn_ids"""
        from sqlalchemy import select as sa_select

        from broca.session.database import db_manager

        if not message_ids:
            return set()

        async with db_manager.get_session() as session:
            result = (
                await session.execute(
                    sa_select(Message.turn_id)
                    .where(Message.agent_id == agent_id)
                    .where(Message.message_id.in_(list(message_ids)))
                    .where(Message.turn_id.isnot(None))
                    .distinct()
                )
            ).scalars().all()
        return {tid for tid in result if tid}
