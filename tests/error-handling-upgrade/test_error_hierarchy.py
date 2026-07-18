"""
Broca 错误处理升级 — 异常继承体系测试

覆盖:
- BrocaError 家族全部 7 个子类
- ErrorCode 元数据（severity / default_message / recovery_hint）
- ErrorInfo 序列化（to_dict / to_user_message / from_exception）
- CancelledError 透传
"""

import asyncio
import traceback

import pytest

from broca.errors import (
    BrocaError,
    BrocaPermissionError,
    CommunicationError,
    LLMError,
    OrchestrationError,
    SessionError,
    ToolError,
    ValidationError,
    ErrorCode,
    ErrorInfo,
)


# ═══════════════════════════════════════════════
# 1. 异常继承体系
# ═══════════════════════════════════════════════

class TestExceptionHierarchy:
    """BrocaError 家族继承与默认行为"""

    def test_all_subclasses_inherit_broca_error(self):
        assert issubclass(LLMError, BrocaError)
        assert issubclass(ToolError, BrocaError)
        assert issubclass(SessionError, BrocaError)
        assert issubclass(CommunicationError, BrocaError)
        assert issubclass(OrchestrationError, BrocaError)
        assert issubclass(ValidationError, BrocaError)
        assert issubclass(BrocaPermissionError, BrocaError)

    @pytest.mark.parametrize("exc_cls,expected_code", [
        (LLMError, ErrorCode.LLM_ERROR),
        (ToolError, ErrorCode.TOOL_ERROR),
        (SessionError, ErrorCode.SESSION_ERROR),
        (CommunicationError, ErrorCode.COMMUNICATION_ERROR),
        (OrchestrationError, ErrorCode.ORCHESTRATION_ERROR),
        (ValidationError, ErrorCode.VALIDATION_ERROR),
        (BrocaPermissionError, ErrorCode.PERMISSION_ERROR),
    ])
    def test_default_error_code(self, exc_cls, expected_code):
        e = exc_cls()
        assert e.error_code == expected_code

    def test_custom_error_code_override(self):
        e = ToolError(error_code=ErrorCode.TOOL_TIMEOUT)
        assert e.error_code == ErrorCode.TOOL_TIMEOUT

    def test_custom_message(self):
        e = BrocaError("自定义消息")
        assert e.message == "自定义消息"
        assert str(e) == "自定义消息"

    def test_info_is_error_info_instance(self):
        e = LLMError()
        assert isinstance(e.info, ErrorInfo)

    def test_to_dict_available(self):
        e = ToolError("出错了", error_code=ErrorCode.TOOL_TIMEOUT)
        d = e.to_dict()
        assert isinstance(d, dict)


# ═══════════════════════════════════════════════
# 2. ErrorCode 元数据
# ═══════════════════════════════════════════════

class TestErrorCode:
    """ErrorCode 枚举的元数据和行为"""

    def test_all_codes_unique(self):
        values = [c.value for c in ErrorCode]
        assert len(values) == len(set(values))

    def test_severity_levels(self):
        assert ErrorCode.LLM_TIMEOUT.severity == "warning"
        assert ErrorCode.TOOL_ERROR.severity == "error"
        assert ErrorCode.SESSION_RUNNER_CRASHED.severity == "critical"

    @pytest.mark.parametrize("code,expected_hint", [
        (ErrorCode.LLM_TIMEOUT, "自动重试中..."),
        (ErrorCode.TOOL_TIMEOUT, "可尝试增大工具超时配置"),
        (ErrorCode.COMMUNICATION_DISCONNECTED, "正在尝试重连..."),
        (ErrorCode.SESSION_RUNNER_CRASHED, "请尝试刷新页面重新连接"),
        (ErrorCode.VALIDATION_CONFIG_ERROR, "请检查配置文件格式"),
        (ErrorCode.TOOL_ERROR, None),
        (ErrorCode.UNKNOWN_ERROR, None),
    ])
    def test_recovery_hints(self, code, expected_hint):
        assert code.recovery_hint == expected_hint

    def test_default_message_not_empty(self):
        for code in ErrorCode:
            assert code.default_message, f"{code} 的 default_message 为空"


# ═══════════════════════════════════════════════
# 3. ErrorInfo
# ═══════════════════════════════════════════════

class TestErrorInfo:
    """ErrorInfo 数据类行为"""

    def test_to_dict_contains_all_fields(self):
        e = ToolError("出错了", error_code=ErrorCode.TOOL_TIMEOUT,
                      details={"tool": "test"}, cause=ValueError("原始错误"))
        d = e.to_dict()
        assert set(d.keys()) == {"code", "severity", "message",
                                 "recovery_hint", "details", "cause", "traceback"}
        assert d["code"] == "TOOL_TIMEOUT"
        assert d["severity"] == "error"
        assert d["details"] == {"tool": "test"}
        assert "原始错误" in d["cause"]
        assert d["traceback"] is not None

    def test_to_user_message_with_hint(self):
        e = ToolError(error_code=ErrorCode.TOOL_TIMEOUT)
        msg = e.to_user_message()
        assert "工具执行超时" in msg
        assert "可尝试增大工具超时配置" in msg

    def test_to_user_message_without_hint(self):
        e = LLMError()
        msg = e.to_user_message()
        assert msg == ErrorCode.LLM_ERROR.default_message

    def test_from_exception_preserves_cause(self):
        try:
            raise ValueError("原始原因")
        except ValueError as orig:
            info = ErrorInfo.from_exception(ErrorCode.TOOL_ERROR, cause=orig)
            assert info.cause_exc is orig
            assert info.cause_msg == "原始原因"
            assert "ValueError" in info.traceback_str

    def test_from_exception_without_cause(self):
        info = ErrorInfo.from_exception(ErrorCode.TOOL_ERROR)
        assert info.cause_exc is None
        assert info.cause_msg is None
        assert info.traceback_str is None

    def test_severity_propagation(self):
        """verify → warning 级别 → to_dict 中 severity 为 warning"""
        d = LLMError(error_code=ErrorCode.LLM_TIMEOUT).to_dict()
        assert d["severity"] == "warning"
        assert d["recovery_hint"] == "自动重试中..."


# ═══════════════════════════════════════════════
# 4. CancelledError 透传
# ═══════════════════════════════════════════════

class TestCancelledErrorPassthrough:
    """CancelledError 不应被 BrocaError catch 吞没"""

    async def _raise_cancel(self):
        raise asyncio.CancelledError()

    def test_cancelled_not_caught_by_broca_error(self):
        with pytest.raises(asyncio.CancelledError):
            try:
                raise asyncio.CancelledError()
            except BrocaError:
                pytest.fail("BrocaError 不应捕获 CancelledError")

    def test_catch_order_matters(self):
        """验证正确的 catch 顺序：CancelledError 必须在 BrocaError 之前"""
        with pytest.raises(asyncio.CancelledError):
            try:
                raise asyncio.CancelledError()
            except asyncio.CancelledError:
                raise  # 透传
            except BrocaError:
                pytest.fail("不应到达这里")
