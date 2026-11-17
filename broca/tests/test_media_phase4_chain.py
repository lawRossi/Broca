"""Task 4.4: 前端上传解耦链路（upload 输出 → parse_message → local ref → 物化 base64）。

模拟后端 POST /files/upload 的返回结构，验证：
1. parse_message 能从 data.files[].local_path 产出 local ref；
2. get_stream_response 在请求前把该 local ref 物化为 base64 wire；
3. 原始传入 messages 不被就地修改。
"""

import hashlib
from urllib.parse import quote

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


def _upload_response(path, data, name="pic.png", mime="image/png"):
    """Mirror the shape returned by POST /files/upload."""
    abs_path = str(path)
    return {
        "name": name,
        "url": f"/files/raw?path={quote(abs_path)}",
        "path": abs_path,
        "local_path": abs_path,
        "size": len(data),
        "type": mime,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


async def _drain(agen):
    async for _ in agen:
        pass


@pytest.mark.asyncio
async def test_upload_output_materializes_to_base64(tmp_path, monkeypatch):
    data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    p = tmp_path / "pic.png"
    p.write_bytes(data)

    upload = _upload_response(p, data)

    msg = Message(
        message_id="msg_phase4_chain",
        session_id="s",
        role="user",
        message_type=MessageType.USER_MESSAGE,
        data={"content": "look", "files": [upload]},
    )

    client = LiteLLMClient(config=CONFIG)
    parsed = client.parse_message("openai", "gpt-4o", msg)

    image_parts = [x for x in parsed["content"] if x.get("type") == "image_url"]
    assert image_parts, "parse_message should yield an image part"
    ref = image_parts[0]["image_url"]["url"]

    meta = decode_media_ref(ref)
    assert meta is not None and meta["kind"] == "local"
    assert meta["path"] == str(p)

    # Now materialize that local ref into base64 wire via get_stream_response.
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)

        async def agen():
            return
            yield  # pragma: no cover

        return agen()

    monkeypatch.setattr("broca.llm.acompletion", fake_acompletion)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": ref}},
                {"type": "text", "text": "describe"},
            ],
        }
    ]
    await _drain(
        client.get_stream_response(
            "openai", "gpt-4o", messages, None, agent_id="a1", session_id="s1"
        )
    )

    url = captured["messages"][0]["content"][0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    # Original messages must stay as ref (not mutated in place).
    assert messages[0]["content"][0]["image_url"]["url"] == ref
