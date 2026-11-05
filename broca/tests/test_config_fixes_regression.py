"""回归测试：配置系统 P1/P2 修复。

覆盖：
- P1a: get_configs() 线程安全（并发初始化不产生多实例）
- P1b: LiteLLMClient 支持 config 注入 + 文件缺失容错
- P2-1: resolve_configs_path() 统一路径解析
- P2-2: dataclass 字段完整性（from_config 白名单与 fields 一致）
- P2-4: pythonpath 确保本地源码优先于已安装副本
"""

from __future__ import annotations

import json
import threading
from dataclasses import fields
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# P1b: LiteLLMClient 容错
# ---------------------------------------------------------------------------


class TestLLMClientFaultTolerance:
    """LiteLLMClient.__init__ 容错行为。"""

    def test_init_with_injected_config(self):
        """传入 config dict 时不应读文件。"""
        from broca.llm import LiteLLMClient

        fake_config = {
            "openai": {
                "base_url": "http://fake",
                "api_key": "sk-fake",
                "models": {
                    "gpt-4": {
                        "model": "gpt-4",
                        "temperature": 0.5,
                        "meta": {"modality": {"text": ""}},
                    }
                },
            }
        }
        client = LiteLLMClient(config=fake_config)
        assert client.config == fake_config
        # execution_config 仍从 get_configs() 获取
        assert hasattr(client, "execution_config")

    def test_init_with_empty_config(self):
        """传入空 dict 时正常工作（不抛异常）。"""
        from broca.llm import LiteLLMClient

        client = LiteLLMClient(config={})
        assert client.config == {}

    def test_init_missing_file_falls_back_to_empty(self, tmp_path, monkeypatch):
        """llm_config.json 不存在时应回退到空配置而非抛异常。"""
        from broca.configs import resolve_llm_config_path
        from broca.llm import LiteLLMClient

        # 让 broca.configs.resolve_llm_config_path 返回一个不存在的文件
        monkeypatch.setattr(
            "broca.configs.resolve_llm_config_path",
            lambda: tmp_path / "nonexistent_llm_config.json",
        )
        # 不应抛异常
        client = LiteLLMClient()
        assert client.config == {}

    def test_init_corrupt_file_falls_back_to_empty(self, tmp_path, monkeypatch):
        """llm_config.json 内容损坏（非法 JSON）时应回退到空配置。"""
        from broca.configs import resolve_llm_config_path
        from broca.llm import LiteLLMClient

        corrupt_file = tmp_path / "corrupt.json"
        corrupt_file.write_text("{invalid json!!", encoding="utf-8")

        monkeypatch.setattr(
            "broca.configs.resolve_llm_config_path",
            lambda: corrupt_file,
        )
        client = LiteLLMClient()
        assert client.config == {}

    def test_injected_config_unknown_provider_still_raises(self):
        """注入的 config 中查未知 provider 仍应抛 ValidationError。"""
        from broca.errors import ValidationError
        from broca.llm import LiteLLMClient

        client = LiteLLMClient(config={"openai": {"models": {"gpt-4": {"model": "gpt-4", "meta": {"modality": {"text": ""}}}}}})
        # parse_message 使用与 get_stream_response 相同的 provider/model 校验
        with pytest.raises(ValidationError):
            client.parse_message("nonexistent-provider", "model", None)


# ---------------------------------------------------------------------------
# P1a: get_configs 线程安全
# ---------------------------------------------------------------------------


