"""Regression tests: tool-injected context messages must not split a tool-result block.

Background
----------
``read_image`` injects a multimodal ``user`` message into the conversation via
``ToolResult.extra_context_messages`` so the LLM can "see" the image.

When the engine appended those extras **inline** (right after the tool result
that produced them), a batch such as ``[read_image, read_file]`` produced::

    assistant(tool_calls=[read_image, read_file])
    tool(read_image result)
    user(image)                 <-- invalid: splits the tool-result block
    tool(read_file result)

Every provider rejects that sequence (tool results must immediately follow the
assistant ``tool_calls`` message, contiguously), so the next LLM call failed.

Fix: ``_process_tool_results`` persists all tool results first and only then
flushes the tool-injected messages. These tests lock that ordering in.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.tests.test_engine_orchestration import (
    FakeLLMStrategy,
    FakeToolStrategy,
    _agent_ref,
    _config,
    _llm_ok,
    _session_manager,
    _tool_call,
    _tool_executor,
    _user_message,
)
from broca.loop_engine.engine import DefaultLoopEngine
from broca.tools.tool import ToolResult, ToolStatus


IMAGE_EXTRA = {
    "llm_message": {
        "role": "user",
        "content": [
            {
                "type": "image_url",
                "image_url": {"url": "https://cdn.example.com/uploads/x.png"},
            },
            {"type": "text", "text": "Image Readed"},
        ],
    },
    "data": {
        "content": "Image Readed",
        "files": [
            {
                "name": "x.png",
                "url": "https://cdn.example.com/uploads/x.png",
                "type": "image/png",
            }
        ],
    },
    "role": "user",
}


def _context():
    """Context mock whose ``format_tool_call_result`` is distinguishable."""
    ctx = MagicMock()
    ctx.history = [{"role": "user", "content": "hi"}]
    ctx.add_message = AsyncMock()
    ctx.format_tool_call_result = MagicMock(
        side_effect=lambda message: {"role": "tool", "content": "tool result"}
    )
    ctx.truncate_last_assistant_message_with_tool_calls = AsyncMock()
    return ctx


def _engine(llm_results, tool_results=None):
    engine = DefaultLoopEngine(
        agent_ref=_agent_ref(),
        llm_client=MagicMock(
            parse_message=MagicMock(return_value={"role": "user", "content": "hi"})
        ),
        context=_context(),
        tool_mapping={},
        config=_config(interactive=False),
        communicator=MagicMock(send_error=AsyncMock()),
        session_manager=_session_manager(),
        tool_executor=_tool_executor(),
        llm_strategy=FakeLLMStrategy(llm_results),
        tool_strategy=FakeToolStrategy(tool_results),
        hooks=[],
    )
    return engine


@pytest.mark.asyncio
async def test_injected_message_comes_after_all_tool_results():
    """read_image first in the batch must NOT sandwich a user message."""
    engine = _engine([_llm_ok()])
    calls = [
        _tool_call("read_image", tc_id="c1"),
        _tool_call("read_file", tc_id="c2"),
    ]
    results = [
        ToolResult(
            status=ToolStatus.SUCCESS,
            content="图片已读取",
            extra_context_messages=[IMAGE_EXTRA],
        ),
        ToolResult(status=ToolStatus.SUCCESS, content="file content"),
    ]

    await engine._process_tool_results(calls, results)

    added = [c.args[0] for c in engine.context.add_message.await_args_list]
    assert [m["role"] for m in added] == ["tool", "tool", "user"], (
        f"tool results must be contiguous, got {[m['role'] for m in added]}"
    )
    # The injected message is the image one and it is last.
    assert added[-1]["content"][0]["type"] == "image_url"


@pytest.mark.asyncio
async def test_injected_message_ordering_is_persisted_too():
    """DB write order must match context order (history is rebuilt from DB)."""
    engine = _engine([_llm_ok()])
    order: list[str] = []
    engine.session_manager.save_tool_call = AsyncMock(
        side_effect=lambda **kw: order.append(f"tool:{kw['tool_call'].id}") or True
    )
    engine.session_manager.save_message = AsyncMock(
        side_effect=lambda **kw: order.append("extra") or True
    )

    calls = [
        _tool_call("read_image", tc_id="c1"),
        _tool_call("read_file", tc_id="c2"),
    ]
    results = [
        ToolResult(
            status=ToolStatus.SUCCESS,
            content="图片已读取",
            extra_context_messages=[IMAGE_EXTRA],
        ),
        ToolResult(status=ToolStatus.SUCCESS, content="file content"),
    ]

    await engine._process_tool_results(calls, results)

    assert order == ["tool:c1", "tool:c2", "extra"]


@pytest.mark.asyncio
async def test_multiple_injecting_tools_keep_results_contiguous():
    """Two image tools in one batch → both images after both tool results."""
    engine = _engine([_llm_ok()])
    calls = [
        _tool_call("read_image", tc_id="c1"),
        _tool_call("read_image", tc_id="c2"),
        _tool_call("bash", tc_id="c3"),
    ]
    results = [
        ToolResult(
            status=ToolStatus.SUCCESS, content="img1", extra_context_messages=[IMAGE_EXTRA]
        ),
        ToolResult(
            status=ToolStatus.SUCCESS, content="img2", extra_context_messages=[IMAGE_EXTRA]
        ),
        ToolResult(status=ToolStatus.SUCCESS, content="bash out"),
    ]

    await engine._process_tool_results(calls, results)

    added = [c.args[0] for c in engine.context.add_message.await_args_list]
    assert [m["role"] for m in added] == ["tool", "tool", "tool", "user", "user"]


@pytest.mark.asyncio
async def test_single_tool_call_still_injects_immediately():
    """Backwards compatibility: ``process_tool_call_result`` defaults to inline."""
    engine = _engine([_llm_ok()])
    call = _tool_call("read_image", tc_id="c1")
    result = ToolResult(
        status=ToolStatus.SUCCESS, content="图片已读取", extra_context_messages=[IMAGE_EXTRA]
    )

    assert await engine.process_tool_call_result(call, result) is True

    added = [c.args[0] for c in engine.context.add_message.await_args_list]
    assert [m["role"] for m in added] == ["tool", "user"]


@pytest.mark.asyncio
async def test_extra_persistence_failure_does_not_break_the_turn():
    """A failed save of the injected message must not raise (image is optional)."""
    engine = _engine([_llm_ok()])
    engine.session_manager.save_message = AsyncMock(side_effect=RuntimeError("db down"))
    call = _tool_call("read_image", tc_id="c1")
    result = ToolResult(
        status=ToolStatus.SUCCESS, content="图片已读取", extra_context_messages=[IMAGE_EXTRA]
    )

    assert await engine.process_tool_call_result(call, result) is True
    # Not appended to the in-memory context either (it was never persisted).
    assert engine.context.add_message.await_count == 1


@pytest.mark.asyncio
async def test_full_turn_with_parallel_image_tool_completes():
    """End-to-end: turn with read_image + another tool still completes."""
    calls = [_tool_call("read_image", tc_id="c1"), _tool_call("bash", tc_id="c2")]
    results = [
        ToolResult(
            status=ToolStatus.SUCCESS, content="图片已读取", extra_context_messages=[IMAGE_EXTRA]
        ),
        ToolResult(status=ToolStatus.SUCCESS, content="ok"),
    ]
    engine = _engine([_llm_ok(calls), _llm_ok()], results)

    result = await engine.execute(_user_message())

    assert result.status.value == "completed"
    added = [c.args[0] for c in engine.context.add_message.await_args_list]
    roles = [m.get("role") for m in added if isinstance(m, dict)]
    # assistant → tool → tool → user(image)
    assert roles[-3:] == ["tool", "tool", "user"]


# ── History repair for already-corrupted sessions ─────────────────────


def _assistant(tool_ids, mid="msg_a"):
    return (
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": tid, "type": "function", "function": {"name": "f", "arguments": "{}"}}
                for tid in tool_ids
            ],
        },
        mid,
    )


def _tool(tid, mid=None):
    return ({"role": "tool", "tool_call_id": tid, "content": "ok"}, mid or f"msg_{tid}")


def _user_image():
    return (IMAGE_EXTRA["llm_message"], "msg_img")


def test_normalize_moves_injected_message_after_tool_block():
    """Legacy broken order (tool, user, tool) is repaired on load."""
    from broca.context import Context

    pairs = [_assistant(["c1", "c2"]), _tool("c1"), _user_image(), _tool("c2")]
    fixed = Context._normalize_tool_call_blocks(pairs)

    assert [p[0]["role"] for p in fixed] == ["assistant", "tool", "tool", "user"]
    # db ids travel with their message (undo/redo alignment)
    assert [p[1] for p in fixed] == ["msg_a", "msg_c1", "msg_c2", "msg_img"]


def test_normalize_keeps_valid_order_untouched():
    from broca.context import Context

    pairs = [
        _assistant(["c1", "c2"]),
        _tool("c1"),
        _tool("c2"),
        _user_image(),
        _assistant(["c3"]),
        _tool("c3"),
    ]
    assert Context._normalize_tool_call_blocks(pairs) == pairs


def test_normalize_is_noop_without_tool_calls():
    from broca.context import Context

    pairs = [
        ({"role": "user", "content": "hi"}, "m1"),
        ({"role": "assistant", "content": "hello"}, "m2"),
        ({"role": "user", "content": "again"}, "m3"),
    ]
    assert Context._normalize_tool_call_blocks(pairs) == pairs


def test_normalize_stops_at_foreign_tool_result():
    from broca.context import Context

    # c2 never gets a result; a foreign tool result must not be swallowed.
    pairs = [_assistant(["c1", "c2"]), _tool("c1"), _tool("zzz"), _user_image()]
    fixed = Context._normalize_tool_call_blocks(pairs)

    assert [p[0]["role"] for p in fixed] == ["assistant", "tool", "tool", "user"]
    assert fixed[2][0]["tool_call_id"] == "zzz"


@pytest.mark.asyncio
async def test_build_history_from_session_repairs_legacy_order():
    """A session persisted with the old (broken) order loads LLM-valid."""
    from broca.context import Context

    def _db_msg(payload, mid, tid=None):
        m = MagicMock()
        m.message_id = mid
        m.is_truncated = False
        m.is_expired = False
        from broca.session import MessageType

        if payload["role"] == "tool":
            m.message_type = MessageType.TOOL_CALL
            m.data = {
                "content": __import__("json").dumps(
                    {"role": "tool", "tool_call_id": tid, "content": "ok"}
                ),
                "arguments": {},
                "tool_name": "f",
                "status": "success",
            }
        else:
            m.message_type = MessageType.USER_MESSAGE
            m.data = {"content": __import__("json").dumps(payload)}
        return m

    assistant_payload = _assistant(["c1", "c2"])[0]
    db_messages = [
        _db_msg(assistant_payload, "m_a"),
        _db_msg({"role": "tool"}, "m_c1", tid="c1"),
        _db_msg(IMAGE_EXTRA["llm_message"], "m_img"),
        _db_msg({"role": "tool"}, "m_c2", tid="c2"),
    ]

    agent_config = MagicMock()
    agent_config.workspace = "/tmp"
    agent_config.system_prompt_template = "You are a test agent."
    agent_config.environment = None
    agent_config.role_description = None
    agent_config.skills = []

    session_manager = MagicMock()
    session_manager.session_id = "s1"
    session_manager.get_messages = AsyncMock(return_value=db_messages)
    ctx = Context(agent_config=agent_config, session_manager=session_manager)

    await ctx.build_history_from_session("agent-1")

    roles = [m.get("role") for m in ctx.history[1:]]  # skip system prompt
    assert roles == ["assistant", "tool", "tool", "user"]
    assert ctx._message_db_ids[-1] == "m_img"
