import uuid
from typing import List, Optional
from broca.snapshot import SnapshotGitManager, track_snapshot, restore_snapshot
from broca.session.database import db_manager
from broca.session.models import Message, MessageType, MessageRole
from sqlalchemy import select


class RevertService:
    """Service for undo/redo operations"""

    def __init__(self):
        pass

    async def undo(
        self,
        session_id: str,
        level: str = "step",
        target_message_id: Optional[str] = None,
    ) -> dict:
        """
        Execute undo operation.
        
        Args:
            session_id: The session ID
            level: "turn" or "step" (default: "step")
            target_message_id: The message ID to anchor undo to
            
        Returns:
            dict with revert metadata
        """
        # Get all messages for this session
        async with db_manager.get_session() as session:
            statement = (
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.sequence_number)
            )
            result = await session.exec(statement)
            messages = result.scalars().all()

        # Find anchor message
        anchor_msg = None
        if target_message_id:
            for msg in messages:
                if msg.message_id == target_message_id:
                    anchor_msg = msg
                    break
        else:
            # Default: undo last step
            for msg in reversed(messages):
                if msg.message_type in (MessageType.STEP_START, MessageType.STEP_FINISH):
                    anchor_msg = msg
                    break

        if not anchor_msg:
            return {"error": "No anchor message found", "success": False}

        # Collect patches from anchor forward
        patch_messages = []
        collect = False
        for msg in messages:
            if msg.message_id == anchor_msg.message_id:
                collect = True
                continue
            if collect and msg.message_type == MessageType.STEP_FINISH:
                patch_messages.append(msg)

        # Capture current snapshot before revert
        workspace = messages[0].data.get("workspace") if messages else None
        if not workspace:
            return {"error": "No workspace found", "success": False}

        snapshot_manager = SnapshotGitManager(workspace)
        current_snapshot = await track_snapshot(workspace)

        # TODO: Restore to anchor snapshot and apply reverse patches

        # Save undo message
        undo_message_id = f"msg_{uuid.uuid4().hex[:16]}"
        undo_data = {
            "level": level,
            "target_message_id": anchor_msg.message_id,
            "snapshot": current_snapshot,
            "files": [msg.data.get("patch", {}).get("files", []) for msg in patch_messages],
            "diff": "",  # TODO: compute diff
        }

        async with db_manager.get_session() as session:
            undo_msg = Message(
                message_id=undo_message_id,
                message_type=MessageType.COMMAND,
                role=MessageRole.SYSTEM,
                session_id=session_id,
                data={"command": "undo", **undo_data},
            )
            session.add(undo_msg)
            await session.commit()

        return {
            "success": True,
            "message_id": undo_message_id,
            "anchor_message_id": anchor_msg.message_id,
            "snapshot": current_snapshot,
        }

    async def redo(self, session_id: str) -> dict:
        """
        Execute redo operation.
        
        Args:
            session_id: The session ID
            
        Returns:
            dict with result
        """
        # Find last undo message
        async with db_manager.get_session() as session:
            statement = (
                select(Message)
                .where(Message.session_id == session_id)
                .where(Message.message_type == MessageType.COMMAND)
                .where(Message.data["command"].astext == "undo")
                .order_by(Message.sequence_number.desc())
                .limit(1)
            )
            result = await session.exec(statement)
            undo_msg = result.scalars().first()

        if not undo_msg:
            return {"error": "No undo found", "success": False}

        undo_data = undo_msg.data
        workspace = undo_msg.data.get("workspace")
        
        if not workspace:
            return {"error": "No workspace found", "success": False}

        # Restore to undo snapshot
        snapshot = undo_data.get("snapshot")
        if snapshot:
            await restore_snapshot(workspace, snapshot)

        # Clear undo state (delete the undo message or mark as undone)
        return {"success": True, "restored_snapshot": snapshot}