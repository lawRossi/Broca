"""
Tests for Task 3.3: LoopEngine 超时适配
Plan: plans/long-running-task-optimization-plan.md

AC 1: bash(code="...", background=True) 时 LoopEngine 不设外层超时
AC 2: 其他工具和其他 bash 调用不受影响
"""

import pytest

from broca.loop_engine import LoopEngine


class TestShouldSkipToolTimeout:
    """测试 _should_skip_tool_timeout 方法"""

    def setup_method(self):
        # 创建 LoopEngine 实例（不实际运行）
        self.engine = LoopEngine.__new__(LoopEngine)

    # ─── AC 1: background=True 时跳过超时 ─────────────────────

    def test_ac01_skip_timeout_for_bash_background(self):
        """AC 1: bash + background=True 应跳过超时"""
        result = self.engine._should_skip_tool_timeout(
            "bash",
            {"background": True, "code": "sleep 100"},
        )
        assert result is True, \
            "bash with background=True should skip timeout"

    # ─── AC 2: 其他情况不跳过 ─────────────────────────────────

    def test_ac02_dont_skip_for_bash_no_background(self):
        """AC 2a: bash + 无 background 不应跳过超时"""
        result = self.engine._should_skip_tool_timeout(
            "bash",
            {"code": "echo hello"},
        )
        assert result is False, \
            "bash without background should not skip timeout"

    def test_ac02_dont_skip_for_bash_background_false(self):
        """AC 2b: bash + background=False 不应跳过超时"""
        result = self.engine._should_skip_tool_timeout(
            "bash",
            {"code": "echo hello", "background": False},
        )
        assert result is False, \
            "bash with background=False should not skip timeout"

    def test_ac02_dont_skip_for_other_tools(self):
        """AC 2c: 其他工具不应跳过超时"""
        other_tools = [
            ("cron", {"action": "list_jobs"}),
            ("read_file", {"path": "/tmp/test"}),
            ("web_search", {"query": "test"}),
            ("web_fetch", {"url": "http://example.com"}),
            ("assign_task", {"task": "test"}),
        ]

        for tool_name, arguments in other_tools:
            result = self.engine._should_skip_tool_timeout(tool_name, arguments)
            assert result is False, \
                f"{tool_name} should not skip timeout"

    def test_ac02_dont_skip_for_empty_arguments(self):
        """AC 2d: 空参数不应跳过超时"""
        result = self.engine._should_skip_tool_timeout("bash", {})
        assert result is False, \
            "Empty arguments should not skip timeout"

    def test_ac02_dont_skip_for_none_arguments(self):
        """AC 2e: 非 dict 参数不应跳过超时"""
        result = self.engine._should_skip_tool_timeout("bash", None)
        assert result is False, \
            "None arguments should not skip timeout"
