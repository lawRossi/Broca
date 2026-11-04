"""Session Runner 模块可导入性与注解绑定回归测试（P0-1）

背景
----
`broca/session_runner/runner.py` 曾在模块级写：

    _agent_factory: Optional[AgentFactory] = None

而 `AgentFactory` 从未被 import。Python 3.14 的 PEP 649 让注解延迟求值，
所以在本机「看起来没问题」；但 3.12 / 3.13 上模块级注解在 import 时立即求值，
直接 `NameError: name 'AgentFactory' is not defined`，整个 runner 子进程起不来。

本机无法用 3.12 解释器复现（venv 里的 pydantic_core 等编译依赖是 3.14 构建，
`python3.12 -c "import broca"` 会先挂在依赖上），因此用 **AST 静态校验**
确定性复现「注解立即求值」的语义：注解中出现的每个名字都必须在模块内已绑定。

注意：`from __future__ import annotations` 会让 `module.__annotations__` 变成字符串，
所以 `test_module_annotations_evaluable` 在修复后恒为绿——真正有效的守门是
`test_module_level_annotations_are_all_bound`。
"""

from __future__ import annotations

import ast
import builtins
import importlib
import pathlib

import pytest

SESSION_RUNNER_DIR = pathlib.Path(__file__).resolve().parents[1] / "session_runner"


def _module_files() -> list[pathlib.Path]:
    """返回 session_runner 包下所有 .py 文件（按路径排序，保证稳定）。"""
    return sorted(SESSION_RUNNER_DIR.rglob("*.py"))


def _module_name(path: pathlib.Path) -> str:
    """把文件路径转换成可 import 的模块名。"""
    rel = path.relative_to(SESSION_RUNNER_DIR.parent.parent)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _bound_names(tree: ast.Module) -> set[str]:
    """收集模块内所有已绑定的名字（含内置名）。

    必须用 ``ast.walk(tree)`` 而不是 ``tree.body``：``if TYPE_CHECKING:`` 下的
    ``from ... import AgentFactory`` 位于 ``If`` 节点内部，只扫顶层会把
    「修复后」的注解名字仍判为未绑定。
    """
    names: set[str] = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names |= {(a.asname or a.name).split(".")[0] for a in node.names}
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _annotations_to_check(tree: ast.Module) -> list[ast.expr]:
    """返回所有「模块级」与「类级」AnnAssign 的注解表达式。"""
    annotations: list[ast.expr] = []
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, ast.AnnAssign):
                    annotations.append(sub.annotation)
    return annotations


def test_all_session_runner_modules_importable() -> None:
    """session_runner 包下每个模块都必须可 import（无 NameError/ImportError）。"""
    files = _module_files()
    assert files, "no session_runner modules found — path resolution is broken"

    failures: list[str] = []
    for path in files:
        name = _module_name(path)
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - 需要汇总所有失败模块
            failures.append(f"{name}: {type(exc).__name__}: {exc}")

    assert not failures, "以下模块无法 import:\n" + "\n".join(failures)


def test_module_annotations_evaluable() -> None:
    """访问每个模块的 ``__annotations__`` 不得抛 NameError。"""
    failures: list[str] = []
    for path in _module_files():
        name = _module_name(path)
        module = importlib.import_module(name)
        try:
            module.__annotations__  # noqa: B018 - 触发属性访问
        except NameError as exc:
            failures.append(f"{name}: {exc}")

    assert not failures, "以下模块的 __annotations__ 求值失败:\n" + "\n".join(failures)


def test_module_level_annotations_are_all_bound() -> None:
    """AST 静态校验：模块级/类级注解中的每个名字都必须在模块内已绑定。

    这是本机唯一能确定性复现 3.12/3.13「注解立即求值」语义的手段，
    不依赖解释器版本、不需要 import 成功。
    """
    violations: list[str] = []
    for path in _module_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bound = _bound_names(tree)
        for annotation in _annotations_to_check(tree):
            for node in ast.walk(annotation):
                if isinstance(node, ast.Name) and node.id not in bound:
                    violations.append(
                        f"{path.relative_to(SESSION_RUNNER_DIR.parent.parent)}:"
                        f"{node.lineno}: {node.id}"
                    )

    assert not violations, (
        "注解引用了未绑定的名字（3.12/3.13 上会 NameError）:\n"
        + "\n".join(sorted(set(violations)))
    )


def test_future_annotations_import_present() -> None:
    """runner.py 首部必须存在 ``from __future__ import annotations``。"""
    source = (SESSION_RUNNER_DIR / "runner.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    has_future = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )
    assert has_future, "runner.py 缺少 `from __future__ import annotations`"


def test_agent_factory_reference_is_guarded() -> None:
    """runner.py 中每一处 ``AgentFactory`` 都必须有 import 或 TYPE_CHECKING 守卫。"""
    source = (SESSION_RUNNER_DIR / "runner.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    # 收集所有出现的 AgentFactory 的 Name 节点
    usages = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "AgentFactory"
    ]
    assert usages, "runner.py 中已无 AgentFactory 引用，本守卫测试可删除"

    # 必须存在 import（无论是在 TYPE_CHECKING 下还是顶层）
    imported = any(
        isinstance(node, ast.ImportFrom)
        and any(alias.name == "AgentFactory" for alias in node.names)
        for node in ast.walk(tree)
    )
    assert imported, "runner.py 引用了 AgentFactory 但没有对应的 import"


# ---------------------------------------------------------------------------
# 导出面（Phase 3 Task 3.5：拆分后公开 API 不得断）
# ---------------------------------------------------------------------------


def test_public_export_surface_is_intact() -> None:
    """`broca.session_runner` 与 `broca.components` 的公开导出必须可导入。

    拆分后 ``IPCClient`` / ``IPCServer`` 来自 ``transport/``，
    ``RunnerManager`` 仍是 ``IPCSessionRunner`` 的别名；任何一处漏改都会让
    `from broca.session_runner import IPCClient` 直接 ImportError。
    """
    from broca.session_runner import IPCClient, IPCServer, RunnerManager
    from broca.session_runner.manager import IPCSessionRunner

    assert RunnerManager is IPCSessionRunner
    assert IPCClient is not None and IPCServer is not None

    # 传输层的真实实现
    from broca.session_runner.transport.client import IPCClient as RealClient
    from broca.session_runner.transport.server import IPCServer as RealServer

    assert IPCClient is RealClient
    assert IPCServer is RealServer

    # 组件层 ABC
    import broca.components  # noqa: F401 - 只验证包可导入
    from broca.components import SessionRunner
    from broca.components.session_runner import SessionRunner as SessionRunnerABC

    assert SessionRunner is SessionRunnerABC
