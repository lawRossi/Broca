import copy
import json
import os
import warnings
from pathlib import Path
from typing import Any, AsyncGenerator

from litellm import Message as LLMMessage
from litellm import acompletion
from litellm.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    BudgetExceededError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    InvalidRequestError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

from broca.components.llm_client import LLMClient as LLMClientABC
from broca.configs import LLM_DEFAULT_KEY
from broca.errors import ErrorCode, LLMError, ValidationError
from broca.logging_config import get_logger
from broca.session.models import Message, MessageType

logger = get_logger(__name__)

warnings.filterwarnings("ignore")

# NOTE: 映射顺序有严格要求 — 子类必须排在父类前面，否则 isinstance() 会先匹配父类
# 异常继承关系（litellm）：
#   ContextWindowExceededError / ContentPolicyViolationError  →  BadRequestError (litellm)
#   Timeout (litellm)  →  APITimeoutError  →  APIConnectionError
#   InvalidRequestError → openai.BadRequestError（与 litellm.BadRequestError 无继承关系）
_EXCEPTION_MAP: list[tuple[type, ErrorCode, str]] = [
    # ── BadRequestError 子类（必须在 BadRequestError 之前）──
    (ContextWindowExceededError, ErrorCode.LLM_CONTEXT_WINDOW_EXCEEDED, "对话超出上下文长度限制"),
    (ContentPolicyViolationError, ErrorCode.LLM_ERROR, "LLM 内容安全策略拒绝"),
    # ── APIConnectionError 子类（必须在 APIConnectionError 之前）──
    (Timeout, ErrorCode.LLM_TIMEOUT, "LLM 请求超时"),
    # ── 独立异常（无继承冲突）──
    (AuthenticationError, ErrorCode.LLM_AUTH_ERROR, "API Key 认证失败"),
    (BudgetExceededError, ErrorCode.LLM_QUOTA_EXCEEDED, "API 额度不足"),
    (RateLimitError, ErrorCode.LLM_RATE_LIMIT, "请求频率过高，触发限流"),
    (InternalServerError, ErrorCode.LLM_SERVICE_UNAVAILABLE, "LLM 服务暂不可用"),
    (ServiceUnavailableError, ErrorCode.LLM_SERVICE_UNAVAILABLE, "LLM 服务暂不可用"),
    (APIConnectionError, ErrorCode.LLM_SERVICE_UNAVAILABLE, "无法连接到 LLM 服务"),
    # ── 父类（必须在所有子类之后）──
    (BadRequestError, ErrorCode.LLM_ERROR, "LLM 请求错误"),
]


