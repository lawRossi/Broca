"""Integration test: verify SQLite connection pool sizing under concurrent load.

Validates:
- 5 concurrent coroutines × 10 save_message calls = 50 writes, no PoolTimeout
- Pool size peak ≤ 8 (pool_size=3 + max_overflow=5)
"""

import asyncio
import uuid

import pytest
import pytest_asyncio

from broca.session.database import db_manager
from broca.session.models import MessageRole, MessageType, Session
from broca.session.service import get_session_service, get_message_service
from datetime import datetime, timezone


@pytest_asyncio.fixture(scope="module")
async def services():
    return {
        "session": get_session_service(),
        "message": get_message_service(),
    }


@pytest.mark.asyncio
async def test_concurrent_writes_no_pool_timeout(services):
    """5 concurrent coroutines each doing 10 save_message, no PoolTimeout"""
    session_svc = services["session"]
    msg_svc = services["message"]

    # Create a test session
    session_id = f"pool_test_{uuid.uuid4().hex[:12]}"
    await session_svc.create(
        session_id=session_id,
        name="pool sizing test",
        created_at=datetime.now(timezone.utc),
    )

    async def worker(worker_id: int):
        """Each worker does 10 message writes."""
        for i in range(10):
            seq = await msg_svc.next_sequence_for_session(session_id)
            await msg_svc.create_message(
                message_id=f"msg_w{worker_id}_{i}_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                turn_id=None,
                agent_id=f"agent_{worker_id}",
                role=MessageRole.USER,
                message_type=MessageType.USER_MESSAGE,
                sequence_number=seq,
                data={"content": f"worker {worker_id} msg {i}"},
            )

    # Run 5 workers concurrently
    workers = [asyncio.create_task(worker(i)) for i in range(5)]
    results = await asyncio.gather(*workers, return_exceptions=True)

    # No PoolTimeout or other exceptions
    for r in results:
        assert not isinstance(r, Exception), f"Worker raised: {r!r}"

    # Verify all 50 messages were written
    total = await msg_svc.count(filters={"session_id": session_id})
    assert total == 50, f"Expected 50 messages, got {total}"


@pytest.mark.asyncio
async def test_pool_size_within_limit(services):
    """After concurrent writes, pool size should not exceed 8 (3+5)"""
    session_svc = services["session"]
    msg_svc = services["message"]

    session_id = f"pool_size_test_{uuid.uuid4().hex[:12]}"
    await session_svc.create(
        session_id=session_id,
        name="pool size test",
        created_at=datetime.now(timezone.utc),
    )

    # Do some concurrent writes to stress the pool
    async def worker(worker_id: int):
        for i in range(5):
            seq = await msg_svc.next_sequence_for_session(session_id)
            await msg_svc.create_message(
                message_id=f"msg_ps_{worker_id}_{i}_{uuid.uuid4().hex[:8]}",
                session_id=session_id,
                turn_id=None,
                agent_id=f"agent_{worker_id}",
                role=MessageRole.USER,
                message_type=MessageType.USER_MESSAGE,
                sequence_number=seq,
                data={"content": f"size test {worker_id}"},
            )

    workers = [asyncio.create_task(worker(i)) for i in range(5)]
    await asyncio.gather(*workers)

    # Check pool size
    pool = db_manager._engine.pool
    assert pool.size() <= 8, (
        f"Pool size {pool.size()} exceeds limit of 8"
    )


@pytest.mark.asyncio
async def test_single_session_no_pool_issues(services):
    """Normal single-session usage should not cause pool problems"""
    session_svc = services["session"]
    msg_svc = services["message"]

    session_id = f"single_pool_{uuid.uuid4().hex[:12]}"
    await session_svc.create(
        session_id=session_id,
        name="single session test",
        created_at=datetime.now(timezone.utc),
    )

    # Sequential writes (normal single-runner pattern)
    for i in range(20):
        seq = await msg_svc.next_sequence_for_session(session_id)
        await msg_svc.create_message(
            message_id=f"msg_single_{i}_{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            turn_id=None,
            agent_id="agent_test",
            role=MessageRole.USER,
            message_type=MessageType.USER_MESSAGE,
            sequence_number=seq,
            data={"content": f"sequential {i}"},
        )

    total = await msg_svc.count(filters={"session_id": session_id})
    assert total == 20
