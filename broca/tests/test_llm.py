"""
LLMClient 单元测试

覆盖：
- LLMClient 初始化（配置文件加载、环境变量覆盖）
- parse_message 方法（多种消息类型）
- aggregate_content / aggregate_tool_calls
- 异常处理（各类型的异常被正确转换为 LLMError）
"""

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.errors import LLMError, ValidationError
from broca.llm import LLMClient
from broca.session.models import Message, MessageType


# ============================================================================
# 测试用配置
# ============================================================================

SAMPLE_CONFIG = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "test-key",
        "models": {
            "gpt-4o": {
                "model": "gpt-4o",
                "meta": {"modality": {"image": {}}},
            }
        },
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key": "test-ds-key",
        "models": {
            "deepseek-chat": {
                "model": "deepseek-chat",
                "meta": {"modality": {}},
                "temperature": 0.7,
            }
        },
    },
}


@pytest.fixture
def llm_config_file():
    """创建临时 LLM 配置文件"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(SAMPLE_CONFIG, f)
        config_path = f.name

    try:
        yield config_path
    finally:
        os.unlink(config_path)


@pytest.fixture
def llm_client(llm_config_file):
    """创建 LLMClient 实例"""
    with patch("broca.configs.resolve_llm_config_path", return_value=__import__("pathlib").Path(llm_config_file)):
        client = LLMClient()
        return client


class TestLLMClientInit:
    """测试 LLMClient 初始化"""

    def test_init_with_config_file(self, llm_config_file):
        """测试从配置文件初始化"""
        from pathlib import Path
        with patch("broca.configs.resolve_llm_config_path", return_value=Path(llm_config_file)):
            client = LLMClient()
            assert "openai" in client.config
            assert "deepseek" in client.config
            assert client.config["openai"]["api_key"] == "test-key"

    def test_config_file_values_used_as_is(self, llm_config_file):
        """测试配置文件中的值直接生效（无环境变量覆盖）"""
        from pathlib import Path
        with patch("broca.configs.resolve_llm_config_path", return_value=Path(llm_config_file)):
            client = LLMClient()
            assert client.config["openai"]["api_key"] == "test-key"
            assert client.config["deepseek"]["base_url"] == "https://api.deepseek.com"

    def test_unknown_provider_raises_error(self, llm_config_file):
        """测试未知提供商抛出异常"""
        from pathlib import Path
        with patch("broca.configs.resolve_llm_config_path", return_value=Path(llm_config_file)):
            client = LLMClient()
            with pytest.raises(ValidationError) as excinfo:
                client.parse_message("unknown_provider", "gpt-4o", MagicMock())
            assert "未知 LLM 提供商" in str(excinfo.value)

    def test_unknown_model_raises_error(self, llm_config_file):
        """测试未知模型抛出异常"""
        from pathlib import Path
        with patch("broca.configs.resolve_llm_config_path", return_value=Path(llm_config_file)):
            client = LLMClient()
            with pytest.raises(ValidationError) as excinfo:
                client.parse_message("openai", "unknown-model", MagicMock())
            assert "未知 LLM 模型" in str(excinfo.value)

    def test_no_mutable_token_state(self, llm_config_file):
        """LiteLLMClient 实例不应持有可变 token 计数器（已通过 stream usage 事件传递）"""
        from pathlib import Path
        with patch("broca.configs.resolve_llm_config_path", return_value=Path(llm_config_file)):
            client = LLMClient()
            assert "input_tokens_used" not in vars(client)
            assert "output_tokens_used" not in vars(client)


class TestParseMessage:
    """测试 parse_message 方法"""

    def test_parse_user_message(self, llm_client):
        """测试解析用户消息"""
        msg = MagicMock(spec=Message)
        msg.message_type = MessageType.USER_MESSAGE
        msg.data = {"content": "Hello, world!"}

        result = llm_client.parse_message("openai", "gpt-4o", msg)
        assert result["role"] == "user"
        assert result["content"] == "Hello, world!"

    def test_parse_task_start(self, llm_client):
        """测试解析任务开始消息"""
        msg = MagicMock(spec=Message)
        msg.message_type = MessageType.TASK_START
        msg.data = {"task_description": "Do something"}

        result = llm_client.parse_message("openai", "gpt-4o", msg)
        assert result["role"] == "user"
        assert result["content"] == "Do something"

    def test_parse_task_complete(self, llm_client):
        """测试解析任务完成消息"""
        msg = MagicMock(spec=Message)
        msg.message_type = MessageType.TASK_COMPLETE
        msg.data = {"result": "Task completed successfully"}

        result = llm_client.parse_message("openai", "gpt-4o", msg)
        assert result["role"] == "user"
        assert result["content"] == "Task completed successfully"

    def test_parse_task_error(self, llm_client):
        """测试解析任务错误消息"""
        msg = MagicMock(spec=Message)
        msg.message_type = MessageType.TASK_ERROR
        msg.data = {"error_message": "Something went wrong"}

        result = llm_client.parse_message("openai", "gpt-4o", msg)
        assert result["role"] == "user"
        assert result["content"] == "Something went wrong"

    def test_parse_unknown_type(self, llm_client):
        """测试未知消息类型（无匹配分支时返回空字典）"""
        msg = MagicMock(spec=Message)
        # 使用一个不会被 parse_message 的 if/elif 链匹配到的枚举值
        msg.message_type = MessageType.PING
        msg.data = {}

        result = llm_client.parse_message("openai", "gpt-4o", msg)
        assert result == {}


class TestParseMessageRawInput:
    """回归测试: parse_message 必须始终为 USER_MESSAGE 设置 raw_input（纯文本）。

    Bug: 之前 raw_input 仅在有非媒体文件附件时才被设置。
    当用户只发送图片时 raw_input=None，广播 hook 将 LLM content parts
    (list of dicts) 直接作为 data.content 发给前端，导致 [object Object]。
    """

    def test_raw_input_set_for_text_only(self, llm_client):
        """纯文本消息 → raw_input = 文本本身"""
        msg = MagicMock(spec=Message)
        msg.message_type = MessageType.USER_MESSAGE
        msg.data = {"content": "Hello, world!"}

        result = llm_client.parse_message("openai", "gpt-4o", msg)
        assert result["raw_input"] == "Hello, world!"
        assert isinstance(result["raw_input"], str)

    def test_raw_input_set_for_image_only(self, llm_client):
        """图片消息（无文本）→ raw_input = 空字符串，content 是 list"""
        msg = MagicMock(spec=Message)
        msg.message_type = MessageType.USER_MESSAGE
        msg.data = {
            "content": "",
            "files": [
                {"name": "photo.png", "url": "http://cdn/x.png", "type": "image/png"},
            ],
        }

        result = llm_client.parse_message("openai", "gpt-4o", msg)
        # content 是多模态 list
        assert isinstance(result["content"], list)
        image_parts = [p for p in result["content"] if p.get("type") == "image_url"]
        assert len(image_parts) == 1
        # raw_input 必须是字符串（不能是 None 或 list）
        assert result["raw_input"] is not None
        assert isinstance(result["raw_input"], str)

    def test_raw_input_set_for_text_and_image(self, llm_client):
        """文本 + 图片 → raw_input = 原始文本（不含文件 section）"""
        msg = MagicMock(spec=Message)
        msg.message_type = MessageType.USER_MESSAGE
        msg.data = {
            "content": "Check this image",
            "files": [
                {"name": "a.png", "url": "http://cdn/a.png", "type": "image/png"},
            ],
        }

        result = llm_client.parse_message("openai", "gpt-4o", msg)
        assert result["raw_input"] == "Check this image"
        assert isinstance(result["content"], list)  # multimodal

    def test_raw_input_not_polluted_by_file_section(self, llm_client):
        """有非媒体文件时，raw_input 不应包含 [附件文件] section"""
        msg = MagicMock(spec=Message)
        msg.message_type = MessageType.USER_MESSAGE
        msg.data = {
            "content": "read this pdf",
            "files": [
                {"name": "doc.pdf", "url": "http://cdn/doc.pdf", "type": "application/pdf"},
            ],
        }

        result = llm_client.parse_message("openai", "gpt-4o", msg)
        # raw_input 应保留原始文本，不应包含文件 section
        assert result["raw_input"] == "read this pdf"
        # content 中应包含文件 section
        if isinstance(result["content"], str):
            assert "[附件文件]" in result["content"]

    def test_raw_input_for_existing_raw_input_passthrough(self, llm_client):
        """message.data 已有 raw_input 时应透传（不覆盖）"""
        msg = MagicMock(spec=Message)
        msg.message_type = MessageType.USER_MESSAGE
        msg.data = {
            "content": "new text",
            "raw_input": "original input",
        }

        result = llm_client.parse_message("openai", "gpt-4o", msg)
        assert result["raw_input"] == "original input"


class TestAggregateFunctions:
    """测试聚合函数"""

    def test_aggregate_content(self, llm_client):
        """测试聚合内容"""
        chunks = [
            {"type": "content", "data": "Hello"},
            {"type": "content", "data": " World"},
            {"type": "reasoning_content", "data": "thinking..."},
        ]
        result = llm_client.aggregate_content(chunks)
        assert result["content"] == "Hello World"
        assert result["reasoning_content"] == "thinking..."

    def test_aggregate_content_empty(self, llm_client):
        """测试空内容聚合"""
        result = llm_client.aggregate_content([])
        assert result["content"] == ""
        assert result["reasoning_content"] == ""

    def test_aggregate_tool_calls(self, llm_client):
        """测试聚合工具调用"""
        mock_chunk1 = MagicMock()
        mock_chunk1.index = 0
        mock_chunk1.id = "call_1"
        mock_chunk1.function.name = "read_file"
        mock_chunk1.function.arguments = '{"path":'

        mock_chunk2 = MagicMock()
        mock_chunk2.index = 0
        mock_chunk2.id = None
        mock_chunk2.function.name = None
        mock_chunk2.function.arguments = ' "/tmp/test"}'

        result = llm_client.aggregate_tool_calls([mock_chunk1, mock_chunk2])
        assert len(result) == 1
        assert result[0]["id"] == "call_1"
        assert result[0]["function"]["name"] == "read_file"
        assert result[0]["function"]["arguments"] == '{"path": "/tmp/test"}'

    def test_aggregate_tool_calls_empty(self, llm_client):
        """测试空工具调用聚合"""
        result = llm_client.aggregate_tool_calls([])
        assert result == []

    def test_aggregate_message_with_content(self, llm_client):
        """测试聚合完整消息"""
        content_chunks = [
            {"type": "content", "data": "Hello"},
            {"type": "reasoning_content", "data": "thinking"},
            {"type": "content", "data": " World"},
        ]
        result = llm_client.aggregate_message(content_chunks, [])
        assert result is not None
        assert result["role"] == "assistant"
        assert result["content"] == "Hello World"

    def test_aggregate_message_empty(self, llm_client):
        """测试空消息聚合返回 None"""
        result = llm_client.aggregate_message([], [])
        assert result is None

    def test_aggregate_message_reasoning_only_not_empty(self, llm_client):
        """回归：仅有 reasoning_content（思考块）而正文为空时不应被判为"空响应"。

        推理型模型可能只返回思考块，此前会被误判为空响应从而触发无谓重试。
        """
        content_chunks = [{"type": "reasoning_content", "data": "thinking..."}]
        result = llm_client.aggregate_message(content_chunks, [])
        assert result is not None
        assert result["content"] is None or result["content"] == ""
        # 思考块应被保留在聚合结果中
        provider_fields = getattr(result, "provider_specific_fields", None) or {}
        assert (result.get("reasoning_content") or provider_fields.get("reasoning_content")) == "thinking..."

    def test_aggregate_message_whitespace_only_still_empty(self, llm_client):
        """仅空白正文 + 无思考块 + 无工具调用，仍应判为空响应"""
        content_chunks = [{"type": "content", "data": "   \n\t  "}]
        result = llm_client.aggregate_message(content_chunks, [])
        assert result is None


class TestGetStreamResponseErrors:
    """测试 get_stream_response 异常处理"""

    @pytest.mark.asyncio
    async def test_unknown_provider(self, llm_client):
        """测试未知提供商"""
        with pytest.raises(ValidationError) as excinfo:
            async for _ in llm_client.get_stream_response("unknown", "gpt-4o", []):
                pass
        assert "未知 LLM 提供商" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_unknown_model(self, llm_client):
        """测试未知模型"""
        with pytest.raises(ValidationError) as excinfo:
            async for _ in llm_client.get_stream_response("openai", "unknown-model", []):
                pass
        assert "未知 LLM 模型" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_auth_error(self, llm_client):
        """测试认证错误转换"""
        from litellm.exceptions import AuthenticationError

        with patch(
            "broca.llm.acompletion",
            new=AsyncMock(side_effect=AuthenticationError(
                message="Invalid API key",
                llm_provider="openai",
                model="gpt-4o",
                response=MagicMock(status_code=401),
            )),
        ):
            with pytest.raises(LLMError) as excinfo:
                async for _ in llm_client.get_stream_response("openai", "gpt-4o", []):
                    pass
            assert "认证失败" in str(excinfo.value) or "auth" in str(excinfo.value).lower()

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, llm_client):
        """测试限流错误转换"""
        from litellm.exceptions import RateLimitError

        with patch(
            "broca.llm.acompletion",
            new=AsyncMock(side_effect=RateLimitError(
                message="Rate limited",
                llm_provider="openai",
                model="gpt-4o",
                response=MagicMock(status_code=429),
            )),
        ):
            with pytest.raises(LLMError) as excinfo:
                async for _ in llm_client.get_stream_response("openai", "gpt-4o", []):
                    pass
            assert "限流" in str(excinfo.value) or "rate" in str(excinfo.value).lower()

    @pytest.mark.asyncio
    async def test_timeout_error(self, llm_client):
        """测试超时错误转换"""
        from litellm.exceptions import Timeout

        with patch(
            "broca.llm.acompletion",
            new=AsyncMock(side_effect=Timeout(
                message="Request timed out",
                model="gpt-4o",
                llm_provider="openai",
            )),
        ):
            with pytest.raises(LLMError) as excinfo:
                async for _ in llm_client.get_stream_response("openai", "gpt-4o", []):
                    pass
            assert "超时" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_context_window_error(self, llm_client):
        """测试上下文超长错误转换"""
        from litellm.exceptions import ContextWindowExceededError

        with patch(
            "broca.llm.acompletion",
            new=AsyncMock(side_effect=ContextWindowExceededError(
                message="Context window exceeded",
                model="gpt-4o",
                llm_provider="openai",
                response=MagicMock(status_code=400),
            )),
        ):
            with pytest.raises(LLMError) as excinfo:
                async for _ in llm_client.get_stream_response("openai", "gpt-4o", []):
                    pass
            assert "上下文" in str(excinfo.value)


class TestProcessChunk:
    """测试 _process_chunk 方法"""

    @pytest.mark.asyncio
    async def test_process_content_chunk(self, llm_client):
        """测试处理内容块"""
        mock_chunk = MagicMock()
        mock_chunk.usage = None
        mock_chunk.choices = [
            MagicMock(
                delta=MagicMock(
                    content="Hello",
                    reasoning_content=None,
                    tool_calls=None,
                ),
                finish_reason=None,
            )
        ]

        results = []
        async for result in llm_client._process_chunk(mock_chunk):
            results.append(result)

        assert len(results) == 1
        assert results[0]["type"] == "content"
        assert results[0]["data"] == "Hello"

    @pytest.mark.asyncio
    async def test_process_empty_chunk(self, llm_client):
        """测试处理空块"""
        mock_chunk = MagicMock()
        mock_chunk.usage = None
        mock_chunk.choices = None

        results = []
        async for result in llm_client._process_chunk(mock_chunk):
            results.append(result)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_process_finish_reason(self, llm_client):
        """测试处理结束原因"""
        mock_chunk = MagicMock()
        mock_chunk.usage = None
        mock_chunk.choices = [
            MagicMock(
                delta=MagicMock(content=None, reasoning_content=None, tool_calls=None),
                finish_reason="stop",
            )
        ]

        results = []
        async for result in llm_client._process_chunk(mock_chunk):
            results.append(result)

        assert len(results) == 1
        assert results[0]["type"] == "finish"
        assert results[0]["data"] == "stop"
