"""Task 3.4: 端到端回归测试（media ref → 物化 → wire）。

场景：
1. 云端图片（parse_message 产出 ref）→ get_stream_response 最终 wire 为 base64。
2. DeepSeek files_api 配置 → POST /files 上传 → wire 为双 key 块；上传失败 → LLMError。
3. 历史重建后再请求 → 仍为 base64（缓存命中，不重复读取存储字节）。
4. 缓存 TTL vs 文件保留期：缓存命中时源文件已删仍可物化；缓存未命中且源文件已删 → 报错。
"""

import base64
import hashlib
import io
import uuid

import httpx
import pytest
from PIL import Image

from broca.errors import LLMError
from broca.llm import LiteLLMClient
from broca.media.ref import encode_media_ref, decode_media_ref
from broca.session.models import Message, MessageType


def make_png(color=(0, 128, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, format="PNG")
    return buf.getvalue()


def make_config(*, files_api=None, media_limits=None, base_url="https://api.deepseek.com/v1"):
    meta = {"modality": {"text": "", "image": {}}}
    if media_limits is not None:
        meta["media_limits"] = media_limits
    prov = {
        "base_url": base_url,
        "api_key": "sk-test",
        "models": {"m": {"model": "openai/deepseek-flash", "meta": meta}},
    }
    if files_api is not None:
        prov["files_api"] = files_api
    return {"deepseek": prov}


def image_msg(ref):
    return [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": ref}},
        {"type": "text", "text": "describe"},
    ]}]


def user_message_with_cloud_file(png: bytes):
    return Message(
        message_id=f"msg_{uuid.uuid4().hex[:16]}",
        session_id="s",
        role="user",
        message_type=MessageType.USER_MESSAGE,
        data={
            "content": "hi",
            "files": [{
                "name": "a.png",
                "url": "https://cdn/a.png",
                "type": "image/png",
                "storage_key": "uploads/a.png",
                "sha256": hashlib.sha256(png).hexdigest(),
                "size": len(png),
            }],
        },
    )


async def _drain(agen):
    async for _ in agen:
        pass


def _fake_acompletion(captured):
    async def fake(**kwargs):
        captured.update(kwargs)

        async def agen():
            return
            yield  # pragma: no cover

        return agen()

    return fake


class TestScenario1CloudToBase64:
    @pytest.mark.asyncio
    async def test_cloud_ref_materializes_to_base64(self, monkeypatch):
        png = make_png()
        client = LiteLLMClient(config=make_config())
        # 1. parse_message 产出 ref（cloud）
        parsed = client.parse_message("deepseek", "m", user_message_with_cloud_file(png))
        img_part = [p for p in parsed["content"] if p.get("type") == "image_url"][0]
        ref_url = img_part["image_url"]["url"]
        assert decode_media_ref(ref_url) is not None  # 是 ref，不是 base64
        assert not ref_url.startswith("data:")

        # 2. mock 云端读取 + acompletion
        from broca.media import storage as storage_mod

        async def fake_read(st, ref):
            return png

        monkeypatch.setattr(storage_mod, "read_cloud_bytes", fake_read)
        captured = {}
        monkeypatch.setattr("broca.llm.acompletion", _fake_acompletion(captured))

        # 3. 发请求
        await _drain(client.get_stream_response(
            "deepseek", "m", [parsed], None, agent_id="a1", session_id="s1",
        ))
        wire_url = captured["messages"][0]["content"][0]["image_url"]["url"]
        assert wire_url.startswith("data:image/png;base64,")
        assert base64.b64decode(wire_url.split(",", 1)[1]) == png


