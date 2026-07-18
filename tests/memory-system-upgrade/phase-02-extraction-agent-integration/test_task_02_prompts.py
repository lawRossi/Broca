"""
Tests for Task 2.2: Extraction Prompts
Plan: plans/memory-system-upgrade-plan.md

AC 1: "Prompt 指示 agent 加载 persistent-memory-extraction skill"
AC 2: "Prompt 中要求检查现有记忆清单避免重复"
AC 3: "Prompt 中包含现有记忆清单"
AC 4: "有 hint 时，prompt 中体现 hint 指示"
AC 5: "Prompt 中提示 load_skill 工具可用"
AC 6: "Prompt 中强调禁止 write_file 覆盖已有文件"
"""

from broca.persistent_memory.prompts import build_extraction_prompt


class TestExtractionPromptContent:
    """验证提取 prompt 的内容完整性"""

    def test_ac01_instructs_to_load_skill(self):
        """AC 1: Prompt 指示 agent 加载 persistent-memory-extraction skill"""
        prompt = build_extraction_prompt(existing_index_content="", hint=None)

        assert "load_skill" in prompt, "Should mention load_skill tool"
        assert "persistent-memory-extraction" in prompt, "Should reference the skill name"
        assert "First step" in prompt.lower() or "load" in prompt.lower(), "Should instruct to load skill first"

    def test_ac02_mentions_skill_contains_rules(self):
        """AC 2: Prompt 说明 skill 中包含详细规则"""
        prompt = build_extraction_prompt(existing_index_content="", hint=None)

        assert "detailed rules" in prompt.lower() or \
               "all the detailed" in prompt.lower(), "Should mention skill has detailed rules"
        assert "Follow the skill" in prompt, "Should instruct to follow the skill"

    def test_ac03_includes_existing_index(self):
        """AC 3: Prompt 中包含现有记忆清单"""
        index_content = "- [test_mem](test_mem.md) — test description (2025-06-15)"
        prompt = build_extraction_prompt(
            existing_index_content=index_content, hint=None
        )

        assert "Existing Memory Index" in prompt
        assert "test_mem" in prompt
        assert "update an existing file rather than creating a duplicate" in prompt

    def test_ac03_empty_index_shows_empty_message(self):
        """AC 3: 索引为空时有明确提示"""
        prompt = build_extraction_prompt(existing_index_content="", hint=None)

        assert "existing memory index is currently empty" in prompt.lower() or \
               "memory index is currently empty" in prompt.lower()

    def test_ac04_includes_hint_when_provided(self):
        """AC 4: 有 hint 时，prompt 中体现 hint 指示"""
        hint = "User prefers concise responses"
        prompt = build_extraction_prompt(existing_index_content="", hint=hint)

        assert "Priority Instruction" in prompt
        assert hint in prompt
        assert "focus on" in prompt.lower()

    def test_ac04_no_hint_when_not_provided(self):
        """AC 4: 无 hint 时，不应包含 Priority Instruction 头部"""
        prompt = build_extraction_prompt(existing_index_content="", hint=None)

        assert "Priority Instruction" not in prompt

    def test_ac05_mentions_load_skill_tool(self):
        """AC 5: Prompt 中提示 load_skill 工具可用"""
        prompt = build_extraction_prompt(existing_index_content="", hint=None)

        assert "load_skill" in prompt, "Should mention load_skill in tools section"
        assert "Skill tools:" in prompt or "load_skill" in prompt, "Should list load_skill as available"

    def test_ac06_forbids_write_file_on_existing(self):
        """AC 6: Prompt 中强调禁止 write_file 覆盖已有文件"""
        prompt = build_extraction_prompt(existing_index_content="", hint=None)

        assert "Do NOT use `write_file` on existing files" in prompt
        assert "always use `edit_file`" in prompt

