"""回归测试：dev 环境绝不能读写生产数据目录。

背景（bug）：
    `dev.sh` 启动的后端读的是 `~/.broca/data/sessions.db`（生产库，300MB+）。
    根因有三处：
      1. `backend/.env` 的 `BROCA_CONFIG` 指向项目根 `configs/configs.json`，
         而该文件的 `database_dir` 就是 `~/.broca/data`；
      2. `backend/.env` 里写的 `BROCA_DATABASE_DIR` 是死配置 ——
         `Settings.broca_database_dir` 字段从未被任何代码消费；
      3. `backend/configs.dev.json` 存在但从未被引用（孤儿文件）。

修复后必须满足的约束，即本文件覆盖的断言。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import (
    BACKEND_DIR,
    Settings,
    check_data_dir_isolation,
    resolve_broca_config_path,
    settings,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
DEV_CONFIG = BACKEND_ROOT / "configs.dev.json"
PROD_CONFIG = BACKEND_ROOT.parents[1] / "configs" / "configs.json"


class _FakeConfigs(SimpleNamespace):
    """模拟 broca.configs.BrocaConfig 的相关字段。"""


@pytest.fixture()
def fake_configs(monkeypatch):
    """替换 broca.configs.get_configs，返回可控的配置对象。"""

    def _install(**kwargs):
        defaults = {"database_dir": None, "log_dir": None, "snapshot_home": None}
        defaults.update(kwargs)
        fake = _FakeConfigs(**defaults)
        monkeypatch.setattr("broca.configs.get_configs", lambda *a, **k: fake)
        return fake

    return _install


# ---------------------------------------------------------------------------
# configs.dev.json 本身必须是隔离的
# ---------------------------------------------------------------------------


class TestDevConfigFile:
    """configs.dev.json 不能把任何路径指向生产目录。"""

    def test_dev_config_exists(self):
        assert DEV_CONFIG.is_file(), "configs.dev.json 缺失，dev 将回退到生产配置"

    def test_dev_config_paths_are_isolated(self):
        from broca.configs import _load_config_file

        cfg = _load_config_file(DEV_CONFIG)
        assert cfg is not None, "configs.dev.json 解析失败"

        home = Path.home() / ".broca"
        for field in ("database_dir", "log_dir", "snapshot_home"):
            value = getattr(cfg, field)
            assert value, f"configs.dev.json 缺少 {field}"
            resolved = Path(value).resolve()
            assert home.resolve() not in resolved.parents and resolved != home.resolve(), (
                f"{field} 仍指向生产目录: {resolved}"
            )

    def test_dev_config_database_dir_is_under_backend(self):
        from broca.configs import _load_config_file

        cfg = _load_config_file(DEV_CONFIG)
        db_dir = Path(cfg.database_dir).resolve()
        assert db_dir == (BACKEND_DIR / ".local-data").resolve(), (
            f"dev 数据库目录应为 backend/.local-data，实际 {db_dir}"
        )

    def test_dev_config_keeps_execution_and_search_groups(self):
        """完整副本：缺 execution/search 会让超时和搜索在 dev 下静默退化。"""
        data = json.loads(DEV_CONFIG.read_text())
        assert "execution" in data
        assert "search" in data
        assert data["execution"].get("llm_timeout") == 300


# ---------------------------------------------------------------------------
# 项目根 configs/configs.json 确实是生产路径（解释 bug 来源）
# ---------------------------------------------------------------------------


def test_project_configs_json_points_at_production_data():
    """守住已知事实：项目 configs.json 的 database_dir 是 ~/.broca/data。

    它本身不是 bug（生产部署也用这份模板），但 dev 必须通过
    configs.dev.json 覆盖它 —— 否则就会重现本 bug。
    """
    assert PROD_CONFIG.is_file()
    data = json.loads(PROD_CONFIG.read_text())
    assert data.get("database_dir") == "~/.broca/data"


# ---------------------------------------------------------------------------
# resolve_broca_config_path：相对路径必须锚定 backend 目录
# ---------------------------------------------------------------------------


class TestResolveBrocaConfigPath:
    def test_relative_path_anchored_to_backend_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # 任意 CWD 都不应影响解析结果
        resolved = resolve_broca_config_path("./configs.dev.json")
        assert resolved == (BACKEND_DIR / "configs.dev.json").resolve()

    def test_absolute_path_kept(self):
        resolved = resolve_broca_config_path(str(DEV_CONFIG))
        assert resolved == DEV_CONFIG.resolve()

    def test_empty_returns_none(self):
        assert resolve_broca_config_path("") is None
        assert resolve_broca_config_path("   ") is None
        assert resolve_broca_config_path(None) is None

    def test_settings_property_uses_resolver(self):
        s = Settings(broca_config="./configs.dev.json")
        assert s.broca_config_path == (BACKEND_DIR / "configs.dev.json").resolve()

    def test_settings_property_none_when_unset(self):
        s = Settings(broca_config="")
        assert s.broca_config_path is None


# ---------------------------------------------------------------------------
# 死配置字段不应复活
# ---------------------------------------------------------------------------


def test_dead_broca_database_dir_field_removed():
    """`broca_database_dir` 曾被写进 .env 但无人消费，造成"看起来隔离了"的假象。

    真正的隔离机制是 BROCA_CONFIG -> configs.dev.json，不要再加回这个字段。
    """
    assert "broca_database_dir" not in Settings.model_fields


def test_env_example_does_not_advertise_dead_field():
    example = (BACKEND_ROOT / ".env.example").read_text()
    assert "BROCA_DATABASE_DIR" not in example
    assert "BROCA_CONFIG=./configs.dev.json" in example


# ---------------------------------------------------------------------------
# check_data_dir_isolation：启动护栏
# ---------------------------------------------------------------------------


class TestCheckDataDirIsolation:
    def test_flags_production_database_dir(self, fake_configs, monkeypatch):
        monkeypatch.setattr(settings, "env", "dev")
        prod = str(Path.home() / ".broca" / "data")
        fake_configs(database_dir=prod)
        assert check_data_dir_isolation() == [prod]

    def test_flags_production_log_dir(self, fake_configs, monkeypatch):
        monkeypatch.setattr(settings, "env", "dev")
        prod_logs = str(Path.home() / ".broca" / "logs")
        fake_configs(log_dir=prod_logs)
        assert prod_logs in check_data_dir_isolation()

    def test_flags_production_snapshot_home(self, fake_configs, monkeypatch):
        monkeypatch.setattr(settings, "env", "dev")
        prod_snap = str(Path.home() / ".broca" / "snapshots")
        fake_configs(snapshot_home=prod_snap)
        assert prod_snap in check_data_dir_isolation()

    def test_flags_nested_path_under_production_root(self, fake_configs, monkeypatch):
        monkeypatch.setattr(settings, "env", "dev")
        nested = str(Path.home() / ".broca" / "data" / "sessions.db")
        fake_configs(database_dir=nested)
        assert check_data_dir_isolation() == [nested]

    def test_clean_when_isolated(self, fake_configs, monkeypatch):
        monkeypatch.setattr(settings, "env", "dev")
        fake_configs(
            database_dir=str(BACKEND_DIR / ".local-data"),
            log_dir=str(BACKEND_DIR / "logs"),
            snapshot_home=str(BACKEND_DIR / ".local-data" / "snapshots"),
        )
        assert check_data_dir_isolation() == []

    def test_production_env_is_exempt(self, fake_configs, monkeypatch):
        """ENV=production 时用 ~/.broca 是正常的，不应误报。"""
        monkeypatch.setattr(settings, "env", "production")
        fake_configs(database_dir=str(Path.home() / ".broca" / "data"))
        assert check_data_dir_isolation() == []

    def test_ignores_non_string_values(self, fake_configs, monkeypatch):
        """配置字段异常（如被 mock 成非字符串）时不应崩溃。"""
        monkeypatch.setattr(settings, "env", "dev")
        fake_configs(database_dir=object(), log_dir=None, snapshot_home=None)
        assert check_data_dir_isolation() == []
