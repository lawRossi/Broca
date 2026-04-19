"""
SessionRevert 服务

提供撤销/重做功能，管理会话级别的操作回滚。
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from ..snapshot import PatchCalculator, PatchReverter, SnapshotTracker
from .models import Message, MessageProtocol, MessageType
from .service import MessageService


class SessionRevertService:
    """会话撤销服务"""

    def __init__(self, session_manager, workspace_path: str):
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
        target_message_id: Optional[str] = None,
        level: str = "step",
    ) -> Dict[str, any]:
        """
        执行撤销操作

        Args:
            session_id: 会话ID
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
        messages = await self._get_agent_messages(session_id)

        # 收集需要撤销的patch
        patches_to_revert = []
        target_step_id = None

        if target_message_id:
            # 撤销到指定消息
            patches_to_revert, target_step_id = await self._collect_patches_to_message(
                messages, target_message_id, level
            )
        else:
            # 撤销最近的操作
            patches_to_revert, target_step_id = await self._collect_recent_patches(
                messages, level
            )

        if not patches_to_revert:
            return {"success": False, "message": "没有可撤销的操作"}

        print(patches_to_revert)

        # 捕获当前快照（用于重做）
        current_snapshot_hash = self.snapshot_tracker.track()

        print("快照哈希:", current_snapshot_hash)

        # 反向应用patch
        self.patch_reverter.revert_patches(patches_to_revert)

        # 计算差异
        diff_content = self._calculate_diff_for_patches(patches_to_revert)
        diff_summary = self.patch_calculator.get_diff_summary(diff_content)

        # 保存撤销记录
        undo_message = await self._create_undo_message(
            session_id=session_id,
            level=level,
            target_step_id=target_step_id,
            snapshot_hash=current_snapshot_hash,
            diff_content=diff_content,
            diff_summary=diff_summary,
        )

        # 标记相关消息为已撤销
        await self._mark_messages_as_reverted(messages, patches_to_revert, level)

        return {
            "success": True,
            "undo_message_id": undo_message.message_id,
            "diff_summary": diff_summary,
            "patches_reverted": len(patches_to_revert),
        }

    async def redo(self, session_id: str) -> Dict[str, any]:
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
        undo_message = await self._get_latest_undo_message(session_id)
        if not undo_message:
            return {"success": False, "message": "没有可重做的操作"}

        # 从撤销记录中恢复快照
        snapshot_hash = undo_message.data.get("arguments").get("snapshot_hash")
        print(snapshot_hash)
        if not snapshot_hash:
            return {"success": False, "message": "撤销记录中没有快照信息"}

        # 恢复到撤销前的状态
        self.patch_reverter.apply_patch({"snapshot_hash": snapshot_hash})

        # 标记相关消息为已重做
        await self._mark_messages_as_redone(session_id, undo_message)

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

    async def _get_agent_messages(self, session_id: str) -> List[Message]:
        """获取agent的所有消息"""
        message_service = MessageService()
        # 注意：这里需要修改 MessageService 的 get_messages_by_session 方法
        # 添加 ignore_reverted 参数，但撤销操作需要看到所有消息
        messages = await message_service.get_messages_by_session(
            session_id=session_id,
            order_by="sequence_number",
            ignore_reverted=False,  # 撤销时需要看到所有消息
        )
        return messages

    async def _collect_patches_to_message(
        self, messages: List[Message], target_message_id: str, level: str
    ) -> Tuple[List[Dict[str, any]], Optional[str]]:
        """收集到指定消息的所有patch"""
        patches = []
        target_step_id = None

        # 找到目标消息
        target_message = None
        for msg in messages:
            if msg.message_id == target_message_id:
                target_message = msg
                break

        if not target_message:
            return [], None

        # 根据level确定收集范围
        if level == "turn":
            # 收集整个turn的patch
            turn_id = target_message.turn_id
            collecting = False
            for msg in messages:
                if (
                    msg.message_type == MessageType.TURN_START
                    and msg.data.get("turn_id") == turn_id
                ):
                    collecting = True
                if collecting and msg.message_type == MessageType.STEP_END:
                    patch = msg.data.get("patch")
                    if patch:
                        patches.append(patch)
                if (
                    msg.message_type == MessageType.TURN_END
                    and msg.data.get("turn_id") == turn_id
                ):
                    break
        else:  # step级别
            # 收集指定step的patch
            step_id = target_message.data.get("step_id")
            if step_id:
                target_step_id = step_id
                for msg in messages:
                    if (
                        msg.message_type == MessageType.STEP_END
                        and msg.data.get("step_id") == step_id
                    ):
                        patch = msg.data.get("patch")
                        if patch:
                            patches.append(patch)
                        break

        return patches, target_step_id

    async def _collect_recent_patches(
        self, messages: List[Message], level: str
    ) -> Tuple[List[Dict[str, any]], Optional[str]]:
        """收集最近的patch"""
        patches = []
        target_step_id = None

        # 从后向前遍历消息
        for msg in reversed(messages):
            if msg.reverted:
                continue

            if level == "turn":
                # 找到最近的TURN_END消息
                if msg.message_type == MessageType.TURN_END:
                    turn_id = msg.data.get("turn_id")
                    # 收集这个turn的所有patch
                    for m in messages:
                        if (
                            m.turn_id == turn_id
                            and m.message_type == MessageType.STEP_END
                        ):
                            patch = m.data.get("patch")
                            if patch:
                                patches.append(patch)
                    break
            else:  # step级别
                # 找到最近的STEP_END消息
                if msg.message_type == MessageType.STEP_END:
                    patch = msg.data.get("patch")
                    if patch:
                        patches.append(patch)
                    target_step_id = msg.data.get("step_id")
                    break

        return patches, target_step_id

    def _calculate_diff_for_patches(self, patches: List[Dict[str, any]]) -> str:
        """计算patch的差异"""
        if not patches:
            return ""

        # 获取第一个patch的起始快照
        first_patch = patches[0]
        from_hash = first_patch.get("snapshot_hash")

        # 获取最后一个patch应用后的状态
        # 这里我们捕获当前状态来计算差异
        current_hash = self.snapshot_tracker.track()

        return self.patch_calculator.calculate_diff(from_hash, current_hash)

    async def _create_undo_message(
        self,
        session_id: str,
        level: str,
        target_step_id: Optional[str],
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
        if target_step_id:
            data["target_step_id"] = target_step_id

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

    async def _get_latest_undo_message(self, session_id: str) -> Optional[Message]:
        """获取最新的撤销消息"""
        message_service = MessageService()
        messages = await message_service.get_messages_by_session(
            session_id=session_id,
            order_by="sequence_number DESC",
            limit=50,
            ignore_reverted=False,
        )

        for msg in messages:
            if (
                msg.message_type == MessageType.COMMAND
                and msg.data.get("command") == "undo"
                and not msg.reverted
            ):
                return msg

        return None

    async def _mark_messages_as_reverted(
        self,
        messages: List[Message],
        patches: List[Dict[str, any]],
        level: str,
    ) -> None:
        """标记消息为已撤销"""
        message_service = MessageService()

        # 收集需要标记的消息ID
        message_ids_to_revert = set()

        for patch in patches:
            # 找到对应的STEP_END消息
            for msg in messages:
                if (
                    msg.message_type == MessageType.STEP_END
                    and msg.data.get("patch") == patch
                ):
                    message_ids_to_revert.add(msg.message_id)
                    # 如果是step级别，还需要标记相关的TOOL_CALL消息
                    if level == "step":
                        step_id = msg.data.get("step_id")
                        for m in messages:
                            if (
                                m.message_type == MessageType.TOOL_CALL
                                and m.data.get("step_id") == step_id
                            ):
                                message_ids_to_revert.add(m.message_id)
                    break

        # 更新消息状态
        for message_id in message_ids_to_revert:
            await message_service.update_message(
                message_id,
                updates={"reverted": True},
            )

    async def _mark_messages_as_redone(
        self, session_id: str, undo_message: Message
    ) -> None:
        """标记消息为已重做"""
        message_service = MessageService()

        # 获取被撤销的消息
        target_step_id = undo_message.data.get("arguments").get("target_step_id")
        level = undo_message.data.get("level", "step")

        messages = await self._get_agent_messages(session_id)

        message_ids_to_redo = set()

        for msg in messages:
            if msg.reverted:
                if level == "turn":
                    # 重做整个turn
                    turn_id = msg.turn_id
                    undo_turn_id = undo_message.turn_id
                    if turn_id == undo_turn_id:
                        message_ids_to_redo.add(msg.message_id)
                else:  # step级别
                    # 重做指定step
                    step_id = msg.data.get("step_id")
                    if step_id == target_step_id:
                        message_ids_to_redo.add(msg.message_id)

        print(message_ids_to_redo)

        # 更新消息状态
        for message_id in message_ids_to_redo:
            await message_service.update_message(
                message_id,
                updates={"reverted": False},
            )
