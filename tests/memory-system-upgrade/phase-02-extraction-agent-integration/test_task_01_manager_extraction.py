"""
Tests for Task 2.1: PersistentMemoryManager Extraction Logic
Plan: plans/memory-system-upgrade-plan.md

AC 1: "check_and_extract() 在消息/步数未达阈值时直接返回"
AC 2: "check_and_extract() 在已达阈值且无提取进行中时触发子 Agent"
AC 3: "trigger_extraction() 跳过阈值检查直接触发"
AC 4: "提取执行中时新请求被跳过（不阻塞）"
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from broca.agent_configs import PersistentMemoryConfig
from broca.persistent_memory.state import PersistentMemoryState
from broca.persistent_memory.manager import PersistentMemoryManager


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.communicator = MagicMock()
    agent.communicator.send_agent_system_message = AsyncMock()
    agent.session_manager = MagicMock()
    agent.session_manager.session_id = "test-session-id"
    return agent


@pytest.fixture
def mock_context():
    context = MagicMock()
    context.history = []
    return context


class TestManagerThresholdLogic:
    """验证 PersistentMemoryManager 的自动提取阈值逻辑"""

    def setup_method(self):
        self.config = PersistentMemoryConfig(
            minimum_messages_to_init=50,
            minimum_messages_between_update=30,
            steps_between_updates=20,
        )

        # Mock agent with necessary attributes
        self.agent = MagicMock()
        self.agent.communicator = MagicMock()
        self.agent.communicator.send_agent_system_message = AsyncMock()
        self.agent.session_manager = MagicMock()
        self.agent.session_manager.session_id = "test-session-id"

        self.context = MagicMock()
        self.context.history = []

        with patch.object(Path, 'resolve', return_value=Path('/tmp/test_workspace/.broca/memories')):
            self.manager = PersistentMemoryManager(
                workspace="/tmp/test_workspace",
                agent=self.agent,
                config=self.config,
            )
            # Mock the store
            self.manager._store = MagicMock()

    def test_ac01_should_not_extract_below_threshold(self):
        """AC 1: 消息/步数未达阈值时 check_and_extract() 直接返回"""
        # Simulate few messages and steps
        self.context.history = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
        self.manager.state.step_count = 5

        result = self.manager._should_extract(self.context)
        assert result is False, "Should NOT extract with only 10 messages (threshold=50)"

    def test_ac02_should_extract_when_met_threshold(self):
        """AC 2: 已达阈值且无提取进行中时 should_extract 返回 True"""
        # Simulate enough messages and steps
        self.context.history = [{"role": "user", "content": f"msg {i}"} for i in range(60)]
        self.manager.state.step_count = 30
        self.manager.state.last_step_count = 0
        self.manager.state.last_message_index = 0

        # First call initializes
        assert self.manager._should_extract(self.context) is True

    def test_ac03_trigger_skips_threshold_check(self):
        """AC 3: trigger_extraction() 跳过阈值检查直接进入提取"""
        # Even with zero messages, trigger should attempt extraction
        self.context.history = []
        self.manager.state.step_count = 0

        # mock the internal trigger
        self.manager._trigger_internal = AsyncMock()

        import asyncio
        asyncio.run(self._test_trigger_no_block())

    async def _test_trigger_no_block(self):
        self.manager._trigger_internal = AsyncMock()
        await self.manager.trigger_extraction(self.context, hint="test hint")
        self.manager._trigger_internal.assert_awaited_once()

    def test_ac04_skip_when_extraction_in_progress(self):
        """AC 4: 提取进行中时新请求被跳过"""
        self.manager.state.extraction_in_progress = True
        self.context.history = [{"role": "user", "content": f"msg {i}"} for i in range(60)]

        # check_and_extract should return early
        import asyncio
        result = asyncio.run(self._test_skip_during_extraction())
        # If we got here without exception, the early return worked

    async def _test_skip_during_extraction(self):
        """Verify that extraction is skipped when already in progress"""
        self.manager._trigger_internal = AsyncMock()
        self.manager.state.extraction_in_progress = True
        await self.manager.check_and_extract(self.context)
        self.manager._trigger_internal.assert_not_awaited()
