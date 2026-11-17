"""媒体物化相关异常。

- :class:`MediaFileTooLargeError`：媒体文件超过配置阈值，压缩后仍无法满足时抛出。
- :class:`MediaMaterializeError`：物化过程中的通用失败（取字节失败、解码失败等）。

这些异常最终会在 ``get_stream_response`` 边界被转成用户可见的 ``LLMError``，
让该轮请求失败并提醒用户（不做静默 url 回退）。
"""

from __future__ import annotations

from broca.errors import ErrorCode
from broca.errors.exceptions import BrocaError


def _fmt_mb(num_bytes: int | float | None) -> str:
    if not num_bytes:
        return "0MB"
    return f"{num_bytes / (1024 * 1024):.2f}MB"


class MediaFileTooLargeError(BrocaError):
    """媒体文件超过阈值（压缩后仍超限）时抛出。

    携带结构化字段（``file_name`` / ``size_bytes`` / ``threshold_bytes`` /
    ``mime``）以及人类可读的 ``suggestion``，便于上层转成用户提示。
    """

    default_error_code: ErrorCode = ErrorCode.LLM_ERROR

    def __init__(
        self,
        file_name: str,
        size_bytes: int,
        threshold_bytes: int,
        *,
        mime: str = "",
        suggestion: str = "",
    ):
        self.file_name = file_name
        self.size_bytes = size_bytes
        self.threshold_bytes = threshold_bytes
        self.mime = mime
        self.suggestion = suggestion or (
            "请配置 files_api 以支持大文件，或缩小/压缩该文件后重试。"
        )
        message = (
            f"媒体文件过大：{file_name}（{_fmt_mb(size_bytes)}）"
            f"超过阈值 {_fmt_mb(threshold_bytes)}，且无法压缩到阈值内。"
            f"{self.suggestion}"
        )
        super().__init__(
            message=message,
            details={
                "file_name": file_name,
                "size_bytes": size_bytes,
                "threshold_bytes": threshold_bytes,
                "mime": mime,
                "suggestion": self.suggestion,
            },
        )


class MediaMaterializeError(BrocaError):
    """媒体物化通用失败（取字节失败、ref 解码失败、上传失败等）。"""

    default_error_code: ErrorCode = ErrorCode.LLM_ERROR

    def __init__(
        self,
        message: str,
        *,
        file_name: str = "",
        details: dict | None = None,
        cause: Exception | None = None,
    ):
        self.file_name = file_name
        super().__init__(message=message, details=details, cause=cause)


__all__ = ["MediaFileTooLargeError", "MediaMaterializeError"]
