import copy
import json
import os
import warnings
from pathlib import Path
from typing import AsyncGenerator

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

from broca.errors import ErrorCode, LLMError, ValidationError
from broca.logging_config import get_logger
from broca.session.models import Message, MessageType

logger = get_logger(__name__)

warnings.filterwarnings("ignore")


class LLMClient:
    """LLM Client for making API calls to various providers"""

    def __init__(self):
        """Initialize LLM Client"""
        self.input_tokens_used = 0
        self.output_tokens_used = 0

        # 优先级: 环境变量 BROCA_LLM_CONFIG > 默认路径
        config_path = os.getenv("BROCA_LLM_CONFIG")
        if not config_path:
            config_path = Path(__file__).parent.parent / "configs" / "llm_config.json"
        config_file = Path(config_path)

        with open(config_file) as f:
            self.config = json.load(f)

        # 环境变量覆盖 API Key: BROCA_API_KEY_{PROVIDER_UPPER}
        self._apply_env_overrides()

    def _apply_env_overrides(self):
        """用环境变量覆盖配置文件中的 API Key 和 Base URL

        格式:
          BROCA_API_KEY_{PROVIDER}       → 覆盖对应 provider 的 api_key (连字符转为下划线)
          BROCA_API_BASE_URL_{PROVIDER}  → 覆盖对应 provider 的 base_url

        示例:
          export BROCA_API_KEY_NVIDIA="nvapi-..."
          export BROCA_API_BASE_URL_DEEPSEEK="https://api.deepseek.com/v1"
        """
        for provider in list(self.config.keys()):
            if not isinstance(self.config[provider], dict):
                continue
            # provider 名中的连字符转下划线，全大写
            provider_env = provider.upper().replace("-", "_")
            key_env = f"BROCA_API_KEY_{provider_env}"
            url_env = f"BROCA_API_BASE_URL_{provider_env}"

            api_key = os.getenv(key_env)
            if api_key:
                self.config[provider]["api_key"] = api_key
                logger.info(
                    "LLM config: %s api_key overridden from env %s", provider, key_env
                )

            base_url = os.getenv(url_env)
            if base_url:
                self.config[provider]["base_url"] = base_url
                logger.info(
                    "LLM config: %s base_url overridden from env %s", provider, url_env
                )

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
        audio_content = []
        video_content = []

        if message.message_type == MessageType.USER_MESSAGE:
            text_content = message.data.get("content", "")
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
                    if raw_input is None:
                        raw_input = text_content
                    files_section = "\n\n[附件文件]:\n" + "\n".join(file_info_parts)
                    text_content = text_content + files_section
        elif message.message_type == MessageType.TASK_START:
            text_content = message.data.get("task_description")
        elif message.message_type == MessageType.TASK_COMPLETE:
            text_content = message.data.get("result")
        elif message.message_type == MessageType.TASK_ERROR:
            text_content = message.data.get("error_message")
        else:
            return {}
        if image_content:
            content = image_content
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
        first_chunk_timeout=30,
        timeout=300,
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
        except AuthenticationError as e:
            raise LLMError(
                message=f"API Key 认证失败 (provider: {provider}): {e}",
                error_code=ErrorCode.LLM_AUTH_ERROR,
                details={"provider": provider, "model": model_name},
                cause=e,
            )
        except BudgetExceededError as e:
            raise LLMError(
                message=f"API 额度不足 (provider: {provider}): {e}",
                error_code=ErrorCode.LLM_QUOTA_EXCEEDED,
                details={"provider": provider, "model": model_name},
                cause=e,
            )
        except RateLimitError as e:
            raise LLMError(
                message=f"请求频率过高，触发限流 (provider: {provider}): {e}",
                error_code=ErrorCode.LLM_RATE_LIMIT,
                details={"provider": provider, "model": model_name},
                cause=e,
            )
        except ContextWindowExceededError as e:
            raise LLMError(
                message=f"对话超出上下文长度限制 (provider: {provider}, model: {model_name}): {e}",
                error_code=ErrorCode.LLM_CONTEXT_WINDOW_EXCEEDED,
                details={"provider": provider, "model": model_name},
                cause=e,
            )
        except (InternalServerError, ServiceUnavailableError) as e:
            raise LLMError(
                message=f"LLM 服务暂不可用 (provider: {provider}): {e}",
                error_code=ErrorCode.LLM_SERVICE_UNAVAILABLE,
                details={"provider": provider, "model": model_name},
                cause=e,
            )
        except Timeout as e:
            raise LLMError(
                message=f"LLM 请求超时 (provider: {provider}): {e}",
                error_code=ErrorCode.LLM_TIMEOUT,
                details={"provider": provider, "model": model_name},
                cause=e,
            )
        except InvalidRequestError as e:
            # 模型不存在/不可用等请求参数错误
            error_msg = str(e).lower()
            if "model" in error_msg and (
                "not found" in error_msg
                or "not exist" in error_msg
                or "not support" in error_msg
                or "does not exist" in error_msg
            ):
                raise LLMError(
                    message=f"模型不可用 (provider: {provider}, model: {model_name}): {e}",
                    error_code=ErrorCode.LLM_INVALID_MODEL,
                    details={"provider": provider, "model": model_name},
                    cause=e,
                )
            raise LLMError(
                message=f"LLM 请求参数错误 (provider: {provider}): {e}",
                error_code=ErrorCode.LLM_ERROR,
                details={"provider": provider, "model": model_name},
                cause=e,
            )
        except APIConnectionError as e:
            raise LLMError(
                message=f"无法连接到 LLM 服务 (provider: {provider}): {e}",
                error_code=ErrorCode.LLM_SERVICE_UNAVAILABLE,
                details={"provider": provider, "model": model_name},
                cause=e,
            )
        except ContentPolicyViolationError as e:
            raise LLMError(
                message=f"LLM 内容安全策略拒绝请求 (provider: {provider}): {e}",
                error_code=ErrorCode.LLM_ERROR,
                details={"provider": provider, "model": model_name},
                cause=e,
            )
        except BadRequestError as e:
            # 某些提供商（如 OpenAI）对无效 API Key 返回 400 BadRequest 而非 401
            error_msg_lower = str(e).lower()
            if "auth" in error_msg_lower or "api key" in error_msg_lower or "invalid" in error_msg_lower:
                raise LLMError(
                    message=f"API Key 认证失败 (provider: {provider}): {e}",
                    error_code=ErrorCode.LLM_AUTH_ERROR,
                    details={"provider": provider, "model": model_name},
                    cause=e,
                )
            raise LLMError(
                message=f"LLM 请求错误 (provider: {provider}): {e}",
                error_code=ErrorCode.LLM_ERROR,
                details={"provider": provider, "model": model_name},
                cause=e,
            )
        except Exception as e:
            # 兜底：所有未归类异常统一包装为 LLMError，避免原始异常被 execute_step 的重试逻辑吞掉
            raise LLMError(
                message=f"LLM 请求失败 (provider: {provider}, model: {model_name}): {e}",
                error_code=ErrorCode.LLM_ERROR,
                details={"provider": provider, "model": model_name},
                cause=e,
            )

    async def _process_chunk(self, chunk) -> AsyncGenerator[dict, None]:
        if hasattr(chunk, "usage") and chunk.usage:
            self.input_tokens_used = chunk.usage.prompt_tokens
            self.output_tokens_used = chunk.usage.completion_tokens

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
        text_content = content.get("content")
        tool_calls = self.aggregate_tool_calls(tool_call_chunks)
        if (not text_content or not text_content.strip()) and not tool_calls:
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
