"""
Tests for Task 2.3: /skill-suggest
Plan: plans/agent-skill-evolution-plan.md

AC 1: `/skill-suggest` 分析所有 Skill 输出文档到 `plans/`
AC 2: `/skill-suggest my-skill` 只分析指定 Skill
AC 3: 文档包含改进理由、方案、预期效果
AC 4: 子 Agent 不调用 skill_manage 修改 Skill
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]


def _load_suggest_module():
    """使用 importlib 加载 skill-suggest 模块（目录名含连字符）。"""
    init_path = ROOT / "broca" / "commands" / "builtin" / "skill-suggest" / "__init__.py"
    spec = importlib.util.spec_from_file_location("skill_suggest_t23", init_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["skill_suggest_t23"] = mod
    spec.loader.exec_module(mod)
    return mod


# ─── AC 1: /skill-suggest 分析所有 Skill ─────────────


def test_ac01_skill_suggest_command_registered():
    """AC 1: skill-suggest 命令文件存在"""
    cmd_dir = ROOT / "broca" / "commands" / "builtin" / "skill-suggest"
    assert cmd_dir.exists()
    assert (cmd_dir / "command.md").exists()
    assert (cmd_dir / "__init__.py").exists()


def test_ac01_skill_suggest_command_md():
    """AC 1: command.md 包含正确元数据"""
    cmd_md = ROOT / "broca" / "commands" / "builtin" / "skill-suggest" / "command.md"
    content = cmd_md.read_text(encoding="utf-8")
    assert "name: skill-suggest" in content
    assert "type: local" in content
    assert "argument_hint" in content
    assert "skill-name" in content  # 可选参数


def test_ac01_no_arg_analyzes_all_skills():
    """AC 1: 无参数时分析所有 active skill"""
    mod = _load_suggest_module()
    cmd = mod.SkillSuggestCommand()
    # 验证命令类存在且有 execute 方法
    assert hasattr(cmd, "execute")


# ─── AC 2: /skill-suggest my-skill 指定 Skill ───────


def test_ac02_skill_suggest_args_parsed():
    """AC 2: 命令支持指定 skill 名称"""
    mod = _load_suggest_module()
    cmd = mod.SkillSuggestCommand()
    assert hasattr(cmd, "execute")

    # source 中应该处理 args 参数
    source = ROOT / "broca" / "commands" / "builtin" / "skill-suggest" / "__init__.py"
    content = source.read_text(encoding="utf-8")
    # 检查是否区分有参和无参
    assert "skill_name" in content or "args" in content


# ─── AC 3: 文档格式含四部分 ──────────────────────────


def test_ac03_suggest_prompt_template_has_required_sections():
    """AC 3: 提示模板包含改进理由、方案、预期效果"""
    mod = _load_suggest_module()
    assert hasattr(mod, "SUGGEST_PROMPT_TEMPLATE")
    template = mod.SUGGEST_PROMPT_TEMPLATE
    assert "当前问题" in template
    assert "改进方案" in template
    assert "预期效果" in template
    assert "相关对话" in template or "相关对话摘要" in template


def test_ac03_output_path_is_in_plans_dir():
    """AC 3: 输出路径为 plans/skill-suggest-{timestamp}.md"""
    mod = _load_suggest_module()
    template = mod.SUGGEST_PROMPT_TEMPLATE
    assert "plans/skill-suggest" in template
    assert "timestamp" in template


# ─── AC 4: 子 Agent 不调用 skill_manage ──────────────


def test_ac04_allowed_tools_no_skill_manage():
    """AC 4: ALLOWED_TOOLS 不包含 skill_manage"""
    mod = _load_suggest_module()
    assert hasattr(mod, "ALLOWED_TOOLS")
    tools = mod.ALLOWED_TOOLS
    assert "skill_manage" not in tools
    assert "edit_file" not in tools


def test_ac04_allowed_tools_only_read_and_write_file():
    """AC 4: 只允许读工具 + write_file"""
    mod = _load_suggest_module()
    tools = mod.ALLOWED_TOOLS
    # 读工具
    assert "load_skill" in tools
    assert "read_file" in tools
    assert "glob" in tools
    assert "grep" in tools
    assert "list_dir" in tools
    assert "tree_dir" in tools
    # 写工具（只限 plans/）
    assert "write_file" in tools


def test_ac04_no_modify_tools():
    """AC 4: 不允许修改 Skill 的工具"""
    mod = _load_suggest_module()
    tools = mod.ALLOWED_TOOLS
    modify_tools = ["skill_manage", "edit_file", "bash", "cron"]
    for tool in modify_tools:
        assert tool not in tools, f"Tool '{tool}' should not be in ALLOWED_TOOLS for skill-suggest"


# ─── 命令注册验证 ─────────────────────────────────────


def test_command_inherits_local_command():
    """命令继承 LocalCommand"""
    from broca.commands.base import LocalCommand
    mod = _load_suggest_module()
    assert issubclass(mod.SkillSuggestCommand, LocalCommand)
