"""Tests for MessageSeqCounter-based sequence number optimization.

Verifies:
- next_sequence_for_session returns sequential values (1, 2, 3, ...)
- Concurrent calls produce no duplicates
- Existing data initializes counters from MAX(sequence_number)
- No SELECT MAX(sequence_number) query is issued
"""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from broca.session.models import Message, MessageRole, MessageType, MessageSeqCounter, Session
from broca.session.service import get_message_service, get_turn_service, get_session_service
from sqlalchemy import select, text


@pytest_asyncio.fixture(scope="module")
async def services():
    """Initialize all service singletons."""
    return {
        "message": get_message_service(),
        "turn": get_turn_service(),
        "session": get_session_service(),
    }


def _unique_session_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class TestMessageSequenceCounter:
    """Test next_sequence_for_session for messages."""

    @pytest.mark.asyncio
    async def test_sequential_increments(self, services):
        """同一 session 连续 10 次调用返回 1-10"""
        msg_svc = services["message"]
        session_id = _unique_session_id("test_seq")

        results = []
        for _ in range(10):
            seq = await msg_svc.next_sequence_for_session(session_id)
            results.append(seq)

        assert results == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], (
            f"Expected [1..10], got {results}"
        )

    @pytest.mark.asyncio
    async def test_concurrent_no_duplicates(self, services):
        """并发 5 个协程调用无重复值"""
        msg_svc = services["message"]
        session_id = _unique_session_id("test_conc")

        async def get_seq():
            return await msg_svc.next_sequence_for_session(session_id)

        results = await asyncio.gather(*[get_seq() for _ in range(5)])

        # All values must be unique
        assert len(set(results)) == 5, f"Duplicate values found: {results}"
        # All values must be in range 1-5
        assert sorted(results) == [1, 2, 3, 4, 5], (
            f"Expected [1,2,3,4,5], got {sorted(results)}"
        )

    @pytest.mark.asyncio
    async def test_different_sessions_independent(self, services):
        """不同 session 的序列号互相独立"""
        msg_svc = services["message"]
        session_a = _unique_session_id("test_a")
        session_b = _unique_session_id("test_b")

        seq_a1 = await msg_svc.next_sequence_for_session(session_a)
        seq_b1 = await msg_svc.next_sequence_for_session(session_b)
        seq_a2 = await msg_svc.next_sequence_for_session(session_a)

        assert seq_a1 == 1
        assert seq_b1 == 1
        assert seq_a2 == 2


class TestTurnSequenceCounter:
    """Test next_turn_sequence_for_session for turns."""

    @pytest.mark.asyncio
    async def test_sequential_increments(self, services):
        """同一 session 连续 10 次调用返回 1-10"""
        turn_svc = services["turn"]
        session_id = _unique_session_id("test_tseq")

        results = []
        for _ in range(10):
            seq = await turn_svc.next_turn_sequence_for_session(session_id)
            results.append(seq)

        assert results == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], (
            f"Expected [1..10], got {results}"
        )

    @pytest.mark.asyncio
    async def test_counter_key_uses_turn_prefix(self, services):
        """Turn 序列号使用 turn_ 前缀作为 counter_key"""
        turn_svc = services["turn"]
        session_id = _unique_session_id("test_prefix")

        await turn_svc.next_turn_sequence_for_session(session_id)

        # Verify the counter_key in the table
        from broca.session.database import db_manager
        async with db_manager.get_session() as session:
            result = await session.execute(
                select(MessageSeqCounter).where(
                    MessageSeqCounter.counter_key == f"turn_{session_id}"
                )
            )
            row = result.scalar_one()
            assert row.last_seq == 1

    @pytest.mark.asyncio
    async def test_turn_and_message_counters_independent(self, services):
        """Turn 和 message 的计数器互相独立"""
        msg_svc = services["message"]
        turn_svc = services["turn"]
        session_id = _unique_session_id("test_indep")

        # Get one turn seq and one message seq
        turn_seq = await turn_svc.next_turn_sequence_for_session(session_id)
        msg_seq = await msg_svc.next_sequence_for_session(session_id)

        assert turn_seq == 1
        assert msg_seq == 1

        # Second calls should both be 2
        turn_seq2 = await turn_svc.next_turn_sequence_for_session(session_id)
        msg_seq2 = await msg_svc.next_sequence_for_session(session_id)

        assert turn_seq2 == 2
        assert msg_seq2 == 2


class TestExistingDataInitialization:
    """Test that existing data initializes counters correctly."""

    @pytest.mark.asyncio
    async def test_existing_data_continues_from_max(self, services):
        """已有数据的 session 初始化后从 MAX+1 继续递增"""
        from broca.session.database import db_manager

        msg_svc = services["message"]
        session_svc = services["session"]
        session_id = _unique_session_id("test_exist")

        # Create session
        await session_svc.create(
            session_id=session_id,
            name="test existing data",
            created_at=datetime.now(timezone.utc),
        )

        # Insert messages with sequence_number 1, 2, 3
        for seq in [1, 2, 3]:
            async with db_manager.get_session() as session:
                msg = Message(
                    message_id=f"msg_{seq}_{uuid.uuid4().hex[:8]}",
                    session_id=session_id,
                    role=MessageRole.USER,
                    message_type=MessageType.USER_MESSAGE,
                    sequence_number=seq,
                    data={"content": f"msg {seq}"},
                    timestamp=datetime.now(timezone.utc),
                )
                session.add(msg)
                await session.commit()

        # Simulate migration: initialize counter with MAX(sequence_number)
        async with db_manager.get_session() as session:
            await session.execute(
                text(
                    "INSERT INTO message_seq_counter (counter_key, last_seq) "
                    "VALUES (:key, :seq) "
                    "ON CONFLICT(counter_key) DO UPDATE SET last_seq = excluded.last_seq"
                ),
                {"key": session_id, "seq": 3},
            )
            await session.commit()

        # Next sequence should be 4
        next_seq = await msg_svc.next_sequence_for_session(session_id)
        assert next_seq == 4, f"Expected 4, got {next_seq}"


class TestNoSelectMaxQuery:
    """Verify that no SELECT MAX(sequence_number) query is issued."""

    @pytest.mark.asyncio
    async def test_next_sequence_no_max_query(self, services):
        """next_sequence_for_session 不执行 SELECT MAX 查询"""
        from broca.session.database import db_manager
        from sqlalchemy import event

        msg_svc = services["message"]
        session_id = _unique_session_id("test_nomax")

        # Capture SQL queries
        queries: list[str] = []

        def capture_query(conn, cursor, statement, parameters, context, executemany):
            queries.append(statement)

        engine = db_manager._engine
        event.listen(engine.sync_engine, "before_cursor_execute", capture_query)

        try:
            await msg_svc.next_sequence_for_session(session_id)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", capture_query)

        # No query should contain SELECT MAX on sequence_number
        for q in queries:
            upper_q = q.upper().replace(" ", "")
            assert "MAX(SEQUENCE_NUMBER)" not in upper_q, (
                f"Found SELECT MAX query: {q}"
            )
