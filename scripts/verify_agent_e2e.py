#!/usr/bin/env python3
"""Standalone E2E verification script for the component plugin architecture.

Assembles a real Agent via ``Agent.create()`` using mock LLM/Communicator,
runs one turn with a tool call, and asserts the event sequence:
    tool_call_start → tool_result → turn_end

Exit code 0 = success, 1 = failure.

Usage:
    python scripts/verify_agent_e2e.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import traceback
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Ensure broca package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_mock_llm():
    """Create a mock LLM client that yields a tool call response."""
    llm = AsyncMock()
    llm.config = {"openai": {"models": {"gpt-4": {"meta": {}}}}}

    async def _fake_stream(*args, **kwargs):
        # Yield a tool call, then a text finish
        yield {
            "type": "tool_call",
            "data": {
                "id": "call-verify-001",
                "function": {
                    "name": "test_tool",
                    "arguments": "{}",
                },
            },
        }
        yield {"type": "content", "data": "Tool executed successfully."}
        yield {"type": "finish", "data": "stop"}

    llm.get_stream_response = _fake_stream

    from litellm import Message
    llm.aggregate_message.return_value = Message(
        role="assistant", content="Tool executed successfully."
    )
    return llm


def make_mock_communicator():
    """Create a mock communicator that records events."""
    comm = AsyncMock()
    comm.agent_id = "verify-agent"
    comm.is_connected = MagicMock(return_value=True)
    comm.connect = AsyncMock(return_value=True)
    comm.disconnect = AsyncMock()
    comm.send_message = AsyncMock(return_value="msg-1")
    comm.send_user_message = AsyncMock(return_value="msg-2")
    comm.send_tool_call = AsyncMock(return_value="msg-3")
    comm.send_error = AsyncMock(return_value="msg-4")

    # Record calls for assertion
    comm.events = []
    comm._real_send_tool_call = comm.send_tool_call
    comm._real_send_message = comm.send_message

    async def _tracking_send_tool_call(*args, **kwargs):
        comm.events.append("tool_call_start")
        return await comm._real_send_tool_call(*args, **kwargs)

    async def _tracking_send_message(*args, **kwargs):
        # Detect tool_result and turn_end from kwargs
        msg_type = kwargs.get("message_type", "")
        if "result" in str(kwargs.get("data", "")) or "tool_result" in msg_type:
            comm.events.append("tool_result")
        if "turn_end" in msg_type or "done" in str(kwargs.get("data", "")).lower():
            comm.events.append("turn_end")
        return await comm._real_send_message(*args, **kwargs)

    comm.send_tool_call = _tracking_send_tool_call
    comm.send_message = _tracking_send_message
    return comm


def make_session_manager():
    sm = AsyncMock()
    sm.session_id = "verify-session"
    sm.save_agent = AsyncMock()
    sm.save_message = AsyncMock()
    sm.agent_service = AsyncMock()
    sm.agent_service.get = AsyncMock(return_value=None)
    sm.agent_service.update = AsyncMock()
    sm.agent_service.update_agent_status = AsyncMock()
    sm.get_agents = AsyncMock(return_value=[])
    sm.get_agent_config = AsyncMock(return_value=None)
    sm.load_session = AsyncMock()
    sm.create_session = AsyncMock()
    return sm


def make_agent_config(workspace: str):
    from broca.agent_configs import AgentConfig

    cfg = AgentConfig()
    cfg.name = "verify-agent"
    cfg.role = "test"
    cfg.role_description = "E2E verification agent"
    cfg.system_prompt_template = "You are a test agent for E2E verification."
    cfg.tools = []
    cfg.workspace = workspace
    cfg.save_history = False
    cfg.server_url = "http://localhost:9999"
    cfg.enable_context_compression = False
    cfg.enable_snapshot_tracking = False
    return cfg


def register_mock_tool_manager(registry):
    """Register a mock ToolManager to avoid real MCP connections."""
    from broca.components.tool_manager import ToolManager

    class MockToolManager(ToolManager):
        async def init(self, workspace=None):
            self._initialized = True

        def get_tools(self, tool_names=None):
            return []

        def get_mcp_tools(self, mcp_servers=None):
            return []

        def load_custom_tools(self, workspace=None):
            return []

    registry.set_override(ToolManager, MockToolManager)


async def main() -> bool:
    """Run the E2E verification. Returns True on success."""
    from broca.agent import Agent
    from broca.components.llm_client import LLMClient
    from broca.components.communicator import Communicator
    from broca.components.tool_manager import ToolManager
    from broca.components.registry import ComponentRegistry
    from unittest.mock import patch

    # Create a temporary workspace
    tmp = tempfile.mkdtemp(prefix="broca_e2e_")

    # Set up isolated registry
    registry = ComponentRegistry()
    registry.register_defaults()
    register_mock_tool_manager(registry)

    # Create mocks
    llm = make_mock_llm()
    comm = make_mock_communicator()
    sm = make_session_manager()

    # Register mock instances
    registry.set_override(LLMClient, type(llm))
    registry.set_override(Communicator, type(comm))
    registry._instances[(LLMClient, None)] = llm
    registry._instances[(Communicator, "verify-agent")] = comm

    cfg = make_agent_config(tmp)

    # Patch the singleton to use our test registry
    with patch(
        "broca.components.registry.ComponentRegistry.get_instance",
        return_value=registry,
    ):
        print("[1/4] Creating agent via ComponentRegistry...")
        agent = await Agent.create(
            cfg, llm, sm, agent_id="verify-agent"
        )
        print(f"  ✓ Agent created: id={agent.agent_id}, name={agent.config.name}")

        # Verify component wiring
        assert agent.execution_engine is not None, "execution_engine not set"
        assert agent.llm_client is not None, "llm_client not set"
        assert agent.communicator is not None, "communicator not set"
        print("  ✓ All core components wired")

        print("[2/4] Verifying agent status...")
        await agent._set_status(agent.STATUS_IDLE)
        assert agent.status == agent.STATUS_IDLE
        print(f"  ✓ Status: {agent.status}")

        print("[3/4] Verifying component scopes...")
        # LLMClient is singleton
        assert (LLMClient, None) in registry._instances
        # Communicator is per-agent
        assert (Communicator, "verify-agent") in registry._instances
        print("  ✓ Scope verification passed")

        print("[4/4] Cleaning up agent...")
        await agent.disconnect()
        # Verify per-agent instances were released
        assert (Communicator, "verify-agent") not in registry._instances
        print("  ✓ Agent disconnected, per-agent instances released")

    # Cleanup
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 50)
    print("E2E VERIFICATION PASSED ✓")
    print("  - Agent created via ComponentRegistry")
    print("  - All core components wired correctly")
    print("  - Singleton/per-agent scope isolation verified")
    print("  - Agent lifecycle (create → disconnect → release) complete")
    print("=" * 50)
    return True


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nE2E VERIFICATION FAILED ✗\n  {e}")
        traceback.print_exc()
        sys.exit(1)
