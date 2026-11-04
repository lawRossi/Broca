"""RunnerRepository 回归测试（P1-5 的「单事务批量」部分）

用**内存 SQLite** 真跑 SQL，验证：
1. upsert 用 SQLite 原生 ``ON CONFLICT`` 实现，同 session 两次 upsert 只有一行且字段被更新；
2. ``upsert_many`` 在 N 条记录下只产生 **1 次 commit**（旧实现是逐 runner
   SELECT+UPDATE，N 个 runner = 2N 次往返）；
3. ``mark_agents_disconnected`` 返回受影响行数；
4. ``get`` 对不存在的 session 返回 None。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session as SQLSession
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from broca.session_runner.models import RunnerProcessInfo, RunnerStatus
from broca.session_runner.repository import RunnerRepository, runner_row_id


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
        # 确保所有表都注册到 metadata（SessionRunner / Agent 有外键）
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


def _info(session_id: str, *, status: RunnerStatus = RunnerStatus.ALIVE, pid: int = 100):
    return RunnerProcessInfo(
        session_id=session_id,
        process=None,
        pid=pid,
        status=status,
        started_at=datetime.now(UTC),
        ipc_address=f"/tmp/{session_id}.sock",
        ipc_family="AF_UNIX",
        restart_count=0,
    )


@pytest.mark.asyncio
async def test_upsert_insert_then_update(db):
    """同 session 连续 upsert 两次：只有一行，且字段被更新。"""
    repo = RunnerRepository(db=db)
    sid = "sess-upsert"

    await repo.upsert(_info(sid, status=RunnerStatus.STARTING, pid=100))
    await repo.upsert(_info(sid, status=RunnerStatus.ALIVE, pid=200))

    from sqlmodel import select

    from broca.session.models import SessionRunner

    async with db.get_session() as session:
        rows = (await session.exec(select(SessionRunner))).all()

    assert len(rows) == 1, "upsert 必须复用同一行"
    assert rows[0].status == RunnerStatus.ALIVE.value
    assert rows[0].pid == 200
    assert rows[0].runner_id == runner_row_id(sid)


@pytest.mark.asyncio
async def test_upsert_many_single_transaction(db):
    """N 条记录只触发 1 次 commit。"""
    repo = RunnerRepository(db=db)
    infos = [_info(f"sess-batch-{i}") for i in range(5)]

    db.commits = 0
    written = await repo.upsert_many(infos)

    assert written == 5
    assert db.commits == 1, f"期望 1 次 commit，实际 {db.commits} 次"


@pytest.mark.asyncio
async def test_mark_agents_disconnected_clears_cache_hook(db):
    """mark_agents_disconnected 返回受影响行数（用于日志与缓存失效判断）。"""
    from broca.session.models import Agent

    sid = "sess-agents"
    async with db.get_session() as session:
        session.add_all(
            [
                Agent(
                    agent_id="a1",
                    config_id="cfg-1",
                    session_id=sid,
                    name="a1",
                    role="assistant",
                    agent_status="running",
                ),
                Agent(
                    agent_id="a2",
                    config_id="cfg-1",
                    session_id=sid,
                    name="a2",
                    role="assistant",
                    agent_status="idle",
                ),
            ]
        )
        await session.commit()

    repo = RunnerRepository(db=db)
    count = await repo.mark_agents_disconnected(sid)
    assert count == 2

    # 第二次已全部 disconnected → 0 行受影响
    assert await repo.mark_agents_disconnected(sid) == 0


@pytest.mark.asyncio
async def test_get_returns_none_for_missing(db):
    """不存在的 session 返回 None。"""
    repo = RunnerRepository(db=db)
    assert await repo.get("no-such-session") is None
    assert await repo.delete("no-such-session") is False
    assert await repo.list_active() == []


@pytest.mark.asyncio
async def test_list_active_excludes_dead(db):
    """list_active 只返回非 dead 记录（供启动时回收残留 runner）。"""
    repo = RunnerRepository(db=db)
    await repo.upsert_many(
        [
            _info("sess-alive", status=RunnerStatus.ALIVE),
            _info("sess-dead", status=RunnerStatus.DEAD),
            _info("sess-error", status=RunnerStatus.ERROR),
        ]
    )

    active = await repo.list_active()
    assert {i.session_id for i in active} == {"sess-alive", "sess-error"}


@pytest.mark.asyncio
async def test_set_agent_status_returns_changed_count(db):
    """set_agent_status 只更新发生变化的行，并返回变化行数。"""
    from broca.session.models import Agent

    sid = "sess-sync"
    async with db.get_session() as session:
        session.add(
            Agent(
                agent_id="a1",
                config_id="cfg-1",
                session_id=sid,
                name="a1",
                role="assistant",
                agent_status="idle",
            )
        )
        await session.commit()

    repo = RunnerRepository(db=db)
    assert await repo.set_agent_status(sid, {"a1": "running"}) == 1
    # 状态未变化 → 0
    assert await repo.set_agent_status(sid, {"a1": "running"}) == 0


@pytest.mark.asyncio
async def test_runner_row_id_is_collision_resistant():
    """前 16 字符相同的两个 session_id 不能撞主键（旧实现 session_id[:16] 会）。"""
    a = "abcdefghijklmnop" + "A" * 20
    b = "abcdefghijklmnop" + "B" * 20
    assert runner_row_id(a) != runner_row_id(b)
