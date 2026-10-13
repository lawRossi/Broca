"""
ReadImage Tool 单元测试

覆盖：
- 文件校验（不存在 / 非图片格式）
- 存储配置校验（未配置 / Cloudflare / Supabase）
- S3 上传成功/失败（mock boto3）
- ToolResult extra_context_messages 格式
- 消息序列顺序（tool result 在 user image message 之前）
- build_history_from_session 重建
- parse_message 多模态消息处理
"""

import asyncio
import json
import os
import tempfile
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.tools.tool import ToolCallContext, ToolResult, ToolStatus
from broca.tools.image import (
    ReadImage,
    _generate_storage_path,
    _generate_unique_filename,
    SUPPORTED_IMAGE_EXTENSIONS,
)
from broca.tools.tool_manager import ToolManager


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def tool():
    return ReadImage()


@pytest.fixture
def context():
    ctx = ToolCallContext()
    ctx.workspace = tempfile.gettempdir()
    return ctx


@pytest.fixture
def mock_agent():
    """Mock agent with image-capable LLM."""
    agent = MagicMock()
    agent.llm_client = MagicMock()
    agent.llm_client.config = {
        "openai": {
            "models": {
                "gpt-4o": {
                    "meta": {"modality": {"text": "", "image": {}}}
                }
            }
        }
    }
    agent.config = MagicMock()
    agent.config.provider = "openai"
    agent.config.model = "gpt-4o"
    return agent


@pytest.fixture
def mock_storage_cloudflare():
    s = MagicMock()
    s.backend = "cloudflare"
    s.cloudflare_account_id = "test-account-123"
    s.cloudflare_access_key_id = "access-key"
    s.cloudflare_secret_access_key = "secret-key"
    s.cloudflare_bucket = "test-bucket"
    s.cloudflare_public_url = "https://cdn.example.com"
    s.supabase_url = ""
    s.supabase_s3_access_key_id = ""
    s.supabase_s3_secret_access_key = ""
    s.supabase_bucket = ""
    return s


@pytest.fixture
def mock_storage_supabase():
    s = MagicMock()
    s.backend = "supabase"
    s.supabase_url = "https://abc.supabase.co"
    s.supabase_s3_access_key_id = "sb-access"
    s.supabase_s3_secret_access_key = "sb-secret"
    s.supabase_bucket = "sb-bucket"
    s.cloudflare_account_id = ""
    s.cloudflare_access_key_id = ""
    s.cloudflare_secret_access_key = ""
    s.cloudflare_bucket = ""
    s.cloudflare_public_url = ""
    return s


@pytest.fixture
def dummy_image(tmp_path):
    """Create a temporary dummy image file."""
    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    return str(img)


@pytest.fixture
def dummy_text(tmp_path):
    """Create a temporary dummy text file."""
    txt = tmp_path / "test.txt"
    txt.write_text("hello world")
    return str(txt)


# ── Helper function tests ─────────────────────────────────────


class TestGenerateFilename:
    def test_basic(self):
        result = _generate_unique_filename("photo.png")
        assert result.endswith(".png")
        parts = result.rsplit("_", 1)
        assert parts[0] == "photo"

    def test_chinese_filename(self):
        result = _generate_unique_filename("图片.png")
        # Should be URL-encoded
        assert "图片" not in result
        assert result.endswith(".png")

    def test_no_extension(self):
        result = _generate_unique_filename("file")
        assert "." not in result[-1:]


class TestGenerateStoragePath:
    def test_format(self):
        path = _generate_storage_path("photo.png")
        date_str = datetime.now().strftime("%Y%m%d")
        assert path.startswith(f"uploads/{date_str}/")
        assert path.endswith(".png")


# ── Tool metadata ─────────────────────────────────────────────


class TestReadImageMetadata:
    def test_name(self, tool):
        assert tool.name == "read_image"

    def test_description(self, tool):
        assert "image" in tool.description.lower()

    def test_parameters(self, tool):
        params = tool.parameters
        assert "file_path" in params["properties"]
        assert "file_path" in params["required"]

    def test_auto_discovered(self):
        tm = ToolManager()
        assert "read_image" in tm.tools
        assert tm.tools["read_image"].name == "read_image"

    def test_in_readonly(self):
        assert "read_image" in ToolManager.READONLY_TOOLS

    def test_not_in_modify(self):
        assert "read_image" not in ToolManager.MODIFY_TOOLS


# ── File validation ───────────────────────────────────────────


