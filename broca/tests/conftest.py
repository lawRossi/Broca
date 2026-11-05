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


@pytest.fixture(autouse=True)
def _reset_broca_config_cache():
    """每个测试前重置 BrocaConfig 单例缓存，防止测试间配置泄漏。

    确保 get_configs() 不会返回上一个测试（或模块导入时）缓存的配置实例。
    """
    from broca.configs import reset_configs_cache

    reset_configs_cache()
    yield
    reset_configs_cache()


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
    """测试结束后清理本测试进程创建的 ``broca_runner_*.sock`` 残留。

    IPC 测试会真实 bind AF_UNIX socket；用例失败/被中断时 ``close()`` 可能没跑到，
    残留文件会让后续用例在 ``Listener`` 处抛 ``EADDRINUSE``（P0-4 的同款症状），
    表现为难以定位的连锁失败。

    ⚠️ 只清理本进程创建的文件（通过 PID 标记），避免误删生产服务正在使用的
    IPC socket 导致 ``broca service`` 崩溃。
    """
    import os
    import tempfile

    # 本测试进程的 PID 作为标记前缀
    _my_pid = os.getpid()
    _tracked: list[str] = []

    # Monkey-patch tempfile.gettempdir 不可行（全局影响），改为记录测试创建的 socket
    # 通过 monkeypatch 在 IPCServer 创建时记录
    import broca.session_runner.transport.addresses as _addr_mod
    _orig_get_ipc_address = _addr_mod.get_ipc_address

    def _tracking_get_ipc_address(session_id: str) -> str:
        addr = _orig_get_ipc_address(session_id)
        if addr and addr.startswith(tempfile.gettempdir()):
            _tracked.append(addr)
        return addr

    _addr_mod.get_ipc_address = _tracking_get_ipc_address
    # transport/base.py 在构造时调用 get_ipc_address，需要同步 patch
    import broca.session_runner.transport.base as _transport_base
    _transport_base.get_ipc_address = _tracking_get_ipc_address

    yield

    # 恢复
    _addr_mod.get_ipc_address = _orig_get_ipc_address
    _transport_base.get_ipc_address = _orig_get_ipc_address

    # 只删除本测试进程跟踪到的 socket 文件
    for path in _tracked:
        try:
            os.unlink(path)
        except OSError:
            pass
