"""事件循环阻塞回归测试（Phase 2 Task 2.4，P1-1 / P1-2 / P1-3）

两个层次：

1. **运行时**：``stop_session`` / ``shutdown_all`` 等待子进程退出时不得冻结事件循环。
   判据用「数量级」而不是「贴近理论上限」——mock 进程 wait 1s，tick 间隔 20ms，
   理论上限 50 tick；同步阻塞时实测 0~2，异步时 ~50。取 10 / 30 作阈值，
   留足余量避免共享 CI 上 flaky。
2. **静态**：``broca/session_runner/`` 下所有 ``async def`` 内不得出现
   白名单外的同步阻塞调用（``time.sleep`` / ``process.wait`` / ``Thread.join`` /
   ``psutil.cpu_percent`` …）。这是一条长期守卫，防止后续重构重新引入阻塞。
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from broca.session_runner.manager import IPCSessionRunner
from broca.session_runner.models import RunnerProcessInfo, RunnerStatus
from broca.session_runner.monitor import HeartbeatMonitor
from broca.session_runner.process.registry import RunnerHandle

SESSION_ID = "session-no-blocking"

# 每个 mock 进程 wait() 阻塞的秒数
WAIT_SECONDS = 1.0
# tick 间隔
TICK_INTERVAL = 0.02


class _SlowProcess:
    """wait() 会真正阻塞（在 to_thread 的工作线程里）的假进程。"""

    def __init__(self, seconds: float = WAIT_SECONDS):
        self.seconds = seconds
        self.waited = 0

    def wait(self, timeout=None):
        self.waited += 1
        time.sleep(self.seconds)
        return 0

    def poll(self):
        return None  # 停止过程中始终「存活」，确保走 wait 分支


def _make_info(session_id: str, process) -> RunnerProcessInfo:
    now = datetime.now(timezone.utc)
    return RunnerProcessInfo(
        session_id=session_id,
        process=process,
        pid=4321,
        status=RunnerStatus.ALIVE,
        started_at=now - timedelta(seconds=60),
        last_heartbeat=now - timedelta(seconds=1),
    )


def _fresh_manager() -> IPCSessionRunner:
    IPCSessionRunner._instance = None
    mgr = IPCSessionRunner()
    mgr._registry.clear()

    # Task 3.1：收敛逻辑在 HeartbeatMonitor，DB/事件协作者改为 mock
    repo = MagicMock()
    repo.upsert = AsyncMock()
    repo.upsert_many = AsyncMock()
    repo.delete = AsyncMock()
    repo.mark_agents_disconnected = AsyncMock(return_value=0)
    mgr._repo = repo

    events = MagicMock()
    events.emit = AsyncMock()
    events.emit_soon = MagicMock()
    mgr._events = events

    mgr._monitor = HeartbeatMonitor(
        policy=mgr._monitor.policy,
        registry=mgr._registry,
        repo=repo,
        reaper=mgr._reaper,
        events=events,
    )
    return mgr


async def _count_ticks(stop: asyncio.Event) -> int:
    """每 TICK_INTERVAL 记一次 tick，直到 stop 被 set。"""
    ticks = 0
    while not stop.is_set():
        await asyncio.sleep(TICK_INTERVAL)
        ticks += 1
    return ticks


# ---------------------------------------------------------------------------
# 运行时：stop_session / shutdown_all 不阻塞事件循环
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_session_does_not_block_event_loop():
    """stop_session 等待 1s 退出的期间，事件循环必须仍在跑（tick ≥ 10）。"""
    mgr = _fresh_manager()
    process = _SlowProcess()
    mgr._registry.add(RunnerHandle(info=_make_info(SESSION_ID, process)))

    stop = asyncio.Event()
    ticker = asyncio.create_task(_count_ticks(stop))
    try:
        assert await mgr.stop_session(SESSION_ID, timeout=WAIT_SECONDS + 1) is True
    finally:
        stop.set()
        ticks = await ticker

    # 同步阻塞实现下这里会是 0~2
    assert ticks >= 10, f"事件循环被阻塞（ticks={ticks}）"
    assert process.waited == 1


@pytest.mark.asyncio
async def test_shutdown_all_does_not_block_event_loop():
    """shutdown_all 串行停止 3 个各阻塞 1s 的 runner，tick 必须 ≥ 30。"""
    mgr = _fresh_manager()
    for idx in range(3):
        sid = f"{SESSION_ID}-{idx}"
        mgr._registry.add(RunnerHandle(info=_make_info(sid, _SlowProcess())))

    stop = asyncio.Event()
    ticker = asyncio.create_task(_count_ticks(stop))
    try:
        stopped = await mgr.shutdown_all()
    finally:
        stop.set()
        ticks = await ticker

    assert stopped == 3
    assert ticks >= 30, f"shutdown_all 阻塞了事件循环（ticks={ticks}）"
    assert len(mgr._registry) == 0


# ---------------------------------------------------------------------------
# 静态守卫：async def 内无白名单外的同步阻塞调用
# ---------------------------------------------------------------------------

# 需要审查的调用名（只保留语义无歧义的；subprocess.run / str.join 太容易误报）
_BLOCKING_ATTRS = {
    "sleep",  # time.sleep / asyncio.sleep
    "wait",  # process.wait / Event.wait
    "cpu_percent",  # psutil 的 interval>0 会 sleep
}

# 显式非阻塞：Popen.poll() / 带 timeout=0 的 poll 立即返回
_NON_BLOCKING_ATTRS = {"poll"}

# await 之后允许的 (base, attr) 组合（白名单）
_AWAITED_ASYNC_MODULES = {"asyncio", "loop"}
_AWAITED_ASYNC_ATTRS = {"wait_for", "to_thread", "run_in_executor", "gather", "shield"}
_AWAITED_EVENT_ATTRS = {"wait"}
_AWAITED_EVENT_BASES = {"_shutdown_event", "event", "stop_event", "queue", "msg_queue"}


def _base_name(call: ast.Call) -> str:
    func = call.func
    if not isinstance(func, ast.Attribute):
        return ""
    value = func.value
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    return ""


def _is_allowed_awaited(call: ast.Call, attr: str) -> bool:
    base = _base_name(call)
    if base in _AWAITED_ASYNC_MODULES and attr in (
        {"sleep", "wait"} | _AWAITED_ASYNC_ATTRS
    ):
        return True
    if attr in _AWAITED_ASYNC_ATTRS and base in _AWAITED_ASYNC_MODULES:
        return True
    if attr in _AWAITED_EVENT_ATTRS and (
        base in _AWAITED_EVENT_BASES or base.endswith("_event")
    ):
        return True
    return False


def _scan_node(node: ast.AST, in_await: bool, findings: list[str], func: str) -> None:
    for child in ast.iter_child_nodes(node):
        # 不进入嵌套函数/类体（它们各自有自己的 async 语义）
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        child_in_await = in_await or isinstance(child, ast.Await)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            attr = child.func.attr
            blocking = attr in _BLOCKING_ATTRS or (
                attr == "join" and "thread" in _base_name(child).lower()
            )
            if blocking and attr not in _NON_BLOCKING_ATTRS:
                if not (in_await and _is_allowed_awaited(child, attr)):
                    findings.append(
                        f"{child.lineno}: async {func}() 内同步调用 {_base_name(child)}.{attr}()"
                    )
        _scan_node(child, child_in_await, findings, func)


def test_ast_no_blocking_calls_in_async():
    """`broca/session_runner/` 下所有 async def 内不得有白名单外的阻塞调用。"""
    root = pathlib.Path(__file__).resolve().parents[1] / "session_runner"
    findings: list[str] = []

    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        file_findings: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                _scan_node(node, False, file_findings, node.name)
        findings.extend(f"{path.name}:{item}" for item in file_findings)

    assert not findings, "async def 内发现同步阻塞调用:\n" + "\n".join(findings)
