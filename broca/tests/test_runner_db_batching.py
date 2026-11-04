"""DB 批量写入 + 心跳同步节流测试（Task 4.3 / P1-5）。

P1-5 的分工在计划里写得很明确：

- **Task 2.2** 负责「单事务批量」：``upsert_many`` 把 N 行合并成 1 次 commit；
- **本 Task** 负责「时间维度聚合」：``persist_interval`` 内的多次状态变化
  合并成一次写，且 10 个 session 的 Agent 状态同步只产生 1 次 commit。

历史问题（写放大的两个来源）：

1. 心跳每 5s 一次，每个 session 一次 ``SELECT + commit`` —— 10 个 session
   就是每秒 2 次 commit，写放大与 session 数线性相关；
2. 状态落库只在 ``start_session`` 时发生一次，DB 里的 status / last_heartbeat
   永远停在启动瞬间，``restore_active_sessions`` 读到脏数据。

本文件的用例都用**真实内存 SQLite**跑，commit 次数通过 SQLAlchemy 的
``commit`` 事件精确计数 —— 用 mock 数 ``commit()`` 调用无法发现
「一次 commit 前塞了 N 次 SELECT」这类真实的写放大。
"""

from __future__ import annotations

import json
import pathlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from broca.session_runner.models import RunnerProcessInfo, RunnerStatus
from broca.session_runner.monitor import HealthPolicy, HeartbeatMonitor
from broca.session_runner.process.registry import RunnerHandle, RunnerRegistry
from broca.session_runner.repository import RunnerRepository


class _InMemoryDB:
    """最小 db_manager 替身：提供 ``get_session()`` 并统计 commit 次数。"""

    def __init__(self) -> None:
        self.engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        self.commits = 0
        event.listen(self.engine.sync_engine, "commit", self._on_commit)

    def _on_commit(self, conn) -> None:  # noqa: ANN001 - SQLAlchemy 事件签名
        self.commits += 1

    @asynccontextmanager
    async def get_session(self):
        async with self.factory() as session:
            try:
                yield session
            except BaseException:
                await session.rollback()
                raise

    async def create_all(self) -> None:
        # 确保所有表都注册到 metadata（Agent / SessionRunner 有外键）
        import broca.session.models  # noqa: F401

        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()


@pytest_asyncio.fixture
async def db():
    database = _InMemoryDB()
    await database.create_all()
    try:
        yield database
    finally:
        await database.dispose()


def _info(session_id: str, *, status: RunnerStatus = RunnerStatus.ALIVE) -> RunnerProcessInfo:
    return RunnerProcessInfo(
        session_id=session_id,
        process=None,
        pid=1000,
        status=status,
        started_at=datetime.now(UTC),
        ipc_address=f"/tmp/{session_id}.sock",
        ipc_family="AF_UNIX",
        restart_count=0,
    )


async def _seed_agents(db, session_id: str, count: int = 2, status: str = "idle") -> None:
    from broca.session.models import Agent

    async with db.get_session() as session:
        session.add_all(
            [
                Agent(
                    agent_id=f"{session_id}-a{i}",
                    config_id="cfg-1",
                    session_id=session_id,
                    name=f"a{i}",
                    role="assistant",
                    agent_status=status,
                )
                for i in range(count)
            ]
        )
        await session.commit()


# ---------------------------------------------------------------------------
# 1. 跨 session 批量：N 个 session 只 commit 一次
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_n_sessions_produce_single_commit(db):
    """10 个 session 的 Agent 状态同步一轮 → 恰好 1 次 commit。"""
    sessions = [f"sess-batch-{i}" for i in range(10)]
    for sid in sessions:
        await _seed_agents(db, sid, count=2)

    repo = RunnerRepository(db=db)
    payload = {sid: {f"{sid}-a{i}": "running" for i in range(2)} for sid in sessions}

    db.commits = 0
    changed = await repo.set_agent_statuses(payload)

    assert changed == 20
    assert db.commits == 1, (
        f"10 个 session 的状态同步必须合并为 1 次 commit，实际 {db.commits} 次"
    )

    # 状态确实落库了
    from sqlmodel import select

    from broca.session.models import Agent

    async with db.get_session() as session:
        agents = (await session.exec(select(Agent))).all()
    assert {a.agent_status for a in agents} == {"running"}


