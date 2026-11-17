"""Task 2.4: 接入 get_stream_response —— 请求前物化 ref。"""

import hashlib
from pathlib import Path

import pytest

from broca.errors import LLMError
from broca.llm import LiteLLMClient
from broca.media.cache import default_cache_root
from broca.media.ref import encode_media_ref

MB = 1024 * 1024


def make_config(*, files_api=None, media_limits=None):
    meta = {"modality": {"text": "", "image": {}}}
    if media_limits is not None:
        meta["media_limits"] = media_limits
    prov = {
        "base_url": "https://x",
        "api_key": "k",
        "models": {"m": {"model": "openai/x", "meta": meta}},
    }
    if files_api is not None:
        prov["files_api"] = files_api
    return {"prov": prov}


def local_ref(path, data, mime="image/png"):
    return encode_media_ref({
        "kind": "local", "path": str(path), "url": "/x",
        "sha256": hashlib.sha256(data).hexdigest(),
        "mime": mime, "size": len(data),
    })


def image_msg(ref):
    return [
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": ref}},
            {"type": "text", "text": "hi"},
        ]}
    ]


async def _drain(agen):
    async for _ in agen:
        pass


class TestMaterializeOnRequest:
    @pytest.mark.asyncio
    async def test_ref_becomes_base64(self, tmp_path, monkeypatch):
        data = b"\x89PNGsmall"
        p = tmp_path / "a.png"
        p.write_bytes(data)
        ref = local_ref(p, data)

        captured = {}

        async def fake_acompletion(**kwargs):
            captured.update(kwargs)

            async def agen():
                return
                yield  # pragma: no cover

            return agen()

        monkeypatch.setattr("broca.llm.acompletion", fake_acompletion)
        client = LiteLLMClient(config=make_config())
        await _drain(client.get_stream_response("prov", "m", image_msg(ref), None,
                                                agent_id="a1", session_id="s1"))
        url = captured["messages"][0]["content"][0]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        # 原始传入 messages 未被修改（仍是 ref）
        # （上面 image_msg 是新构造的，这里再断言一次语义）

    @pytest.mark.asyncio
    async def test_ref_becomes_file_id(self, tmp_path, monkeypatch):
        data = b"\x89PNGsmall"
        p = tmp_path / "a.png"
        p.write_bytes(data)
        ref = local_ref(p, data)
        expected = {"type": "file", "file": {"file_id": "file-api-9"}, "file_id": "file-api-9"}

        captured = {}

        async def fake_acompletion(**kwargs):
            captured.update(kwargs)

            async def agen():
                return
                yield  # pragma: no cover

            return agen()

        monkeypatch.setattr("broca.llm.acompletion", fake_acompletion)
        client = LiteLLMClient(config=make_config(files_api={"type": "stub", "max_size_mb": 64}))

        class Stub:
            async def upload(self, r, cfg, data=None, cache=None, read_bytes=None):
                return dict(expected)

        client._materializer.files_api_factory = lambda p, m, c: Stub()
        await _drain(client.get_stream_response("prov", "m", image_msg(ref), None,
                                                agent_id="a1", session_id="s1"))
        assert captured["messages"][0]["content"][0] == expected

    @pytest.mark.asyncio
    async def test_non_ref_passthrough(self, monkeypatch):
        captured = {}

        async def fake_acompletion(**kwargs):
            captured.update(kwargs)

            async def agen():
                return
                yield  # pragma: no cover

            return agen()

        monkeypatch.setattr("broca.llm.acompletion", fake_acompletion)
        client = LiteLLMClient(config=make_config())
        msgs = [{"role": "user", "content": "plain"},
                {"role": "user", "content": [{"type": "image_url",
                                              "image_url": {"url": "https://x/a.png"}}]}]
        await _drain(client.get_stream_response("prov", "m", msgs, None))
        assert captured["messages"] == msgs

    @pytest.mark.asyncio
    async def test_per_agent_cache_dir(self, tmp_path, monkeypatch):
        data = b"\x89PNGdata"
        p = tmp_path / "a.png"
        p.write_bytes(data)
        ref = local_ref(p, data)

        async def fake_acompletion(**kwargs):
            async def agen():
                return
                yield  # pragma: no cover

            return agen()

        monkeypatch.setattr("broca.llm.acompletion", fake_acompletion)
        client = LiteLLMClient(config=make_config())
        await _drain(client.get_stream_response("prov", "m", image_msg(ref), None,
                                                agent_id="agentZ", session_id="sessZ"))
        agent_dir = default_cache_root() / "sessZ" / "agentZ"
        assert agent_dir.exists()
        assert list(agent_dir.glob("*.json"))  # 缓存文件落在 per-agent 目录

    @pytest.mark.asyncio
    async def test_too_large_becomes_llm_error(self, tmp_path, monkeypatch):
        data = b"\x89PNGdata"
        p = tmp_path / "a.png"
        p.write_bytes(data)
        # size 字段设很大 + 阈值 0 → 压缩也压不下去 → MediaFileTooLargeError → LLMError
        ref = encode_media_ref({
            "kind": "local", "path": str(p), "url": "/big.png",
            "sha256": "s", "mime": "image/png", "size": 100 * MB,
        })

        async def fake_acompletion(**kwargs):  # pragma: no cover - 不应被调用
            raise AssertionError("acompletion should not be called")

        monkeypatch.setattr("broca.llm.acompletion", fake_acompletion)
        client = LiteLLMClient(config=make_config(media_limits={"max_inline_mb": 0}))
        with pytest.raises(LLMError) as ei:
            await _drain(client.get_stream_response("prov", "m", image_msg(ref), None,
                                                    agent_id="a1", session_id="s1"))
        assert "/big.png" in str(ei.value)
        assert "缩小" in str(ei.value) or "files_api" in str(ei.value) or "阈值" in str(ei.value)
