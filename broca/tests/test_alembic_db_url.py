"""回归测试：alembic 迁移必须落在「运行时真正读写的那个库」上。

背景（bug）：
    `scripts/install.sh` 曾用环境变量传迁移目标库：
        BROCA_DATABASE_DIR="$BROCA_DB_DIR" $PYTHON -m alembic -c broca/alembic.ini upgrade head
    但 `broca/alembic/env.py` 早已改成 `get_configs()` 解析路径（纯文件驱动），
    环境变量是死配置 —— 迁移目标由 configs.json 决定，而不是安装脚本传的路径。
    用户自定义过 `database_dir`、或安装脚本与运行时看到不同 configs.json 时，
    就会出现「表建在一个库、Web 运行时读写另一个库」。
    同理 `SQLITE_DATABASE_PATH` 对后端 alembic 也无效（见
    broca-web/tests/unit/test_alembic_db_url.py）。

修复：`env.py` 支持 `-x db_url=<完整 URL>`，安装脚本改用它显式指定目标库。
本文件锁定这条优先级链：
    -x db_url > BROCA_DATABASE_DIR > configs.json > alembic.ini > 默认路径
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "broca" / "alembic.ini"

pytestmark = pytest.mark.skipif(
    not ALEMBIC_INI.is_file(), reason="broca/alembic.ini 缺失"
)


def _run_alembic(tmp_home: Path, *extra_args: str, env_extra: dict[str, str] | None = None):
    """在隔离的 HOME 下跑 `alembic upgrade head`，返回 CompletedProcess。"""
    env = os.environ.copy()
    env["HOME"] = str(tmp_home)
    env.pop("BROCA_DATABASE_DIR", None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "broca/alembic.ini", *extra_args, "upgrade", "head"],
        cwd=str(REPO_ROOT),
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


def _make_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".broca" / "data").mkdir(parents=True, exist_ok=True)
    return home


class TestExplicitDbUrl:
    """`-x db_url=` 是最高优先级：安装脚本靠它保证迁移目标 == 运行时库。"""

    def test_x_argument_wins_over_configs_json(self, tmp_path):
        home = _make_home(tmp_path)
        target = tmp_path / "custom-dir" / "sessions.db"
        target.parent.mkdir(parents=True, exist_ok=True)

        result = _run_alembic(home, "-x", f"db_url=sqlite:///{target}")
        assert result.returncode == 0, result.stderr[-3000:]

        assert target.is_file(), "迁移没有落到 -x db_url 指定的库上"
        assert "alembic_version" in _tables(target)
        assert "session" in _tables(target)

        # configs.json 里的 database_dir（~/.broca/data）不能被顺带创建
        assert not (home / ".broca" / "data" / "sessions.db").exists(), (
            "迁移同时写入了 configs.json 指向的库 —— 目标库不唯一"
        )

    def test_x_argument_wins_over_env_var(self, tmp_path):
        home = _make_home(tmp_path)
        target = tmp_path / "from-x.db"
        env_db_dir = tmp_path / "from-env"

        result = _run_alembic(
            home,
            "-x",
            f"db_url=sqlite:///{target}",
            env_extra={"BROCA_DATABASE_DIR": str(env_db_dir)},
        )
        assert result.returncode == 0, result.stderr[-3000:]

        assert target.is_file()
        assert not (env_db_dir / "sessions.db").exists(), (
            "环境变量不该压过 -x db_url"
        )


class TestEnvVarFallback:
    """没有 -x 时，BROCA_DATABASE_DIR 必须真的生效（docstring 承诺过的行为）。"""

    def test_broca_database_dir_env_var_is_honored(self, tmp_path):
        home = _make_home(tmp_path)
        db_dir = tmp_path / "env-dir"
        db_dir.mkdir()

        result = _run_alembic(home, env_extra={"BROCA_DATABASE_DIR": str(db_dir)})
        assert result.returncode == 0, result.stderr[-3000:]

        assert (db_dir / "sessions.db").is_file(), (
            "BROCA_DATABASE_DIR 被忽略了 —— 迁移落到了别处"
        )
        assert not (home / ".broca" / "data" / "sessions.db").exists()

    def test_falls_back_to_configs_json(self, tmp_path):
        """既没有 -x 也没有环境变量时，回到 configs.json 的 database_dir。"""
        home = _make_home(tmp_path)

        result = _run_alembic(home)
        assert result.returncode == 0, result.stderr[-3000:]

        default_db = home / ".broca" / "data" / "sessions.db"
        assert default_db.is_file(), "未按 configs.json 的 database_dir 迁移"