class TestFileValidation:
    @pytest.mark.asyncio
    async def test_file_not_found(self, tool, context):
        result = await tool._execute({"file_path": "/nonexistent/image.png"}, context)
        assert result.status == ToolStatus.ERROR
        assert "文件不存在" in result.content
        assert result.extra_context_messages == []

    @pytest.mark.asyncio
    async def test_non_image_file(self, tool, context, dummy_text):
        result = await tool._execute({"file_path": dummy_text}, context)
        assert result.status == ToolStatus.ERROR
        assert "不是图片文件" in result.content
        assert result.extra_context_messages == []

    @pytest.mark.asyncio
    async def test_workspace_relative_path(self, tool, tmp_path, dummy_image):
        # Place image inside the workspace
        ctx = ToolCallContext()
        ctx.workspace = str(tmp_path)
        # The dummy_image fixture is already in tmp_path
        result = await tool._execute(
            {"file_path": "test.png"}, ctx
        )
        # Will fail at storage config (not at file validation),
        # which proves file was found
        if result.status == ToolStatus.ERROR:
            assert "文件不存在" not in result.content


# ── Storage config validation ─────────────────────────────────


class TestStorageValidation:
    @pytest.mark.asyncio
    async def test_no_storage_configured(self, tool, context, dummy_image):
        mock_cfg = MagicMock()
        mock_cfg.storage = MagicMock()
        mock_cfg.storage.backend = ""
        with patch("broca.tools.image.get_configs", return_value=mock_cfg):
            result = await tool._execute({"file_path": dummy_image}, context)
        assert result.status == ToolStatus.ERROR
        assert "云端存储未配置" in result.content
        assert result.extra_context_messages == []

    @pytest.mark.asyncio
    async def test_invalid_backend(self, tool, context, dummy_image):
        mock_cfg = MagicMock()
        mock_cfg.storage = MagicMock()
        mock_cfg.storage.backend = "s3"  # not cloudflare/supabase
        with patch("broca.tools.image.get_configs", return_value=mock_cfg):
            result = await tool._execute({"file_path": dummy_image}, context)
        assert result.status == ToolStatus.ERROR
        assert "云端存储未配置" in result.content


# ── S3 upload ─────────────────────────────────────────────────


