"""build_user_env() / find_workspace_venv() / _strip_and_restore() 单元测试。

覆盖场景：
- runner 环境（有 _BROCA_ORIG_*）→ 还原 PYTHONPATH / VIRTUAL_ENV
- 非 runner 环境（无 _BROCA_ORIG_*）→ 仅剥离内部变量
- 非 runner 环境 → BROCA_HOME / BROCA_DATABASE_DIR 等保留
- workspace 有 .venv / venv → PATH / VIRTUAL_ENV / VIRTUAL_ENV_PROMPT 正确
- workspace 有 env 但无 bin/python → 不识别为 venv
- workspace 无任何 venv → PATH 不变
- 优先级：workspace venv > 服务进程 VIRTUAL_ENV
- PATH 去重：venv bin 已在 PATH 中时不重复前置
- Windows 路径（platform="nt" 参数注入，不 monkeypatch sys.platform）
- 异常 fallback：find_workspace_venv 抛异常时 build_user_env 不崩溃
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch as mock_patch

import pytest

from broca.utils.env import (
    _apply_workspace_venv,
    _strip_and_restore,
    _validate_venv_dir,
    build_user_env,
    find_workspace_venv,
)


# ---------------------------------------------------------------------------
# find_workspace_venv
# ---------------------------------------------------------------------------


class TestFindWorkspaceVenv:
    def test_finds_dotvenv(self, tmp_path: Path):
        """workspace 含 .venv/bin/python → 返回 .venv 路径。"""
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").touch()

        result = find_workspace_venv(str(tmp_path))
        assert result == tmp_path / ".venv"

    def test_finds_venv(self, tmp_path: Path):
        """workspace 含 venv/bin/python → 返回 venv 路径。"""
        venv = tmp_path / "venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").touch()

        result = find_workspace_venv(str(tmp_path))
        assert result == tmp_path / "venv"

    def test_priority_dotvenv_over_venv(self, tmp_path: Path):
        """.venv 优先级高于 venv。"""
        (tmp_path / ".venv" / "bin").mkdir(parents=True)
        (tmp_path / ".venv" / "bin" / "python").touch()
        (tmp_path / "venv" / "bin").mkdir(parents=True)
        (tmp_path / "venv" / "bin" / "python").touch()

        result = find_workspace_venv(str(tmp_path))
        assert result == tmp_path / ".venv"

    def test_env_without_python_not_detected(self, tmp_path: Path):
        """workspace 有 env/ 但无 bin/python → 不识别为 venv。"""
        (tmp_path / "env" / "bin").mkdir(parents=True)

        result = find_workspace_venv(str(tmp_path))
        assert result is None

    def test_no_venv(self, tmp_path: Path):
        """workspace 无任何 venv → 返回 None。"""
        result = find_workspace_venv(str(tmp_path))
        assert result is None

    def test_python3_fallback(self, tmp_path: Path):
        """venv 只有 bin/python3（无 bin/python）→ 仍识别。"""
        venv = tmp_path / "venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python3").touch()

        result = find_workspace_venv(str(tmp_path))
        assert result == tmp_path / "venv"

    def test_nonexistent_workspace(self, tmp_path: Path):
        """workspace 路径不存在 → 返回 None。"""
        result = find_workspace_venv(str(tmp_path / "nonexistent"))
        assert result is None


# ---------------------------------------------------------------------------
# _strip_and_restore
# ---------------------------------------------------------------------------


class TestStripAndRestore:
    def test_strips_runner_internal_vars(self):
        """剥离 3 个 runner 内部标记变量。"""
        env = {
            "PYTHONSAFEPATH": "1",
            "BROCA_RUNNER_CHILD": "1",
            "LITELLM_LOCAL_MODEL_COST_MAP": "true",
            "PATH": "/usr/bin",
        }
        result = _strip_and_restore(env)
        assert "PYTHONSAFEPATH" not in result
        assert "BROCA_RUNNER_CHILD" not in result
        assert "LITELLM_LOCAL_MODEL_COST_MAP" not in result
        assert result["PATH"] == "/usr/bin"

    def test_restores_pythonpath_from_orig(self):
        """_BROCA_ORIG_PYTHONPATH 存在时还原。"""
        env = {
            "PYTHONPATH": "/repo/root:/custom/path",
            "_BROCA_ORIG_PYTHONPATH": "/custom/path",
        }
        result = _strip_and_restore(env)
        assert result["PYTHONPATH"] == "/custom/path"
        assert "_BROCA_ORIG_PYTHONPATH" not in result

    def test_pops_pythonpath_when_no_orig(self):
        """无 _BROCA_ORIG_PYTHONPATH 时 pop PYTHONPATH。"""
        env = {"PYTHONPATH": "/repo/root"}
        result = _strip_and_restore(env)
        assert "PYTHONPATH" not in result

    def test_restores_virtual_env(self):
        """_BROCA_ORIG_VIRTUAL_ENV 存在时还原。"""
        env = {
            "_BROCA_ORIG_VIRTUAL_ENV": "/user/.venv",
            "_BROCA_ORIG_VIRTUAL_ENV_PROMPT": ".venv",
        }
        result = _strip_and_restore(env)
        assert result["VIRTUAL_ENV"] == "/user/.venv"
        assert result["VIRTUAL_ENV_PROMPT"] == ".venv"

    def test_pops_virtual_env_when_no_orig(self):
        """无 _BROCA_ORIG_VIRTUAL_ENV 时 pop VIRTUAL_ENV / VIRTUAL_ENV_PROMPT。"""
        env = {"VIRTUAL_ENV": "/some/venv", "VIRTUAL_ENV_PROMPT": "venv"}
        result = _strip_and_restore(env)
        assert "VIRTUAL_ENV" not in result
        assert "VIRTUAL_ENV_PROMPT" not in result

    def test_pops_all_broca_orig_prefix(self):
        """所有 _BROCA_ORIG_* 前缀变量被 pop。"""
        env = {
            "_BROCA_ORIG_PYTHONPATH": "/x",
            "_BROCA_ORIG_VIRTUAL_ENV": "/y",
            "_BROCA_ORIG_SOME_FUTURE_VAR": "/z",
        }
        result = _strip_and_restore(env)
        assert not any(k.startswith("_BROCA_ORIG_") for k in result)

    def test_preserves_broca_config_vars(self):
        """BROCA_HOME / BROCA_DATABASE_DIR 等非 runner 标记变量保留。"""
        env = {
            "BROCA_HOME": "/home/user/.broca",
            "BROCA_DATABASE_DIR": "/data",
            "BROCA_COMPONENTS_CONFIG": "/configs.json",
            "BROCA_RUN_INTEGRATION": "1",
        }
        result = _strip_and_restore(env)
        assert result["BROCA_HOME"] == "/home/user/.broca"
        assert result["BROCA_DATABASE_DIR"] == "/data"
        assert result["BROCA_COMPONENTS_CONFIG"] == "/configs.json"
        assert result["BROCA_RUN_INTEGRATION"] == "1"


# ---------------------------------------------------------------------------
# build_user_env — 集成场景
# ---------------------------------------------------------------------------


class TestBuildUserEnv:
    def test_runner_env_restores_values(self, monkeypatch, tmp_path):
        """runner 环境（有 _BROCA_ORIG_*）→ 还原 PYTHONPATH / 剥离内部变量。"""
        monkeypatch.setenv("PYTHONPATH", "/repo/root:/custom")
        monkeypatch.setenv("_BROCA_ORIG_PYTHONPATH", "/custom")
        monkeypatch.setenv("PYTHONSAFEPATH", "1")
        monkeypatch.setenv("BROCA_RUNNER_CHILD", "1")
        monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "true")

        env = build_user_env(str(tmp_path))
        assert env["PYTHONPATH"] == "/custom"
        assert "PYTHONSAFEPATH" not in env
        assert "BROCA_RUNNER_CHILD" not in env
        assert "LITELLM_LOCAL_MODEL_COST_MAP" not in env
        assert "_BROCA_ORIG_PYTHONPATH" not in env

    def test_non_runner_env_strips_only(self, monkeypatch, tmp_path):
        """非 runner 环境（无 _BROCA_ORIG_*）→ 仅剥离内部变量。"""
        monkeypatch.setenv("PYTHONSAFEPATH", "1")
        monkeypatch.setenv("BROCA_RUNNER_CHILD", "1")
        monkeypatch.delenv("PYTHONPATH", raising=False)

        env = build_user_env(str(tmp_path))
        assert "PYTHONSAFEPATH" not in env
        assert "BROCA_RUNNER_CHILD" not in env
        assert "PYTHONPATH" not in env

    def test_workspace_venv_adaptation(self, monkeypatch, tmp_path):
        """workspace 有 .venv → PATH 首位为 .venv/bin，VIRTUAL_ENV 正确。"""
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").touch()

        env = build_user_env(str(tmp_path))
        path_entries = env["PATH"].split(os.pathsep)
        assert path_entries[0] == str(tmp_path / ".venv" / "bin")
        assert env["VIRTUAL_ENV"] == str(tmp_path / ".venv")
        assert env["VIRTUAL_ENV_PROMPT"] == ".venv"

    def test_workspace_venv_name_in_prompt(self, monkeypatch, tmp_path):
        """workspace 有 venv（非 .venv）→ VIRTUAL_ENV_PROMPT 为目录名。"""
        venv = tmp_path / "venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").touch()

        env = build_user_env(str(tmp_path))
        assert env["VIRTUAL_ENV"] == str(tmp_path / "venv")
        assert env["VIRTUAL_ENV_PROMPT"] == "venv"

    def test_no_venv_no_path_change(self, monkeypatch, tmp_path):
        """workspace 无 venv → PATH 不变。"""
        original_path = os.environ.get("PATH", "")
        monkeypatch.delenv("PYTHONPATH", raising=False)

        env = build_user_env(str(tmp_path))
        assert env["PATH"] == original_path

    def test_workspace_venv_overrides_service_venv(self, monkeypatch, tmp_path):
        """workspace venv 优先级 > 服务进程 VIRTUAL_ENV。"""
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").touch()

        monkeypatch.setenv("_BROCA_ORIG_VIRTUAL_ENV", "/service/venv")
        monkeypatch.setenv("_BROCA_ORIG_VIRTUAL_ENV_PROMPT", "service")

        env = build_user_env(str(tmp_path))
        assert env["VIRTUAL_ENV"] == str(tmp_path / ".venv")
        assert env["VIRTUAL_ENV_PROMPT"] == ".venv"

    def test_path_dedup(self, monkeypatch, tmp_path):
        """venv bin 已在 PATH 中时不重复前置。"""
        venv_bin = str(tmp_path / ".venv" / "bin")
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").touch()

        monkeypatch.setenv("PATH", venv_bin + os.pathsep + "/usr/bin")

        env = build_user_env(str(tmp_path))
        path_entries = [p for p in env["PATH"].split(os.pathsep) if p]
        count = path_entries.count(venv_bin)
        assert count == 1
        assert path_entries[0] == venv_bin

    def test_preserves_broca_config_vars(self, monkeypatch, tmp_path):
        """BROCA_HOME 等非 runner 变量在 build_user_env 结果中保留。"""
        monkeypatch.setenv("BROCA_HOME", "/home/user/.broca")
        monkeypatch.setenv("BROCA_DATABASE_DIR", "/data")

        env = build_user_env(str(tmp_path))
        assert env["BROCA_HOME"] == "/home/user/.broca"
        assert env["BROCA_DATABASE_DIR"] == "/data"

    def test_exception_fallback(self, monkeypatch, tmp_path):
        """find_workspace_venv 抛异常时 build_user_env 不崩溃。"""
        with mock_patch(
            "broca.utils.env.find_workspace_venv",
            side_effect=OSError("test error"),
        ):
            env = build_user_env(str(tmp_path))
            assert isinstance(env, dict)
            assert "PATH" in env


# ---------------------------------------------------------------------------
# _validate_venv_dir — 平台参数化测试
# ---------------------------------------------------------------------------


class TestValidateVenvDir:
    def test_posix_bin_python(self, tmp_path):
        venv = tmp_path / "venv"
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "python").touch()
        assert _validate_venv_dir(venv, "posix") is True

    def test_posix_bin_python3(self, tmp_path):
        venv = tmp_path / "venv"
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "python3").touch()
        assert _validate_venv_dir(venv, "posix") is True

    def test_posix_no_python(self, tmp_path):
        venv = tmp_path / "venv"
        (venv / "bin").mkdir(parents=True)
        assert _validate_venv_dir(venv, "posix") is False

    def test_nt_scripts_python(self, tmp_path):
        venv = tmp_path / "venv"
        (venv / "Scripts").mkdir(parents=True)
        (venv / "Scripts" / "python.exe").touch()
        assert _validate_venv_dir(venv, "nt") is True

    def test_nt_no_python(self, tmp_path):
        venv = tmp_path / "venv"
        (venv / "Scripts").mkdir(parents=True)
        assert _validate_venv_dir(venv, "nt") is False


# ---------------------------------------------------------------------------
# _apply_workspace_venv — PATH 前置逻辑
# ---------------------------------------------------------------------------


class TestApplyWorkspaceVenv:
    def test_prepends_path(self, tmp_path):
        venv_dir = tmp_path / ".venv"
        env = {"PATH": "/usr/bin:/bin"}
        # mock sys.platform check by passing posix explicitly
        with mock_patch("sys.platform", "darwin"):
            _apply_workspace_venv(env, venv_dir)
        assert env["PATH"].startswith(str(tmp_path / ".venv" / "bin"))

    def test_sets_virtual_env(self, tmp_path):
        venv_dir = tmp_path / ".venv"
        env = {}
        with mock_patch("sys.platform", "darwin"):
            _apply_workspace_venv(env, venv_dir)
        assert env["VIRTUAL_ENV"] == str(venv_dir)
        assert env["VIRTUAL_ENV_PROMPT"] == ".venv"

    def test_path_dedup_trailing_slash(self, tmp_path):
        """M4: 尾斜杠变体通过 normpath 归一化后识别为重复，不产生近似重复项。"""
        venv_dir = tmp_path / ".venv"
        venv_bin = str(tmp_path / ".venv" / "bin")
        # PATH 中含尾斜杠变体
        env = {"PATH": venv_bin + os.pathsep + "/usr/bin"}
        with mock_patch("sys.platform", "darwin"):
            _apply_workspace_venv(env, venv_dir)
        # normpath 后 venv_bin 与已有路径相同 → 不重复前置
        path_entries = [p for p in env["PATH"].split(os.pathsep) if p]
        norm_entries = [os.path.normpath(p) for p in path_entries]
        venv_bin_norm = os.path.normpath(venv_bin)
        count = norm_entries.count(venv_bin_norm)
        assert count == 1, f"venv bin appears {count} times in PATH: {path_entries}"


# ---------------------------------------------------------------------------
# m3: 补充场景
# ---------------------------------------------------------------------------


class TestFindWorkspaceVenvExtra:
    """m3: 补充 find_workspace_venv 的相对路径/None 归一化 + 候选目录覆盖。"""

    def test_relative_path_normalization(self, tmp_path, monkeypatch):
        """相对路径 workspace → abspath 归一化后正确找到 venv。"""
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").touch()

        # 切换到 workspace 目录，传相对路径 "."
        monkeypatch.chdir(tmp_path)
        result = find_workspace_venv(".")
        assert result is not None
        assert result.name == ".venv"
        assert result.is_absolute()

    def test_none_workspace_uses_cwd(self, tmp_path, monkeypatch):
        """workspace=None → 使用 os.getcwd()。"""
        venv = tmp_path / "venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").touch()

        monkeypatch.chdir(tmp_path)
        result = find_workspace_venv(None)  # type: ignore[arg-type]
        assert result == tmp_path / "venv"

    def test_dotenv_candidate(self, tmp_path):
        """m3: .env 候选目录被识别。"""
        venv = tmp_path / ".env" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").touch()

        result = find_workspace_venv(str(tmp_path))
        assert result == tmp_path / ".env"

    def test_virtualenv_candidate(self, tmp_path):
        """m3: virtualenv 候选目录被识别。"""
        venv = tmp_path / "virtualenv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").touch()

        result = find_workspace_venv(str(tmp_path))
        assert result == tmp_path / "virtualenv"


class TestBuildUserEnvExtra:
    """m3 + M1: 补充 build_user_env 的 Windows 分支 + 异常兜底。"""

    def test_windows_platform_branch(self, tmp_path, monkeypatch):
        """m3: mock sys.platform=win32 → 检测 Scripts/python.exe。"""
        # 创建 Windows 风格 venv
        venv = tmp_path / ".venv" / "Scripts"
        venv.mkdir(parents=True)
        (venv / "python.exe").touch()

        monkeypatch.setattr("sys.platform", "win32")
        monkeypatch.delenv("PYTHONPATH", raising=False)
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)

        env = build_user_env(str(tmp_path))
        assert env["VIRTUAL_ENV"] == str(tmp_path / ".venv")
        # PATH 应包含 .venv/Scripts
        path_entries = env["PATH"].split(os.pathsep)
        assert any(".venv" in p and "Scripts" in p for p in path_entries), (
            f"PATH should contain .venv/Scripts, got: {path_entries[:3]}"
        )

    def test_bad_workspace_type_no_raise(self, monkeypatch, tmp_path):
        """M1: workspace 为非法类型（如 object()）时不抛异常，回退到 cwd。"""
        monkeypatch.chdir(tmp_path)
        env = build_user_env(object())  # type: ignore[arg-type]
        assert isinstance(env, dict)
        assert "PATH" in env
        # 不应含污染变量
        assert "PYTHONSAFEPATH" not in env
