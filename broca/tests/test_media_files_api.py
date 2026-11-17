"""Task 3.1: FilesApiStrategy 接口与按类型选择 单测。

覆盖：未配置/type 未知/缺 type/构造失败 → None；type=deepseek → DeepSeekFilesStrategy；
materializer 在 strategy 为 None（type 未知）时安全回退 base64。
"""

import os

import pytest

from broca.media.deepseek_files import DeepSeekFilesStrategy
from broca.media.files_api import (
    FilesApiStrategy,
    build_files_api_strategy,
    make_files_api_factory,
    register_strategy,
)
from broca.media.materializer import MediaMaterializer
from broca.media.ref import encode_media_ref

PROVIDER_CFG = {"base_url": "https://api.deepseek.com/v1", "api_key": "k"}


class TestBuildStrategy:
    def test_no_config_returns_none(self):
        assert build_files_api_strategy("deepseek", "m", None, PROVIDER_CFG) is None
        assert build_files_api_strategy("deepseek", "m", {}, PROVIDER_CFG) is None

    def test_missing_type_returns_none(self):
        assert build_files_api_strategy("deepseek", "m", {"purpose": "user_data"}, PROVIDER_CFG) is None

    def test_unknown_type_returns_none(self):
        assert build_files_api_strategy("prov", "m", {"type": "nonexistent"}, PROVIDER_CFG) is None

    def test_deepseek_returns_instance(self):
        strat = build_files_api_strategy("deepseek", "m", {"type": "deepseek"}, PROVIDER_CFG)
        assert isinstance(strat, DeepSeekFilesStrategy)
        assert isinstance(strat, FilesApiStrategy)
        assert strat.max_size_bytes == 64 * 1024 * 1024
        assert strat.base_url == "https://api.deepseek.com/v1"

    def test_construction_failure_returns_none(self, monkeypatch):
        def boom(provider_cfg, cfg):
            raise RuntimeError("bad config")

        register_strategy("boomtype")(boom)
        assert build_files_api_strategy("prov", "m", {"type": "boomtype"}, PROVIDER_CFG) is None


class TestFactory:
    def test_factory_reads_provider_config(self):
        llm_config = {"deepseek": PROVIDER_CFG}
        factory = make_files_api_factory(llm_config)
        strat = factory("deepseek", "m", {"type": "deepseek", "max_size_mb": 10})
        assert isinstance(strat, DeepSeekFilesStrategy)
        assert strat.max_size_bytes == 10 * 1024 * 1024

    def test_factory_unknown_provider_ok(self):
        factory = make_files_api_factory({})
        # provider 不在 config 中 → provider_cfg 空 → 仍构造出 strategy（用默认 base_url）
        strat = factory("unknown", "m", {"type": "deepseek"})
        assert isinstance(strat, DeepSeekFilesStrategy)


class TestMaterializerFallback:
    @pytest.mark.asyncio
    async def test_unknown_type_falls_back_to_base64(self, tmp_path):
        p = tmp_path / "a.png"
        data = b"\x89PNG\r\n\x1a\nsmall"
        p.write_bytes(data)
        config = {
            "prov": {
                "base_url": "https://x",
                "api_key": "k",
                "files_api": {"type": "nonexistent", "max_size_mb": 64},
                "models": {
                    "m": {
                        "model": "openai/x",
                        "meta": {
                            "modality": {"text": "", "image": {}},
                        },
                    }
                },
            }
        }
        factory = make_files_api_factory(config)
        mat = MediaMaterializer(config, files_api_factory=factory)
        ref = encode_media_ref(
            {"kind": "local", "path": str(p), "url": "/files/raw?path=x",
             "sha256": "s", "mime": "image/png", "size": len(data)}
        )
        msg = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": ref}},
            {"type": "text", "text": "hi"},
        ]}]
        out = await mat.materialize_messages(msg, "prov", "m")
        url = out[0]["content"][0]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