class TestS3Upload:
    @pytest.mark.asyncio
    async def test_upload_success_cloudflare(
        self, tool, context, mock_agent, mock_storage_cloudflare, dummy_image
    ):
        ctx = ToolCallContext()
        ctx.workspace = context.workspace
        ctx.agent = mock_agent

        mock_s3 = MagicMock()
        mock_s3.upload_file = MagicMock()  # success

        mock_cfg = MagicMock()
        mock_cfg.storage = mock_storage_cloudflare

        with (
            patch("broca.tools.image.get_configs", return_value=mock_cfg),
            patch.object(
                ReadImage, "_create_s3_client", return_value=mock_s3
            ),
            patch.object(
                ReadImage,
                "_get_public_url_base",
                return_value="https://cdn.example.com",
            ),
        ):
            result = await tool._execute({"file_path": dummy_image}, ctx)

        assert result.status == ToolStatus.SUCCESS
        assert "图片已读取" in result.content
        # S3 client was called
        mock_s3.upload_file.assert_called_once()
        call_args = mock_s3.upload_file.call_args
        assert call_args[0][1] == "test-bucket"  # bucket
        assert call_args[0][2].startswith("uploads/")  # storage path

        # extra_context_messages
        assert len(result.extra_context_messages) == 1
        extra = result.extra_context_messages[0]
        assert extra["role"] == "user"
        assert extra["llm_message"]["role"] == "user"
        content = extra["llm_message"]["content"]
        assert isinstance(content, list)
        assert content[0]["type"] == "image_url"
        assert "url" in content[0]["image_url"]
        # DB data
        assert extra["data"]["files"][0]["name"] == "test.png"
        assert "https://" in extra["data"]["files"][0]["url"]

    @pytest.mark.asyncio
    async def test_upload_success_supabase(
        self, tool, context, mock_agent, mock_storage_supabase, dummy_image
    ):
        ctx = ToolCallContext()
        ctx.workspace = context.workspace
        ctx.agent = mock_agent

        mock_s3 = MagicMock()
        mock_s3.upload_file = MagicMock()

        mock_cfg = MagicMock()
        mock_cfg.storage = mock_storage_supabase

        with (
            patch("broca.tools.image.get_configs", return_value=mock_cfg),
            patch.object(
                ReadImage, "_create_s3_client", return_value=mock_s3
            ),
            patch.object(
                ReadImage,
                "_get_public_url_base",
                return_value="https://abc.supabase.co/storage/v1/object/public/sb-bucket",
            ),
        ):
            result = await tool._execute({"file_path": dummy_image}, ctx)

        assert result.status == ToolStatus.SUCCESS
        mock_s3.upload_file.assert_called_once()
        call_args = mock_s3.upload_file.call_args
        assert call_args[0][1] == "sb-bucket"

    @pytest.mark.asyncio
    async def test_upload_failure(
        self, tool, context, mock_agent, mock_storage_cloudflare, dummy_image
    ):
        ctx = ToolCallContext()
        ctx.workspace = context.workspace
        ctx.agent = mock_agent

        mock_s3 = MagicMock()
        mock_s3.upload_file = MagicMock(
            side_effect=Exception("Connection timeout")
        )

        mock_cfg = MagicMock()
        mock_cfg.storage = mock_storage_cloudflare

        with (
            patch("broca.tools.image.get_configs", return_value=mock_cfg),
            patch.object(
                ReadImage, "_create_s3_client", return_value=mock_s3
            ),
        ):
            result = await tool._execute({"file_path": dummy_image}, ctx)

        assert result.status == ToolStatus.ERROR
        assert "上传失败" in result.content
        assert "Connection timeout" in result.content
        assert result.extra_context_messages == []

    @pytest.mark.asyncio
    async def test_model_no_image_support(
        self, tool, context, mock_storage_cloudflare, dummy_image
    ):
        """When model doesn't support image, return text-only URL."""
        mock_agent_no_image = MagicMock()
        mock_agent_no_image.llm_client = MagicMock()
        mock_agent_no_image.llm_client.config = {
            "openai": {
                "models": {
                    "gpt-4o": {
                        "meta": {"modality": {"text": ""}}  # no image
                    }
                }
            }
        }
        mock_agent_no_image.config = MagicMock()
        mock_agent_no_image.config.provider = "openai"
        mock_agent_no_image.config.model = "gpt-4o"

        ctx = ToolCallContext()
        ctx.workspace = context.workspace
        ctx.agent = mock_agent_no_image

        mock_s3 = MagicMock()
        mock_s3.upload_file = MagicMock()

        mock_cfg = MagicMock()
        mock_cfg.storage = mock_storage_cloudflare

        with (
            patch("broca.tools.image.get_configs", return_value=mock_cfg),
            patch.object(
                ReadImage, "_create_s3_client", return_value=mock_s3
            ),
            patch.object(
                ReadImage,
                "_get_public_url_base",
                return_value="https://cdn.example.com",
            ),
        ):
            result = await tool._execute({"file_path": dummy_image}, ctx)

        assert result.status == ToolStatus.SUCCESS
        assert "不支持图片输入" in result.content
        assert result.extra_context_messages == []


# ── S3 client creation ────────────────────────────────────────


class TestS3ClientCreation:
    def test_cloudflare_endpoint(self, tool, mock_storage_cloudflare):
        client = tool._create_s3_client(mock_storage_cloudflare)
        # boto3 S3 client is created successfully
        assert client is not None

    def test_supabase_endpoint(self, tool, mock_storage_supabase):
        client = tool._create_s3_client(mock_storage_supabase)
        assert client is not None

    def test_unsupported_backend(self, tool):
        s = MagicMock()
        s.backend = "azure"
        with pytest.raises(ValueError, match="Unsupported storage backend"):
            tool._create_s3_client(s)


# ── Message sequence verification ─────────────────────────────


