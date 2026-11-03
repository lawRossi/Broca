"""回归测试：安装脚本的数据库迁移必须落在「运行时读写的那个库」上。

背景（bug）：
    安装后出现「Web 读到的库和实际写入的库不是同一个」。根因是 install 脚本
    用**环境变量**给 alembic 传目标库，而迁移期和运行时的配置解析链是两套：

      - `broca/configs.py` 与 `broca-web/backend/app/core/config.py` 都是纯文件
        驱动（后者 `settings_customise_sources` 明确移除了 `env_settings`），
        环境变量会被静默忽略：
            BROCA_DATABASE_DIR="$BROCA_DB_DIR" $PYTHON -m alembic ...   # 死配置
            SQLITE_DATABASE_PATH="sqlite:///...backend.db" $PYTHON ...  # 死配置
        后者尤其致命：迁移实际写进 CWD 下仓库开发 .env 指定的
        `broca-web/backend/dev.db`，运行时却读 `~/.broca/data/backend.db`。

      - 迁移用的解释器是 `$PYTHON`（系统 python）而不是 `$BROCA_PYTHON`
        （装了 broca/alembic 的 venv）。全新安装（非已激活 venv）路径下
        `python -m alembic` 直接 ModuleNotFoundError，而脚本只 `warn` 不退出，
        表于是永远不存在（代码里没有 create_all）。

      - 迁移排在 `sync_configs.py` 之前，迁移期用户配置还不存在。

本文件锁定修复后的契约（静态检查脚本内容，不执行安装）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"
INSTALL_PS1 = REPO_ROOT / "scripts" / "install.ps1"
GEN_ENV = REPO_ROOT / "scripts" / "gen_backend_env.py"


def _read(path: Path) -> str:
    assert path.is_file(), f"缺少 {path}"
    return path.read_text(encoding="utf-8")


def _alembic_lines(text: str) -> list[str]:
    """脚本里所有调用 alembic 的行（含续行拼接后的命令）。"""
    # 先把 shell/ps 的续行拼起来，便于按"一条命令"分析
    joined = re.sub(r"\\\n\s*", " ", text)
    joined = re.sub(r"`\n\s*", " ", joined)
    return [ln.strip() for ln in joined.splitlines() if "alembic" in ln and "-m alembic" in ln]


class TestInstallShMigration:
    def test_uses_venv_python_not_system_python(self):
        """必须用 $BROCA_PYTHON —— 系统 python 里没有 alembic/broca。"""
        lines = _alembic_lines(_read(INSTALL_SH))
        assert lines, "install.sh 里找不到 alembic 迁移命令"
        for line in lines:
            assert '"$BROCA_PYTHON" -m alembic' in line, (
                f"迁移没有使用 venv 解释器: {line}"
            )
            assert "$PYTHON -m alembic" not in line.replace('"$BROCA_PYTHON"', ""), (
                f"迁移仍在使用系统解释器 $PYTHON: {line}"
            )

    def test_passes_explicit_db_url(self):
        """必须用 -x db_url= 显式指定目标库（环境变量是死配置）。"""
        lines = _alembic_lines(_read(INSTALL_SH))
        assert lines
        for line in lines:
            assert '-x "db_url=sqlite:///' in line, (
                f"迁移没有显式指定目标库: {line}"
            )

    def test_no_dead_env_var_prefix(self):
        """不得再以环境变量前缀的方式传目标库。"""
        text = _read(INSTALL_SH)
        for pattern in (
            r'BROCA_DATABASE_DIR="[^"]*"\s+\$',
            r'SQLITE_DATABASE_PATH="[^"]*"\s+\$',
            r"\$env:BROCA_DATABASE_DIR\s*=",
            r"\$env:SQLITE_DATABASE_PATH\s*=",
        ):
            assert not re.search(pattern, text), (
                f"install.sh 仍用环境变量传迁移目标库: /{pattern}/"
            )

    def test_config_sync_runs_before_migration(self):
        """sync_configs 必须先于迁移，否则迁移读不到用户 configs.json。"""
        text = _read(INSTALL_SH)
        sync_idx = text.find("sync_configs.py")
        alembic_idx = text.find("-m alembic")
        assert sync_idx != -1, "install.sh 没有调用 sync_configs.py"
        assert alembic_idx != -1, "install.sh 没有 alembic 迁移"
        assert sync_idx < alembic_idx, (
            "sync_configs.py 排在 alembic 之后 —— 迁移会回退到仓库模板配置"
        )

    def test_migration_failure_is_fatal(self):
        """迁移失败必须退出，不能只 warn（否则"装完了但没表"极难排查）。"""
        text = _read(INSTALL_SH)
        # 两个失败分支都要 exit 1
        assert text.count("主数据库迁移失败") == 1
        assert text.count("后端数据库迁移失败") == 1
        for marker in ("主数据库迁移失败", "后端数据库迁移失败"):
            idx = text.find(marker)
            assert idx != -1
            tail = text[idx : idx + 400]
            assert "exit 1" in tail, f"{marker} 分支没有 exit 1"

    def test_verifies_backend_db_path_consistency(self):
        """生成 .env 后必须校验 SQLITE_DATABASE_PATH 与迁移目标一致。"""
        text = _read(INSTALL_SH)
        assert "SQLITE_DATABASE_PATH=sqlite:" in text, (
            "install.sh 没有从生成的 .env 里回读 SQLITE_DATABASE_PATH 做一致性校验"
        )
        idx = text.find("库路径一致性校验通过")
        assert idx != -1, "缺少 backend.db 路径一致性护栏"


class TestInstallPs1Migration:
    def test_uses_explicit_db_url(self):
        lines = _alembic_lines(_read(INSTALL_PS1))
        assert lines, "install.ps1 里找不到 alembic 迁移命令"
        for line in lines:
            assert '-x "db_url=sqlite:///' in line, (
                f"install.ps1 迁移没有显式指定目标库: {line}"
            )

    def test_config_sync_runs_before_migration(self):
        text = _read(INSTALL_PS1)
        sync_idx = text.find("sync_configs.py")
        alembic_idx = text.find("-m alembic")
        assert sync_idx != -1 and alembic_idx != -1
        assert sync_idx < alembic_idx, "install.ps1 的 sync_configs 排在 alembic 之后"

    def test_generates_backend_env(self):
        """Windows 侧也必须生成 backend/.env，否则 Settings 全走默认值。"""
        text = _read(INSTALL_PS1)
        assert "gen_backend_env.py" in text, (
            "install.ps1 没有生成 backend/.env —— 后端会退回到 dev 默认配置"
        )


class TestGeneratorContract:
    """迁移目标与 .env 里的 SQLITE_DATABASE_PATH 必须同源（同一个公式）。"""

    def test_generator_uses_broca_home_data_dir(self):
        text = _read(GEN_ENV)
        assert 'f"SQLITE_DATABASE_PATH=sqlite:///{broca_home}/data/backend.db\\n"' in text, (
            "gen_backend_env.py 的 backend.db 路径公式变了，"
            "需同步 scripts/install.sh 里的 BACKEND_DB_PATH"
        )

    @pytest.mark.parametrize("script", [INSTALL_SH, INSTALL_PS1])
    def test_installers_point_backend_db_at_broca_home_data(self, script: Path):
        text = _read(script)
        assert "data/backend.db" in text or "data\\backend.db" in text, (
            f"{script.name} 没有把 backend.db 定位到 ~/.broca/data"
        )
