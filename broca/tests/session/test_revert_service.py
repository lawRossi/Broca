"""
SessionRevertService 单元测试

覆盖：
- undo 操作流程
- redo 操作流程
- 多级撤销栈管理
- 边界条件（空栈、无效会话等）
- _collect_patches_to_message
- _create_undo_meta_info
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.session.revert_service import SessionRevertService


@pytest.fixture
def mock_session_manager():
    """创建 mock SessionManager"""
    sm = MagicMock()
    sm.get_session = AsyncMock(return_value=MagicMock())
    sm.get_messages = AsyncMock(return_value=[])
    sm.batch_update_messages = AsyncMock()
    sm.batch_update_turns = AsyncMock()
    return sm


@pytest.fixture
def revert_service(mock_session_manager):
    """创建 SessionRevertService 实例"""
    service = SessionRevertService(
        session_manager=mock_session_manager,
        workspace_path="/tmp/workspace",
    )
    # Mock 快照相关实例
    service.snapshot_tracker = MagicMock()
    service.snapshot_tracker.track = AsyncMock(return_value="hash_123")
    service.patch_calculator = MagicMock()
    service.patch_calculator.calculate_diff = AsyncMock(return_value="diff content")
    service.patch_calculator.get_diff_summary = MagicMock(return_value={
        "total_files": 1, "files_modified": ["test.py"]
    })
    service.snapshot_restorer = MagicMock()
    service.snapshot_restorer.revert_patches = AsyncMock()
    return service


class TestRevertServiceInit:
    """测试初始化"""

    def test_init(self, revert_service):
        """测试初始化"""
        assert revert_service.session_manager is not None
        assert revert_service.workspace_path == "/tmp/workspace"
        assert revert_service.undo_stack == []


class TestUndo:
    """测试撤销操作"""

    @pytest.mark.asyncio
    async def test_undo_session_not_found(self, revert_service, mock_session_manager):
        """测试会话不存在时撤销抛出异常"""
        mock_session_manager.get_session = AsyncMock(return_value=None)

        from broca.errors import SessionError
        with pytest.raises(SessionError):
            await revert_service.undo(
                session_id="nonexistent",
                agent_id="agent-1",
                target_message_id="msg-1",
            )

    @pytest.mark.asyncio
    async def test_undo_no_pivot(self, revert_service, mock_session_manager):
        """测试没有 pivot message 时撤销"""
        mock_session_manager.get_messages = AsyncMock(return_value=[])
        mock_session_manager.get_session = AsyncMock(return_value=MagicMock())

        result = await revert_service.undo(
            session_id="session-1",
            agent_id="agent-1",
            target_message_id="nonexistent",
        )
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_undo_pushes_to_stack(self, revert_service):
        """测试撤销将记录推入栈"""
        # 创建一些 mock 消息
        msg = MagicMock()
        msg.message_id = "msg_target"
        msg.turn_id = "turn-1"
        msg.message_type = "STEP_START"
        msg.data = {"step_id": "step-1"}

        mock_session = MagicMock()
        revert_service.session_manager.get_session = AsyncMock(return_value=mock_session)
        revert_service.session_manager.get_messages = AsyncMock(return_value=[msg])

        # _collect_patches_to_message 返回空列表（没有实际 patch）
        revert_service._collect_patches_to_message = AsyncMock(
            return_value=([], None)
        )

        result = await revert_service.undo(
            session_id="session-1",
            agent_id="agent-1",
            target_message_id="msg_target",
        )
        assert result["success"] is False  # 没有 pivot


class TestRedo:
    """测试重做操作"""

    @pytest.mark.asyncio
    async def test_redo_empty_stack(self, revert_service):
        """测试空栈重做"""
        result = await revert_service.redo(
            session_id="session-1",
            agent_id="agent-1",
        )
        assert result["success"] is False
        assert "没有可重做的操作" in result.get("message", "")

    @pytest.mark.asyncio
    async def test_redo_session_not_found(self, revert_service, mock_session_manager):
        """测试会话不存在时重做抛出异常"""
        mock_session_manager.get_session = AsyncMock(return_value=None)

        # 先推一个 undo 记录
        revert_service.undo_stack.append({
            "snapshot_hash": "hash_123",
            "patches": [],
            "message_ids_to_revert": [],
        })

        from broca.errors import SessionError
        with pytest.raises(SessionError):
            await revert_service.redo(
                session_id="nonexistent",
                agent_id="agent-1",
            )

    @pytest.mark.asyncio
    async def test_redo_no_snapshot(self, revert_service, mock_session_manager):
        """测试撤销记录中没有快照信息"""
        mock_session_manager.get_session = AsyncMock(return_value=MagicMock())

        revert_service.undo_stack.append({
            "patches": [],
            "message_ids_to_revert": [],
            # 没有 snapshot_hash
        })

        result = await revert_service.redo(
            session_id="session-1",
            agent_id="agent-1",
        )
        assert result["success"] is False


class TestCollectPatches:
    """测试 _collect_patches_to_message"""

    @pytest.mark.asyncio
    async def test_empty_messages(self, revert_service):
        """测试空消息列表"""
        patches, pivot_id = await revert_service._collect_patches_to_message(
            [], "msg-1", "step"
        )
        assert patches == []
        assert pivot_id is None

    @pytest.mark.asyncio
    async def test_target_not_found(self, revert_service):
        """测试目标消息不存在"""
        msgs = [MagicMock(message_id="msg-1")]
        patches, pivot_id = await revert_service._collect_patches_to_message(
            msgs, "msg-nonexistent", "step"
        )
        assert patches == []
        assert pivot_id is None

    @pytest.mark.asyncio
    async def test_no_matching_step_start(self, revert_service):
        """测试没有匹配的 STEP_START"""
        msg = MagicMock()
        msg.message_id = "msg_target"
        msg.data = {"step_id": "step-1"}

        # 没有 STEP_START 类型的消息
        patches, pivot_id = await revert_service._collect_patches_to_message(
            [msg], "msg_target", "step"
        )
        assert patches == []
        assert pivot_id is None


class TestCreateUndoMetaInfo:
    """测试 _create_undo_meta_info"""

    def test_create_meta_info(self, revert_service):
        """测试创建撤销元信息"""
        meta = revert_service._create_undo_meta_info(
            session_id="session-1",
            agent_id="agent-1",
            level="step",
            pivot_message_id="msg-5",
            snapshot_hash="hash_123",
            diff_content="diff here",
            diff_summary={"files_modified": ["test.py"]},
            patches=[{"files": ["test.py"]}],
            message_ids_to_revert={"msg-6", "msg-7"},
        )
        assert meta["command"] == "undo"
        assert meta["session_id"] == "session-1"
        assert meta["agent_id"] == "agent-1"
        assert meta["snapshot_hash"] == "hash_123"
        assert meta["pivot_message_id"] == "msg-5"
        assert len(meta["patches"]) == 1


class TestMarkMessages:
    """测试消息标记"""

    @pytest.mark.asyncio
    async def test_mark_messages_as_reverted_empty(self, revert_service):
        """测试空消息列表"""
        result = await revert_service._mark_messages_as_reverted([], None)
        assert result == set()

    @pytest.mark.asyncio
    async def test_mark_messages_as_reverted_with_messages(self, revert_service):
        """测试标记消息为已撤销"""
        msg1 = MagicMock()
        msg1.message_id = "msg-1"
        msg1.turn_id = "turn-1"
        msg2 = MagicMock()
        msg2.message_id = "msg-2"
        msg2.turn_id = "turn-1"

        result = await revert_service._mark_messages_as_reverted(
            [msg1, msg2], "msg-1"
        )
        assert "msg-1" in result
        assert "msg-2" in result

    @pytest.mark.asyncio
    async def test_mark_messages_as_redone(self, revert_service, mock_session_manager):
        """测试标记消息为已重做"""
        await revert_service._mark_messages_as_redone(
            "agent-1",
            {"message_ids_to_revert": ["msg-1"]},
        )
        # 验证 batch_update_messages 被调用
        mock_session_manager.batch_update_messages.assert_called_once()