class TestMessageSequence:
    """Verify the message ordering: assistant(tool_call) → tool(result) → user(image)."""

    @pytest.mark.asyncio
    async def test_context_history_order(self):
        """
        Simulate the sequence:
        1. assistant sends tool_call for read_image
        2. tool result is processed (saved + added to context)
        3. extra context message (user image) is injected after tool result
        """
        # Build a minimal context-like object
        history = []

        # Step 1: assistant message with tool_calls
        assistant_msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_123",
                    "type": "function",
                    "function": {
                        "name": "read_image",
                        "arguments": json.dumps({"file_path": "test.png"}),
                    },
                }
            ],
        }
        history.append(assistant_msg)

        # Step 2: tool result
        tool_result = {
            "role": "tool",
            "tool_call_id": "call_123",
            "content": "图片已读取并上传: https://cdn.example.com/uploads/20261013/test.png",
        }
        history.append(tool_result)

        # Step 3: user image message (injected via extra_context_messages)
        user_image = {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "https://cdn.example.com/uploads/20261013/test.png"
                    }
                },
                {"type": "text", "text": "Image: test.png"},
            ],
        }
        history.append(user_image)

        # Verify ordering
        assert history[0]["role"] == "assistant"
        assert history[1]["role"] == "tool"
        assert history[2]["role"] == "user"
        # The tool result comes BEFORE the user image message
        assert history[1]["role"] == "tool"
        assert history[2]["content"][0]["type"] == "image_url"

    @pytest.mark.asyncio
    async def test_process_tool_call_result_injection_order(self):
        """
        Verify that process_tool_call_result adds extra messages AFTER the tool result
        in context.history.
        """
        from broca.loop_engine import LoopEngine

        # Create a minimal LoopEngine mock
        engine = MagicMock(spec=LoopEngine)
        engine.config = MagicMock()
        engine.config.interactive = False
        engine.turn_id = "turn_1"
        engine.agent_id = "agent_1"
        engine.session_id = "session_1"
        engine.step_id = "step_1"
        engine.communicator = AsyncMock()
        engine.session_manager = AsyncMock()
        engine.context = MagicMock()

        # Track what's added to context
        added_messages = []

        async def mock_add_message(msg, db_id=None):
            added_messages.append(msg)

        engine.context.add_message = mock_add_message
        engine.context.format_tool_call_result = lambda m: {
            "role": "tool",
            "tool_call_id": "call_123",
            "content": "tool result here",
        }

        # Mock message service
        mock_db_msg = MagicMock()
        engine.session_manager.message_service.get = AsyncMock(return_value=mock_db_msg)
        engine.session_manager.save_message = AsyncMock(return_value=True)

        # Tool call mock
        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function = MagicMock()
        tool_call.function.name = "read_image"
        tool_call.function.arguments = '{"file_path": "test.png"}'

        # ToolResult with extra context messages
        extra_msg = {
            "llm_message": {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://cdn.example.com/img.png"},
                    },
                    {"type": "text", "text": "Image: test.png"},
                ],
            },
            "data": {
                "content": "Image: test.png",
                "files": [
                    {"name": "test.png", "url": "https://cdn.example.com/img.png", "type": "image/png"}
                ],
            },
            "role": "user",
        }
        tool_result = ToolResult(
            status=ToolStatus.SUCCESS,
            content="图片已读取",
            extra_context_messages=[extra_msg],
        )

        # Run process_tool_call_result
        result = await LoopEngine.process_tool_call_result(engine, tool_call, tool_result)

        assert result is True

        # The first message added is the tool result
        assert added_messages[0]["role"] == "tool"
        # The second message added is the user image
        assert added_messages[1]["role"] == "user"
        assert added_messages[1]["content"][0]["type"] == "image_url"

        # save_message should have been called for the extra message
        assert engine.session_manager.save_message.called
        # Verify tool_injected marker is set in the saved data
        save_call = engine.session_manager.save_message.call_args
        saved_data = save_call[1].get("data", {})
        assert saved_data.get("tool_injected") is True

        # No broadcast to frontend (tool_injected messages are internal)
        engine.communicator.send_message.assert_not_called()


# ── parse_message compatibility ───────────────────────────────


class TestParseMessageCompatibility:
    """Verify that the LLM client's parse_message can handle user messages with images."""

    def test_parse_user_message_with_image_files(self):
        """
        Simulate what happens when a user message with image files is parsed.
        The read_image tool's DB data format must be compatible with parse_message.
        """
        from broca.session.models import Message, MessageType

        # Simulate the data that read_image stores in DB
        files = [
            {
                "name": "photo.png",
                "url": "https://cdn.example.com/uploads/20261013/photo.png",
                "type": "image/png",
            }
        ]
        data = {
            "content": "Image: photo.png",
            "files": files,
        }

        # Build a Message object similar to what would be stored
        msg = Message(
            message_id=f"msg_{uuid.uuid4().hex[:16]}",
            session_id="test_session",
            role="user",
            message_type=MessageType.USER_MESSAGE,
            data=data,
        )

        # Use the LLM client's parse_message
        from broca.llm import LLMClient

        # Create a minimal LLM config with image support
        llm_client = MagicMock(spec=LLMClient)
        llm_client.config = {
            "openai": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "models": {
                    "gpt-4o": {
                        "model": "gpt-4o",
                        "meta": {"modality": {"text": "", "image": {}}},
                    }
                },
            }
        }

        # parse_message is an instance method; call it with proper self
        result = LLMClient.parse_message(
            llm_client, provider="openai", model="gpt-4o", message=msg
        )

        assert result["role"] == "user"
        # Content should include image_url parts
        assert isinstance(result["content"], list)
        image_parts = [p for p in result["content"] if p.get("type") == "image_url"]
        assert len(image_parts) == 1
        assert image_parts[0]["image_url"]["url"] == files[0]["url"]


