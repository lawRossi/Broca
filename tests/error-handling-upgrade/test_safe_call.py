"""
Broca 错误处理升级 — safe_call 装饰器测试

覆盖:
- 同步函数装饰
- 异步函数装饰
- 无括号语法
- 异常链保留
- 自定义 error_class / error_code / message
"""

import asyncio

import pytest

from broca.errors import (
    BrocaError,
    LLMError,
    ToolError,
    ErrorCode,
    safe_call,
)


class TestSafeCall:
    """safe_call 装饰器工厂行为"""

    def test_sync_success(self):
        @safe_call(error_class=ToolError, error_code=ErrorCode.TOOL_ERROR, message="工具崩溃")
        def fn(x):
            return x * 2

        assert fn(5) == 10

    def test_sync_converts_exception(self):
        @safe_call(error_class=ToolError, error_code=ErrorCode.TOOL_ERROR, message="工具崩溃")
        def fn(x):
            if x < 0:
                raise ValueError("negative")
            return x

        with pytest.raises(ToolError) as exc_info:
            fn(-1)
        assert "工具崩溃" in str(exc_info.value)
        assert exc_info.value.error_code == ErrorCode.TOOL_ERROR

    def test_sync_preserves_cause(self):
        @safe_call(error_class=ToolError, error_code=ErrorCode.TOOL_ERROR)
        def fn():
            raise RuntimeError("原始原因")

        with pytest.raises(ToolError) as exc_info:
            fn()
        assert exc_info.value.info.cause_msg == "原始原因"

    def test_async_success(self):
        @safe_call(error_class=LLMError, error_code=ErrorCode.LLM_TIMEOUT, message="LLM 超时")
        async def fn():
            return "ok"

        result = asyncio.run(fn())
        assert result == "ok"

    def test_async_converts_exception(self):
        @safe_call(error_class=LLMError, error_code=ErrorCode.LLM_TIMEOUT, message="LLM 超时")
        async def fn():
            raise TimeoutError("connection timeout")

        with pytest.raises(LLMError) as exc_info:
            asyncio.run(fn())
        assert "LLM 超时" in str(exc_info.value)
        assert exc_info.value.error_code == ErrorCode.LLM_TIMEOUT

    def test_no_parentheses_syntax(self):
        @safe_call
        def fn(x):
            if x < 0:
                raise RuntimeError("oops")
            return x

        assert fn(5) == 5
        with pytest.raises(BrocaError):
            fn(-1)

    def test_empty_parentheses_syntax(self):
        @safe_call()
        def fn(x):
            if x < 0:
                raise RuntimeError("oops")
            return x

        assert fn(3) == 3
        with pytest.raises(BrocaError):
            fn(-1)

    def test_broca_error_passthrough(self):
        """BrocaError 不应该被 safe_call 二次包装"""
        @safe_call(error_class=ToolError)
        def fn():
            raise LLMError("已经是 LLMError")

        with pytest.raises(LLMError):
            fn()
