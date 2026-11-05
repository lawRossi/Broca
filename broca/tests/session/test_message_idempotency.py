"""
Regression tests: MessageService.create_message 幂等性。

验证重复 message_id 不会触发 UNIQUE constraint 异常，
而是返回已有的消息记录（ON CONFLICT 幂等兜底）。

根因：SocketIO 重连/retry 可能导致同一 message_id 的
用户消息被二次持久化。
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from broca.session.database import db_manager
from broca.session.models import Message, MessageRole, MessageType


@pytest_asyncio.fixture()
async def _clean_messages():
    """确保每个测试在干净的消息表上运行。"""
    async with db_manager.get_session() as session:
        from sqlalchemy import delete
        await session.execute(delete(Message))
        await session.commit()
    yield
    async with db_manager.get_session() as session:
        from sqlalchemy import delete
        await session.execute(delete(Message))
        await session.commit()


class TestCreateMessageIdempotency:
    """MessageService.create_message: 重复 message_id 返回已有记录。"""

    @pytest.mark.asyncio
    async def test_duplicate_message_id_returns_existing(self, _clean_messages):
        """第一次创建成功，第二次相同 message_id 不抛异常且返回已有记录。"""
        from broca.session.service import MessageService

        svc = MessageService()

        # 第一次创建
        msg1 = await svc.create_message(
            message_id="msg-test-dup-001",
            session_id="sess-test",
            turn_id="turn-1",
            agent_id="agent-1",
            role=MessageRole.USER,
            message_type=MessageType.USER_MESSAGE,
            sequence_number=1,
            data={"content": "hello"},
        )
        assert msg1 is not None
        assert msg1.message_id == "msg-test-dup-001"

        # 第二次：相同 message_id，不应抛异常
        msg2 = await svc.create_message(
            message_id="msg-test-dup-001",
            session_id="sess-test",
            turn_id="turn-1",
            agent_id="agent-1",
            role=MessageRole.USER,
            message_type=MessageType.USER_MESSAGE,
            sequence_number=1,
            data={"content": "hello again"},
        )
        # 应返回已有记录（幂等）
        assert msg2 is not None
        assert msg2.message_id == "msg-test-dup-001"

    @pytest.mark.asyncio
    async def test_different_message_ids_both_persisted(self, _clean_messages):
        """不同 message_id 应正常各自入库。"""
        from broca.session.service import MessageService

        svc = MessageService()

        await svc.create_message(
            message_id="msg-test-dup-A",
            session_id="sess-test",
            turn_id=None,
            agent_id=None,
            role=MessageRole.ASSISTANT,
            message_type=MessageType.AGENT_RESPONSE,
            sequence_number=1,
        )
        await svc.create_message(
            message_id="msg-test-dup-B",
            session_id="sess-test",
            turn_id=None,
            agent_id=None,
            role=MessageRole.USER,
            message_type=MessageType.USER_MESSAGE,
            sequence_number=2,
        )

        # 验证两条都入库了
        async with db_manager.get_session() as session:
            from sqlalchemy import select, func
            count = (
                await session.execute(
                    select(func.count()).select_from(Message).where(
                        Message.message_id.in_(["msg-test-dup-A", "msg-test-dup-B"])
                    )
                )
            ).scalar_one()
            assert count == 2

    @pytest.mark.asyncio
    async def test_non_unique_error_still_raises(self, _clean_messages):
        """非 message_id UNIQUE 约束的 IntegrityError 不应被吞掉。"""
        from unittest.mock import patch
        from sqlalchemy.exc import IntegrityError
        from broca.session.service import MessageService, BaseService

        svc = MessageService()

        # 模拟一个非 message_id 的 IntegrityError
        fake_err = IntegrityError(
            "INSERT INTO message ...",
            {},
            Exception("UNIQUE constraint failed: message.session_id"),
        )

        with patch.object(BaseService, "create", side_effect=fake_err):
            with pytest.raises(IntegrityError, match="session_id"):
                await svc.create_message(
                    message_id="msg-test-non-unique",
                    session_id="sess-bad",
                    turn_id=None,
                    agent_id=None,
                    role=MessageRole.USER,
                )
