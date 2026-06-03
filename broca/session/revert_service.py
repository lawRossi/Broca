"""
SessionRevert 服务

提供撤销/重做功能，管理会话级别的操作回滚。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from broca.logging_config import get_logger
from broca.session.models import Message, MessageType
from broca.session.session_manager import SessionManager
from broca.snapshot import PatchCalculator, SnapshotRestorer, SnapshotTracker

logger = get_logger(__name__)


class SessionRevertService:
    """会话撤销服务"""

    def __init__(self, session_manager: SessionManager, workspace_path: str):
        """
        初始化会话撤销服务

        Args:
            session_manager: 会话管理器
            workspace_path: 工作空间路径
        """
        self.session_manager = session_manager
        self.workspace_path = workspace_path
        self.snapshot_tracker = SnapshotTracker(self.workspace_path)
        self.patch_calculator = PatchCalculator(self.workspace_path)
        self.snapshot_restorer = SnapshotRestorer(self.workspace_path)
        self.undo_meta_info: dict = {}

    async def undo(
        self,
        session_id: str,
        agent_id: str,
        target_message_id: str,
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
            raise ValueError(f"会话不存在: {session_id}")

        # 获取agent所有消息
        messages = await self.session_manager.get_messages(agent_id)

        patches_to_revert, pivot_message_id = await self._collect_patches_to_message(
            messages, target_message_id, level
        )

        logger.info(f"pivot_message_id: {pivot_message_id}")
        logger.info(f"patches_to_revert: {patches_to_revert}")

        if not pivot_message_id:
            return {
                "success": False,
                "error": "No pivot message found",
                "patches_reverted": 0,
            }

        # 捕获当前快照（用于重做）
        current_snapshot_hash = await self.snapshot_tracker.track()

        # 如果有patch，反向应用patch
        diff_content = ""
        diff_summary = {}
        if patches_to_revert:
            # 反向应用patch
            await self.snapshot_restorer.revert_patches(patches_to_revert)

            # 计算差异
            diff_content = await self._calculate_diff_for_patches(current_snapshot_hash)
            diff_summary = self.patch_calculator.get_diff_summary(diff_content)

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
        )
        self.undo_meta_info = undo_meta_info

        # 标记相关消息为已撤销
        await self._mark_messages_as_reverted(messages, pivot_message_id)

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
            raise ValueError(f"会话不存在: {session_id}")

        # 获取最新的撤销记录
        undo_meta_info = self.undo_meta_info
        if not undo_meta_info:
            return {"success": False, "message": "没有可重做的操作"}

        # 从撤销记录中恢复快照
        snapshot_hash = undo_meta_info.get("snapshot_hash")
        if not snapshot_hash:
            return {"success": False, "message": "撤销记录中没有快照信息"}

        if undo_meta_info["patches"]:
            await self.snapshot_restorer.restore(snapshot_hash)

        # 标记相关消息为已重做
        await self._mark_messages_as_redone(agent_id, undo_meta_info)

        # 删除撤销记录
        self.undo_meta_info = {}
        logger.info("redo成功")

        return {"success": True}

    async def _collect_patches_to_message(
        self, messages: List[Message], target_message_id: str, level: str
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

        if not pivot_message:
            return [], pivot_message_id

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
        current_hash = await self.snapshot_tracker.track()

        return await self.patch_calculator.calculate_diff(from_hash, current_hash)

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
        }
        return message

    async def _mark_messages_as_reverted(
        self, messages: List[Message], pivot_message_id: str | None
    ) -> None:
        """标记消息为已撤销"""

        # 收集需要标记的消息ID
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
        for message_id in message_ids_to_revert:
            await self.session_manager.batch_update_messages(
                message_ids_to_revert, reverted=True)

    async def _mark_messages_as_redone(
        self, agent_id: str, undo_meta_info: dict
    ) -> None:
        """标记消息为已重做"""
        pivot_message_id = undo_meta_info.get("pivot_message_id")
        messages = await self.session_manager.get_messages(
            agent_id, ignore_reverted=False
        )

        message_ids_to_mark = []
        collecting = False
        for msg in messages:
            if msg.message_id == pivot_message_id:
                message_ids_to_mark.append(msg.message_id)
                collecting = True
                continue

            if collecting:
                message_ids_to_mark.append(msg.message_id)

        await self.session_manager.batch_update_messages(
            message_ids_to_mark, reverted=False
        )
