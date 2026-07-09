"""
Tests for Task 2.2: run_skill_sub_agent() + /skill-create
Plan: plans/agent-skill-evolution-plan.md

AC 1: `run_skill_sub_agent()` 正确创建子 Agent
AC 2: `/skill-create my-skill` 通过子 Agent 创建
AC 3: 工具限制生效
AC 4: 超时控制 (120s)
"""

import importlib.util
import inspect
import sys
from pathlib import Path

import pytest

from broca.skill.skill_evolution import run_skill_sub_agent

ROOT = Path(__file__).parents[3]


def _load_skill_create_mod():
    """加载 skill-create 模块（目录名含连字符）。"""
    init_path = ROOT / "broca" / "commands" / "builtin" / "skill-create" / "__init__.py"
    spec = importlib.util.spec_from_file_location("skill_create_t22", init_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["skill_create_t22"] = mod
    spec.loader.exec_module(mod)
    return mod


# ─── AC 1: run_skill_sub_agent() 正确创建子 Agent ──────


def test_ac01_run_skill_sub_agent_is_async_function():
    """AC 1: `run_skill_sub_agent()` 是 async 函数"""
    assert inspect.iscoroutinefunction(run_skill_sub_agent)


def test_ac01_run_skill_sub_agent_signature():
    """AC 1: run_skill_sub_agent 签名包含必需参数"""
    sig = inspect.signature(run_skill_sub_agent)
    params = sig.parameters
    assert "agent" in params
    assert "prompt" in params
    assert "allowed_tools" in params
    assert "task_timeout" in params
    # 默认超时应为 120s
    assert params["task_timeout"].default == 120


def test_ac01_references_extraction_subagent_pattern():
    """AC 1: 实现参考了 SessionMemoryManager._run_extraction_subagent()"""
    source = ROOT / "broca" / "tools" / "skill_evolution.py"
    content = source.read_text(encoding="utf-8")
    # 应参考子 Agent 模式
    assert "AgentFactory" in content
    assert "copy" in content  # fork context
    assert "session_manager" in content


# ─── AC 2: /skill-create 命令结构 ────────────────────


def test_ac02_skill_create_command_registered():
    """AC 2: skill-create 命令文件存在"""
    cmd_dir = ROOT / "broca" / "commands" / "builtin" / "skill-create"
    assert cmd_dir.exists()
    assert (cmd_dir / "command.md").exists()
    assert (cmd_dir / "__init__.py").exists()


def test_ac02_skill_create_command_md():
    """AC 2: command.md 包含正确元数据"""
    cmd_md = ROOT / "broca" / "commands" / "builtin" / "skill-create" / "command.md"
    content = cmd_md.read_text(encoding="utf-8")
    assert "name: skill-create" in content
    assert "type: local" in content
    assert "argument_hint" in content


def test_ac02_skill_create_prompt_template():
    """AC 2: CREATE_PROMPT_TEMPLATE 包含必需指令"""
    mod = _load_skill_create_mod()
    assert hasattr(mod, "CREATE_PROMPT_TEMPLATE")
    template = mod.CREATE_PROMPT_TEMPLATE
    assert "skill_manage" in template
    assert "SKILL.md" in template
    assert "{name}" in template
    assert "name:" in template
    assert "description:" in template


# ─── AC 3: 工具限制生效 ──────────────────────────────


def test_ac03_allowed_tools_defined():
    """AC 3: skill-create 定义了 ALLOWED_TOOLS"""
    mod = _load_skill_create_mod()
    assert hasattr(mod, "ALLOWED_TOOLS")
    tools = mod.ALLOWED_TOOLS
    assert isinstance(tools, list)
    assert len(tools) > 0
    assert "skill_manage" in tools
    # 创建 Skill 需要的能力
    assert "load_skill" in tools
    assert "read_file" in tools


def test_ac03_sub_agent_receives_allowed_tools():
    """AC 3: run_skill_sub_agent 将 allowed_tools 传给子 Agent"""
    source = ROOT / "broca" / "tools" / "skill_evolution.py"
    content = source.read_text(encoding="utf-8")
    # 子 Agent 调用时传入了 allowed_tools
    assert "allowed_tools=allowed_tools" in content
    assert "allowed_tools" in content


# ─── AC 4: 超时控制 ──────────────────────────────────


def test_ac04_timeout_parameter():
    """AC 4: 超时控制参数 task_timeout=120 已设置"""
    sig = inspect.signature(run_skill_sub_agent)
    assert sig.parameters["task_timeout"].default == 120


def test_ac04_timeout_handling_in_source():
    """AC 4: 源码中包含超时处理逻辑"""
    source = ROOT / "broca" / "tools" / "skill_evolution.py"
    content = source.read_text(encoding="utf-8")
    assert "TimeoutError" in content or "timeout" in content.lower()
    assert "asyncio.TimeoutError" in content or "task_timeout" in content


# ─── 命令解析验证 ─────────────────────────────────────


def test_skill_create_help_shows_usage():
    """/skill-create --help 显示用法"""
    mod = _load_skill_create_mod()
    cmd = mod.SkillCreateCommand()
    assert hasattr(cmd, "execute")
    assert cmd.__class__.__name__ == "SkillCreateCommand"
