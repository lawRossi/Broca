"""
TurnService 单元测试

测试新增的 3 个方法：
- get_turns_by_session
- get_turn_time_range
- count_turns_by_session

以及 BaseService.get_batch 增强的 IN 查询支持。
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio

from broca.session.models import MessageType
from broca.session.service import (
    get_message_service,
    get_session_service,
    get_turn_service,
)


@pytest_asyncio.fixture(scope="module")
async def services():
    """初始化所有服务实例"""
    return {
        "turn": get_turn_service(),
        "message": get_message_service(),
        "session": get_session_service(),
    }


@pytest_asyncio.fixture(scope="module")
async def test_session(services):
    """创建测试用的 Session"""
    svc = services["session"]
    session = await svc.create(
        session_id="test_concise_mode_session",
        title="Concise Mode Test Session",
    )
    yield session
    # 清理
    await svc.delete(session.session_id)


@pytest_asyncio.fixture(scope="module")
async def test_turns_and_messages(services, test_session):
    """创建测试用的 Turn 和 Message 数据"""
    turn_svc = services["turn"]
    msg_svc = services["message"]
    session_id = test_session.session_id

    now = datetime.utcnow()

    # 创建 3 个 turn
    turns = []
    for i in range(3):
        turn = await turn_svc.create(
            turn_id=f"test_turn_{i}",
            session_id=session_id,
            agent_id=f"agent_{i % 2}",
            turn_description=f"Test turn {i}",
            sequence_number=i + 1,
            created_at=now - timedelta(minutes=10 * (2 - i)),
        )
        turns.append(turn)

    # 为每个 turn 创建 TURN_START 和 TURN_END 消息
    # turn 0: 有 start + end（已完成）
    await msg_svc.create(
        message_id="msg_start_0",
        message_type=MessageType.TURN_START,
        turn_id="test_turn_0",
        session_id=session_id,
        timestamp=now - timedelta(minutes=20),
        role="system",
        data={"turn_id": "test_turn_0"},
    )
    await msg_svc.create(
        message_id="msg_end_0",
        message_type=MessageType.TURN_END,
        turn_id="test_turn_0",
        session_id=session_id,
        timestamp=now - timedelta(minutes=15),
        role="system",
        data={"turn_id": "test_turn_0"},
    )

    # turn 1: 只有 start（活跃中）
    await msg_svc.create(
        message_id="msg_start_1",
        message_type=MessageType.TURN_START,
        turn_id="test_turn_1",
        session_id=session_id,
        timestamp=now - timedelta(minutes=5),
        role="system",
        data={"turn_id": "test_turn_1"},
    )

    # turn 2: 有 start + end（已完成）
    await msg_svc.create(
        message_id="msg_start_2",
        message_type=MessageType.TURN_START,
        turn_id="test_turn_2",
        session_id=session_id,
        timestamp=now - timedelta(minutes=3),
        role="system",
        data={"turn_id": "test_turn_2"},
    )
    await msg_svc.create(
        message_id="msg_end_2",
        message_type=MessageType.TURN_END,
        turn_id="test_turn_2",
        session_id=session_id,
        timestamp=now - timedelta(minutes=1),
        role="system",
        data={"turn_id": "test_turn_2"},
    )

    yield turns

    # 清理消息
    for i in range(3):
        await msg_svc.delete(f"msg_start_{i}")
        await msg_svc.delete(f"msg_end_{i}")
    # 清理 turn
    for t in turns:
        await turn_svc.delete(t.turn_id)


class TestTurnService:
    """TurnService 新增方法测试"""

    @pytest.mark.asyncio
    async def test_count_turns_by_session(
        self, services, test_session, test_turns_and_messages
    ):
        """测试 count_turns_by_session 返回正确的 turn 总数"""
        turn_svc = services["turn"]
        session_id = test_session.session_id

        count = await turn_svc.count_turns_by_session(session_id)
        assert count == 3, f"Expected 3 turns, got {count}"

    @pytest.mark.asyncio
    async def test_count_turns_by_session_empty(self, services):
        """测试不存在的 session 返回 0"""
        turn_svc = services["turn"]
        count = await turn_svc.count_turns_by_session("nonexistent_session")
        assert count == 0, f"Expected 0, got {count}"

    @pytest.mark.asyncio
    async def test_get_turns_by_session_returns_all(
        self, services, test_session, test_turns_and_messages
    ):
        """测试 get_turns_by_session 返回该 session 的所有 turn"""
        turn_svc = services["turn"]
        session_id = test_session.session_id

        turns = await turn_svc.get_turns_by_session(session_id)
        assert len(turns) == 3, f"Expected 3 turns, got {len(turns)}"

    @pytest.mark.asyncio
    async def test_get_turns_by_session_ordering(
        self, services, test_session, test_turns_and_messages
    ):
        """测试 get_turns_by_session 默认按 sequence_number desc 排序"""
        turn_svc = services["turn"]
        session_id = test_session.session_id

        turns = await turn_svc.get_turns_by_session(
            session_id, order_by="sequence_number desc"
        )
        assert len(turns) == 3
        # 最新的在前：3, 2, 1
        assert turns[0].sequence_number == 3
        assert turns[1].sequence_number == 2
        assert turns[2].sequence_number == 1

    @pytest.mark.asyncio
    async def test_get_turns_by_session_pagination(
        self, services, test_session, test_turns_and_messages
    ):
        """测试 get_turns_by_session 支持 skip/limit 分页"""
        turn_svc = services["turn"]
        session_id = test_session.session_id

        # skip=0, limit=2 → 返回 2 条
        turns_page1 = await turn_svc.get_turns_by_session(session_id, skip=0, limit=2)
        assert len(turns_page1) == 2

        # skip=2, limit=2 → 返回 1 条
        turns_page2 = await turn_svc.get_turns_by_session(session_id, skip=2, limit=2)
        assert len(turns_page2) == 1

        # 两页不重复
        ids_page1 = {t.turn_id for t in turns_page1}
        ids_page2 = {t.turn_id for t in turns_page2}
        assert ids_page1.isdisjoint(ids_page2)

    @pytest.mark.asyncio
    async def test_get_turn_time_range_completed(
        self, services, test_turns_and_messages
    ):
        """测试已完成 turn 的起止时间正确返回"""
        turn_svc = services["turn"]

        start, end = await turn_svc.get_turn_time_range("test_turn_0")
        assert start is not None, "start_time should not be None for completed turn"
        assert end is not None, "end_time should not be None for completed turn"
        assert end > start, "end_time should be after start_time"
        # 持续时间应约为 5 分钟（300 秒）
        duration = (end - start).total_seconds()
        assert duration > 0, f"Duration should be positive, got {duration}"

    @pytest.mark.asyncio
    async def test_get_turn_time_range_active(self, services, test_turns_and_messages):
        """测试活跃 turn（无 TURN_END）返回 end=None"""
        turn_svc = services["turn"]

        start, end = await turn_svc.get_turn_time_range("test_turn_1")
        assert start is not None, "start_time should not be None for active turn"
        assert end is None, "end_time should be None for active turn (no TURN_END)"

    @pytest.mark.asyncio
    async def test_get_turn_time_range_nonexistent(self, services):
        """测试不存在的 turn 返回 (None, None)"""
        turn_svc = services["turn"]

        start, end = await turn_svc.get_turn_time_range("nonexistent_turn")
        assert start is None
        assert end is None


class TestGetBatchInQuery:
    """BaseService.get_batch IN 查询增强测试"""

    @pytest.mark.asyncio
    async def test_get_batch_in_query(
        self, services, test_session, test_turns_and_messages
    ):
        """测试 get_batch 支持 list 值进行 IN 查询"""
        msg_svc = services["message"]
        session_id = test_session.session_id

        # 查询 TURN_START 和 TURN_END 两种类型
        messages = await msg_svc.get_batch(
            filters={
                "session_id": session_id,
                "message_type": [MessageType.TURN_START, MessageType.TURN_END],
            },
            order_by="timestamp asc",
        )
        # 应该有 5 条：turn0(start+end), turn1(start), turn2(start+end)
        assert len(messages) == 5, f"Expected 5 messages, got {len(messages)}"

        # 验证返回的都是正确类型
        for m in messages:
            assert m.message_type in (
                MessageType.TURN_START,
                MessageType.TURN_END,
            ), f"Unexpected type: {m.message_type}"

    @pytest.mark.asyncio
    async def test_get_batch_in_query_empty_result(self, services):
        """测试 IN 查询无匹配时返回空列表"""
        msg_svc = services["message"]

        messages = await msg_svc.get_batch(
            filters={
                "session_id": "nonexistent_session",
                "message_type": [MessageType.TURN_START, MessageType.TURN_END],
            },
        )
        assert len(messages) == 0

    @pytest.mark.asyncio
    async def test_get_batch_equality_still_works(
        self, services, test_session, test_turns_and_messages
    ):
        """测试 get_batch 等值查询不受 IN 增强影响"""
        msg_svc = services["message"]

        # 只用 等值查询（不是 list）
        messages = await msg_svc.get_batch(
            filters={
                "turn_id": "test_turn_0",
                "message_type": MessageType.TURN_START,
            },
        )
        assert len(messages) == 1
        assert messages[0].message_id == "msg_start_0"
