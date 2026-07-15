"""
Broca 异常继承体系

所有 Broca 异常的基类 BrocaError 直接携带 ErrorInfo 实例。
子类按模块划分，各自有默认的 ErrorCode。
"""

from __future__ import annotations

import traceback
from typing import Any

from broca.errors.types import ErrorCode, ErrorInfo


class BrocaError(Exception):
    """所有 Broca 异常的基类 — 直接携带 ErrorInfo"""

    default_error_code: ErrorCode = ErrorCode.UNKNOWN_ERROR

    def __init__(
        self,
        message: str = "",
        error_code: ErrorCode | None = None,
        details: dict | None = None,
        cause: Exception | None = None,
    ):
        self.info = ErrorInfo.from_exception(
            code=error_code or self.default_error_code,
            message=message or (error_code or self.default_error_code).default_message,
            details=details,
            cause=cause,
        )
        super().__init__(self.info.message)

    @property
    def error_code(self) -> ErrorCode:
        return self.info.code

    @property
    def message(self) -> str:
        return self.info.message

    def to_user_message(self) -> str:
        """返回仅用户可见的消息，不含技术细节"""
        return self.info.to_user_message()

    def to_dict(self) -> dict:
        """返回完整序列化字典 — 用于 Socket.IO / IPC 传输"""
        return self.info.to_dict()


class LLMError(BrocaError):
    """LLM 相关错误"""
    default_error_code: ErrorCode = ErrorCode.LLM_ERROR


class ToolError(BrocaError):
    """工具执行相关错误"""
    default_error_code: ErrorCode = ErrorCode.TOOL_ERROR


class SessionError(BrocaError):
    """会话管理 + Runner 子进程错误"""
    default_error_code: ErrorCode = ErrorCode.SESSION_ERROR


class CommunicationError(BrocaError):
    """Socket.IO + IPC 通信错误"""
    default_error_code: ErrorCode = ErrorCode.COMMUNICATION_ERROR


class OrchestrationError(BrocaError):
    """编排执行错误"""
    default_error_code: ErrorCode = ErrorCode.ORCHESTRATION_ERROR


class ValidationError(BrocaError):
    """参数校验 / 配置校验错误"""
    default_error_code: ErrorCode = ErrorCode.VALIDATION_ERROR


class BrocaPermissionError(BrocaError):
    """权限错误（避免与内置 PermissionError 冲突）"""
    default_error_code: ErrorCode = ErrorCode.PERMISSION_ERROR
