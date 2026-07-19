"""
Error Types Module

Defines the core error data structures for Broca's error handling system:
- ErrorCode: Enum with embedded metadata (severity, message, recovery hint)
- ErrorInfo: Structured error payload used everywhere (exceptions, IPC, Socket.IO)
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from enum import Enum


class ErrorCode(str, Enum):
    """错误码枚举 — 每个值携带 severity / default_message / recovery_hint 元数据"""

    # 运行时由 __new__ 动态设置，此处声明以满足类型检查
    _severity: str
    _message: str
    _hint: str | None

    # == LLM ==
    LLM_ERROR = ("LLM_ERROR", "error", "LLM 调用失败", None)
    LLM_TIMEOUT = ("LLM_TIMEOUT", "warning", "LLM 调用超时，请检查网络连接", "自动重试中...")
    LLM_RATE_LIMIT = ("LLM_RATE_LIMIT", "warning", "LLM 调用过于频繁", "等待后自动重试")
    LLM_AUTH_ERROR = (
        "LLM_AUTH_ERROR", "error",
        "LLM API Key 认证失败，请检查 API Key 是否正确",
        "请检查 configs/llm_config.json 中的 api_key 或设置环境变量 BROCA_API_KEY_{PROVIDER}",
    )
    LLM_QUOTA_EXCEEDED = (
        "LLM_QUOTA_EXCEEDED", "error",
        "LLM API 额度不足，请求被拒绝",
        "请检查账户余额或等待配额刷新",
    )
    LLM_INVALID_MODEL = (
        "LLM_INVALID_MODEL", "error",
        "LLM 模型不可用或不存在",
        "请检查 configs/llm_config.json 中的模型配置是否正确",
    )
    LLM_CONTEXT_WINDOW_EXCEEDED = (
        "LLM_CONTEXT_WINDOW_EXCEEDED", "error",
        "对话超出模型上下文长度限制",
        "尝试缩短对话或重启新会话",
    )
    LLM_SERVICE_UNAVAILABLE = (
        "LLM_SERVICE_UNAVAILABLE", "error",
        "LLM 服务暂不可用",
        "请稍后重试或检查服务状态",
    )

    # == Tool ==
    TOOL_ERROR = ("TOOL_ERROR", "error", "工具执行失败", None)
    TOOL_TIMEOUT = ("TOOL_TIMEOUT", "error", "工具执行超时", "可尝试增大工具超时配置")
    TOOL_NOT_FOUND = ("TOOL_NOT_FOUND", "error", "工具不存在", "请检查工具名称是否正确")
    TOOL_PERMISSION_DENIED = ("TOOL_PERMISSION_DENIED", "error", "工具执行被拒绝", "需要你的授权")

    # == Session (含 Runner 子进程管理) ==
    SESSION_ERROR = ("SESSION_ERROR", "error", "会话错误", None)
    SESSION_NOT_FOUND = ("SESSION_NOT_FOUND", "error", "会话不存在", "可能已被清除")
    SESSION_INIT_ERROR = ("SESSION_INIT_ERROR", "error", "会话初始化失败", "请尝试重新加载")
    SESSION_RUNNER_ERROR = ("SESSION_RUNNER_ERROR", "error", "会话进程管理异常", None)
    SESSION_RUNNER_CRASHED = (
        "SESSION_RUNNER_CRASHED",
        "critical",
        "会话进程意外退出",
        "请尝试刷新页面重新连接",
    )
    SESSION_RUNNER_TIMEOUT = (
        "SESSION_RUNNER_TIMEOUT",
        "error",
        "会话进程无响应",
        "可能已卡死，请刷新页面",
    )

    # == Communication (含 IPC 进程间通信) ==
    COMMUNICATION_ERROR = ("COMMUNICATION_ERROR", "error", "通信异常", None)
    COMMUNICATION_TIMEOUT = ("COMMUNICATION_TIMEOUT", "warning", "通信超时", "自动重试中...")
    COMMUNICATION_DISCONNECTED = (
        "COMMUNICATION_DISCONNECTED",
        "error",
        "连接已断开",
        "正在尝试重连...",
    )
    COMMUNICATION_IPC_ERROR = ("COMMUNICATION_IPC_ERROR", "error", "进程间通信异常", "正在尝试重连...")
    COMMUNICATION_IPC_TIMEOUT = (
        "COMMUNICATION_IPC_TIMEOUT",
        "warning",
        "进程间通信超时",
        None,
    )

    # == Orchestration ==
    ORCHESTRATION_ERROR = ("ORCHESTRATION_ERROR", "error", "编排执行失败", None)
    ORCHESTRATION_AGENT_NOT_FOUND = (
        "ORCHESTRATION_AGENT_NOT_FOUND",
        "error",
        "编排中的 Agent 不存在",
        "请检查编排配置",
    )

    # == Validation ==
    VALIDATION_ERROR = ("VALIDATION_ERROR", "error", "参数校验失败", None)
    VALIDATION_CONFIG_ERROR = (
        "VALIDATION_CONFIG_ERROR",
        "error",
        "配置校验失败",
        "请检查配置文件格式",
    )

    # == Permission ==
    PERMISSION_ERROR = ("PERMISSION_ERROR", "error", "权限异常", None)
    PERMISSION_DENIED = ("PERMISSION_DENIED", "error", "权限被拒绝", None)

    # == Unknown ==
    UNKNOWN_ERROR = ("UNKNOWN_ERROR", "error", "未知错误", None)

    def __new__(cls, code: str, severity: str, message: str, recovery_hint: str | None):
        obj = str.__new__(cls, code)
        obj._value_ = code
        obj._severity = severity
        obj._message = message
        obj._hint = recovery_hint
        return obj

    @property
    def severity(self) -> str:
        """错误严重级别: warning | error | critical"""
        return self._severity

    @property
    def default_message(self) -> str:
        """默认用户友好错误消息"""
        return self._message

    @property
    def recovery_hint(self) -> str | None:
        """恢复建议（用户可见），None 表示无建议"""
        return self._hint


@dataclass
class ErrorInfo:
    """错误信息的统一格式 — 作为异常的 payload，也可直接序列化用于 IPC / Socket.IO

    Attributes:
        code: 错误码（内含 severity / default_message / recovery_hint）
        message: 用户友好提示
        details: 调试用上下文（可选）
        cause_exc: 原始异常对象（保留异常链，仅内存中）
        cause_msg: 原始异常信息（用于序列化/展示）
        traceback_str: 完整调用栈（仅调试用）
    """

    code: ErrorCode
    message: str
    details: dict | None = None
    cause_exc: Exception | None = None
    cause_msg: str | None = None
    traceback_str: str | None = None

    def to_user_message(self) -> str:
        """返回仅用户可见的消息，不含技术细节"""
        msg = self.message
        if self.code.recovery_hint:
            msg += f"\n💡 {self.code.recovery_hint}"
        return msg

    def to_dict(self) -> dict:
        """返回完整序列化字典（包含调试信息）— 用于 Socket.IO / IPC 传输"""
        return {
            "code": self.code.value,
            "severity": self.code.severity,
            "message": self.message,
            "recovery_hint": self.code.recovery_hint,
            "details": self.details,
            "cause": self.cause_msg,
            "traceback": self.traceback_str,
        }

    @classmethod
    def from_exception(
        cls,
        code: ErrorCode,
        message: str = "",
        details: dict | None = None,
        cause: Exception | None = None,
    ) -> "ErrorInfo":
        """从异常对象创建 ErrorInfo（自动提取 traceback）"""
        return cls(
            code=code,
            message=message or code.default_message,
            details=details,
            cause_exc=cause,
            cause_msg=str(cause) if cause else None,
            traceback_str=traceback.format_exc() if cause else None,
        )
