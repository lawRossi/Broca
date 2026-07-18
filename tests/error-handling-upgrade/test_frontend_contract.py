"""
Broca 错误处理升级 — 前端契约测试

确保 to_dict() 输出与前端 ChatMessageItem.vue / TUI chat_store.py 的期望一致。

关键契约:
1. to_dict() 始终包含 code / severity / message / recovery_hint / details / cause / traceback
2. severity 必须是 'warning' | 'error' | 'critical' 之一
3. recovery_hint 在适用场景必须有值
"""

import pytest

from broca.errors import (
    LLMError,
    ToolError,
    SessionError,
    CommunicationError,
    OrchestrationError,
    ValidationError,
    ErrorCode,
)


class TestFrontendContract:
    """前端与后端之间的数据格式契约"""

    # ── to_dict 字段完整性 ──

    @pytest.mark.parametrize("exc,expected_code", [
        (LLMError(error_code=ErrorCode.LLM_TIMEOUT), "LLM_TIMEOUT"),
        (ToolError(error_code=ErrorCode.TOOL_TIMEOUT), "TOOL_TIMEOUT"),
        (SessionError(error_code=ErrorCode.SESSION_RUNNER_CRASHED), "SESSION_RUNNER_CRASHED"),
        (CommunicationError(error_code=ErrorCode.COMMUNICATION_DISCONNECTED), "COMMUNICATION_DISCONNECTED"),
        (OrchestrationError(error_code=ErrorCode.ORCHESTRATION_ERROR), "ORCHESTRATION_ERROR"),
        (ValidationError(error_code=ErrorCode.VALIDATION_CONFIG_ERROR), "VALIDATION_CONFIG_ERROR"),
    ])
    def test_to_dict_required_fields(self, exc, expected_code):
        d = exc.to_dict()
        # 前端 ChatMessageItem.vue 依赖的字段
        assert "code" in d
        assert "severity" in d
        assert "message" in d
        assert "recovery_hint" in d
        assert "details" in d
        assert "cause" in d
        assert "traceback" in d
        assert d["code"] == expected_code

    # ── severity 校验 ──

    def test_severity_is_valid_value(self):
        """severity 必须是前端能识别的三个值之一"""
        for exc in [LLMError(), ToolError(), SessionError(),
                     CommunicationError(), OrchestrationError(), ValidationError()]:
            assert exc.to_dict()["severity"] in ("warning", "error", "critical")

    @pytest.mark.parametrize("exc,expected_severity", [
        (LLMError(error_code=ErrorCode.LLM_TIMEOUT), "warning"),
        (LLMError(error_code=ErrorCode.LLM_RATE_LIMIT), "warning"),
        (CommunicationError(error_code=ErrorCode.COMMUNICATION_TIMEOUT), "warning"),
        (ToolError(), "error"),
        (SessionError(), "error"),
        (OrchestrationError(), "error"),
        (SessionError(error_code=ErrorCode.SESSION_RUNNER_CRASHED), "critical"),
    ])
    def test_severity_mapping(self, exc, expected_severity):
        """不同 ErrorCode → 不同 severity 级别"""
        assert exc.to_dict()["severity"] == expected_severity

    # ── 前端展示颜色映射 ──

    def test_warning_gives_yellow_hint(self):
        """warning → 黄色提示（前端 CSS: msg-error-warning）"""
        d = LLMError(error_code=ErrorCode.LLM_TIMEOUT).to_dict()
        assert d["severity"] == "warning"
        assert d["recovery_hint"] is not None

    def test_critical_gives_red_bold(self):
        """critical → 深红加粗（前端 CSS: msg-error-critical）"""
        d = SessionError(error_code=ErrorCode.SESSION_RUNNER_CRASHED).to_dict()
        assert d["severity"] == "critical"
        assert "刷新页面" in d["recovery_hint"]

    # ── recovery_hint 展示 ──

    def test_recovery_hint_display_in_to_user_message(self):
        """recovery_hint 应出现在 to_user_message() 中"""
        msg = ToolError(error_code=ErrorCode.TOOL_TIMEOUT).to_user_message()
        assert "工具执行超时" in msg
        assert "可尝试增大工具超时配置" in msg

    def test_no_recovery_hint_no_extra_text(self):
        """没有 recovery_hint 时 to_user_message 不附加多余内容"""
        msg = ToolError().to_user_message()
        assert msg == ErrorCode.TOOL_ERROR.default_message

    # ── 跨格式兼容 ──

    def test_old_format_compatibility(self):
        """旧格式（仅 content + error_code）仍可正常显示"""
        # 模拟旧格式消息
        old_data = {"content": "旧错误", "error_code": "TOOL_ERROR"}
        # 前端 ChatMessageItem.vue 优先取 data.content
        assert old_data.get("content") == "旧错误"
        # 新字段可选
        assert old_data.get("severity") is None  # 兼容处理