# ── build_history_from_session reconstruction ─────────────────


class TestBuildHistoryReconstruction:
    """Verify build_history_from_session can reconstruct image messages."""

    @pytest.mark.asyncio
    async def test_reconstruct_image_message(self):
        """
        Simulate: a user image message saved by read_image tool is in DB.
        build_history_from_session should reconstruct it correctly.
        """
        from broca.session.models import Message, MessageRole, MessageType

        # The image message as stored by the tool (via process_tool_call_result)
        llm_message = {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "https://cdn.example.com/uploads/20261013/test.png"
                    },
                },
                {"type": "text", "text": "Image: test.png"},
            ],
        }

        # In DB, content is stored as json.dumps(llm_message)
        stored_content = json.dumps(llm_message, ensure_ascii=False)

        db_message = MagicMock(spec=Message)
        db_message.message_id = "msg_test123"
        db_message.message_type = MessageType.USER_MESSAGE
        db_message.is_truncated = False
        db_message.is_expired = False
        db_message.data = {"content": stored_content, "files": []}
        db_message.role = MessageRole.USER

        # Build context with mocked session_manager
        from broca.context import Context
        from broca.agent_configs import AgentConfig

        agent_config = MagicMock(spec=AgentConfig)
        agent_config.workspace = "/tmp"
        agent_config.system_prompt_template = "You are a test agent."
        agent_config.environment = None
        agent_config.role_description = None
        agent_config.skills = []

        session_manager = AsyncMock()
        session_manager.session_id = "test_session"

        # Mock get_messages to return our image message
        async def mock_get_messages(agent_id=None):
            return [db_message]

        session_manager.get_messages = mock_get_messages

        context = Context(agent_config, session_manager)

        # Run build_history_from_session
        await context.build_history_from_session("test_agent")

        # Find the user image message in history
        user_msgs = [m for m in context.history if m.get("role") == "user"]
        # There should be at least one user message (the image)
        assert len(user_msgs) >= 1

        # The last user message should be the image
        image_msg = user_msgs[-1]
        assert isinstance(image_msg["content"], list)
        assert image_msg["content"][0]["type"] == "image_url"
        assert (
            image_msg["content"][0]["image_url"]["url"]
            == "https://cdn.example.com/uploads/20261013/test.png"
        )


# ── Integration: full tool execution with mocked S3 ──────────


class TestFullToolExecution:
    """End-to-end test: tool execution → ToolResult → message structure."""

    @pytest.mark.asyncio
    async def test_full_flow(self, tool, mock_agent, mock_storage_cloudflare, dummy_image):
        """Full flow: validate → upload → construct message → ToolResult."""
        ctx = ToolCallContext()
        ctx.workspace = tempfile.gettempdir()
        ctx.agent = mock_agent

        mock_s3 = MagicMock()
        mock_s3.upload_file = MagicMock()

        mock_cfg = MagicMock()
        mock_cfg.storage = mock_storage_cloudflare

        with (
            patch("broca.tools.image.get_configs", return_value=mock_cfg),
            patch.object(ReadImage, "_create_s3_client", return_value=mock_s3),
            patch.object(
                ReadImage,
                "_get_public_url_base",
                return_value="https://cdn.example.com",
            ),
        ):
            result = await tool.execute(
                arguments=json.dumps({"file_path": dummy_image}),
                context=ctx,
            )

        assert result.status == ToolStatus.SUCCESS
        assert len(result.extra_context_messages) == 1

        # Verify the complete structure
        extra = result.extra_context_messages[0]

        # llm_message: valid LLM API format
        llm = extra["llm_message"]
        assert llm["role"] == "user"
        assert isinstance(llm["content"], list)
        types = [p["type"] for p in llm["content"]]
        assert "image_url" in types
        assert "text" in types

        # data: valid DB format
        assert "content" in extra["data"]
        assert "files" in extra["data"]
        assert extra["data"]["files"][0]["name"] == "test.png"
        assert extra["data"]["files"][0]["type"] == "image/png"

        # role: for DB storage
        assert extra["role"] == "user"

        # to_dict should NOT include extra_context_messages
        d = result.to_dict()
        assert "extra_context_messages" not in d
        assert d["status"] == ToolStatus.SUCCESS
