"""
持久化记忆 MemoryTool 测试
"""

from broca.tools.memory import MemoryTool


class TestMemoryTool:
    def test_tool_name(self):
        tool = MemoryTool()
        assert tool.name == "memory"

    def test_tool_parameters(self):
        tool = MemoryTool()
        params = tool.parameters
        assert params["type"] == "object"
        props = params["properties"]
        assert "hint" in props
        # Old parameters should not exist
        assert "action" not in props
        assert "target" not in props
        assert "content" not in props
        assert "old_text" not in props

    def test_hint_is_optional(self):
        tool = MemoryTool()
        params = tool.parameters
        required = params.get("required", [])
        assert "hint" not in required  # hint is optional

    def test_tool_description_has_trigger_semantics(self):
        tool = MemoryTool()
        desc = tool.description.lower()
        assert "trigger" in desc or "extraction" in desc or "save" in desc
        # Should not mention add/replace/remove
        assert "add" not in tool.parameters["properties"]