class TestGetConfigsThreadSafety:
    """并发首次调用 get_configs() 应产生同一个实例。"""

    def test_concurrent_first_init_same_instance(self):
        """多线程同时首次调用，所有线程拿到同一个 BrocaConfig 对象。"""
        from broca.configs import BrocaConfig, get_configs, reset_configs_cache

        reset_configs_cache()
        results: list[BrocaConfig] = []
        barrier = threading.Barrier(8)
        errors: list[Exception] = []

        def worker():
            try:
                barrier.wait(timeout=5)
                config = get_configs()
                results.append(config)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Errors in threads: {errors}"
        assert len(results) == 8
        # 所有线程拿到的是同一个实例
        assert all(r is results[0] for r in results)

        reset_configs_cache()

    def test_explicit_path_thread_safety(self):
        """多线程同时用显式路径调用，不崩溃且值正确。"""
        from broca.configs import get_configs, reset_configs_cache

        reset_configs_cache()
        config_file = Path("/tmp/_test_thread_config.json")
        config_file.write_text(json.dumps({"log_level": "ERROR"}))

        results = []
        errors = []
        barrier = threading.Barrier(4)

        def worker():
            try:
                barrier.wait(timeout=5)
                results.append(get_configs(str(config_file)))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Errors: {errors}"
        assert len(results) == 4
        # 每个线程都拿到了正确值的配置（显式路径每次加载新实例，锁只防损坏）
        assert all(r.log_level == "ERROR" for r in results)
        reset_configs_cache()


# ---------------------------------------------------------------------------
# P2-2: dataclass 字段完整性
# ---------------------------------------------------------------------------


class TestDataclassFields:
    """验证 dataclass 字段与 from_config 白名单一致。"""

    def test_execution_config_fields_match_from_config_whitelist(self):
        """dataclass fields 就是 from_config 的白名单来源。"""
        from broca.configs import ExecutionConfig

        field_names = {f.name for f in fields(ExecutionConfig)}
        # 已知必须存在的核心字段
        assert "step_max_errors" in field_names
        assert "llm_timeout" in field_names
        assert "tool_call_timeout" in field_names
        assert "runner_heartbeat_interval" in field_names
        assert "runner_ipc_queue_size" in field_names

    def test_storage_config_fields(self):
        from broca.configs import StorageConfig

        field_names = {f.name for f in fields(StorageConfig)}
        assert "backend" in field_names
        assert "cloudflare_bucket" in field_names
        assert "supabase_bucket" in field_names

    def test_search_config_fields(self):
        from broca.configs import SearchConfig

        search_fields = {f.name for f in fields(SearchConfig)}
        assert "tavily_api_key" in search_fields
        assert "anysearch_api_key" in search_fields
        assert "default_search_provider" in search_fields
        assert "default_fetch_provider" in search_fields

    def test_from_config_filters_unknown_and_keeps_known(self):
        """from_config 过滤未知字段、保留已知字段（dataclass 版行为）。"""
        from broca.configs import ExecutionConfig

        input_dict = {
            "llm_timeout": 600,
            "unknown_future_field": "should_be_removed",
            "step_max_errors": 5,
        }
        result = ExecutionConfig.from_config(input_dict)
        assert result.llm_timeout == 600
        assert result.step_max_errors == 5
        assert not hasattr(result, "unknown_future_field")
        # input dict 被就地修改（向后兼容行为）
        assert "unknown_future_field" not in input_dict

    def test_from_config_defaults_preserved_for_missing_keys(self):
        """未提供的字段保持 dataclass 默认值。"""
        from broca.configs import ExecutionConfig

        result = ExecutionConfig.from_config({"llm_timeout": 999})
        assert result.llm_timeout == 999
        assert result.step_max_errors == 3  # 默认值
        assert result.runner_heartbeat_interval == 5  # 默认值


# ---------------------------------------------------------------------------
# P2-1: resolve_configs_path 统一入口
# ---------------------------------------------------------------------------