@pytest.mark.asyncio
async def test_unchanged_statuses_produce_no_commit(db):
    """状态完全没变时不得产生任何 commit（否则节流形同虚设）。"""
    sid = "sess-noop"
    await _seed_agents(db, sid, count=2, status="running")

    repo = RunnerRepository(db=db)
    db.commits = 0
    changed = await repo.set_agent_statuses({sid: {f"{sid}-a{i}": "running" for i in range(2)}})

    assert changed == 0
    assert db.commits == 0


# ---------------------------------------------------------------------------
# 2. 时间维度聚合：persist_interval 内重复状态不再写库
# ---------------------------------------------------------------------------


def _build_monitor(registry: RunnerRegistry, repo: MagicMock, persist_interval: float) -> HeartbeatMonitor:
    return HeartbeatMonitor(
        policy=HealthPolicy(persist_interval=persist_interval),
        registry=registry,
        repo=repo,
        reaper=MagicMock(),
        events=MagicMock(),
    )


@pytest.mark.asyncio
async def test_status_change_within_interval_is_coalesced():
    """同一状态在 persist_interval 内重复上报 → 只写一次。"""
    registry = RunnerRegistry()
    info = _info("sess-coalesce")
    registry.add(RunnerHandle(info=info))

    repo = MagicMock(upsert_many=AsyncMock())
    monitor = _build_monitor(registry, repo, persist_interval=60.0)

    await monitor._persist_states()
    await monitor._persist_states()
    await monitor._persist_states()

    assert repo.upsert_many.await_count == 1, (
        "60s 内的重复状态必须合并为一次 upsert_many"
    )
    assert len(repo.upsert_many.await_args.args[0]) == 1


@pytest.mark.asyncio
async def test_real_status_change_bypasses_interval():
    """状态真的变了（哪怕在 interval 内）必须立刻落库。"""
    registry = RunnerRegistry()
    info = _info("sess-change")
    registry.add(RunnerHandle(info=info))

    repo = MagicMock(upsert_many=AsyncMock())
    monitor = _build_monitor(registry, repo, persist_interval=60.0)

    await monitor._persist_states()
    info.status = RunnerStatus.ERROR
    await monitor._persist_states()

    assert repo.upsert_many.await_count == 2


@pytest.mark.asyncio
async def test_interval_expiry_triggers_rewrite():
    """超过 persist_interval 后，即使状态没变也要刷新 last_heartbeat。"""
    registry = RunnerRegistry()
    info = _info("sess-expire")
    handle = RunnerHandle(info=info)
    registry.add(handle)

    repo = MagicMock(upsert_many=AsyncMock())
    monitor = _build_monitor(registry, repo, persist_interval=0.0)

    await monitor._persist_states()
    # interval=0 → 下一次必然超期
    await monitor._persist_states()

    assert repo.upsert_many.await_count == 2


# ---------------------------------------------------------------------------
# 3. manager 侧：10 个 session 的心跳只触发 1 次 flush
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manager_flushes_ten_sessions_in_one_call():
    """10 个 session 的心跳在同一窗口内到达 → 1 次 set_agent_statuses。"""
    from broca.session_runner.manager import IPCSessionRunner

    IPCSessionRunner._instance = None
    mgr = IPCSessionRunner()
    mgr._registry.clear()
    mgr._pending_agent_status.clear()

    repo = MagicMock()
    repo.set_agent_statuses = AsyncMock(return_value=10)
    mgr._repo = repo

    for i in range(10):
        sid = f"sess-flush-{i}"
        handle = RunnerHandle(info=_info(sid))
        mgr._registry.add(handle)
        mgr._schedule_agent_status_sync(handle, {"a1": "running"})

    if mgr._agent_flush_task is not None:
        import asyncio

        await asyncio.wait([mgr._agent_flush_task], timeout=3.0)

    assert repo.set_agent_statuses.await_count == 1
    payload = repo.set_agent_statuses.await_args.args[0]
    assert len(payload) == 10, "10 个 session 必须一次性提交"
    await mgr._tasks.aclose()
    mgr._registry.clear()


