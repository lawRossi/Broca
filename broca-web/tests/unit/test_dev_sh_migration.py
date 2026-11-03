"""回归测试：dev.sh 必须自己迁移「隔离后的 dev 数据库」。

背景（bug）：
    `broca-web/dev.sh` 启动 dev 实例时报：
        Failed to restore active sessions:
        (sqlite3.OperationalError) no such table: session_runner

    根因不是迁移失败，而是**根本没有迁移这一步**：
      1. 迁移只写在 `scripts/install.sh` 里，且只迁生产库
         (`~/.broca/data/sessions.db`)；
      2. dev 通过 `BROCA_CONFIG=./configs.dev.json` 把数据目录隔离到
         `backend/.local-data`，那是全新目录；
      3. SQLAlchemy 的 engine 一 `connect()`，SQLite 就自动创建了
         `sessions.db`（4096B，只有文件头，0 张表）；
      4. 于是 `RunnerManager.restore_active_sessions()` 查 `session_runner` 直接炸。

    而且这里**不能**简单加一句 `alembic upgrade head`：
    `broca/alembic/env.py` 的 `get_configs()` 是纯文件驱动、不读 `BROCA_CONFIG`
    环境变量，会回退到仓库 `configs/configs.json`（`database_dir=~/.broca/data`），
    把**生产库**当成迁移目标。必须用 `-x db_url=` 显式指定。

本文件锁定修复后的契约：
  - 静态：dev.sh 里有迁移段、用 `-x db_url=`、排在 uvicorn 之前、失败即退出；
  - 动态：dev.sh 用的那条 alembic 命令确实能把空库迁出 `session_runner` 表。
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "broca-web" / "backend"
DEV_SH = REPO_ROOT / "broca-web" / "dev.sh"
BROCA_ALEMBIC_INI = REPO_ROOT / "broca" / "alembic.ini"

pytestmark = pytest.mark.skipif(
    not (DEV_SH.is_file() and BROCA_ALEMBIC_INI.is_file()),
    reason="dev.sh 或 broca/alembic.ini 缺失",
)


# ---------------------------------------------------------------------------
# 静态契约：脚本内容
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    assert path.is_file(), f"缺少 {path}"
    return path.read_text(encoding="utf-8")


def _alembic_lines(text: str) -> list[str]:
    """脚本里所有**真正执行** alembic 的命令行（先拼接续行）。

    排除 `echo "..."` 提示行（里面会带一条给用户手动复制的命令）。
    """
    joined = re.sub(r"\\\n\s*", " ", text)
    lines = []
    for raw in joined.splitlines():
        line = raw.strip()
        if "-m alembic" not in line:
            continue
        if line.startswith(("echo ", "#")):
            continue
        lines.append(line)
    return lines


class TestDevShRunsMigration:
    def test_has_migrate_step(self):
        text = _read(DEV_SH)
        assert "[migrate]" in text, "dev.sh 没有迁移步骤 —— 空库会报 no such table"

    def test_migration_runs_before_uvicorn(self):
        """迁移必须早于后端启动，否则 startup 钩子还是会撞上 0 表空库。"""
        text = _read(DEV_SH)
        migrate_idx = text.find("[migrate]")
        uvicorn_idx = text.find("uvicorn app.main:app")
        assert migrate_idx != -1, "dev.sh 没有 [migrate] 段"
        assert uvicorn_idx != -1, "dev.sh 没有启动 uvicorn"
        assert migrate_idx < uvicorn_idx, "迁移排在 uvicorn 之后 —— 启动时表还不存在"

    def test_migrates_both_databases(self):
        """sessions.db（broca 会话库）与 backend.db（登录/用户库）都要迁。"""
        text = _read(DEV_SH)
        assert "SESSIONS_DB" in text, "没有迁移 broca 的 sessions.db"
        assert "BACKEND_DB" in text, "没有迁移后端的 backend.db"

    def test_target_resolved_from_runtime_config(self):
        """目标库必须从运行时配置反解，不能硬编码 dev.db 路径。"""
        text = _read(DEV_SH)
        assert "get_configs()" in text, "sessions.db 路径没有从 broca 配置反解"
        assert "settings.sqlite_database_path" in text, (
            "backend.db 路径没有从 settings 反解（会与运行时读的库不一致）"
        )


class TestDevShSurvivesDeadPid:
    """`set -e` + `kill <已退出进程>` = 脚本静默中止。

    另一个独立 bug：启动前的清理段先 `kill`（SIGTERM）再 `kill -9`。旧后端
    收到 SIGTERM 后立刻退出，紧接着的 `kill -9` 返回 1 —— 脚本开了 `set -e`，
    于是直接中止。现象极具误导性：日志停在「[cleanup] 杀掉旧后端 PID: xxx」，
    既不启动后端也不报错。
    """

    def test_set_e_is_enabled(self):
        """这条约束只在 set -e 下才致命，先确认前提成立。"""
        text = _read(DEV_SH)
        assert re.search(r"^set -e", text, re.MULTILINE), (
            "dev.sh 不再使用 set -e，本文件的 kill 容错约束需重新评估"
        )

    def test_all_kill_calls_are_tolerant(self):
        offenders = [
            (i, line.strip())
            for i, line in enumerate(_read(DEV_SH).splitlines(), 1)
            if re.match(r"^\s*(kill|pkill)\s", line) and "||" not in line
        ]
        assert not offenders, (
            "以下 kill/pkill 在目标进程已退出时会返回 1，"
            f"配合 set -e 会静默中止脚本: {offenders}"
        )


class TestDevShPassesExplicitDbUrl:
    """环境变量是死配置，必须用 `-x db_url=` 显式传目标库。"""

    def test_every_alembic_call_passes_db_url(self):
        lines = _alembic_lines(_read(DEV_SH))
        assert lines, "dev.sh 里找不到 alembic 迁移命令"
        for line in lines:
            assert '-x "db_url=sqlite:///' in line, f"迁移没有显式指定目标库: {line}"

    def test_no_dead_env_var_prefix(self):
        text = _read(DEV_SH)
        for pattern in (
            r'BROCA_DATABASE_DIR="[^"]*"\s+\$',
            r'SQLITE_DATABASE_PATH="[^"]*"\s+\$',
        ):
            assert not re.search(pattern, text), (
                f"dev.sh 仍用环境变量传迁移目标库: /{pattern}/"
            )

    def test_migration_failure_is_fatal(self):
        """迁移失败必须退出 —— 否则又是一个「服务起来了但没有表」。"""
        text = _read(DEV_SH)
        for marker in ("sessions.db 迁移失败", "backend.db 迁移失败"):
            idx = text.find(marker)
            assert idx != -1, f"缺少失败分支: {marker}"
            assert "exit 1" in text[idx : idx + 300], f"{marker} 分支没有 exit 1"

    def test_guards_against_migrating_production_db(self):
        """BROCA_CONFIG 配置异常时，不能顺手把仓库新迁移应用到生产库。"""
        text = _read(DEV_SH)
        assert "BROCA_ALLOW_PROD_DATA" in text
        idx = text.find("跳过 sessions.db 迁移")
        assert idx != -1, "缺少「目标库在生产目录则跳过」的护栏"


# ---------------------------------------------------------------------------
# 动态契约：dev.sh 用的那条命令真的能把空库迁出表来
# ---------------------------------------------------------------------------


def _tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


def _run_alembic(cwd: Path, ini: str | None, db_path: Path):
    """复刻 dev.sh 的调用方式（同一 CWD / PYTHONPATH / -x 形式）。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env.pop("BROCA_DATABASE_DIR", None)
    cmd = [sys.executable, "-m", "alembic"]
    if ini:
        cmd += ["-c", ini]
    cmd += ["-x", f"db_url=sqlite:///{db_path}", "upgrade", "head"]
    return subprocess.run(
        cmd, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=300
    )


