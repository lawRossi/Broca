"""回归测试：install.sh 生成的后端 `.env` 必须满足 App 的生产安全护栏。

背景（bug）：
    `install.sh` 原先用裸 heredoc 生成 `~/.broca/web/backend/.env`：
        ENV=production
        JWT_SECRET=${JWT_SECRET:-}              # 空
        CORS_ALLOW_ORIGINS=${CORS_ORIGINS:-*}   # 通配符
    而 `app/core/config.py::_enforce_production_safety` 在 `ENV=production` 时
    拒绝空 JWT_SECRET 与 `*` 通配 CORS。于是 `settings = Settings()` 在
    **import 阶段**抛 ValidationError → uvicorn 秒退 → supervisor `FATAL`
    → nginx 对 `/api/*` 全部 502 → 安装完成后页面打不开。

修复方式：install.sh 改为调用 `scripts/gen_backend_env.py`，
由它生成 .env 并用 App 自己的 Settings 自检。本文件锁定该契约。
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from app.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "gen_backend_env.py"
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"
BACKEND_DIR = REPO_ROOT / "broca-web" / "backend"


def _load_generator():
    """按文件路径加载 scripts/gen_backend_env.py（它不是包内模块）。"""
    assert SCRIPT_PATH.is_file(), f"缺少 {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("gen_backend_env", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


gen = _load_generator()

BROCA_HOME = Path("/tmp/broca-test-home")

# Settings 认可的全部环境变量名（字段名大写 + 显式 alias）
_ACCEPTED_ENV_KEYS: set[str] = set()
for _name, _field in Settings.model_fields.items():
    _ACCEPTED_ENV_KEYS.add(_name.upper())
    _alias = getattr(_field, "validation_alias", None)
    if _alias is not None:
        for _choice in getattr(_alias, "choices", []) or []:
            if isinstance(_choice, str):
                _ACCEPTED_ENV_KEYS.add(_choice.upper())


def _parse_env(text: str) -> dict[str, str]:
    """极简 .env 解析（KEY=VALUE，忽略注释与空行）。"""
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def _render(**overrides) -> str:
    params = {
        "port": 9000,
        "socketio_port": 6868,
        "broca_home": BROCA_HOME,
        "jwt_secret": "a" * 64,
        "cors_origins": gen.default_cors_origins(),
    }
    params.update(overrides)
    return gen.render_env(**params)


# ---------------------------------------------------------------------------
# 核心回归：生成的 .env 必须能通过 App 自己的生产护栏
# ---------------------------------------------------------------------------


class TestGeneratedEnvPassesGuardrails:
    def test_generated_env_instantiates_settings(self, tmp_path):
        """这是本 bug 的直接回归点：原先这里会抛 ValidationError。"""
        env_file = tmp_path / ".env"
        env_file.write_text(_render(), encoding="utf-8")

        settings = Settings(_env_file=str(env_file))
        assert settings.env == "production"
        assert settings.jwt_secret == "a" * 64
        assert settings.cors_allow_origins != "*"

    def test_old_broken_template_is_rejected(self, tmp_path):
        """旧模板（空 JWT + CORS=*）必须被护栏拦下 —— 证明测试有效。"""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "ENV=production\nPORT=9000\nJWT_SECRET=\nCORS_ALLOW_ORIGINS=*\n",
            encoding="utf-8",
        )
        with pytest.raises(Exception) as exc:
            Settings(_env_file=str(env_file))
        assert "JWT_SECRET" in str(exc.value)

    def test_wildcard_cors_alone_also_rejected(self, tmp_path):
        """即使 JWT 正常，CORS=* 同样违规（修复前会紧接着炸第二次）。"""
        env_file = tmp_path / ".env"
        env_file.write_text(
            f"ENV=production\nPORT=9000\nJWT_SECRET={'b' * 64}\nCORS_ALLOW_ORIGINS=*\n",
            encoding="utf-8",
        )
        with pytest.raises(Exception) as exc:
            Settings(_env_file=str(env_file))
        assert "CORS_ALLOW_ORIGINS" in str(exc.value)


# ---------------------------------------------------------------------------
# JWT_SECRET：必须非空，且重装不轮换
# ---------------------------------------------------------------------------


class TestJwtSecret:
    def test_generated_secret_is_non_empty_hex(self, tmp_path):
        out = tmp_path / ".env"
        gen.generate(out=out, broca_home=BROCA_HOME, validate=False)
        parsed = _parse_env(out.read_text(encoding="utf-8"))

        secret = parsed["JWT_SECRET"]
        assert secret
        assert secret != gen.DEV_JWT_DEFAULT
        assert re.fullmatch(r"[0-9a-f]{64}", secret), "应为 32 字节十六进制"

    def test_reinstall_reuses_existing_secret(self, tmp_path):
        """重装不能轮换密钥，否则所有用户登录态失效。"""
        out = tmp_path / ".env"
        gen.generate(out=out, broca_home=BROCA_HOME, validate=False)
        first = _parse_env(out.read_text(encoding="utf-8"))["JWT_SECRET"]

        gen.generate(out=out, broca_home=BROCA_HOME, validate=False)
        second = _parse_env(out.read_text(encoding="utf-8"))["JWT_SECRET"]

        assert first == second

    def test_dev_default_secret_is_not_reused(self, tmp_path):
        """已有 .env 里是 dev 默认密钥时，必须换成新生成的强密钥。"""
        out = tmp_path / ".env"
        out.write_text(f"ENV=production\nJWT_SECRET={gen.DEV_JWT_DEFAULT}\n", encoding="utf-8")

        gen.generate(out=out, broca_home=BROCA_HOME, validate=False)
        secret = _parse_env(out.read_text(encoding="utf-8"))["JWT_SECRET"]

        assert secret != gen.DEV_JWT_DEFAULT
        assert re.fullmatch(r"[0-9a-f]{64}", secret)

    def test_explicit_secret_wins(self, tmp_path):
        out = tmp_path / ".env"
        gen.generate(out=out, broca_home=BROCA_HOME, jwt_secret="explicit-secret", validate=False)
        assert _parse_env(out.read_text(encoding="utf-8"))["JWT_SECRET"] == "explicit-secret"


# ---------------------------------------------------------------------------
# CORS：不能是通配符
# ---------------------------------------------------------------------------


class TestCorsOrigins:
    def test_default_is_explicit_and_not_wildcard(self):
        origins = gen.default_cors_origins().split(",")
        assert origins
        assert "*" not in origins
        assert "http://localhost:5166" in origins

    def test_wildcard_input_falls_back_to_default(self, tmp_path):
        out = tmp_path / ".env"
        gen.generate(out=out, broca_home=BROCA_HOME, cors_origins="*", validate=False)
        value = _parse_env(out.read_text(encoding="utf-8"))["CORS_ALLOW_ORIGINS"]
        assert value != "*"
        assert "localhost:5166" in value

    def test_explicit_origins_respected(self, tmp_path):
        out = tmp_path / ".env"
        gen.generate(
            out=out,
            broca_home=BROCA_HOME,
            cors_origins="https://broca.example.com",
            validate=False,
        )
        assert _parse_env(out.read_text(encoding="utf-8"))["CORS_ALLOW_ORIGINS"] == (
            "https://broca.example.com"
        )


# ---------------------------------------------------------------------------
# 不允许再写"看起来生效其实无效"的死配置
# ---------------------------------------------------------------------------


class TestNoDeadConfigKeys:
    def test_every_key_is_a_real_settings_field(self):
        parsed = _parse_env(_render())
        unknown = sorted(set(parsed) - _ACCEPTED_ENV_KEYS)
        assert not unknown, (
            f"生成的 .env 含 Settings 不认识的键 {unknown} —— "
            "extra='ignore' 会静默丢弃，属于误导性死配置"
        )

    @pytest.mark.parametrize("dead_key", ["BROCA_DATABASE_DIR", "BROCA_LLM_CONFIG"])
    def test_legacy_dead_keys_removed(self, dead_key):
        assert dead_key not in _render()


# ---------------------------------------------------------------------------
# 生成失败必须回滚，不能留下坏文件
# ---------------------------------------------------------------------------


class TestValidationAndRollback:
    def test_validation_passes_for_good_file(self, tmp_path):
        out = tmp_path / ".env"
        gen.generate(out=out, broca_home=BROCA_HOME, backend_dir=BACKEND_DIR)
        assert out.is_file()
        gen.validate_env_file(out, BACKEND_DIR)  # 不抛异常

    def test_validate_env_file_rejects_broken_file(self, tmp_path):
        out = tmp_path / ".env"
        out.write_text("ENV=production\nJWT_SECRET=\nCORS_ALLOW_ORIGINS=*\n", encoding="utf-8")
        with pytest.raises(RuntimeError):
            gen.validate_env_file(out, BACKEND_DIR)

    def test_generate_rolls_back_when_validation_fails(self, tmp_path, monkeypatch):
        out = tmp_path / ".env"
        original = "ORIGINAL=1\n"
        out.write_text(original, encoding="utf-8")

        def _boom(_env_path, _backend_dir):
            raise RuntimeError("模拟自检失败")

        monkeypatch.setattr(gen, "validate_env_file", _boom)
        with pytest.raises(RuntimeError):
            gen.generate(out=out, broca_home=BROCA_HOME, backend_dir=BACKEND_DIR)

        assert out.read_text(encoding="utf-8") == original, "自检失败后应回滚原文件"

    def test_generate_removes_file_when_no_previous_file(self, tmp_path, monkeypatch):
        out = tmp_path / ".env"
        monkeypatch.setattr(
            gen, "validate_env_file", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
        )
        with pytest.raises(RuntimeError):
            gen.generate(out=out, broca_home=BROCA_HOME, backend_dir=BACKEND_DIR)
        assert not out.exists()


# ---------------------------------------------------------------------------
# install.sh 必须真的调用生成器（防止回退到裸 heredoc）
# ---------------------------------------------------------------------------


class TestInstallShWiring:
    @pytest.fixture(scope="class")
    def script(self) -> str:
        assert INSTALL_SH.is_file()
        return INSTALL_SH.read_text(encoding="utf-8")

    def test_calls_generator(self, script):
        assert "gen_backend_env.py" in script

    def test_passes_required_arguments(self, script):
        for flag in (
            "--out",
            "--backend-dir",
            "--broca-home",
            "--port",
            "--socketio-port",
            "--jwt-secret",
            "--cors-origins",
        ):
            assert flag in script, f"install.sh 未传递 {flag}"

    def test_no_inline_env_heredoc(self, script):
        """旧的裸 heredoc 会重新引入本 bug。"""
        assert "ENVEOF" not in script
        assert not re.search(r"^ENV=production\s*$", script, re.MULTILINE)

    def test_excludes_dev_artifacts_from_backend_copy(self, script):
        """backend 目录必须排除 dev 产物，否则 configs.dev.json 会被搬进安装目录。"""
        # excludes 由 BACKEND_DEV_ARTIFACTS 数组循环生成，故检查数组 + --exclude 用法
        for item in ("configs.dev.json", ".env.local", ".env.production", ".env.development"):
            assert item in script, f"install.sh 未把 {item} 列入待排除项"
        assert '--exclude="$item"' in script or "--exclude=" in script, "rsync 未使用 --exclude"
        assert "purge_backend_dev_artifacts" in script, "缺少兜底清理（cp 回退/历史遗留）"


# ---------------------------------------------------------------------------
# 残留 env 文件必须被清理 —— 它们的优先级高于 .env
# ---------------------------------------------------------------------------


class TestStrayEnvFileCleanup:
    """bug：部署目录里残留的 .env.local 会把生产实例悄悄切回 dev 配置。

    `Settings.model_config` 的 env_file 列表是
    [".env", ".env.local", ".env.production", ".env.development"]，
    pydantic-settings 后加载者优先 —— 所以 `.env.local` 里的
    `BROCA_CONFIG=./configs.dev.json` 会盖掉生成的生产配置，
    数据被写到 backend/.local-data。
    """

    def test_generate_removes_stray_env_files(self, tmp_path):
        out = tmp_path / ".env"
        strays = [tmp_path / name for name in gen.STRAY_ENV_FILES]
        for stray in strays:
            stray.write_text("BROCA_CONFIG=./configs.dev.json\n", encoding="utf-8")

        gen.generate(out=out, broca_home=BROCA_HOME, validate=False)

        assert all(not stray.exists() for stray in strays), "残留 env 文件必须被删除"
        assert out.is_file(), "生成的 .env 不能被误删"

    def test_unrelated_files_untouched(self, tmp_path):
        out = tmp_path / ".env"
        keep = tmp_path / "configs.dev.json"
        keep.write_text("{}", encoding="utf-8")

        gen.generate(out=out, broca_home=BROCA_HOME, validate=False)

        assert keep.is_file(), "清理只针对 env 文件，不能顺手删别的"

    def test_purge_returns_removed_paths(self, tmp_path):
        stray = tmp_path / ".env.local"
        stray.write_text("X=1\n", encoding="utf-8")

        removed = gen.purge_stray_env_files(tmp_path / ".env")

        assert removed == [stray]
        assert gen.purge_stray_env_files(tmp_path / ".env") == [], "幂等：第二次无文件可删"


# ---------------------------------------------------------------------------
# 生产配置绝不能指向 configs.dev.json
# ---------------------------------------------------------------------------


class TestDevConfigGuard:
    """生产实例读 configs.dev.json = 数据写进 backend/.local-data 且日志 DEBUG。"""

    def _prod_env(self, broca_config: str) -> str:
        return (
            "ENV=production\n"
            f"JWT_SECRET={'c' * 64}\n"
            "CORS_ALLOW_ORIGINS=https://broca.example.com\n"
            f"BROCA_CONFIG={broca_config}\n"
        )

    def test_generator_refuses_dev_config_path(self):
        with pytest.raises(RuntimeError) as exc:
            gen.assert_not_dev_config("ENV=production\nBROCA_CONFIG=./configs.dev.json\n")
        assert "configs.dev.json" in str(exc.value)

    def test_generator_accepts_production_config_path(self):
        gen.assert_not_dev_config("BROCA_CONFIG=/home/u/.broca/configs/configs.json\n")

    def test_settings_rejects_dev_config_in_production(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(self._prod_env("./configs.dev.json"), encoding="utf-8")

        with pytest.raises(Exception) as exc:
            Settings(_env_file=str(env_file))
        assert "configs.dev.json" in str(exc.value)

    def test_settings_allows_dev_config_in_dev_env(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("ENV=dev\nBROCA_CONFIG=./configs.dev.json\n", encoding="utf-8")

        settings = Settings(_env_file=str(env_file))
        assert settings.env == "dev"
        assert settings.broca_config_path.name == "configs.dev.json"

    def test_stray_env_local_fails_fast_instead_of_silently_going_dev(self, tmp_path):
        """残留 .env.local 指向 dev 配置时：必须启动失败，而不是静默跑 dev 数据。"""
        env_file = tmp_path / ".env"
        env_file.write_text(
            self._prod_env("/home/u/.broca/configs/configs.json"), encoding="utf-8"
        )
        stray = tmp_path / ".env.local"
        stray.write_text("BROCA_CONFIG=./configs.dev.json\n", encoding="utf-8")

        with pytest.raises(Exception) as exc:
            Settings(_env_file=[str(env_file), str(stray)])
        assert "configs.dev.json" in str(exc.value)

    def test_strays_removed_before_write_and_self_check(self, tmp_path, monkeypatch):
        """顺序契约：清理必须早于写盘/自检。

        pydantic-settings 会把 `.env.local` 和 `.env` 一起加载，且 `.env.local`
        优先（连 `_env_file` 显式指定也压不住）。若清理晚于自检，自检读到的
        就不是刚生成的内容，安装会以莫名其妙的校验错误中断。
        """
        out = tmp_path / ".env"
        stray = tmp_path / ".env.local"
        stray.write_text("BROCA_CONFIG=./configs.dev.json\n", encoding="utf-8")

        seen: dict[str, bool] = {}
        original = gen.write_env_atomic

        def _spy(path, content):
            seen["stray_exists_at_write"] = stray.exists()
            return original(path, content)

        monkeypatch.setattr(gen, "write_env_atomic", _spy)
        gen.generate(out=out, broca_home=BROCA_HOME, validate=False)

        assert seen["stray_exists_at_write"] is False, "残留 env 文件必须在写盘前清理"