class TestResolveConfigsPath:
    """resolve_configs_path() 统一路径解析行为。"""

    def test_explicit_absolute_path(self, tmp_path):
        """绝对路径直接返回（即使文件不存在）。"""
        from broca.configs import resolve_configs_path

        target = tmp_path / "my_config.json"
        result = resolve_configs_path(str(target))
        assert result == target

    def test_explicit_relative_path_with_base_dir(self, tmp_path):
        """相对路径以 base_dir 为基准解析。"""
        from broca.configs import resolve_configs_path

        result = resolve_configs_path("./configs.json", base_dir=tmp_path)
        assert result == (tmp_path / "configs.json").resolve()

    def test_explicit_relative_path_without_base_dir(self):
        """相对路径无 base_dir 时仅 expanduser，保持相对形式（不推荐）。"""
        from broca.configs import resolve_configs_path

        result = resolve_configs_path("configs.json")
        # 无 base_dir → 不 resolve 为绝对路径，保持原始相对形式
        assert result.name == "configs.json"
        assert not result.is_absolute()

    def test_empty_string_treated_as_no_path(self):
        """空字符串 / 纯空白视为未提供，走默认发现链。"""
        from broca.configs import resolve_configs_path

        # 空字符串 → 走默认发现链（项目 configs/ 或 ~/.broca/）
        result = resolve_configs_path("")
        # 不应该返回空 Path
        if result is not None:
            assert str(result).strip() != ""

        result_whitespace = resolve_configs_path("   ")
        if result_whitespace is not None:
            assert str(result_whitespace).strip() != ""

    def test_none_returns_default_discovery(self):
        """None 走默认发现链，返回第一个存在的文件（或 None）。"""
        from broca.configs import resolve_configs_path

        result = resolve_configs_path(None)
        # 在开发环境应该能找到项目 configs/configs.json
        if result is not None:
            assert result.name == "configs.json"

    def test_tilde_expansion(self, tmp_path, monkeypatch):
        """~ 路径被正确展开。"""
        from broca.configs import resolve_configs_path

        home = Path.home()
        result = resolve_configs_path("~/.broca/configs/configs.json")
        assert str(result).startswith(str(home))
        assert not str(result).startswith("~")

    def test_default_search_chain_order(self):
        """默认发现链按优先级排列：项目 → ~/.broca/configs/ → ~/.broca/。"""
        from broca.configs import _get_default_search_paths

        paths = _get_default_search_paths()
        assert len(paths) == 3
        # 第一个是项目 configs/
        assert paths[0].name == "configs.json"
        assert "configs" in paths[0].parts
        # 第二个是 ~/.broca/configs/
        assert paths[1] == Path.home() / ".broca" / "configs" / "configs.json"
        # 第三个是 ~/.broca/
        assert paths[2] == Path.home() / ".broca" / "configs.json"

    def test_web_backend_uses_same_resolver(self):
        """验证 broca-web 的 resolve_broca_config_path 委托给了统一函数。"""
        # 如果 broca-web 不在 path 中则跳过（纯核心包测试环境）
        try:
            from app.core.config import resolve_broca_config_path, BACKEND_DIR
        except ImportError:
            pytest.skip("broca-web backend 不可用")

        from broca.configs import resolve_configs_path

        # 两者对同一输入应返回相同结果
        raw = "./test_config.json"
        r1 = resolve_broca_config_path(raw)
        r2 = resolve_configs_path(raw, base_dir=BACKEND_DIR)
        assert r1 == r2


# ---------------------------------------------------------------------------
# P2-4: pythonpath guard
# ---------------------------------------------------------------------------


class TestLocalSourcePriority:
    """确保测试运行时 import 的是本地源码而非 site-packages 中的安装副本。"""

    def test_broca_package_resolves_to_project_source(self):
        """broca 包必须从项目根目录加载（pythonpath='.'生效）。"""
        import broca

        broca_path = Path(broca.__file__).resolve()
        project_root = Path(__file__).resolve().parents[2]  # broca/tests/ → project root

        # broca/__init__.py 应在 <project_root>/broca/ 下
        assert project_root in broca_path.parents, (
            f"broca 包从 {broca_path} 加载，"
            f"期望在 {project_root / 'broca'} 下。"
            f"检查 pyproject.toml 是否配置了 [tool.pytest.ini_options] pythonpath = ['.']"
        )

    def test_configs_module_is_local(self):
        """broca.configs 必须来自本地源码（含我们的修复）。"""
        import broca.configs

        module_path = Path(broca.configs.__file__).resolve()
        project_root = Path(__file__).resolve().parents[2]

        assert str(project_root) in str(module_path), (
            f"broca.configs 从 {module_path} 加载（非本地源码），"
            f"可能导致测试验证的是旧代码。"
        )
