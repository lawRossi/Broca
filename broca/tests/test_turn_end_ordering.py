"""回归测试：`turn_end` 广播必须晚于所有残余流式 chunk（agent_response）。

Bug：简洁模式下「turn 里没有调用工具」时，卡片结束后状态稳定停在「进行中」。

根因：
- ``_execute_step`` 无 tool_calls 的分支此前不 flush 残余 chunk，末尾不足
  ``_CHUNK_FLUSH_CHARS`` 的内容留在 ``_chunk_buffer``，只由 0.1s 延迟任务兜底；
- 无写操作的 turn 在 ``_finalize_turn`` 里几乎没有耗时（``_compute_turn_level_diff``
  直接返回 None + 两次本地 SQLite 写入），于是 ``turn_end`` 抢在延迟 flush 之前发出；
- 前端收到迟到的 ``agent_response`` 后把 ``turn.status`` 从 completed 改回 thinking，
  卡片从此卡在「进行中」。

修复：``_execute_step``（无工具分支）与 ``_finalize_turn`` 开头都显式
``await self._flush_now()``，保证 ``turn_end`` 一定是该 turn 的最后一条广播。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.components.loop_engine import ExecutionResult, ExecutionStatus
from broca.components.loop_hook import TurnContext
from broca.loop_engine.engine import DefaultLoopEngine
from broca.loop_engine.hooks.lifecycle_broadcast_hook import LifecycleBroadcastHook


class _RecordingCommunicator:
    """记录广播顺序的假 communicator。"""

    def __init__(self) -> None:
        self.events: list[tuple[str, str | None]] = []

    async def send_agent_response(self, content="", reasoning_content="", **kwargs):
        self.events.append(("agent_response", content))
        return "msg"

    async def send_turn_start(self, turn_id, turn_description, **kwargs):
        self.events.append(("turn_start", turn_id))
        return "msg"

    async def send_turn_end(self, turn_id, result=None, **kwargs):
        self.events.append(("turn_end", result))
        return "msg"

    async def send_message(self, message, callback=None):
        self.events.append((str(message.message_type), None))
        return "msg"

    async def send_error(self, *args, **kwargs):
        self.events.append(("error", None))

    def agent_response_count(self) -> int:
        return sum(1 for kind, _ in self.events if kind == "agent_response")


class _StreamingLLMStrategy:
    """流式吐出若干**小** chunk（总量 < _CHUNK_FLUSH_CHARS），且无 tool_calls。"""

    def __init__(self, pieces: list[str]) -> None:
        self._pieces = pieces

    async def call(self, *, history, tools, on_chunk, on_error, should_abort):
        for piece in self._pieces:
            await on_chunk(
                {
                    "type": "content",
                    "data": piece,
                    "index": 0,
                    "message_id": "msg_llm_1",
                }
            )
        message = SimpleNamespace(
            content="".join(self._pieces), tool_calls=[], message_id="msg_llm_1"
        )
        return SimpleNamespace(
            success=True,
            aborted=False,
            message=message,
            input_tokens=1,
            output_tokens=1,
        )


class _FakeContext:
    history: list = []

    async def add_message(self, *args, **kwargs):
        pass

    async def truncate_last_assistant_message_with_tool_calls(self, **kwargs):
        pass


def _make_engine(communicator: _RecordingCommunicator, pieces: list[str]) -> DefaultLoopEngine:
    config = SimpleNamespace(
        interactive=True,
        enable_snapshot_tracking=False,
        workspace="",
        provider="p",
        model="m",
    )
    engine = DefaultLoopEngine.__new__(DefaultLoopEngine)
    engine.agent_id = "agent-1"
    engine.session_id = "session-1"
    engine.turn_id = "turn-1"
    engine.step_id = None
    engine.abort_event = asyncio.Event()
    engine.config = config
    engine.communicator = communicator
    engine.context = _FakeContext()
    engine.session_manager = MagicMock()
    engine.session_manager.save_agent_response = AsyncMock(return_value=True)
    engine.session_manager.save_turn_end = AsyncMock(return_value=True)
    engine.session_manager.save_message = AsyncMock(return_value=True)
    engine.tool_mapping = {}
    engine.allowed_tools = None
    engine.namespace = None
    engine._llm_strategy = _StreamingLLMStrategy(pieces)
    engine._tool_strategy = None
    engine._strategies_ready = True
    engine._chunk_buffer = []
    engine._chunk_buffer_len = 0
    engine._chunk_flush_task = None
    engine._flush_lock = None
    engine._CHUNK_FLUSH_CHARS = 128
    engine._CHUNK_FLUSH_INTERVAL = 0.1
    engine._CHUNK_BUFFER_MAX = 512
    engine._message_source = None
    engine._on_chunk_handler = None
    engine._on_error_handler = None
    engine.agent_ref = SimpleNamespace(
        on_llm_call_completed=AsyncMock(), turn_id="turn-1"
    )
    engine._hooks = [LifecycleBroadcastHook(communicator, config, "session-1")]
    return engine


def _make_turn_ctx() -> TurnContext:
    return TurnContext(
        turn_id="turn-1",
        agent_id="agent-1",
        session_id="session-1",
        user_message={},
        message_id="msg_u1",
        data={},
    )


@pytest.mark.asyncio
async def test_turn_end_is_broadcast_after_all_stream_chunks():
    """无工具调用的 turn：turn_end 必须是最后一条广播（核心回归）。"""
    communicator = _RecordingCommunicator()
    engine = _make_engine(communicator, ["第一段", "第二段", "第三段"])
    turn_ctx = _make_turn_ctx()
    engine._on_chunk_handler = engine._make_chunk_handler()
    engine._on_error_handler = engine._make_error_handler()

    step_ctx = await engine._execute_step(turn_ctx)
    assert step_ctx.status is ExecutionStatus.COMPLETED

    await engine._finalize_turn(turn_ctx, ExecutionResult(status=ExecutionStatus.COMPLETED))
    # 给延迟 flush 任务留出执行机会：修复前它会在 turn_end 之后补发尾 chunk
    await asyncio.sleep(0.3)

    kinds = [kind for kind, _ in communicator.events]
    assert kinds[-1] == "turn_end", f"turn_end 不是最后一条广播: {kinds}"
    assert communicator.agent_response_count() == 1, kinds
    # 尾 chunk 的内容必须在 turn_end 之前完整送达
    merged = "".join(content or "" for kind, content in communicator.events if kind == "agent_response")
    assert merged == "第一段第二段第三段"


@pytest.mark.asyncio
async def test_finalize_flushes_leftover_chunks_even_without_step_flush():
    """兜底：即使 buffer 里仍有残余 chunk（未经 _execute_step 的 flush），
    `_finalize_turn` 也必须先 flush 再广播 turn_end。"""
    communicator = _RecordingCommunicator()
    engine = _make_engine(communicator, [])
    turn_ctx = _make_turn_ctx()
    engine._on_chunk_handler = engine._make_chunk_handler()

    # 直接注入一条残余 chunk，模拟延迟 flush 尚未触发的状态
    await engine._on_chunk_handler(
        {"type": "content", "data": "尾巴", "index": 0, "message_id": "msg_llm_1"}
    )
    assert len(engine._chunk_buffer) == 1

    await engine._finalize_turn(turn_ctx, ExecutionResult(status=ExecutionStatus.COMPLETED))
    await asyncio.sleep(0.3)

    kinds = [kind for kind, _ in communicator.events]
    assert kinds == ["agent_response", "turn_end"], kinds
