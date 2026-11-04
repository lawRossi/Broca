"""Unit tests for ``LifecycleBroadcastHook`` (Task 3.2).

Covers the migration of ``_broadcast_step_message`` / ``_broadcast_user_message`` /
``_send_turn_error_notification`` and the ``send_turn_end`` half of
``_save_and_broadcast_turn_end``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.components.loop_engine import ExecutionResult, ExecutionStatus
from broca.components.loop_hook import StepContext, TurnContext
from broca.loop_engine.hooks.lifecycle_broadcast_hook import LifecycleBroadcastHook
from broca.session.models import MessageType


class FakeConfig:
    def __init__(
        self,
        interactive: bool = True,
        enable_snapshot_tracking: bool = True,
        workspace: str = "/tmp/ws",
    ):
        self.interactive = interactive
        self.enable_snapshot_tracking = enable_snapshot_tracking
        self.workspace = workspace


def make_communicator() -> MagicMock:
    communicator = MagicMock()
    communicator.send_turn_start = AsyncMock()
    communicator.send_turn_end = AsyncMock()
    communicator.send_message = AsyncMock()
    communicator.send_error = AsyncMock()
    return communicator


def make_turn_ctx(
    status: ExecutionStatus = ExecutionStatus.COMPLETED,
    *,
    from_agent: bool = False,
    files: list | None = None,
    raw_input: str = "",
    message_id: str = "msg-1",
) -> TurnContext:
    result = ExecutionResult(status)
    ctx = TurnContext(
        turn_id="turn-1",
        agent_id="agent-1",
        session_id="sess-1",
        user_message={"content": "hello"},
        message_id=message_id,
        sender_id="user-1",
        files=files or [],
        from_agent=from_agent,
        raw_input=raw_input,
        result=result,
    )
    ctx.data["turn_end_message_id"] = "msg_turn_end"
    ctx.data["turn_end_message"] = "Turn completed successfully"
    return ctx


def make_step_ctx(step_patch: dict | None = None) -> StepContext:
    return StepContext(
        step_id="step-1",
        turn_id="turn-1",
        agent_id="agent-1",
        session_id="sess-1",
        step_start_snapshot="hash-start",
        step_end_snapshot="hash-end",
        step_patch=step_patch if step_patch is not None else {"files": {"a.py": {}}},
    )


class TestGating:
    @pytest.mark.asyncio
    async def test_non_interactive_is_noop(self):
        communicator = make_communicator()
        hook = LifecycleBroadcastHook(communicator, FakeConfig(interactive=False), "sess-1")
        turn_ctx = make_turn_ctx()
        step_ctx = make_step_ctx()

        await hook.on_turn_start(turn_ctx)
        await hook.on_step_start(step_ctx)
        await hook.on_step_end(step_ctx)
        await hook.on_turn_finalized(turn_ctx)

        assert communicator.send_turn_start.await_count == 0
        assert communicator.send_turn_end.await_count == 0
        assert communicator.send_message.await_count == 0
        assert communicator.send_error.await_count == 0

    @pytest.mark.asyncio
    async def test_missing_communicator_is_noop(self):
        hook = LifecycleBroadcastHook(None, FakeConfig(interactive=True), "sess-1")
        await hook.on_turn_start(make_turn_ctx())  # must not raise
        await hook.on_turn_finalized(make_turn_ctx())


class TestTurnStart:
    @pytest.mark.asyncio
    async def test_broadcasts_turn_start_once(self):
        communicator = make_communicator()
        hook = LifecycleBroadcastHook(communicator, FakeConfig(), "sess-1")

        await hook.on_turn_start(make_turn_ctx())

        assert communicator.send_turn_start.await_count == 1
        kwargs = communicator.send_turn_start.await_args.kwargs
        assert kwargs["turn_id"] == "turn-1"
        assert kwargs["turn_description"] == "Processing user message: hello"
        assert kwargs["subscription"] == "sess-1"

    @pytest.mark.asyncio
    async def test_broadcasts_user_message_with_files_and_raw_input(self):
        communicator = make_communicator()
        hook = LifecycleBroadcastHook(communicator, FakeConfig(), "sess-1")

        await hook.on_turn_start(
            make_turn_ctx(files=["a.png"], raw_input="raw text")
        )

        assert communicator.send_message.await_count == 1
        message = communicator.send_message.await_args.args[0]
        assert message.message_type == MessageType.USER_MESSAGE
        # raw_input 存在时优先作为 content（纯文本，避免 list 类型 content 泄漏到前端）
        assert message.data["content"] == "raw text"
        assert message.data["files"] == ["a.png"]
        assert message.data["raw_input"] == "raw text"
        assert message.message_id == "msg-1"
        assert message.turn_id == "turn-1"

    @pytest.mark.asyncio
    async def test_broadcast_content_is_string_when_multimodal(self):
        """回归: 多模态 content (list of dicts) 不应直接广播给前端。

        之前 parse_message 在有图片时返回 content=list，广播 hook 直接
        传给 create_user_message()，前端收到 list 后渲染为 [object Object]。
        修复后：应优先使用 raw_input（纯文本）作为广播 content。
        """
        communicator = make_communicator()
        hook = LifecycleBroadcastHook(communicator, FakeConfig(), "sess-1")

        # 模拟 parse_message 在有图片时的输出
        multimodal_content = [
            {"type": "image_url", "image_url": {"url": "http://cdn/a.png"}},
            {"type": "text", "text": "Check this"},
        ]
        ctx = TurnContext(
            turn_id="turn-1",
            agent_id="agent-1",
            session_id="sess-1",
            user_message={"content": multimodal_content, "raw_input": "Check this"},
            message_id="msg-1",
            sender_id="user-1",
            files=[{"name": "a.png", "url": "http://cdn/a.png", "type": "image/png"}],
            from_agent=False,
            raw_input="Check this",
        )
        ctx.data["turn_end_message_id"] = "msg_turn_end"
        ctx.data["turn_end_message"] = "Turn completed"

        await hook.on_turn_start(ctx)

        message = communicator.send_message.await_args.args[0]
        # content 必须是字符串，不能是 list
        assert isinstance(message.data["content"], str), (
            f"Broadcast content must be str, got {type(message.data['content'])}"
        )
        assert message.data["content"] == "Check this"

    @pytest.mark.asyncio
    async def test_broadcast_fallback_extracts_text_from_list_content(self):
        """raw_input 为空时，应从 list content 中提取 text 部分。"""
        communicator = make_communicator()
        hook = LifecycleBroadcastHook(communicator, FakeConfig(), "sess-1")

        multimodal_content = [
            {"type": "image_url", "image_url": {"url": "http://cdn/a.png"}},
            {"type": "text", "text": "Hello"},
        ]
        ctx = TurnContext(
            turn_id="turn-1",
            agent_id="agent-1",
            session_id="sess-1",
            user_message={"content": multimodal_content, "raw_input": ""},
            message_id="msg-1",
            sender_id="user-1",
            files=[],
            from_agent=False,
            raw_input="",  # 空字符串 → falsy
        )
        ctx.data["turn_end_message_id"] = "msg_turn_end"
        ctx.data["turn_end_message"] = "Turn completed"

        await hook.on_turn_start(ctx)

        message = communicator.send_message.await_args.args[0]
        assert isinstance(message.data["content"], str)
        assert message.data["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_skips_user_message_broadcast_for_agent_turns(self):
        communicator = make_communicator()
        hook = LifecycleBroadcastHook(communicator, FakeConfig(), "sess-1")

        await hook.on_turn_start(make_turn_ctx(from_agent=True))

        assert communicator.send_turn_start.await_count == 1
        assert communicator.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_skips_user_message_without_message_id(self):
        communicator = make_communicator()
        hook = LifecycleBroadcastHook(communicator, FakeConfig(), "sess-1")

        await hook.on_turn_start(make_turn_ctx(message_id=""))

        assert communicator.send_message.await_count == 0


class TestStepBroadcasts:
    @pytest.mark.asyncio
    async def test_step_start_carries_snapshot_hash(self):
        communicator = make_communicator()
        hook = LifecycleBroadcastHook(communicator, FakeConfig(), "sess-1")

        await hook.on_step_start(make_step_ctx())

        assert communicator.send_message.await_count == 1
        message = communicator.send_message.await_args.args[0]
        assert message.message_type == MessageType.STEP_START
        assert message.data["step_id"] == "step-1"
        assert message.data["snapshot_hash"] == "hash-start"
        assert message.session_id == "sess-1"
        assert message.turn_id == "turn-1"
        assert message.agent_id == "agent-1"
        assert message.subscription == "sess-1"

    @pytest.mark.asyncio
    async def test_step_start_skipped_when_snapshot_tracking_disabled(self):
        """Legacy parity (review m3): no snapshot tracking → no step_start event.

        Legacy ``_capture_step_start`` returned early without a snapshot
        manager, so it neither persisted a STEP_START row nor broadcast one.
        """
        communicator = make_communicator()
        hook = LifecycleBroadcastHook(
            communicator, FakeConfig(enable_snapshot_tracking=False), "sess-1"
        )

        await hook.on_step_start(make_step_ctx())

        assert communicator.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_step_start_skipped_without_workspace(self):
        communicator = make_communicator()
        hook = LifecycleBroadcastHook(communicator, FakeConfig(workspace=""), "sess-1")

        await hook.on_step_start(make_step_ctx())

        assert communicator.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_step_end_still_broadcast_without_snapshot_tracking(self):
        """Legacy broadcast step_end unconditionally (only ``step_id`` gated)."""
        communicator = make_communicator()
        hook = LifecycleBroadcastHook(
            communicator, FakeConfig(enable_snapshot_tracking=False), "sess-1"
        )

        await hook.on_step_end(make_step_ctx())

        assert communicator.send_message.await_count == 1
        assert (
            communicator.send_message.await_args.args[0].message_type
            == MessageType.STEP_END
        )

    @pytest.mark.asyncio
    async def test_step_end_carries_patch(self):
        communicator = make_communicator()
        hook = LifecycleBroadcastHook(communicator, FakeConfig(), "sess-1")
        patch = {"files": {"a.py": {"status": "M"}}, "summary": {"total_files": 1}}

        await hook.on_step_end(make_step_ctx(step_patch=patch))

        message = communicator.send_message.await_args.args[0]
        assert message.message_type == MessageType.STEP_END
        assert message.data["snapshot_hash"] == "hash-end"
        assert message.data["patch"] == patch


class TestTurnFinalized:
    @pytest.mark.asyncio
    async def test_broadcasts_changed_files_from_result(self):
        communicator = make_communicator()
        hook = LifecycleBroadcastHook(communicator, FakeConfig(), "sess-1")
        ctx = make_turn_ctx()
        changed = {"total_modified": 1, "files_modified": ["a.py"]}
        ctx.result.data["changed_files"] = changed

        await hook.on_turn_finalized(ctx)

        kwargs = communicator.send_turn_end.await_args.kwargs
        assert kwargs["turn_id"] == "turn-1"
        assert kwargs["result"] == "completed"
        assert kwargs["message_id"] == "msg_turn_end"
        assert kwargs["changed_files"] == changed
        assert kwargs["subscription"] == "sess-1"
        # completed → no error notification
        assert communicator.send_error.await_count == 0

    @pytest.mark.asyncio
    async def test_sends_error_notification_for_non_completed_status(self):
        communicator = make_communicator()
        hook = LifecycleBroadcastHook(communicator, FakeConfig(), "sess-1")
        ctx = make_turn_ctx(status=ExecutionStatus.ERROR)

        await hook.on_turn_finalized(ctx)

        assert communicator.send_turn_end.await_count == 1
        assert communicator.send_error.await_count == 1
        error_info = communicator.send_error.await_args.kwargs["error_info"]
        assert error_info["code"] == "EXECUTION_ERROR"
        assert error_info["severity"] == "error"
        assert error_info["message"] == "Turn completed successfully"
        assert error_info["details"] == {"status": "error"}
        assert error_info["recovery_hint"] is None
        assert error_info["cause"] is None
        assert error_info["traceback"] is None

    @pytest.mark.asyncio
    async def test_turn_end_without_result_is_noop(self):
        communicator = make_communicator()
        hook = LifecycleBroadcastHook(communicator, FakeConfig(), "sess-1")
        ctx = make_turn_ctx()
        ctx.result = None

        await hook.on_turn_finalized(ctx)

        assert communicator.send_turn_end.await_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_failures_are_swallowed(self):
        communicator = make_communicator()
        communicator.send_turn_end = AsyncMock(side_effect=RuntimeError("socket down"))
        hook = LifecycleBroadcastHook(communicator, FakeConfig(), "sess-1")

        await hook.on_turn_finalized(make_turn_ctx())  # must not raise

    def test_on_turn_end_not_overridden(self):
        # Broadcast must live in on_turn_finalized (after save_turn_end).
        assert "on_turn_end" not in LifecycleBroadcastHook.__dict__

    def test_name_is_unique(self):
        assert LifecycleBroadcastHook.name == "lifecycle_broadcast"
