"""
Tests for Task 3.1: 增强 bash 工具参数与描述
Plan: plans/long-running-task-optimization-plan.md

AC 1: 工具描述清晰说明 background 场景
AC 2: notify 参数可被 LLM 理解和调用
AC 3: 现有参数兼容
"""

import pytest

from broca.tools.bash import Bash


# ─── AC 1: 工具描述清晰说明 background 场景 ─────────────────────

def test_ac01_description_background_scenario():
    """AC 1: 工具描述清晰说明 background 场景"""
    bash = Bash()
    desc = bash.description

    # 必须包含 background 相关说明
    assert "background" in desc.lower(), "Description should mention 'background'"
    assert "long-running" in desc.lower() or "long running" in desc.lower(), \
        "Description should mention long-running commands"
    assert "timeout" in desc.lower(), "Description should mention timeout"


# ─── AC 2: notify 参数可被 LLM 理解和调用 ───────────────────────

def test_ac02_notify_parameter_exists():
    """AC 2a: notify 参数存在于 parameters 定义中"""
    bash = Bash()
    params = bash.parameters
    props = params.get("properties", {})

    assert "notify" in props, "notify parameter should be defined"

    notify_schema = props["notify"]
    assert notify_schema.get("type") == "boolean", \
        f"notify should be boolean, got {notify_schema.get('type')}"
    # 注意：JSON Schema 中没有 default 键，默认值在代码层面处理（notify: bool = False）
    assert "description" in notify_schema, \
        "notify should have description"


def test_ac02_notify_parameter_llm_understandable():
    """AC 2b: notify 参数的描述可让 LLM 理解其用途"""
    bash = Bash()
    params = bash.parameters
    notify_desc = params["properties"]["notify"]["description"]

    # 描述应说明 notify 的作用
    assert "notification" in notify_desc.lower() or "notify" in notify_desc.lower()
    assert "background" in notify_desc.lower() or "complete" in notify_desc.lower()


# ─── AC 3: 现有参数兼容 ─────────────────────────────────────────

def test_ac03_existing_parameters_compatible():
    """AC 3: 现有参数兼容，不破坏已有调用"""
    bash = Bash()
    params = bash.parameters
    props = params.get("properties", {})
    required = params.get("required", [])

    # 原有的 code 参数必须存在
    assert "code" in props, "code parameter must exist"
    assert "code" in required, "code must be in required fields"

    # 原有的 background 参数必须存在
    assert "background" in props, "background parameter must exist"
    assert props["background"]["type"] == "boolean", \
        "background should be boolean"

    # required 中不应有新增的参数（notify 不是 required）
    assert "notify" not in required, \
        "notify should not be required (backward compatibility)"