class LiteLLMClient(LLMClientABC):
    """Default LLM Client implementation using LiteLLM.

    Renamed from ``LLMClient`` in Phase 4.  The backward-compatible
    alias ``LLMClient = LiteLLMClient`` is kept at the bottom of this
    module.
    """

    def __init__(self):
        """Initialize LLM Client"""
        # 配置路径从 configs.json 读取
        from broca.configs import resolve_llm_config_path

        config_file = resolve_llm_config_path()
        with open(config_file) as f:
            self.config = json.load(f)

        # 全局配置（configs.json）中执行相关参数，用于 LLM 调用超时
        from broca.configs import get_configs

        self.execution_config = get_configs().execution

    def parse_message(self, provider: str, model: str, message: Message) -> dict:
        """
        将内部 Message 对象解析为 LLM 需要的消息格式

        Args:
            provider: LLM 提供商
            model: LLM 模型
            message: 内部消息对象

        Returns:
            LLM 消息格式的字典，包含 role 和 content 字段
        """

        if provider not in self.config:
            raise ValidationError(
                f"未知 LLM 提供商: {provider}",
                error_code=ErrorCode.VALIDATION_CONFIG_ERROR,
            )
        if model not in self.config[provider].get("models", {}):
            raise ValidationError(
                f"未知 LLM 模型: {model} (提供商: {provider})",
                error_code=ErrorCode.VALIDATION_CONFIG_ERROR,
            )

        modality = self.config[provider]["models"][model]["meta"]["modality"]
        raw_input = message.data.get("raw_input") if message.data else None

        # Initialize content containers for all message types
        text_content = ""
        image_content = []
        audio_content: list[dict[str, Any]] = []
        video_content = []

        if message.message_type == MessageType.USER_MESSAGE:
            text_content = str(message.data.get("content", ""))
            files = message.data.get("files")
            if files:
                file_info_parts = []
                for file in files:
                    file_url = file.get("url", "")
                    file_type = file.get("type", "")
                    if file_type.startswith("image") and "image" in modality:
                        image_part = {
                            "type": "image_url",
                            "image_url": {"url": file_url},
                        }
                        image_part.update(modality["image"])
                        image_content.append(image_part)
                    elif file_type.startswith("video") and "video" in modality:
                        video_part = {
                            "type": "video_url",
                            "video_url": {"url": file_url},
                        }
                        video_part.update(modality["video"])
                        video_content.append(video_part)
                    elif file_type.startswith("audio") and "audio" in modality:
                        pass
                    else:
                        file_info = f"文件类型：{file_type}\n文件链接：{file_url}"
                        file_info_parts.append(file_info)
                if file_info_parts:
                    files_section = "\n\n[附件文件]:\n" + "\n".join(file_info_parts)
                    text_content = text_content + files_section
            # 始终保留原始文本（不含文件 section），供前端展示 / 广播使用
            raw_input = raw_input if raw_input is not None else (
                message.data.get("content", "") if message.data else ""
            )
        elif message.message_type == MessageType.TASK_START:
            text_content = str(message.data.get("task_description") or "")
        elif message.message_type == MessageType.TASK_COMPLETE:
            text_content = str(message.data.get("result") or "")
        elif message.message_type == MessageType.TASK_ERROR:
            text_content = str(message.data.get("error_message") or "")
        else:
            return {}
        if image_content:
            content: Any = image_content
        elif video_content:
            content = video_content
        elif audio_content:
            content = audio_content
        else:
            content = text_content
        if isinstance(content, list):
            content.append({"type": "text", "text": text_content})
        return {"role": "user", "content": content, "raw_input": raw_input}

    async def get_stream_response(
        self,
        provider,
        model,
        messages,
        tools=None,
        first_chunk_timeout=None,
        timeout=None,
    ) -> AsyncGenerator[dict, None]:
        if provider not in self.config:
            raise ValidationError(
                f"未知 LLM 提供商: {provider}",
                error_code=ErrorCode.VALIDATION_CONFIG_ERROR,
            )
        if model not in self.config[provider].get("models", {}):
            raise ValidationError(
                f"未知 LLM 模型: {model} (提供商: {provider})",
                error_code=ErrorCode.VALIDATION_CONFIG_ERROR,
            )
        args = copy.deepcopy(self.config[provider]["models"][model])
        del args["meta"]

        model_name = args.get("model", model)
        # 未显式传入时使用全局配置中的超时参数
        if first_chunk_timeout is None:
            first_chunk_timeout = self.execution_config.llm_first_chunk_timeout
        if timeout is None:
            timeout = self.execution_config.llm_timeout
        try:
            response = await acompletion(
                base_url=self.config[provider]["base_url"],
                api_key=self.config[provider]["api_key"],
                messages=messages,
                tools=tools,
                stream=True,
                stream_options={"include_usage": True},
                stream_timeout=first_chunk_timeout,
                timeout=timeout,
                **args,
            )

            async for chunk in response:
                async for result in self._process_chunk(chunk):
                    yield result
        except InvalidRequestError as e:
            # InvalidRequestError 继承自 openai.BadRequestError（非 litellm.BadRequestError），
            # 不会被 except Exception 中的 BadRequestError isinstance 匹配，需独立处理
            raise self._classify_request_error(e, provider, model_name, "LLM 请求参数错误") from e
        except Exception as e:
            for exc_type, code, prefix in _EXCEPTION_MAP:
                if isinstance(e, exc_type):
                    # BadRequestError 需要子分类（auth key 检测）
                    if exc_type is BadRequestError:
                        raise self._classify_request_error(e, provider, model_name, prefix) from e
                    raise LLMError(
                        message=f"{prefix} (provider: {provider}, model: {model_name}): {e}",
                        error_code=code,
                        details={"provider": provider, "model": model_name},
                        cause=e,
                    ) from e
            # 兜底：所有未归类异常统一包装为 LLMError
            raise LLMError(
                message=f"LLM 请求失败 (provider: {provider}, model: {model_name}): {e}",
                error_code=ErrorCode.LLM_ERROR,
                details={"provider": provider, "model": model_name},
                cause=e,
            ) from e

    def _classify_request_error(
        self, e: Exception, provider: str, model_name: str, prefix: str
    ) -> LLMError:
        """子分类 InvalidRequestError / BadRequestError 为更精确的 ErrorCode."""
        error_msg = str(e).lower()
        # InvalidRequestError: 模型不存在/不可用
        if isinstance(e, InvalidRequestError) and "model" in error_msg and (
            "not found" in error_msg
            or "not exist" in error_msg
            or "not support" in error_msg
            or "does not exist" in error_msg
        ):
            return LLMError(
                message=f"模型不可用 (provider: {provider}, model: {model_name}): {e}",
                error_code=ErrorCode.LLM_INVALID_MODEL,
                details={"provider": provider, "model": model_name},
                cause=e,
            )
        # BadRequestError: 某些提供商对无效 API Key 返回 400 而非 401
        if isinstance(e, BadRequestError) and (
            "auth" in error_msg
            or "api key" in error_msg
            or "invalid" in error_msg
        ):
            return LLMError(
                message=f"API Key 认证失败 (provider: {provider}): {e}",
                error_code=ErrorCode.LLM_AUTH_ERROR,
                details={"provider": provider, "model": model_name},
                cause=e,
            )
        # 通用 fallback
        return LLMError(
            message=f"{prefix} (provider: {provider}): {e}",
            error_code=ErrorCode.LLM_ERROR,
            details={"provider": provider, "model": model_name},
            cause=e,
        )

    async def _process_chunk(self, chunk) -> AsyncGenerator[dict, None]:
        if hasattr(chunk, "usage") and chunk.usage:
            # Yield a usage event so strategies can read tokens from the
            # stream itself instead of shared instance state.
            yield {
                "type": "usage",
                "data": {
                    "input_tokens": chunk.usage.prompt_tokens or 0,
                    "output_tokens": chunk.usage.completion_tokens or 0,
                },
            }

        if hasattr(chunk, "choices") and chunk.choices:
            choice = chunk.choices[0]
            if hasattr(choice, "delta") and choice.delta:
                delta = choice.delta
                if hasattr(delta, "content") and delta.content:
                    yield {"type": "content", "data": delta.content}
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    yield {
                        "type": "reasoning_content",
                        "data": delta.reasoning_content,
                    }
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tool_call in delta.tool_calls:
                        yield {"type": "tool_call", "data": tool_call}
            if hasattr(choice, "finish_reason") and choice.finish_reason:
                yield {"type": "finish", "data": choice.finish_reason}

    def aggregate_message(self, content_chunks, tool_call_chunks) -> LLMMessage | None:
        content = self.aggregate_content(content_chunks)
        text_content = (content.get("content") or "").strip()
        reasoning_content = (content.get("reasoning_content") or "").strip()
        tool_calls = self.aggregate_tool_calls(tool_call_chunks)
        # 只要有正文、推理内容（思考块）或工具调用之一，即视为有效响应。
        # 推理型模型可能只返回思考块而正文为空，不能误判为"空响应"触发无谓重试。
        if not text_content and not reasoning_content and not tool_calls:
            return None

        return LLMMessage.model_validate(
            {
                "role": "assistant",
                "content": content.get("content"),
                "tool_calls": tool_calls,
                "reasoning_content": content.get("reasoning_content"),
                "provider_specific_fields": {
                    "reasoning_content": content.get("reasoning_content")
                },
            }
        )

    def aggregate_content(self, content_chunks) -> dict:
        content = ""
        reasoning_content = ""
        for chunk in content_chunks:
            if chunk["type"] == "content":
                content += chunk["data"]
            elif chunk["type"] == "reasoning_content":
                reasoning_content += chunk["data"]
        return {"content": content, "reasoning_content": reasoning_content}

    def aggregate_tool_calls(self, tool_call_chunks) -> list[dict]:
        tool_calls: dict[int, dict] = {}

        for chunk in tool_call_chunks:
            if hasattr(chunk, "index"):
                index = chunk.index
                if index not in tool_calls:
                    tool_calls[index] = {
                        "id": None,
                        "type": "function",
                        "function": {"name": None, "arguments": ""},
                    }

                if hasattr(chunk, "id") and chunk.id:
                    tool_calls[index]["id"] = chunk.id
                if hasattr(chunk, "function") and chunk.function:
                    if hasattr(chunk.function, "name") and chunk.function.name:
                        tool_calls[index]["function"]["name"] = chunk.function.name
                    if (
                        hasattr(chunk.function, "arguments")
                        and chunk.function.arguments
                    ):
                        tool_calls[index]["function"]["arguments"] += (
                            chunk.function.arguments
                        )

        return list(tool_calls.values())


# Backward-compatible alias: existing code doing
# ``from broca.llm import LLMClient`` still works (resolves to LiteLLMClient).
LLMClient = LiteLLMClient
