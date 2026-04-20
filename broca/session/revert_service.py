"""
SessionRevert 服务

提供撤销/重做功能，管理会话级别的操作回滚。
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from broca.session.session_manager import SessionManager

from ..snapshot import PatchCalculator, PatchReverter, SnapshotTracker
from .models import Message, MessageProtocol, MessageType
from .service import MessageService


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
        self.snapshot_tracker = SnapshotTracker(workspace_path)
        self.patch_calculator = PatchCalculator(workspace_path)
        self.patch_reverter = PatchReverter(workspace_path)

    async def undo(
        self,
        session_id: str,
        agent_id: str,
        target_message_id: Optional[str] = None,
        level: str = "step",
    ) -> Dict[str, any]:
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
        # 验证会话状态
        session = await self.session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"会话不存在: {session_id}")

        # 获取agent所有消息
        messages = await self.session_manager.get_messages(agent_id)

        if target_message_id:
            # 撤销到指定消息
            (
                patches_to_revert,
                pivot_message_id,
            ) = await self._collect_patches_to_message(
                messages, target_message_id, level
            )
        else:
            # 撤销最近的操作
            patches_to_revert, pivot_message_id = await self._collect_recent_patches(
                messages, level
            )

        # 捕获当前快照（用于重做）
        current_snapshot_hash = self.snapshot_tracker.track()

        # 如果有patch，反向应用patch
        diff_content = ""
        diff_summary = {}
        if patches_to_revert:
            # 反向应用patch
            self.patch_reverter.revert_patches(patches_to_revert)

            # 计算差异
            diff_content = self._calculate_diff_for_patches(current_snapshot_hash)
            diff_summary = self.patch_calculator.get_diff_summary(diff_content)

        # 保存撤销记录
        undo_message = await self._create_undo_message(
            session_id=session_id,
            level=level,
            pivot_message_id=pivot_message_id,
            snapshot_hash=current_snapshot_hash,
            diff_content=diff_content,
            diff_summary=diff_summary,
        )

        # 标记相关消息为已撤销
        await self._mark_messages_as_reverted(messages, pivot_message_id)

        return {
            "success": True,
            "undo_message_id": undo_message.message_id,
            "diff_summary": diff_summary,
            "patches_reverted": len(patches_to_revert),
        }

    async def redo(self, session_id: str, agent_id: str) -> Dict[str, any]:
        """
        执行重做操作

        Args:
            session_id: 会话ID

        Returns:
            重做结果
        """
        # 验证会话状态
        session = await self.session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"会话不存在: {session_id}")

        # 获取最新的撤销记录
        undo_message = await self._get_latest_undo_message(agent_id)
        if not undo_message:
            return {"success": False, "message": "没有可重做的操作"}

        # 从撤销记录中恢复快照
        snapshot_hash = undo_message.data.get("arguments").get("snapshot_hash")
        if not snapshot_hash:
            return {"success": False, "message": "撤销记录中没有快照信息"}

        # 恢复到撤销前的状态
        self.patch_reverter.apply_patch({"snapshot_hash": snapshot_hash})

        # 标记相关消息为已重做
        await self._mark_messages_as_redone(agent_id, undo_message)

        # 保存重做记录
        redo_message = await self._create_redo_message(
            session_id=session_id,
            undo_message_id=undo_message.message_id,
            snapshot_hash=snapshot_hash,
        )

        return {
            "success": True,
            "redo_message_id": redo_message.message_id,
            "undo_message_id": undo_message.message_id,
        }

    async def _collect_patches_to_message(
        self, messages: List[Message], target_message_id: str, level: str
    ) -> Tuple[List[Dict[str, any]], Optional[str]]:
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
            return [], None

        # 根据level确定pivot message
        pivot_message = None
        if level == "turn":
            # 找到对应的TURN_START消息作为pivot
            turn_id = target_message.turn_id
            for msg in reversed(messages):
                if (
                    msg.message_type == MessageType.TURN_END
                    and msg.data.get("turn_id") == turn_id
                ):
                    pivot_message = msg
                    pivot_message_id = pivot_message.message_id
                    break
        else:
            step_id = target_message.data.get("step_id")
            if step_id:
                for msg in reversed(messages):
                    if (
                        msg.message_type == MessageType.STEP_END
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

    async def _collect_recent_patches(
        self, messages: List[Message], level: str
    ) -> Tuple[List[Dict[str, any]], Optional[str]]:
        """收集最近的patch"""
        patches = []
        target_step_id = None

        # 从后向前遍历消息，找到最近的未撤销的消息
        recent_message = None
        for msg in reversed(messages):
            if not msg.reverted:
                recent_message = msg
                break

        if not recent_message:
            return [], None

        # 根据level确定pivot message
        pivot_message = None
        if level == "turn":
            # 找到对应的TURN_START消息作为pivot
            turn_id = recent_message.turn_id
            for msg in messages:
                if (
                    msg.message_type == MessageType.TURN_START
                    and msg.data.get("turn_id") == turn_id
                ):
                    pivot_message = msg
                    break
        else:  # step级别
            # 找到最近的STEP_END消息作为pivot
            for msg in reversed(messages):
                if msg.message_type == MessageType.STEP_END and not msg.reverted:
                    pivot_message = msg
                    target_step_id = msg.data.get("step_id")
                    break

        if not pivot_message:
            return [], target_step_id

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

                # 如果是turn级别，遇到TURN_END就停止
                if level == "turn" and msg.message_type == MessageType.TURN_END:
                    break

        return patches, target_step_id

    def _calculate_diff_for_patches(self, from_hash: str) -> str:
        """计算patch的差异"""
        current_hash = self.snapshot_tracker.track()

        return self.patch_calculator.calculate_diff(from_hash, current_hash)

    async def _create_undo_message(
        self,
        session_id: str,
        level: str,
        pivot_message_id: Optional[str],
        snapshot_hash: str,
        diff_content: str,
        diff_summary: Dict[str, any],
    ) -> Message:
        """创建撤销消息"""
        data = {
            "command": "undo",
            "level": level,
            "snapshot_hash": snapshot_hash,
            "diff": diff_content,
            "diff_summary": diff_summary,
        }
        if pivot_message_id:
            data["pivot_message_id"] = pivot_message_id

        message = MessageProtocol.create_command("undo", data)
        message.session_id = session_id
        message.timestamp = datetime.now(timezone.utc)

        message_service = MessageService()
        # 使用create方法创建消息
        await message_service.create(
            message_id=message.message_id,
            session_id=message.session_id,
            turn_id=message.turn_id,
            agent_id=message.agent_id,
            role=message.role,
            message_type=message.message_type,
            sequence_number=message.sequence_number or 1,
            data=message.data,
        )

        return message

    async def _create_redo_message(
        self,
        session_id: str,
        undo_message_id: str,
        snapshot_hash: str,
    ) -> Message:
        """创建重做消息"""
        data = {
            "command": "redo",
            "undo_message_id": undo_message_id,
            "snapshot_hash": snapshot_hash,
        }

        message = MessageProtocol.create_command("redo", data)
        message.session_id = session_id
        message.timestamp = datetime.now(timezone.utc)

        message_service = MessageService()
        # 使用create方法创建消息
        await message_service.create(
            message_id=message.message_id,
            session_id=message.session_id,
            turn_id=message.turn_id,
            agent_id=message.agent_id,
            role=message.role,
            message_type=message.message_type,
            sequence_number=message.sequence_number or 1,
            data=message.data,
        )

        return message

    async def _get_latest_undo_message(self, agent_id: str) -> Optional[Message]:
        """获取最新的撤销消息"""
        messages = await self.session_manager.get_messages(agent_id)

        for msg in reversed(messages):
            if (
                msg.message_type == MessageType.COMMAND
                and msg.data.get("command") == "undo"
                and not msg.reverted
            ):
                return msg

        return None

    async def _mark_messages_as_reverted(
        self, messages: List[Message], pivot_message_id: str | None
    ) -> None:
        """标记消息为已撤销"""
        message_service = MessageService()

        # 收集需要标记的消息ID
        message_ids_to_revert = set()

        collecting = False
        for msg in messages:
            if msg.message_id == pivot_message_id:
                collecting = True
                continue
            # 排除UNDO消息
            if msg.message_type == MessageType.COMMAND:
                if msg.data.get("command") == "undo":
                    continue
            if collecting:
                message_ids_to_revert.add(msg.message_id)

        # 更新消息状态
        for message_id in message_ids_to_revert:
            await message_service.update_message(
                message_id,
                updates={"reverted": True},
            )

    async def _mark_messages_as_redone(
        self, agent_id: str, undo_message: Message
    ) -> None:
        """标记消息为已重做"""
        message_service = MessageService()
        pivot_message_id = undo_message.data.get("pivot_message_id")
        messages = await self.session_manager.get_messages(
            agent_id, ignore_reverted=False
        )

        messages_to_mark = []
        collecting = False
        for msg in messages:
            if msg.message_id == pivot_message_id:
                collecting = True
                continue

            if collecting:
                messages_to_mark.append(msg)

        for msg in messages_to_mark:
            await message_service.update_message(
                msg.message_id,
                updates={"reverted": False},
            )
