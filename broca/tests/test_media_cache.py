"""Task 2.3: 全量持久化缓存（per-agent 隔离，TTL≤3 天）。"""

import json
import time

import pytest

from broca.media.cache import MediaCache, clear_session_cache
from broca.media.materializer import MediaMaterializer


@pytest.fixture
def cache_root(tmp_path):
    return tmp_path / "media_cache"


class TestBasic:
    @pytest.mark.asyncio
    async def test_put_get_roundtrip(self, cache_root):
        c = MediaCache("s1", "a1", root=cache_root)
        await c.put("sha-abc", "data:image/png;base64,XXXX")
        assert await c.get("sha-abc") == "data:image/png;base64,XXXX"

    @pytest.mark.asyncio
    async def test_tuple_key(self, cache_root):
        c = MediaCache("s1", "a1", root=cache_root)
        await c.put(("deepseek", "sha-1"), "file-api-123", kind="file_id")
        assert await c.get(("deepseek", "sha-1")) == "file-api-123"

    @pytest.mark.asyncio
    async def test_miss_returns_none(self, cache_root):
        c = MediaCache("s1", "a1", root=cache_root)
        assert await c.get("nope") is None


class TestPersistence:
    @pytest.mark.asyncio
    async def test_new_instance_hits_persisted(self, cache_root):
        c1 = MediaCache("s1", "a1", root=cache_root)
        await c1.put("sha", "value-1")
        # 模拟进程重启：新实例、同目录
        c2 = MediaCache("s1", "a1", root=cache_root)
        assert await c2.get("sha") == "value-1"

    @pytest.mark.asyncio
    async def test_agent_isolation(self, cache_root):
        c_a = MediaCache("s1", "agentA", root=cache_root)
        c_b = MediaCache("s1", "agentB", root=cache_root)
        await c_a.put("sha", "for-A")
        assert await c_b.get("sha") is None  # 互不可见
        # 目录确实不同
        assert c_a.dir != c_b.dir
        assert "agentA" in str(c_a.dir)
        assert "agentB" in str(c_b.dir)

    @pytest.mark.asyncio
    async def test_cache_files_on_disk_not_db(self, cache_root):
        c = MediaCache("s1", "a1", root=cache_root)
        await c.put("sha", "value")
        files = list(c.dir.glob("*.json"))
        assert len(files) == 1  # 仅落盘文件，无 DB 交互


class TestTTL:
    @pytest.mark.asyncio
    async def test_expired_entry_miss_and_deleted(self, cache_root):
        c = MediaCache("s1", "a1", root=cache_root, ttl_seconds=3600)
        await c.put("sha", "v")
        path = next(c.dir.glob("*.json"))
        # 把 created_at 改到 2 小时前
        entry = json.loads(path.read_text("utf-8"))
        entry["created_at"] = time.time() - 7200
        path.write_text(json.dumps(entry), "utf-8")
        assert await c.get("sha") is None
        assert not path.exists()  # 已删除

    @pytest.mark.asyncio
    async def test_gc_expired(self, cache_root):
        c = MediaCache("s1", "a1", root=cache_root, ttl_seconds=3600)
        await c.put("fresh", "v1")
        await c.put("old", "v2")
        old_path = None
        for p in c.dir.glob("*.json"):
            e = json.loads(p.read_text("utf-8"))
            if e["key"] == "old":
                old_path = p
                e["created_at"] = time.time() - 7200
                p.write_text(json.dumps(e), "utf-8")
        removed = await c.gc_expired()
        assert removed == 1
        assert not old_path.exists()
        assert await c.get("fresh") == "v1"


class TestClear:
    @pytest.mark.asyncio
    async def test_clear_removes_only_agent_dir(self, cache_root):
        c_a = MediaCache("s1", "agentA", root=cache_root)
        c_b = MediaCache("s1", "agentB", root=cache_root)
        await c_a.put("k", "va")
        await c_b.put("k", "vb")
        await c_a.clear()
        assert not c_a.dir.exists()
        assert c_b.dir.exists()
        assert await c_b.get("k") == "vb"

    @pytest.mark.asyncio
    async def test_clear_session_removes_all_agents(self, cache_root):
        c_a = MediaCache("s1", "agentA", root=cache_root)
        c_b = MediaCache("s1", "agentB", root=cache_root)
        await c_a.put("k", "va")
        await c_b.put("k", "vb")
        await c_a.clear_session()
        assert not (cache_root / "s1").exists()

    def test_module_clear_session_cache(self, cache_root):
        c = MediaCache("s9", "a", root=cache_root)
        import asyncio
        asyncio.run(c.put("k", "v"))
        assert (cache_root / "s9").exists()
        clear_session_cache("s9", root=cache_root)
        assert not (cache_root / "s9").exists()


class TestMaterializerCacheIntegration:
    @pytest.mark.asyncio
    async def test_second_request_hits_cache_no_reread(self, cache_root, tmp_path):
        data = b"image-bytes-here"
        p = tmp_path / "a.png"
        p.write_bytes(data)
        import hashlib
        sha = hashlib.sha256(data).hexdigest()

        from broca.media.ref import encode_media_ref
        ref = encode_media_ref({
            "kind": "local", "path": str(p), "url": "/x",
            "sha256": sha, "mime": "image/png", "size": len(data),
        })
        msg = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": ref}},
            {"type": "text", "text": "hi"},
        ]}]

        config = {"prov": {"base_url": "x", "api_key": "k",
                           "models": {"m": {"model": "openai/x",
                                            "meta": {"modality": {"text": "", "image": {}}}}}}}
        mat = MediaMaterializer(config, cache_factory=lambda s, a: MediaCache(s, a, root=cache_root))

        count = {"n": 0}
        orig = mat._read_bytes

        async def counting(r):
            count["n"] += 1
            return await orig(r)

        mat._read_bytes = counting

        await mat.materialize_messages(msg, "prov", "m", session_id="s1", agent_id="a1")
        await mat.materialize_messages(msg, "prov", "m", session_id="s1", agent_id="a1")
        assert count["n"] == 1  # 第二次命中缓存，未重复读盘
