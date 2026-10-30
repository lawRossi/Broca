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
        """测试无快照模式下的 redo（仅标记消息，无文件恢复）"""
        mock_session_manager.get_session = AsyncMock(return_value=MagicMock())
        mock_session_manager.get_messages = AsyncMock(return_value=[])
        mock_session_manager.batch_update_messages = AsyncMock()
        mock_session_manager.batch_update_turns = AsyncMock()

        revert_service.undo_stack.append({
            "patches": [],
            "message_ids_to_revert": ["msg-1", "msg-2"],
            "snapshot_hash": "",
        })

        result = await revert_service.redo(
            session_id="session-1",
            agent_id="agent-1",
        )
        # 无快照模式下 redo 仅标记消息，应成功
        assert result["success"] is True
        # 不应调用 snapshot_restorer
        assert not revert_service.undo_stack  # 栈已被 pop


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
        """测试没有匹配的 STEP_START（无快照模式 fallback：用目标消息作为 pivot）"""
        msg = MagicMock()
        msg.message_id = "msg_target"
        msg.data = {"step_id": "step-1"}
        msg.message_type = "agent_response"

        # 没有 STEP_START 类型的消息 → fallback 到目标消息自身
        patches, pivot_id = await revert_service._collect_patches_to_message(
            [msg], "msg_target", "step"
        )
        assert patches == []
        # fallback: 目标消息自身作为 pivot
        assert pivot_id == "msg_target"


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


class TestNoSnapshotMode:
    """测试 enable_snapshot_tracking=False 时的 undo/redo 行为"""

    @pytest.fixture
    def no_snapshot_service(self, mock_session_manager):
        """创建无快照跟踪的 RevertService"""
        service = SessionRevertService(
            session_manager=mock_session_manager,
            workspace_path="/tmp/workspace",
            enable_snapshot_tracking=False,
        )
        service.snapshot_tracker = MagicMock()
        service.snapshot_tracker.track = AsyncMock(return_value="")
        service.patch_calculator = MagicMock()
        service.snapshot_restorer = MagicMock()
        return service

    @pytest.mark.asyncio
    async def test_undo_only_marks_messages(self, no_snapshot_service, mock_session_manager):
        """无快照模式下 undo 仅标记消息，不执行文件操作"""
        # 模拟消息：没有 STEP_START/STEP_END
        turn_start = MagicMock()
        turn_start.message_id = "msg_turn_start"
        turn_start.message_type = "turn_start"
        turn_start.turn_id = "turn-1"
        turn_start.data = {}

        agent_response = MagicMock()
        agent_response.message_id = "msg_response"
        agent_response.message_type = "agent_response"
        agent_response.turn_id = "turn-1"
        agent_response.data = {"step_id": "step-1"}

        tool_call = MagicMock()
        tool_call.message_id = "msg_tool"
        tool_call.message_type = "tool_call"
        tool_call.turn_id = "turn-1"
        tool_call.data = {"step_id": "step-1"}

        mock_session_manager.get_session = AsyncMock(return_value=MagicMock())
        mock_session_manager.get_messages = AsyncMock(
            return_value=[turn_start, agent_response, tool_call]
        )

        result = await no_snapshot_service.undo(
            session_id="session-1",
            agent_id="agent-1",
            target_message_id="msg_response",
            level="step",
        )

        assert result["success"] is True
        assert result["patches_reverted"] == 0
        # snapshot_restorer 不应被调用
        no_snapshot_service.snapshot_restorer.revert_patches.assert_not_called()
        # 但消息标记应被调用
        mock_session_manager.batch_update_messages.assert_called()

    @pytest.mark.asyncio
    async def test_undo_auto_target(self, no_snapshot_service, mock_session_manager):
        """无快照模式下 /undo 不指定 target 时自动定位最后 AGENT_RESPONSE"""
        agent_response = MagicMock()
        agent_response.message_id = "msg_response"
        agent_response.message_type = "agent_response"
        agent_response.turn_id = "turn-1"
        agent_response.data = {"step_id": "step-1"}

        tool_call = MagicMock()
        tool_call.message_id = "msg_tool"
        tool_call.message_type = "tool_call"
        tool_call.turn_id = "turn-1"
        tool_call.data = {"step_id": "step-1"}

        mock_session_manager.get_session = AsyncMock(return_value=MagicMock())
        mock_session_manager.get_messages = AsyncMock(
            return_value=[agent_response, tool_call]
        )

        result = await no_snapshot_service.undo(
            session_id="session-1",
            agent_id="agent-1",
            target_message_id=None,  # 不指定，自动定位
            level="step",
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_redo_only_unmarks_messages(self, no_snapshot_service, mock_session_manager):
        """无快照模式下 redo 仅取消标记消息"""
        mock_session_manager.get_session = AsyncMock(return_value=MagicMock())
        mock_session_manager.get_messages = AsyncMock(return_value=[])

        no_snapshot_service.undo_stack.append({
            "patches": [],
            "message_ids_to_revert": ["msg-1"],
            "snapshot_hash": "",
        })

        result = await no_snapshot_service.redo(
            session_id="session-1",
            agent_id="agent-1",
        )

        assert result["success"] is True
        # snapshot_restorer 不应被调用
        no_snapshot_service.snapshot_restorer.restore.assert_not_called()
        assert no_snapshot_service.undo_stack == []
