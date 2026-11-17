"""parse_message 对 files 产出 ref 的单元测试（Task 1.3）。"""

import uuid

import pytest

from broca.llm import LiteLLMClient
from broca.media.ref import decode_media_ref
from broca.session.models import Message, MessageType

CONFIG = {
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


def _make_client():
    return LiteLLMClient(config=CONFIG)


def _make_message(files):
    return Message(
        message_id=f"msg_{uuid.uuid4().hex[:16]}",
        session_id="s",
        role="user",
        message_type=MessageType.USER_MESSAGE,
        data={"content": "hi", "files": files},
    )


def _image_url(result):
    parts = [p for p in result["content"] if p.get("type") == "image_url"]
    return parts[0]["image_url"]["url"]


class TestParseMessageRef:
    def test_cloud_ref_from_storage_key(self):
        client = _make_client()
        msg = _make_message(
            [
                {
                    "name": "a.png",
                    "url": "https://cdn/a.png",
                    "type": "image/png",
                    "storage_key": "uploads/a.png",
                    "sha256": "abc",
                    "size": 10,
                }
            ]
        )
        result = client.parse_message("openai", "gpt-4o", msg)
        meta = decode_media_ref(_image_url(result))
        assert meta["kind"] == "cloud"
        assert meta["key"] == "uploads/a.png"
        assert meta["url"] == "https://cdn/a.png"

    def test_local_ref_from_local_path(self):
        client = _make_client()
        msg = _make_message(
            [
                {
                    "name": "a.png",
                    "url": "/files/raw?path=/tmp/a.png",
                    "type": "image/png",
                    "local_path": "/tmp/a.png",
                    "sha256": "abc",
                    "size": 10,
                }
            ]
        )
        result = client.parse_message("openai", "gpt-4o", msg)
        meta = decode_media_ref(_image_url(result))
        assert meta["kind"] == "local"
        assert meta["path"] == "/tmp/a.png"

    def test_local_ref_from_absolute_path(self):
        client = _make_client()
        msg = _make_message(
            [
                {
                    "name": "a.png",
                    "url": "",
                    "type": "image/png",
                    "path": "/abs/a.png",
                }
            ]
        )
        result = client.parse_message("openai", "gpt-4o", msg)
        meta = decode_media_ref(_image_url(result))
        assert meta["kind"] == "local"
        assert meta["path"] == "/abs/a.png"

    def test_legacy_relative_path_plus_url_becomes_cloud(self):
        client = _make_client()
        msg = _make_message(
            [
                {
                    "name": "a.png",
                    "url": "https://r2.example.com/uploads/a.png",
                    "type": "image/png",
                    "path": "uploads/2024/a.png",
                }
            ]
        )
        result = client.parse_message("openai", "gpt-4o", msg)
        meta = decode_media_ref(_image_url(result))
        assert meta["kind"] == "cloud"
        assert meta["key"] == "uploads/2024/a.png"

    def test_plain_url_no_ref(self):
        client = _make_client()
        msg = _make_message(
            [
                {
                    "name": "a.png",
                    "url": "https://cdn/a.png",
                    "type": "image/png",
                }
            ]
        )
        result = client.parse_message("openai", "gpt-4o", msg)
        assert _image_url(result) == "https://cdn/a.png"

    def test_no_base64_in_output(self):
        client = _make_client()
        msg = _make_message(
            [
                {
                    "name": "a.png",
                    "url": "https://cdn/a.png",
                    "type": "image/png",
                    "storage_key": "uploads/a.png",
                    "sha256": "abc",
                    "size": 10,
                }
            ]
        )
        result = client.parse_message("openai", "gpt-4o", msg)
        import json

        assert "base64," not in json.dumps(result)