class TestMigrationActuallyCreatesTables:
    def test_sessions_db_gets_session_runner_table(self, tmp_path):
        """核心回归：空库迁移后必须存在 session_runner，否则启动必炸。"""
        target = tmp_path / ".local-data" / "sessions.db"
        target.parent.mkdir(parents=True)

        result = _run_alembic(BACKEND_DIR, str(BROCA_ALEMBIC_INI), target)
        assert result.returncode == 0, (result.stdout + result.stderr)[-3000:]

        tables = _tables(target)
        assert "session_runner" in tables, (
            f"迁移后仍缺 session_runner（现有表: {sorted(tables)}）"
        )
        assert {"session", "turn", "message", "alembic_version"} <= tables

    def test_sessions_db_migration_is_idempotent(self, tmp_path):
        """dev.sh 每次启动都会跑，重复执行必须是 no-op。"""
        target = tmp_path / "sessions.db"
        first = _run_alembic(BACKEND_DIR, str(BROCA_ALEMBIC_INI), target)
        assert first.returncode == 0, (first.stdout + first.stderr)[-3000:]

        second = _run_alembic(BACKEND_DIR, str(BROCA_ALEMBIC_INI), target)
        assert second.returncode == 0, (second.stdout + second.stderr)[-3000:]
        assert "session_runner" in _tables(target)

    def test_backend_db_gets_auth_tables(self, tmp_path):
        """后端库迁移后必须有 user_auth（否则登录接口 500）。"""
        target = tmp_path / "backend.db"

        result = _run_alembic(BACKEND_DIR, None, target)
        assert result.returncode == 0, (result.stdout + result.stderr)[-3000:]

        tables = _tables(target)
        assert "user_auth" in tables, f"迁移后缺 user_auth（现有表: {sorted(tables)}）"
        assert "alembic_version" in tables
