"""
Regression tests for ToolResult.error_info structured error preservation.

Verifies that:
1. Tool.execute() catches BrocaError → result.error_info is set
2. Non-BrocaError exceptions → result.error_info remains None
3. ToolResult.to_dict() includes error_info when present
"""

import json
from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest

from broca.errors import BrocaError, ErrorCode, ToolError
from broca.tools.tool import Tool, ToolCallContext, ToolResult, ToolStatus


class _TestErrorTool(Tool):
    """A tool that raises a BrocaError."""

    @property
    def name(self) -> str:
        return "test_error_tool"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def _execute(self, args: dict, context: ToolCallContext) -> ToolResult:
        raise ToolError("test tool failure", error_code=ErrorCode.TOOL_ERROR)


class _TestGenericErrorTool(Tool):
    """A tool that raises a non-BrocaError exception."""

    @property
    def name(self) -> str:
        return "test_generic_error_tool"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def _execute(self, args: dict, context: ToolCallContext) -> ToolResult:
        raise ValueError("some generic error")


class _TestSuccessTool(Tool):
    """A tool that succeeds."""

    @property
    def name(self) -> str:
        return "test_success_tool"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def _execute(self, args: dict, context: ToolCallContext) -> ToolResult:
        return ToolResult(status=ToolStatus.SUCCESS, content="ok")


class TestToolResultErrorInfo:
    """ToolResult.error_info behavior."""

    def test_error_info_none_by_default(self):
        """ToolResult without error_info defaults to None."""
        result = ToolResult(status=ToolStatus.SUCCESS, content="ok")
        assert result.error_info is None

    def test_error_info_set(self):
        """ToolResult can carry an ErrorInfo."""
        from broca.errors.types import ErrorInfo

        info = ErrorInfo(code=ErrorCode.TOOL_ERROR, message="test")
        result = ToolResult(
            status=ToolStatus.ERROR, content="err", error_info=info
        )
        assert result.error_info is info


class TestExecuteBrocaError:
    """Tool.execute() preserves BrocaError structured info."""

    @pytest.mark.asyncio
    async def test_broca_error_sets_error_info(self):
        """BrocaError → result.error_info is set with correct code."""
        tool = _TestErrorTool()
        context = ToolCallContext()

        result = await tool.execute("{}", context)

        assert result.status == ToolStatus.ERROR
        assert result.error_info is not None
        assert result.error_info.code == ErrorCode.TOOL_ERROR

    @pytest.mark.asyncio
    async def test_broca_error_content_is_user_message(self):
        """BrocaError → result.content uses to_user_message()."""
        tool = _TestErrorTool()
        context = ToolCallContext()

        result = await tool.execute("{}", context)

        assert "test tool failure" in result.content


class TestExecuteNonBrocaError:
    """Non-BrocaError exceptions don't set error_info (backward compatible)."""

    @pytest.mark.asyncio
    async def test_value_error_no_error_info(self):
        """ValueError → result.error_info is None."""
        tool = _TestGenericErrorTool()
        context = ToolCallContext()

        result = await tool.execute("{}", context)

        assert result.status == ToolStatus.ERROR
        assert result.error_info is None


class TestToolResultToDict:
    """ToolResult.to_dict() serialization includes error_info when present."""

    def test_to_dict_with_error_info(self):
        """to_dict() includes error_info field when set."""
        from broca.errors.types import ErrorInfo

        info = ErrorInfo(
            code=ErrorCode.TOOL_ERROR,
            message="test error",
            cause_msg="original cause",
        )
        result = ToolResult(
            status=ToolStatus.ERROR, content="err", error_info=info
        )
        d = result.to_dict()

        assert "error_info" in d
        assert d["error_info"]["code"] == "TOOL_ERROR"
        assert d["error_info"]["message"] == "test error"

    def test_to_dict_without_error_info(self):
        """to_dict() omits error_info when None."""
        result = ToolResult(status=ToolStatus.SUCCESS, content="ok")
        d = result.to_dict()

        assert "error_info" not in d
        assert d == {"status": result.status, "content": "ok"}


class TestSuccessTool:
    """Successful tool execution is unaffected."""

    @pytest.mark.asyncio
    async def test_success_no_error_info(self):
        """Successful execution → error_info is None."""
        tool = _TestSuccessTool()
        context = ToolCallContext()

        result = await tool.execute("{}", context)

        assert result.status == ToolStatus.SUCCESS
        assert result.error_info is None
