"""
Phase 3 集成测试: Bash 工具增强
Plan: plans/long-running-task-optimization-plan.md

Phase AC 1: npm run dev & 等带 & 的命令自动转为 background 模式走 Scheduler
Phase AC 2: 工具描述明确说明使用 background 的场景
Phase AC 3: 新增 notify 参数（默认 False），控制是否接收进程结束通知
Phase AC 4: 非 background 命令保持原有超时杀进程行为不变
Phase AC 5: LoopEngine 对 background 和长时间运行的 bash 调用不做外层超时拦截
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from broca.tools.bash import Bash
from broca.loop_engine import LoopEngine


# ─── Phase AC 1: & 自动转 background ───────────────────────────

@pytest.mark.asyncio
async def test_phase_ac01_ampersand_auto_background():
    """Phase AC 1: & 命令自动转为 background 模式走 Scheduler"""
    bash = Bash()

    with patch.object(bash, '_run_background', new_callable=AsyncMock) as mock_bg:
        with patch.object(bash, '_run_code_async', new_callable=AsyncMock) as mock_async:
            mock_context = MagicMock()
            mock_context.session_id = "test_session"
            mock_context.agent.agent_id = "test_agent"

            # 带 & 的命令应走 _run_background
            await bash._execute(
                {"code": "npm run dev &"},
                mock_context,
            )

            mock_bg.assert_called_once()
            mock_async.assert_not_called()

    # 验证 _run_background 收到的 code 已去除 &
    bash2 = Bash()
    assert bash2._strip_background_ampersand("npm run dev &") == "npm run dev"


# ─── Phase AC 2: 工具描述说明 background ─────────────────────

def test_phase_ac02_description_has_background_info():
    """Phase AC 2: 工具描述明确说明使用 background 的场景"""
    bash = Bash()
    desc = bash.description

    # 必须包含使用背景说明
    assert "background" in desc
    assert "timeout" in desc
    assert "long-running" in desc or "long running" in desc


# ─── Phase AC 3: notify 参数 ─────────────────────────────────

def test_phase_ac03_notify_parameter():
    """Phase AC 3: 新增 notify 参数（默认 False）"""
    bash = Bash()
    params = bash.parameters["properties"]

    assert "notify" in params, "notify parameter must exist"
    assert params["notify"]["type"] == "boolean"
    # 默认值在代码层面处理（notify: bool = False），JSON Schema 中不强制包含 default


# ─── Phase AC 4: 非 background 保持超时 ──────────────────────

def test_phase_ac04_non_background_preserves_timeout():
    """Phase AC 4: 非 background 命令保持原有 120s 超时杀进程行为"""
    bash = Bash()

    # 验证 _run_code_async 默认 120s 超时
    import inspect
    sig = inspect.signature(bash._run_code_async)
    timeout_param = sig.parameters.get("timeout")
    assert timeout_param is not None, "_run_code_async should have timeout parameter"
    assert timeout_param.default == 120, \
        f"Default timeout should be 120, got {timeout_param.default}"


# ─── Phase AC 5: LoopEngine 不拦截 background ────────────────

def test_phase_ac05_loopengine_skips_outer_timeout():
    """Phase AC 5: LoopEngine 对 background bash 不做外层超时拦截"""
    engine = LoopEngine.__new__(LoopEngine)

    # background=True 应跳过
    assert engine._should_skip_tool_timeout("bash", {"background": True}) is True

    # 非 background 不跳过
    assert engine._should_skip_tool_timeout("bash", {}) is False
    assert engine._should_skip_tool_timeout("bash", {"background": False}) is False

    # 其他工具不跳过
    assert engine._should_skip_tool_timeout("cron", {"action": "list_jobs"}) is False