# ---------------------------------------------------------------------------
# 4. 配置项守卫
# ---------------------------------------------------------------------------

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CONFIGS_JSON = _ROOT / "configs" / "configs.json"

# 已知「只存在于 ExecutionConfig、未写入 configs.json」的字段：
# 它们都由 getattr(..., default) 兜底，且不属于 session_runner 改造范围。
# 新增 runner_* 配置项时**不允许**加入本白名单 —— 必须两处同步。
_KNOWN_UNCONFIGURED = {
    "max_concurrent_runners",
    "max_parallel_tools",
    "tool_execution_mode",
}


def _execution_json() -> dict:
    return json.loads(_CONFIGS_JSON.read_text(encoding="utf-8"))["execution"]


def test_persist_interval_from_config():
    """HealthPolicy.persist_interval 必须来自 configs.json（而非硬编码 60）。"""
    assert HealthPolicy.from_config().persist_interval == float(
        _execution_json()["runner_status_persist_interval"]
    )


def test_execution_config_matches_configs_json():
    """configs.json 的 execution 组与 ExecutionConfig 字段一一对应。

    这是 Task 4.3 的长期守卫：新增 ``runner_*`` 配置项时若只改一处，
    这里立刻变红（白名单里的三个历史字段除外）。
    """
    from broca.configs import ExecutionConfig

    configured = set(ExecutionConfig().__dict__) - _KNOWN_UNCONFIGURED
    in_json = set(_execution_json())

    assert configured - in_json == set(), "ExecutionConfig 有字段未写入 configs.json"
    assert in_json - configured == set(), "configs.json 有字段未被 ExecutionConfig 接收"


def test_runner_config_fields_are_all_in_json():
    """本计划新增的 runner_* 配置项必须全部显式写入 configs.json。"""
    from broca.configs import ExecutionConfig

    cfg = ExecutionConfig().__dict__
    runner_fields = {k for k in cfg if k.startswith("runner_")}
    assert runner_fields <= set(_execution_json())


def test_configs_json_has_no_stale_runner_fields():
    """configs.json 里不得残留 ExecutionConfig 已删除的 runner_* 字段。"""
    from broca.configs import ExecutionConfig

    cfg = ExecutionConfig().__dict__
    stale = {k for k in _execution_json() if k.startswith("runner_") and k not in cfg}
    assert stale == set(), f"configs.json 残留失效字段：{stale}"


# ---------------------------------------------------------------------------
# 5. 与 Task 2.2 的分工：upsert_many 仍是单事务
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_many_still_single_transaction(db):
    """回归守卫：Task 4.3 不得把 Task 2.2 的「单事务批量」改回逐条写。"""
    repo = RunnerRepository(db=db)
    infos = [_info(f"sess-up-{i}") for i in range(10)]

    db.commits = 0
    written = await repo.upsert_many(infos)

    assert written == 10
    assert db.commits == 1


@pytest.mark.asyncio
async def test_persist_states_uses_upsert_many_not_upsert():
    """回归守卫：``_persist_states`` 必须走批量接口，不能退回逐 runner upsert。"""
    registry = RunnerRegistry()
    for i in range(5):
        registry.add(RunnerHandle(info=_info(f"sess-many-{i}")))

    repo = MagicMock(upsert=AsyncMock(), upsert_many=AsyncMock())
    monitor = _build_monitor(registry, repo, persist_interval=60.0)

    await monitor._persist_states()

    assert repo.upsert.await_count == 0
    assert repo.upsert_many.await_count == 1
    assert len(repo.upsert_many.await_args.args[0]) == 5
