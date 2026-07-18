"""
Tests for Task 2.3: MemoryTool execution
Plan: plans/memory-system-upgrade-plan.md

AC 1: "memory 工具只有 hint 一个可选参数（可为空）" — covered by test_tool.py
AC 2: "调用 memory 不阻塞主 Agent（异步）"
AC 3: "工具返回 'Memory extraction triggered' + hint 信息（如有）"
AC 4: "删除原 MemoryStore 类和 add/replace/remove 逻辑" — covered by test_tool.py
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from broca.tools.memory import MemoryTool
from broca.tools.tool import ToolCallContext, ToolResult, ToolStatus


class TestMemoryToolExecution:
    """验证 MemoryTool 的执行行为"""

    def setup_method(self):
        self.tool = MemoryTool()

    def _make_context(self, has_manager=True):
        """创建一个带有 persistent_memory_manager 的上下文"""
        context = MagicMock(spec=ToolCallContext)
        if has_manager:
            manager = MagicMock()
            manager.trigger_extraction = AsyncMock()
            context.persistent_memory_manager = manager
            context.agent = MagicMock()
            context.agent.persistent_memory_manager = manager
            context.agent.context = MagicMock()
            context.context = context.agent.context
        else:
            context.persistent_memory_manager = None
            context.agent = None
        return context

    def test_ac02_async_non_blocking(self):
        """AC 2: 调用 memory 不阻塞主 Agent（异步）"""
        context = self._make_context(has_manager=True)
        params = {"hint": "test hint"}

        import asyncio
        result = asyncio.run(self.tool._execute(params, context))

        assert result.status == ToolStatus.SUCCESS
        # Verify trigger_extraction was called
        manager = context.persistent_memory_manager
        manager.trigger_extraction.assert_called_once()

    def test_ac03_returns_trigger_message(self):
        """AC 3: 工具返回包含 'Memory extraction triggered' 的 JSON"""
        context = self._make_context(has_manager=True)
        params = {"hint": "test hint"}

        import asyncio
        result = asyncio.run(self.tool._execute(params, context))

        assert result.status == ToolStatus.SUCCESS
        content = json.loads(result.content)
        assert content["success"] is True
        assert "Memory extraction triggered" in content["message"]
        assert content["hint"] == "test hint"

    def test_ac03_returns_trigger_message_no_hint(self):
        """AC 3: 无 hint 时工具仍返回正确消息"""
        context = self._make_context(has_manager=True)
        params = {}

        import asyncio
        result = asyncio.run(self.tool._execute(params, context))

        assert result.status == ToolStatus.SUCCESS
        content = json.loads(result.content)
        assert content["success"] is True
        assert "hint" not in content

    def test_error_when_manager_missing(self):
        """AC: 当 manager 不可用时返回错误"""
        context = self._make_context(has_manager=False)
        params = {"hint": "test"}

        import asyncio
        result = asyncio.run(self.tool._execute(params, context))

        assert result.status == ToolStatus.ERROR
        content = json.loads(result.content)
        assert content["success"] is False
