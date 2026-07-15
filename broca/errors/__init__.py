"""
Broca 统一错误处理系统

提供规范的异常继承体系 + 统一错误码 + 结构化错误信息格式。

使用方式:
    from broca.errors import (
        BrocaError, LLMError, ToolError,
        ErrorCode, ErrorInfo,
        safe_call,
    )

    # 抛出异常
    raise ToolError("工具执行失败", error_code=ErrorCode.TOOL_TIMEOUT)

    # 入口点兜底
    except BrocaError as e:
        await communicator.send_error(error_info=e.to_dict())
        return ToolResult(status=ToolStatus.ERROR, content=e.to_user_message())
"""

from broca.errors.exceptions import (
    BrocaError,
    BrocaPermissionError,
    CommunicationError,
    LLMError,
    OrchestrationError,
    SessionError,
    ToolError,
    ValidationError,
)
from broca.errors.types import ErrorCode, ErrorInfo
from broca.errors.utils import safe_call

__all__ = [
    # Exception hierarchy
    "BrocaError",
    "LLMError",
    "ToolError",
    "SessionError",
    "CommunicationError",
    "OrchestrationError",
    "ValidationError",
    "BrocaPermissionError",
    # Error types
    "ErrorCode",
    "ErrorInfo",
    # Utilities
    "safe_call",
]
