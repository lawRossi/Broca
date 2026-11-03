"""回归测试：后端 alembic 迁移必须落在「运行时真正读写的那个库」上。

背景（bug）：
    `scripts/install.sh` 曾这样迁移后端库：
        SQLITE_DATABASE_PATH="sqlite:///${BROCA_HOME}/data/backend.db" \\
            $PYTHON -m alembic upgrade head      # cwd = broca-web/backend
    但 `app/core/config.py::Settings.settings_customise_sources` 明确移除了
    `env_settings` 源（纯 .env 文件驱动，不读 os.environ），所以
    `SQLITE_DATABASE_PATH` 在迁移期被静默忽略；`alembic/env.py` 走的是
    `settings.sync_database_url`，即 CWD 里**仓库开发 .env** 的值
    `sqlite:///./dev.db`。结果：表被建进 `broca-web/backend/dev.db`，
    而运行时读的是 `~/.broca/data/backend.db` —— 部署后登录接口 500。

修复：`alembic/env.py` 支持 `-x db_url=<完整 URL>`，安装脚本改用它。
本文件锁定 `-x db_url` 的优先级与「不再写 dev.db」的契约。
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

pytestmark = pytest.mark.skipif(
    not ALEMBIC_INI.is_file(), reason="backend/alembic.ini 缺失"
)


def _run_alembic(*extra_args: str, env_extra: dict[str, str] | None = None):
    """在 backend 目录下跑 `alembic upgrade head`。"""
    env = os.environ.copy()
    env.pop("SQLITE_DATABASE_PATH", None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "alembic", *extra_args, "upgrade", "head"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


class TestExplicitDbUrl:
    """`-x db_url=` 决定迁移目标；环境变量不再参与（它本来就没生效过）。"""

    def test_x_argument_targets_requested_file(self, tmp_path):
        target = tmp_path / "data" / "backend.db"
        target.parent.mkdir(parents=True, exist_ok=True)

        result = _run_alembic("-x", f"db_url=sqlite:///{target}")
        assert result.returncode == 0, result.stderr[-3000:]

        assert target.is_file(), "迁移没有落到 -x db_url 指定的库上"
        tables = _tables(target)
        assert "alembic_version" in tables
        assert "user_auth" in tables
        assert "user_profile" in tables

    def test_x_argument_beats_env_var(self, tmp_path):
        """SQLITE_DATABASE_PATH 环境变量不能改变 -x 指定的目标。

        这条曾经是 bug 本体：安装脚本用环境变量传目标库，而 Settings 根本不读
        os.environ，迁移静默写到了 dev.db。
        """
        target = tmp_path / "explicit.db"
        env_target = tmp_path / "from-env.db"

        result = _run_alembic(
            "-x",
            f"db_url=sqlite:///{target}",
            env_extra={"SQLITE_DATABASE_PATH": f"sqlite:///{env_target}"},
        )
        assert result.returncode == 0, result.stderr[-3000:]

        assert target.is_file()
        assert not env_target.exists(), "环境变量不该压过 -x db_url"
