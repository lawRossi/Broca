"""Shared test fixtures for component-based testing.

These fixtures provide a consistent mock/stub environment for all
component tests across all phases.  They are auto-discovered by pytest
when running tests under ``broca/tests/``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_workspace(tmp_path):
    """Temporary directory as workspace root."""
    return str(tmp_path)


@pytest.fixture
def fresh_registry():
    """A fresh ``ComponentRegistry`` instance with ``reset()`` on teardown.

    Ensures each test gets a clean registry state (no cached instances,
    no overrides, no discovered plugins) from previous tests.
    """
    from broca.components.registry import ComponentRegistry

    reg = ComponentRegistry()
    reg.register_defaults()
    yield reg
    reg.reset()


@pytest.fixture
def mock_communicator() -> AsyncMock:
    """AsyncMock implementing the ``Communicator`` interface.

    All send_* methods return a fake message ID.
    """
    comm = AsyncMock()
    comm.agent_id = "test-agent"
    comm.is_connected.return_value = True
    comm.send_message.return_value = "msg-001"
    comm.send_user_message.return_value = "msg-002"
    comm.send_tool_call.return_value = "msg-003"
    comm.send_error.return_value = "msg-004"
    comm.connect.return_value = True
    return comm


@pytest.fixture
def mock_llm_client() -> AsyncMock:
    """AsyncMock implementing the ``LLMClient`` interface.

    Returns a predefined streaming response (content chunk + finish).
    ``aggregate_message`` returns a simple LLMMessage-like dict.
    """
    llm = AsyncMock()

    # Streaming response: yield content, then finish
    async def _fake_stream(*args, **kwargs):
        yield {"type": "content", "data": "Hello from mock LLM"}
        yield {"type": "finish", "data": "stop"}

    llm.get_stream_response = _fake_stream

    # aggregate_message returns a simple object
    from litellm import Message as LLMMessage

    mock_msg = LLMMessage(
        role="assistant",
        content="Hello from mock LLM",
    )
    llm.aggregate_message.return_value = mock_msg
    llm.config = {"openai": {"models": {"gpt-4": {"meta": {}}}}}
    return llm


@pytest.fixture
def mock_permission_provider() -> AsyncMock:
    """AsyncMock implementing the ``PermissionProvider`` interface.

    Default behavior: all tools are "allow".
    Can be reconfigured per test for "ask" or "forbidden" scenarios.
    """
    pp = AsyncMock()
    pp.get_permission.return_value = "allow"
    pp.request_permission.return_value = True
    pp.request_tool_permission.return_value = (True, None)
    return pp


@pytest.fixture
def test_context():
    """Minimal ``Context`` instance with an empty message list."""
    from broca.context import Context

    ctx = Context()
    ctx.history = []
    return ctx


@pytest.fixture
def test_tool():
    """Simple test ``Tool`` subclass that returns a fixed result."""
    from broca.tools.tool import Tool, ToolResult, ToolStatus

    class _TestTool(Tool):
        @property
        def name(self) -> str:
            return "test_tool"

        @property
        def description(self) -> str:
            return "A test tool"

        @property
        def parameters(self) -> dict:
            return {"type": "object", "properties": {}}

        async def _execute(self, arguments: dict, context) -> ToolResult:
            return ToolResult(
                status=ToolStatus.SUCCESS,
                content="test result",
            )

    return _TestTool()


# ---------------------------------------------------------------------------
# Async test helper
# ---------------------------------------------------------------------------


def run_async(coro):
    """Run an async coroutine in a new event loop (for sync test functions)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# GitManager snapshot 仓库清理
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cleanup_git_manager_instances():
    """测试结束后清理 GitManager 单例及其 snapshot 仓库目录。

    测试使用 tempfile.TemporaryDirectory() 作为 workspace，
    GitManager.initialize() 会在 ~/.broca/snapshots/<hash>/ 创建仓库。
    tempfile 只清理 workspace 目录本身，snapshot 仓库会残留。
    此 fixture 在每个测试后统一清理，防止孤儿目录累积。
    """
    yield

    from broca.snapshot.git_manager import GitManager

    for _ws, gm in list(GitManager._instances.items()):
        try:
            gm.cleanup()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Session Runner IPC socket 清理
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _cleanup_runner_ipc_sockets():
    """测试结束后清理 tempdir 下的 ``broca_runner_*.sock`` 残留。

    IPC 测试会真实 bind AF_UNIX socket；用例失败/被中断时 ``close()`` 可能没跑到，
    残留文件会让后续用例在 ``Listener`` 处抛 ``EADDRINUSE``（P0-4 的同款症状），
    表现为难以定位的连锁失败。这里做统一兜底清理。
    """
    import glob
    import os
    import tempfile

    yield

    pattern = os.path.join(tempfile.gettempdir(), "broca_runner_*.sock")
    for path in glob.glob(pattern):
        try:
            os.unlink(path)
        except OSError:
            pass