class TestScenario2DeepSeekFilesApi:
    @pytest.mark.asyncio
    async def test_files_api_uploads_and_emits_double_key(self, tmp_path, monkeypatch):
        png = make_png()
        p = tmp_path / "a.png"
        p.write_bytes(png)
        ref = encode_media_ref({
            "kind": "local", "path": str(p), "url": "/files/raw?path=a.png",
            "sha256": hashlib.sha256(png).hexdigest(), "mime": "image/png", "size": len(png),
        })
        client = LiteLLMClient(config=make_config(
            files_api={"type": "deepseek", "purpose": "user_data", "max_size_mb": 64}
        ))
        # mock httpx upload
        upload_calls = {"n": 0}
        orig = httpx.AsyncClient

        def fake_client(*a, **kw):
            def handler(request):
                upload_calls["n"] += 1
                assert str(request.url).endswith("/files")
                return httpx.Response(200, json={"id": "file-api-777", "created_at": 1790000000})

            kw.pop("timeout", None)
            return orig(transport=httpx.MockTransport(handler), **kw)

        monkeypatch.setattr(httpx, "AsyncClient", fake_client)
        captured = {}
        monkeypatch.setattr("broca.llm.acompletion", _fake_acompletion(captured))

        await _drain(client.get_stream_response("deepseek", "m", image_msg(ref), None,
                                                agent_id="a1", session_id="s1"))
        part = captured["messages"][0]["content"][0]
        assert part == {"type": "file", "file": {"file_id": "file-api-777"}, "file_id": "file-api-777"}
        assert upload_calls["n"] == 1

    @pytest.mark.asyncio
    async def test_files_api_upload_failure_raises_llm_error(self, tmp_path, monkeypatch):
        png = make_png()
        p = tmp_path / "a.png"
        p.write_bytes(png)
        ref = encode_media_ref({
            "kind": "local", "path": str(p), "url": "/x", "sha256": "s",
            "mime": "image/png", "size": len(png),
        })
        client = LiteLLMClient(config=make_config(files_api={"type": "deepseek"}))
        orig = httpx.AsyncClient

        def fake_client(*a, **kw):
            def handler(request):
                return httpx.Response(400, text="bad")

            kw.pop("timeout", None)
            return orig(transport=httpx.MockTransport(handler), **kw)

        monkeypatch.setattr(httpx, "AsyncClient", fake_client)
        monkeypatch.setattr("broca.llm.acompletion", _fake_acompletion({}))
        with pytest.raises(LLMError):
            await _drain(client.get_stream_response("deepseek", "m", image_msg(ref), None,
                                                    agent_id="a1", session_id="s1"))


class TestScenario3CacheReuse:
    @pytest.mark.asyncio
    async def test_second_request_hits_cache_no_storage_read(self, monkeypatch):
        png = make_png()
        client = LiteLLMClient(config=make_config())
        parsed = client.parse_message("deepseek", "m", user_message_with_cloud_file(png))
        from broca.media import storage as storage_mod

        reads = {"n": 0}

        async def fake_read(st, ref):
            reads["n"] += 1
            return png

        monkeypatch.setattr(storage_mod, "read_cloud_bytes", fake_read)
        captured = {}
        monkeypatch.setattr("broca.llm.acompletion", _fake_acompletion(captured))

        for _ in range(2):
            await _drain(client.get_stream_response("deepseek", "m", [parsed], None,
                                                    agent_id="a1", session_id="s1"))
        # 第二次命中 base64 缓存 → 仅读取一次存储
        assert reads["n"] == 1


class TestScenario4CacheVsFileRetention:
    @pytest.mark.asyncio
    async def test_cache_hit_survives_source_deletion(self, tmp_path, monkeypatch):
        png = make_png()
        p = tmp_path / "a.png"
        p.write_bytes(png)
        ref = encode_media_ref({
            "kind": "local", "path": str(p), "url": "/x",
            "sha256": hashlib.sha256(png).hexdigest(), "mime": "image/png", "size": len(png),
        })
        client = LiteLLMClient(config=make_config())
        captured = {}
        monkeypatch.setattr("broca.llm.acompletion", _fake_acompletion(captured))

        # 第一次：写缓存
        await _drain(client.get_stream_response("deepseek", "m", image_msg(ref), None,
                                                agent_id="a1", session_id="s1"))
        assert captured["messages"][0]["content"][0]["image_url"]["url"].startswith("data:")

        # 删除源文件（模拟过期），第二次仍可从缓存物化
        p.unlink()
        await _drain(client.get_stream_response("deepseek", "m", image_msg(ref), None,
                                                agent_id="a1", session_id="s1"))
        assert captured["messages"][0]["content"][0]["image_url"]["url"].startswith("data:")

    @pytest.mark.asyncio
    async def test_cache_miss_and_source_deleted_raises(self, tmp_path, monkeypatch):
        # 源文件不存在，且用全新 session（无缓存）→ 明确报错提示重新上传
        ref = encode_media_ref({
            "kind": "local", "path": str(tmp_path / "gone.png"), "url": "/gone.png",
            "sha256": "no-such", "mime": "image/png", "size": 10,
        })
        client = LiteLLMClient(config=make_config())
        monkeypatch.setattr("broca.llm.acompletion", _fake_acompletion({}))
        with pytest.raises(LLMError) as ei:
            await _drain(client.get_stream_response("deepseek", "m", image_msg(ref), None,
                                                    agent_id="fresh", session_id="fresh"))
        assert "重新上传" in str(ei.value) or "不存在" in str(ei.value)
