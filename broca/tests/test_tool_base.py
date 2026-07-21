"""
Tool 基类单元测试

覆盖：
- ToolStatus 枚举
- ToolResult 创建
- ToolCallContext 创建
- Tool 基类接口方法（name, description, parameters, format, execute）
- 参数验证（validate_arguments）
- 结果后处理（_post_process_result）
"""

import json
import pytest

from broca.tools.tool import (
    Tool,
    ToolCallContext,
    ToolResult,
    ToolStatus,
)


class TestToolStatus:
    """测试 ToolStatus 枚举"""

    def test_enum_values(self):
        """测试枚举值"""
        assert ToolStatus.SUCCESS.value == "success"
        assert ToolStatus.ERROR.value == "error"

    def test_enum_members(self):
        """测试枚举成员"""
        assert ToolStatus.SUCCESS.name == "SUCCESS"
        assert ToolStatus.ERROR.name == "ERROR"


class TestToolResult:
    """测试 ToolResult 类"""

    def test_create_success_result(self):
        """创建成功结果"""
        result = ToolResult(status=ToolStatus.SUCCESS, content="Operation completed")
        assert result.status == ToolStatus.SUCCESS
        assert result.content == "Operation completed"

    def test_create_error_result(self):
        """创建错误结果"""
        result = ToolResult(status=ToolStatus.ERROR, content="Something went wrong")
        assert result.status == ToolStatus.ERROR
        assert result.content == "Something went wrong"

    def test_to_dict(self):
        """测试 to_dict 方法"""
        result = ToolResult(status=ToolStatus.SUCCESS, content="ok")
        d = result.to_dict()
        assert d["status"] == ToolStatus.SUCCESS
        assert d["content"] == "ok"


class TestToolCallContext:
    """测试 ToolCallContext 类"""

    def test_create_context(self):
        """创建上下文并设置属性"""
        ctx = ToolCallContext()
        ctx.agent = "agent-1"
        ctx.workspace = "/tmp/workspace"
        ctx.session_id = "session-1"
        ctx.execution_id = "exec-1"
        ctx.namespace = "test"

        assert ctx.agent == "agent-1"
        assert ctx.workspace == "/tmp/workspace"
        assert ctx.session_id == "session-1"
        assert ctx.execution_id == "exec-1"
        assert ctx.namespace == "test"

    def test_context_defaults(self):
        """测试默认值"""
        ctx = ToolCallContext()
        assert ctx.agent is None
        assert ctx.workspace is None
        assert ctx.session_id is None
        assert ctx.execution_id is None
        assert ctx.namespace is None


# ── 辅助测试用 Tool 子类 ──────────────────────────


class SimpleTool(Tool):
    """简单工具，无参数"""

    @property
    def name(self) -> str:
        return "simple_tool"

    @property
    def description(self) -> str:
        return "A simple test tool"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}


class FailingTool(Tool):
    """总是失败的工具"""

    @property
    def name(self) -> str:
        return "failing_tool"

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        raise RuntimeError("Intentional failure")


class ParametrizedTool(Tool):
    """带参数的工具"""

    @property
    def name(self) -> str:
        return "param_tool"

    @property
    def description(self) -> str:
        return "A tool with parameters"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name parameter"},
                "count": {"type": "integer", "description": "Count parameter"},
            },
            "required": ["name"],
        }

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        return ToolResult(
            status=ToolStatus.SUCCESS,
            content=f"Got name={arguments.get('name')}, count={arguments.get('count')}",
        )


class SimpleImplementingTool(Tool):
    """实现了 _execute 的简单工具"""

    @property
    def name(self) -> str:
        return "impl_tool"

    async def _execute(self, arguments: dict, context: ToolCallContext) -> ToolResult:
        return ToolResult(status=ToolStatus.SUCCESS, content="executed")


class TestToolBase:
    """测试 Tool 基类"""

    @pytest.mark.asyncio
    async def test_tool_execute_success(self):
        """测试工具执行成功"""
        tool = SimpleImplementingTool()
        ctx = ToolCallContext()
        result = await tool.execute(arguments="{}", context=ctx)
        assert result.status == ToolStatus.SUCCESS
        assert result.content == "executed"

    @pytest.mark.asyncio
    async def test_tool_execute_error(self):
        """测试工具执行失败"""
        tool = FailingTool()
        ctx = ToolCallContext()
        result = await tool.execute(arguments="{}", context=ctx)
        assert result.status == ToolStatus.ERROR
        assert "Intentional failure" in result.content

    @pytest.mark.asyncio
    async def test_tool_with_parameters(self):
        """测试带参数的工具"""
        tool = ParametrizedTool()
        ctx = ToolCallContext()
        args = json.dumps({"name": "test", "count": 5})
        result = await tool.execute(arguments=args, context=ctx)
        assert result.status == ToolStatus.SUCCESS
        assert "test" in result.content
        assert "5" in result.content

    @pytest.mark.asyncio
    async def test_missing_required_parameter(self):
        """测试缺少必需参数"""
        tool = ParametrizedTool()
        ctx = ToolCallContext()
        result = await tool.execute(arguments="{}", context=ctx)
        assert result.status == ToolStatus.ERROR
        assert "Missing required parameter" in result.content

    @pytest.mark.asyncio
    async def test_tool_name_and_description(self):
        """测试工具名称和描述"""
        tool = SimpleTool()
        assert tool.name == "simple_tool"
        assert tool.description == "A simple test tool"
        assert tool.parameters is not None

    def test_tool_parameters_schema(self):
        """测试工具参数 schema"""
        tool = ParametrizedTool()
        assert "name" in tool.parameters["properties"]
        assert "count" in tool.parameters["properties"]
        assert "name" in tool.parameters["required"]

    def test_format_method(self):
        """测试 format 方法"""
        tool = SimpleTool()
        formatted = tool.format()
        assert formatted["type"] == "function"
        assert formatted["function"]["name"] == "simple_tool"
        assert formatted["function"]["description"] == "A simple test tool"
        assert "parameters" in formatted["function"]

    def test_validate_arguments_required(self):
        """测试参数验证 - 必需参数"""
        tool = ParametrizedTool()
        error = tool.validate_arguments({"name": "test"})
        assert error is None  # name 存在

        error = tool.validate_arguments({})
        assert error is not None
        assert "name" in error

    @pytest.mark.asyncio
    async def test_invalid_json_arguments(self):
        """测试无效的 JSON 参数"""
        tool = SimpleImplementingTool()
        ctx = ToolCallContext()
        result = await tool.execute(arguments="not valid json", context=ctx)
        assert result.status == ToolStatus.ERROR
        assert "Invalid JSON" in result.content

    def test_post_process_truncation(self):
        """测试结果后处理截断 - 原始内容被截断且添加了截断提示"""
        tool = SimpleTool(max_content_length=10)
        original = "Hello World! This is a long content"
        result = ToolResult(status=ToolStatus.SUCCESS, content=original)
        processed = tool._post_process_result(result)
        # 原始内容被截断：只保留前后各一半
        half = tool.max_content_length // 2
        assert processed.content.startswith(original[:half])
        assert "..." in processed.content
        assert "truncated" in processed.content

    def test_post_process_short_content(self):
        """测试短内容不会被截断"""
        tool = SimpleTool(max_content_length=100)
        result = ToolResult(status=ToolStatus.SUCCESS, content="Short")
        processed = tool._post_process_result(result)
        assert processed.content == "Short"
