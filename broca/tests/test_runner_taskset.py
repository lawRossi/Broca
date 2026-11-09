"""`TaskSet` 与后台任务可追踪性测试（Phase 2 Task 2.5，P1-4）

历史问题：``asyncio.create_task`` / ``ensure_future`` 的返回值没有强引用，
既可能被 GC 提前回收，异常也只会以 "Task exception was never retrieved"
的形式在解释器退出时冒出来 —— 生产上表现为「某次 crew 事件回调静默失效」。
"""

from __future__ import annotations

import ast
import asyncio
import gc
import pathlib
import pytest

import logging
from unittest.mock import patch

from broca.session_runner.events import TaskSet


@pytest.fixture(autouse=True)
def _stdlib_logger():
    """确保 caplog 可捕获 events 模块的日志。"""
    stdlib_logger = logging.getLogger("broca.session_runner.events")
    with patch("broca.session_runner.events.logger", stdlib_logger):
        yield stdlib_logger


SESSION_ROOT = pathlib.Path(__file__).resolve().parents[1] / "session_runner"


# ---------------------------------------------------------------------------
# TaskSet
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawned_task_exception_is_logged(caplog):
    """spawn 的协程抛异常 → 记录 ERROR，且不产生未取回异常的告警。"""

    async def _boom():
        raise RuntimeError("kaboom")

    tasks = TaskSet("test")
    task = tasks.spawn(_boom())

    with caplog.at_level("ERROR", logger="broca.session_runner.events"):
        await asyncio.wait([task], timeout=2.0)
        # done_callback 是同步回调，需要让事件循环转一圈
        await asyncio.sleep(0)

    assert task.done()
    assert task.exception() is not None  # 已被 _on_done 取回，不会泄漏告警
    assert any(
        "kaboom" in record.getMessage() for record in caplog.records
    ), [r.getMessage() for r in caplog.records]

    await tasks.aclose()


@pytest.mark.asyncio
async def test_task_reference_held_until_done():
    """任务在完成前必须被 TaskSet 强引用（gc.collect() 后仍存活）。"""
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow():
        started.set()
        await release.wait()

    tasks = TaskSet("test")
    task = tasks.spawn(_slow())
    await started.wait()

    gc.collect()
    await asyncio.sleep(0)

    assert not task.done(), "任务被 GC 回收了（缺少强引用）"
    assert len(tasks) == 1

    release.set()
    await asyncio.wait([task], timeout=2.0)
    await asyncio.sleep(0)
    # 完成后自动从集合中移除，避免长期持有
    assert len(tasks) == 0

    await tasks.aclose()


@pytest.mark.asyncio
async def test_aclose_cancels_pending_and_is_idempotent():
    """aclose() 取消在途任务，且重复调用不抛异常。"""

    async def _forever():
        await asyncio.sleep(3600)

    tasks = TaskSet("test")
    task = tasks.spawn(_forever())
    await asyncio.sleep(0)

    await tasks.aclose()
    assert task.cancelled() or task.done()

    await tasks.aclose()  # 幂等

    # 关闭后不允许再 spawn（协程对象需显式 close，避免 RuntimeWarning）
    coro = _forever()
    try:
        with pytest.raises(RuntimeError):
            tasks.spawn(coro)
    finally:
        coro.close()


# ---------------------------------------------------------------------------
# 长期守卫：不得新增裸 create_task
# ---------------------------------------------------------------------------

# 允许的「已持引用」形态之外，额外白名单：(文件名, 函数名)
# 目前为空：所有 create_task 调用点都已赋值持引用
_WHITELIST: set[tuple[str, str]] = set()


def _assigned_targets(node: ast.AST) -> bool:
    """调用结果是否被赋值/追加（即已持有引用）。"""
    parent = getattr(node, "_parent", None)
    return isinstance(parent, (ast.Assign, ast.AnnAssign, ast.AugAssign))


def test_no_untracked_create_task():
    """`asyncio.create_task(` 的结果必须被持有引用（赋值/append），否则失败。"""
    offenders: list[str] = []

    for path in sorted(SESSION_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # 记录每个节点的父节点，便于判断是否被赋值
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                child._parent = parent

        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in {"create_task", "ensure_future"}:
                    continue

                if (path.name, func.name) in _WHITELIST:
                    continue
                if _assigned_targets(node):
                    continue
                # 作为参数传入（如 asyncio.gather(...) 的实参）也算被持有
                parent = getattr(node, "_parent", None)
                if isinstance(parent, ast.Call):
                    continue
                offenders.append(f"{path.name}:{node.lineno} in {func.name}()")

    assert not offenders, "存在未被持有的后台任务（异常会静默丢失）:\n" + "\n".join(
        offenders
    )
