"""`SessionRunner` ABC 契约测试（Phase 4 Task 4.1）

本阶段的目标是「彻底消除抽象泄漏」：API 层只能依赖 ABC 的 13 个方法，
不得访问 `IPCSessionRunner` 的私有属性。

ABC 的唯一修改方是 Task 4.1（Task 1.4 只加了 `request_stop`），
`test_abc_method_count_is_13` 就是防止两个 Task 各写一半后无人发现。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from broca.components.session_runner import SessionRunner
from broca.session_runner.manager import IPCSessionRunner

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
API_FILE = REPO_ROOT / "broca-web" / "backend" / "app" / "api" / "session_runner.py"
API_DIR = REPO_ROOT / "broca-web" / "backend" / "app" / "api"

EXPECTED_ABC_METHODS = {
    "start_session",
    "stop_session",
    "request_stop",
    "restart_session",
    "send_command",
    "get_status",
    "list_sessions",
    "get_stats",
    "on",
    "start_heartbeat_monitor",
    "stop_heartbeat_monitor",
    "restore_active_sessions",
    "shutdown_all",
}


def test_ipc_session_runner_implements_abc():
    """实现类必须满足 ABC：issubclass 且无残留抽象方法。"""
    assert issubclass(IPCSessionRunner, SessionRunner)
    assert IPCSessionRunner.__abstractmethods__ == frozenset()


def test_abc_method_count_is_13():
    """ABC 恰好 13 个抽象方法，与 Task 1.4 + Task 4.1 的清单一致。"""
    assert SessionRunner.__abstractmethods__ == frozenset(EXPECTED_ABC_METHODS)
    assert len(SessionRunner.__abstractmethods__) == 13


def test_abc_covers_all_api_calls():
    """API 层调用的每个 `runner_manager.<attr>` 都必须在 ABC 中定义。"""
    tree = ast.parse(API_FILE.read_text(encoding="utf-8"), filename=str(API_FILE))

    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if not isinstance(node.value, ast.Name) or node.value.id != "runner_manager":
            continue
        called.add(node.attr)

    assert called, "未在 API 层发现任何 runner_manager 调用，测试失效"

    missing = sorted(attr for attr in called if not hasattr(SessionRunner, attr))
    assert not missing, f"API 层调用了 ABC 未声明的方法: {missing}"

    abstract_missing = sorted(
        attr for attr in called if attr not in SessionRunner.__abstractmethods__
    )
    assert not abstract_missing, (
        f"API 层调用了非 ABC 抽象方法（可能是实现类私有 API）: {abstract_missing}"
    )


def test_no_private_attr_access_in_api():
    """API 目录下不得访问 runner manager 的私有属性（抽象泄漏）。"""
    offenders: list[str] = []

    for path in sorted(API_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            if not isinstance(node.value, ast.Name):
                continue
            if node.value.id not in {"runner_manager", "RunnerManager"}:
                continue
            if node.attr.startswith("_"):
                offenders.append(f"{path.name}:{node.lineno}: {node.value.id}.{node.attr}")

    assert not offenders, "API 层访问了私有属性:\n" + "\n".join(offenders)


def test_legacy_get_session_status_emits_deprecation_warning():
    """旧名 `get_session_status` 仍可用，但必须触发 DeprecationWarning。"""
    manager = IPCSessionRunner()
    manager._registry.clear()

    with pytest.warns(DeprecationWarning, match="get_status"):
        result = manager.get_session_status("no-such-session")

    assert result is None
    # 新名不告警
    assert manager.get_status("no-such-session") is None


def test_legacy_get_session_status_is_only_used_by_deprecation_test():
    """`get_session_status(` 只允许出现在 `test_legacy_*` 用例内部。

    计划的 AC 写的是 `grep -rn "\\.get_session_status(" broca/tests/ | grep -v test_legacy_`
    为空，但 grep 是逐行的：调用语句单独成行时不包含 `test_legacy_` 字样，
    该命令永远不可能为空。这里用 AST 精确实现同一意图（按**所属函数**过滤）。
    """
    tests_dir = pathlib.Path(__file__).resolve().parent
    offenders: list[str] = []

    for path in sorted(tests_dir.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr != "get_session_status":
                    continue
                if func.name.startswith("test_legacy_"):
                    continue
                offenders.append(f"{path.name}:{node.lineno} in {func.name}()")

    assert not offenders, "以下用例仍调用已废弃的 get_session_status():\n" + "\n".join(
        offenders
    )
