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
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.errors import LLMError, ValidationError
from broca.llm import LLMClient
from broca.session.models import Message, MessageType, MessageRole


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
    with patch.dict(os.environ, {"BROCA_LLM_CONFIG": llm_config_file}):
        client = LLMClient()
        return client


class TestLLMClientInit:
    """测试 LLMClient 初始化"""

    def test_init_with_config_file(self, llm_config_file):
        """测试从配置文件初始化"""
        with patch.dict(os.environ, {"BROCA_LLM_CONFIG": llm_config_file}):
            client = LLMClient()
            assert "openai" in client.config
            assert "deepseek" in client.config
            assert client.config["openai"]["api_key"] == "test-key"

    def test_env_key_override(self, llm_config_file):
        """测试环境变量覆盖 API Key"""
        with patch.dict(
            os.environ,
            {
                "BROCA_LLM_CONFIG": llm_config_file,
                "BROCA_API_KEY_OPENAI": "env-override-key",
            },
        ):
            client = LLMClient()
            assert client.config["openai"]["api_key"] == "env-override-key"

    def test_env_base_url_override(self, llm_config_file):
        """测试环境变量覆盖 Base URL"""
        with patch.dict(
            os.environ,
            {
                "BROCA_LLM_CONFIG": llm_config_file,
                "BROCA_API_BASE_URL_DEEPSEEK": "https://custom.deepseek.com",
            },
        ):
            client = LLMClient()
            assert client.config["deepseek"]["base_url"] == "https://custom.deepseek.com"

    def test_unknown_provider_raises_error(self, llm_config_file):
        """测试未知提供商抛出异常"""
        with patch.dict(os.environ, {"BROCA_LLM_CONFIG": llm_config_file}):
            client = LLMClient()
            with pytest.raises(ValidationError) as excinfo:
                client.parse_message("unknown_provider", "gpt-4o", MagicMock())
            assert "未知 LLM 提供商" in str(excinfo.value)

    def test_unknown_model_raises_error(self, llm_config_file):
        """测试未知模型抛出异常"""
        with patch.dict(os.environ, {"BROCA_LLM_CONFIG": llm_config_file}):
            client = LLMClient()
            with pytest.raises(ValidationError) as excinfo:
                client.parse_message("openai", "unknown-model", MagicMock())
            assert "未知 LLM 模型" in str(excinfo.value)

    def test_token_counters_init(self, llm_config_file):
        """测试 token 计数器初始化"""
        with patch.dict(os.environ, {"BROCA_LLM_CONFIG": llm_config_file}):
            client = LLMClient()
            assert client.input_tokens_used == 0
            assert client.output_tokens_used == 0


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
