"""Phase 1 integration: ref persists in DB content and survives history rebuild."""

import json

import pytest

from broca.media.ref import decode_media_ref, encode_media_ref


REF = encode_media_ref(
    {
        "kind": "local",
        "path": "/tmp/x.png",
        "url": "/files/raw?path=%2Ftmp%2Fx.png",
        "sha256": "abc",
        "mime": "image/png",
        "size": 10,
    }
)


class TestDbContent:
    def test_ref_in_saved_content_no_base64(self):
        """A tool-injected image message stored as JSON keeps the ref, no base64."""
        llm_message = {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": REF}},
                {"type": "text", "text": "Image Loaded."},
            ],
        }
        stored = json.dumps(llm_message, ensure_ascii=False)
        assert "ref://" in stored
        assert "base64," not in stored


class TestHistoryRebuildPreservesRef:
    @pytest.mark.asyncio
    async def test_rebuild_keeps_ref(self):
        from unittest.mock import AsyncMock, MagicMock

        from broca.agent_configs import AgentConfig
        from broca.context import Context
        from broca.session.models import Message, MessageRole, MessageType

        llm_message = {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": REF}},
                {"type": "text", "text": "Image Loaded."},
            ],
        }
        db_message = MagicMock(spec=Message)
        db_message.message_id = "msg_1"
        db_message.message_type = MessageType.USER_MESSAGE
        db_message.is_truncated = False
        db_message.is_expired = False
        db_message.data = {"content": json.dumps(llm_message), "files": []}
        db_message.role = MessageRole.USER

        agent_config = MagicMock(spec=AgentConfig)
        agent_config.workspace = "/tmp"
        agent_config.system_prompt_template = "sys"
        agent_config.environment = None
        agent_config.role_description = None
        agent_config.skills = []

        session_manager = AsyncMock()
        session_manager.session_id = "s"

        async def mock_get_messages(agent_id=None):
            return [db_message]

        session_manager.get_messages = mock_get_messages

        context = Context(agent_config, session_manager)
        await context.build_history_from_session("agent_1")

        user_msgs = [m for m in context.history if m.get("role") == "user"]
        assert user_msgs
        url = user_msgs[-1]["content"][0]["image_url"]["url"]
        assert decode_media_ref(url) is not None
        assert "base64," not in json.dumps(context.history)
