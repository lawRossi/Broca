"""
Service类实现模块

为Session、Turn、Message、Agent、AgentConfig等数据模型提供Service类
实现CRUD操作和业务逻辑。
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Generic, List, Optional, Tuple, Type, TypeVar

from sqlalchemy import String, cast, desc, func, or_, select, text
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, and_

from broca.logging_config import get_logger
from broca.session.database import db_manager
from broca.snapshot.patch import PatchCalculator
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from broca.session.models import (
    Agent,
    AgentConfig,
    JobExecution,
    JobStatus,
    JobType,
    Message,
    MessageRole,
    MessageType,
    MessageSeqCounter,
    ScheduledJob,
    Session,
    Task,
    TaskComment,
    TaskPriority,
    TaskStatus,
    Turn,
)

logger = get_logger(__name__)

# 泛型类型变量
T = TypeVar("T", bound=SQLModel)


class BaseService(Generic[T]):
    """Service基类，提供通用的CRUD操作"""

    def __init__(self, model_class: Type[T]):
        self.model_class = model_class
        # 根据模型类名确定ID字段名
        self.id_field = self._get_id_field_name()

    def _get_id_field_name(self) -> str:
        """根据模型类名获取ID字段名"""
        class_name = self.model_class.__name__.lower()
        if class_name == "session":
            return "session_id"
        elif class_name == "turn":
            return "turn_id"
        elif class_name == "message":
            return "message_id"
        elif class_name == "agent":
            return "agent_id"
        elif class_name == "agentconfig":
            return "config_id"
        elif class_name == "scheduledjob":
            return "job_id"
        elif class_name == "jobexecution":
            return "execution_id"
        else:
            # 默认规则：类名 + "_id"
            return f"{class_name}_id"

    async def create(self, **kwargs) -> T:
        """创建新记录"""
        async with db_manager.get_session() as session:
            instance = self.model_class(**kwargs)
            session.add(instance)
            await session.commit()
            await session.refresh(instance)
            return instance

    async def get(self, id: str) -> Optional[T]:
        """根据ID获取记录"""
        async with db_manager.get_session() as session:
            statement = select(self.model_class).where(
                getattr(self.model_class, self.id_field) == id
            )
            result = await session.exec(statement)
            return result.scalars().first()

    async def get_batch(
        self,
        filters: Optional[Dict[str, Any]] = None,
        order_by: Optional[str] = None,
        skip=None,
        limit=None,
    ) -> List[T]:
        """获取批量记录"""

        async with db_manager.get_session() as session:
            statement = select(self.model_class)

            if filters:
                conditions = []
                for key, value in filters.items():
                    if hasattr(self.model_class, key):
                        if isinstance(value, list):
                            # list 值使用 IN 查询
                            conditions.append(getattr(self.model_class, key).in_(value))
                        else:
                            conditions.append(getattr(self.model_class, key) == value)
                if conditions:
                    statement = statement.where(and_(*conditions))
            if order_by:
                parts = order_by.strip().split()
                if len(parts) >= 1:
                    column_name = parts[0]
                    if hasattr(self.model_class, column_name):
                        column = getattr(self.model_class, column_name)
                        if len(parts) >= 2 and parts[1].lower() == "desc":
                            statement = statement.order_by(desc(column))
                        else:
                            statement = statement.order_by(column)

            if skip is not None and limit is not None:
                statement = statement.offset(skip).limit(limit)

            result = await session.exec(statement)
            # 使用scalars()获取模型实例列表
            return result.scalars().all()

    async def update(self, id: str, **kwargs) -> Optional[T]:
        """更新记录"""
        async with db_manager.get_session() as session:
            # 直接查询而不是调用self.get，避免额外的会话
            statement = select(self.model_class).where(
                getattr(self.model_class, self.id_field) == id
            )
            result = await session.exec(statement)
            instance = result.scalars().first()

            if not instance:
                return None

            for key, value in kwargs.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)

            session.add(instance)
            await session.commit()
            await session.refresh(instance)
            return instance

    async def update_batch(self, ids: List[str], **kwargs) -> int:
        """批量更新记录，返回更新数量"""
        if not ids:
            return 0

        async with db_manager.get_session() as session:
            statement = (
                sql_update(self.model_class)
                .where(getattr(self.model_class, self.id_field).in_(ids))
                .values(**kwargs)
            )

            result = await session.exec(statement)
            count = result.rowcount
            await session.commit()
            return count

    async def delete(self, id: str) -> bool:
        """删除记录"""
        async with db_manager.get_session() as session:
            statement = select(self.model_class).where(
                getattr(self.model_class, self.id_field) == id
            )
            result = await session.exec(statement)
            instance = result.scalars().first()

            if not instance:
                return False

            await session.delete(instance)
            await session.commit()
            return True

    async def delete_batch(self, ids: List[str]) -> int:
        """批量删除记录，返回删除数量"""
        if not ids:
            return 0

        async with db_manager.get_session() as session:
            statement = select(self.model_class).where(
                getattr(self.model_class, self.id_field).in_(ids)
            )
            result = await session.exec(statement)
            instances = result.scalars().all()

            count = 0
            for instance in instances:
                await session.delete(instance)
                count += 1

            await session.commit()
            return count

    async def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """统计记录数量"""
        async with db_manager.get_session() as session:
            statement = select(func.count(self.id_field))

            if filters:
                conditions = []
                for key, value in filters.items():
                    if hasattr(self.model_class, key):
                        if isinstance(value, list):
                            # list 值使用 IN 查询
                            conditions.append(getattr(self.model_class, key).in_(value))
                        else:
                            conditions.append(getattr(self.model_class, key) == value)
                if conditions:
                    statement = statement.where(and_(*conditions))

            result = await session.exec(statement)
            return result.scalar()


class SessionService(BaseService[Session]):
    """Session Service类"""

    def __init__(self):
        super().__init__(Session)

    async def create_session(
        self,
        session_id: str,
        description: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> Session:
        """创建新会话"""
        return await self.create(
            session_id=session_id,
            description=description,
            workspace=workspace,
            created_at=datetime.now(timezone.utc),
        )

    async def close_session(self, session_id: str) -> Optional[Session]:
        """关闭会话"""
        return await self.update(
            session_id,
            finished_at=datetime.now(timezone.utc),
        )


class TurnService(BaseService[Turn]):
    """Turn Service类"""

    def __init__(self):
        super().__init__(Turn)

    async def create_turn(
        self,
        turn_id: str,
        session_id: str,
        agent_id: str,
        sequence_number: int,
        turn_description: Optional[str] = None,
        execution_id: Optional[str] = None,
    ) -> Turn:
        """创建新轮次"""
        return await self.create(
            turn_id=turn_id,
            session_id=session_id,
            agent_id=agent_id,
            sequence_number=sequence_number,
            turn_description=turn_description,
            execution_id=execution_id,
            created_at=datetime.now(timezone.utc),
        )

    async def get_latest_turn(self, session_id: str) -> Optional[Turn]:
        """获取会话的最新轮次"""
        async with db_manager.get_session() as session:
            statement = (
                select(Turn)
                .where(Turn.session_id == session_id)
                .order_by(Turn.sequence_number.desc())
                .limit(1)
            )
            result = await session.exec(statement)
            return result.scalars().first()

    async def get_next_sequence_number(self, session_id: str) -> int:
        """[DEPRECATED] 获取下一个轮次序列号

        .. deprecated::
            使用 :meth:`next_turn_sequence_for_session` 代替。
        """
        import warnings
        warnings.warn(
            "TurnService.get_next_sequence_number is deprecated. "
            "Use next_turn_sequence_for_session instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.next_turn_sequence_for_session(session_id)

    async def next_turn_sequence_for_session(self, session_id: str) -> int:
        """原子递增并返回该 session 的下一个 turn 序列号"""
        async with db_manager.get_session() as session:
            stmt = (
                sqlite_insert(MessageSeqCounter)
                .values(counter_key=f"turn_{session_id}", last_seq=1)
                .on_conflict_do_update(
                    index_elements=["counter_key"],
                    set_={"last_seq": MessageSeqCounter.last_seq + 1},
                )
                .returning(MessageSeqCounter.last_seq)
            )
            result = await session.execute(stmt)
            value = result.scalar_one()
            await session.commit()
            return value

    async def next_turn_seq_in_session(
        self, db_session: "AsyncSession", session_id: str
    ) -> int:
        """在外部事务中递增 turn 序列号。不 commit。

        ⚠️ 调用者必须确保 db_session 处于活跃事务中（通过 get_multi_session 获取）。
        """
        assert db_session.in_transaction(), (
            "next_turn_seq_in_session requires an active transaction (use get_multi_session)"
        )
        stmt = (
            sqlite_insert(MessageSeqCounter)
            .values(counter_key=f"turn_{session_id}", last_seq=1)
            .on_conflict_do_update(
                index_elements=["counter_key"],
                set_={"last_seq": MessageSeqCounter.last_seq + 1},
            )
            .returning(MessageSeqCounter.last_seq)
        )
        result = await db_session.execute(stmt)
        return result.scalar_one()

    async def create_turn_in_session(
        self, db_session: "AsyncSession", **kwargs
    ) -> Turn:
        """在外部事务中创建 turn。

        ⚠️ 此方法不做 commit/rollback——事务生命周期由外层 get_multi_session() 管理。
        """
        assert db_session.in_transaction(), (
            "create_turn_in_session requires an active transaction (use get_multi_session)"
        )
        instance = Turn(**kwargs)
        db_session.add(instance)
        await db_session.flush()
        return instance

    async def get_turns_by_session(
        self,
        session_id: str,
        order_by: str = "sequence_number desc",
        skip: int = 0,
        limit: int = 20,
        execution_id: Optional[str] = None,
    ) -> List[Turn]:
        """获取会话的 turn 列表，支持按 execution_id 过滤"""
        filters = {"session_id": session_id, "reverted": False}
        if execution_id:
            filters["execution_id"] = execution_id
        return await self.get_batch(
            filters=filters,
            order_by=order_by,
            skip=skip,
            limit=limit,
        )

    async def get_turn_time_range(
        self, turn_id: str
    ) -> Tuple[Optional[datetime], Optional[datetime]]:
        """获取指定 turn 的 TURN_START 和 TURN_END 时间戳"""
        from broca.session.service import get_message_service

        msg_service = get_message_service()
        messages = await msg_service.get_batch(
            filters={
                "turn_id": turn_id,
                "message_type": [MessageType.TURN_START, MessageType.TURN_END],
            },
            order_by="timestamp asc",
        )
        start_time = None
        end_time = None
        for m in messages:
            if m.message_type == MessageType.TURN_START:
                start_time = m.timestamp
            elif m.message_type == MessageType.TURN_END:
                end_time = m.timestamp
        return start_time, end_time

    async def get_turn_stats(self, turn_id: str) -> Dict[str, Any]:
        """获取指定 turn 的统计信息（SQL 聚合优化版）

        使用 SQL 聚合查询获取可统计部分（total_steps, tool_call_stats, is_reverted），
        仅对需要解析 JSON data 字段的消息类型做最小化加载。

        返回：
            is_reverted: 该 turn 的所有消息是否都已撤销
            user_message: 用户问题原文或 None
            total_steps: step_start 消息数量
            tool_call_stats: [{tool_name, count}, ...]
            current_file_path: 最后一个 read_file/edit_file/write_file 的 path
            current_todo_list: [{name, status}, ...] 或空列表
            final_response: 拼接后的 agent_response 内容
        """
        from broca.session.database import db_manager
        from broca.session.models import Message as MsgModel

        stats: Dict[str, Any] = {
            "is_reverted": True,
            "user_message": None,
            "total_steps": 0,
            "tool_call_stats": [],
            "current_file_path": None,
            "current_todo_list": [],
            "final_response": "",
            "last_message_id": None,
            "changed_files": {},
        }

        async with db_manager.get_session() as session:
            # 1. SQL 聚合：total_steps
            total_steps = (
                await session.execute(
                    select(func.count(MsgModel.message_id))
                    .where(MsgModel.turn_id == turn_id)
                    .where(MsgModel.message_type == MessageType.STEP_START)
                    .where(MsgModel.reverted == False)  # noqa: E712
                )
            ).scalar() or 0
            stats["total_steps"] = total_steps

            # 2. SQL 聚合：tool_call_stats (GROUP BY tool_name via json_extract)
            tool_rows = (
                await session.execute(
                    select(
                        func.json_extract(MsgModel.data, "$.tool_name"),
                        func.count(MsgModel.message_id),
                    )
                    .where(MsgModel.turn_id == turn_id)
                    .where(MsgModel.message_type == MessageType.TOOL_CALL)
                    .where(MsgModel.reverted == False)  # noqa: E712
                    .group_by(func.json_extract(MsgModel.data, "$.tool_name"))
                )
            ).all()
            stats["tool_call_stats"] = [
                {"tool_name": row[0], "count": row[1]}
                for row in sorted(tool_rows, key=lambda x: -x[1])
                if row[0]
            ]

            # 3. SQL：is_reverted 和 last_message_id
            active_count = (
                await session.execute(
                    select(func.count(MsgModel.message_id))
                    .where(MsgModel.turn_id == turn_id)
                    .where(MsgModel.reverted == False)  # noqa: E712
                )
            ).scalar() or 0
            stats["is_reverted"] = active_count == 0

            last_msg_id = (
                await session.execute(
                    select(MsgModel.message_id)
                    .where(MsgModel.turn_id == turn_id)
                    .where(MsgModel.reverted == False)  # noqa: E712
                    .order_by(MsgModel.sequence_number.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            stats["last_message_id"] = last_msg_id

            # 4. 仅加载需要解析 JSON data 的消息（最小化 Python 处理）
            content_types = [
                MessageType.USER_MESSAGE,
                MessageType.AGENT_RESPONSE,
                MessageType.TURN_END,
                MessageType.TOOL_CALL,
            ]
            content_messages = list(
                (
                    await session.execute(
                        select(MsgModel)
                        .where(MsgModel.turn_id == turn_id)
                        .where(MsgModel.reverted == False)  # noqa: E712
                        .where(MsgModel.message_type.in_(content_types))
                        .order_by(MsgModel.sequence_number)
                    )
                )
                .scalars()
                .all()
            )

        # 5. Python 解析（仅对需要的消息）
        for m in content_messages:
            if m.message_type == MessageType.USER_MESSAGE:
                if stats["user_message"] is None:
                    raw_input = m.data.get("raw_input") if m.data else None
                    if raw_input is not None:
                        stats["user_message"] = str(raw_input)
                    else:
                        raw = m.data.get("content") if m.data else None
                        if raw:
                            try:
                                parsed = json.loads(raw) if isinstance(raw, str) else raw
                                if isinstance(parsed, dict):
                                    stats["user_message"] = parsed.get("content", str(parsed))
                                else:
                                    stats["user_message"] = str(parsed)
                            except (json.JSONDecodeError, TypeError):
                                stats["user_message"] = str(raw)

            elif m.message_type == MessageType.TOOL_CALL:
                tool_name = m.data.get("tool_name") if m.data else None
                if tool_name in ("read_file", "edit_file", "write_file"):
                    args = m.data.get("arguments")
                    if args:
                        try:
                            parsed = json.loads(args) if isinstance(args, str) else args
                            if isinstance(parsed, dict) and parsed.get("path"):
                                stats["current_file_path"] = parsed["path"]
                        except (json.JSONDecodeError, TypeError):
                            pass
                if tool_name == "todo_management":
                    if not (m.data and m.data.get("status") == "error"):
                        args = m.data.get("arguments") if m.data else None
                        if args:
                            try:
                                parsed = json.loads(args) if isinstance(args, str) else args
                                if isinstance(parsed, dict) and parsed.get("todos"):
                                    stats["current_todo_list"] = parsed["todos"]
                            except (json.JSONDecodeError, TypeError):
                                pass

            elif m.message_type == MessageType.TURN_END:
                if m.data and "changed_files" in m.data:
                    stats["changed_files"] = m.data["changed_files"]

            elif m.message_type == MessageType.AGENT_RESPONSE:
                content = m.data.get("content") if m.data else None
                if content:
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, dict) and parsed.get("content"):
                            is_new_message = stats.get("_last_agent_msg_id") and stats["_last_agent_msg_id"] != m.message_id
                            if is_new_message:
                                stats["final_response"] = parsed["content"]
                            else:
                                stats["final_response"] += parsed["content"]
                            stats["_last_agent_msg_id"] = m.message_id
                    except (json.JSONDecodeError, TypeError):
                        is_new_message = stats.get("_last_agent_msg_id") and stats["_last_agent_msg_id"] != m.message_id
                        if is_new_message:
                            stats["final_response"] = str(content)
                        else:
                            stats["final_response"] += str(content)
                        stats["_last_agent_msg_id"] = m.message_id

        return stats

    async def get_file_diff(self, session_id: str, turn_id: str, file_path: str) -> Optional[str]:
        """获取 turn 中指定文件的 unified diff

        从 turn_end 消息中提取最早/最晚快照哈希，通过 PatchCalculator 实时计算 diff。

        Args:
            session_id: 会话 ID（用于获取 workspace 路径）
            turn_id: Turn ID
            file_path: 文件路径

        Returns:
            unified diff 文本，或 None（快照不可用或没有变更）
        """
        # 查 Session 拿 workspace 路径
        session_service = SessionService()
        sess = await session_service.get(session_id)
        if not sess or not sess.workspace:
            return None

        # 创建 PatchCalculator
        calculator = PatchCalculator(sess.workspace)

        # 从 turn 的 turn_end 消息中拿快照哈希
        stats = await self.get_turn_stats(turn_id)
        cf = stats.get("changed_files", {})
        first_hash = cf.get("first_snapshot_hash")
        last_hash = cf.get("last_snapshot_hash")
        if not first_hash or not last_hash:
            return None

        # 计算指定文件的 diff
        try:
            return await calculator.calculate_diff(
                first_hash, last_hash, file_path=file_path
            )
        except Exception as e:
            logger.warning(f"Error calculating file diff for {file_path}: {e}")
            return None

    async def count_turns_by_session(self, session_id: str, execution_id: Optional[str] = None) -> int:
        """统计会话的 turn 总数，支持按 execution_id 过滤"""
        filters = {"session_id": session_id, "reverted": False}
        if execution_id:
            filters["execution_id"] = execution_id
        return await self.count(filters)


class MessageService(BaseService[Message]):
    """Message Service类"""

    def __init__(self):
        super().__init__(Message)

    async def create_message(
        self,
        message_id: str,
        session_id: str,
        turn_id: Optional[str],
        agent_id: Optional[str],
        role: MessageRole,
        content: Optional[str] = None,
        message_type: MessageType = MessageType.USER_MESSAGE,
        sequence_number: int = 1,
        data: Optional[Dict[str, Any]] = None,
        execution_id: Optional[str] = None,
    ) -> Message:
        """创建新消息"""
        # 构建data字段
        message_data = data or {}
        if content:
            message_data["content"] = content

        kwargs = dict(
            message_id=message_id,
            session_id=session_id,
            turn_id=turn_id,
            agent_id=agent_id,
            role=role,
            message_type=message_type,
            sequence_number=sequence_number,
            timestamp=datetime.now(timezone.utc),
            data=message_data,
        )
        # 仅编排消息设置 execution_id（普通会话为 None，不影响）
        if execution_id:
            kwargs["execution_id"] = execution_id

        return await self.create(**kwargs)

    async def get_messages_by_session(
        self,
        session_id: str,
        order_by="sequence_number",
        skip=None,
        limit=None,
        ignore_reverted=True,
        execution_id: Optional[str] = None,
    ) -> List[Message]:
        """根据会话ID获取消息"""
        if execution_id:
            from sqlalchemy import text

            async with db_manager.get_session() as session:
                stmt = (
                    select(Message)
                    .where(Message.session_id == session_id)
                    .where(Message.execution_id == execution_id)
                )
                if ignore_reverted:
                    stmt = stmt.where(Message.reverted == False)  # noqa: E712
                stmt = stmt.order_by(text(order_by))
                if skip:
                    stmt = stmt.offset(skip)
                if limit:
                    stmt = stmt.limit(limit)
                result = await session.execute(stmt)
                return list(result.scalars().all())

        filters = {"session_id": session_id}
        if ignore_reverted:
            filters["reverted"] = False
        return await self.get_batch(
            filters=filters,
            order_by=order_by,
            skip=skip,
            limit=limit,
        )

    async def count_messages_by_execution(
        self, session_id: str, execution_id: str, ignore_reverted=True
    ) -> int:
        """统计编排执行相关的消息总数"""
        from sqlalchemy import func

        async with db_manager.get_session() as session:
            stmt = (
                select(func.count(Message.message_id))
                .where(Message.session_id == session_id)
                .where(Message.execution_id == execution_id)
            )
            if ignore_reverted:
                stmt = stmt.where(Message.reverted == False)  # noqa: E712
            result = await session.execute(stmt)
            return result.scalar() or 0

    async def get_messages_by_agent(
        self, agent_id: str, ignore_reverted=True
    ) -> List[Message]:
        """根据Agent ID获取消息"""
        filters = {"agent_id": agent_id}
        if ignore_reverted:
            filters["reverted"] = False
        return await self.get_batch(filters=filters, order_by="sequence_number")

    async def get_next_sequence_number(self, session_id: str) -> int:
        """[DEPRECATED] 获取下一个消息序列号

        .. deprecated::
            使用 :meth:`next_sequence_for_session` 代替。
        """
        import warnings
        warnings.warn(
            "MessageService.get_next_sequence_number is deprecated. "
            "Use next_sequence_for_session instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.next_sequence_for_session(session_id)

    async def next_sequence_for_session(self, session_id: str) -> int:
        """原子递增并返回该 session 的下一个 message 序列号"""
        async with db_manager.get_session() as session:
            stmt = (
                sqlite_insert(MessageSeqCounter)
                .values(counter_key=session_id, last_seq=1)
                .on_conflict_do_update(
                    index_elements=["counter_key"],
                    set_={"last_seq": MessageSeqCounter.last_seq + 1},
                )
                .returning(MessageSeqCounter.last_seq)
            )
            result = await session.execute(stmt)
            value = result.scalar_one()
            await session.commit()
            return value

    async def next_sequence_in_session(
        self, db_session: "AsyncSession", session_id: str
    ) -> int:
        """在外部事务中递增序列号。不 commit。

        ⚠️ 调用者必须确保 db_session 处于活跃事务中（通过 get_multi_session 获取）。
        """
        assert db_session.in_transaction(), (
            "next_sequence_in_session requires an active transaction (use get_multi_session)"
        )
        stmt = (
            sqlite_insert(MessageSeqCounter)
            .values(counter_key=session_id, last_seq=1)
            .on_conflict_do_update(
                index_elements=["counter_key"],
                set_={"last_seq": MessageSeqCounter.last_seq + 1},
            )
            .returning(MessageSeqCounter.last_seq)
        )
        result = await db_session.execute(stmt)
        return result.scalar_one()

    async def create_message_in_session(
        self, db_session: "AsyncSession", **kwargs
    ) -> Message:
        """在外部事务中创建消息。

        ⚠️ 此方法不做 commit/rollback——事务生命周期由外层 get_multi_session() 管理。
        调用者必须确保 db_session 处于活跃事务中。
        """
        assert db_session.in_transaction(), (
            "create_message_in_session requires an active transaction (use get_multi_session)"
        )
        instance = Message(**kwargs)
        db_session.add(instance)
        await db_session.flush()
        return instance

    async def get_message_ids_from_pivot(
        self, agent_id: str, pivot_message_id: str
    ) -> set:
        """获取从 pivot 开始（含）的所有 message_id（仅查 ID，不加载完整 data）"""
        async with db_manager.get_session() as session:
            pivot_seq = (
                await session.execute(
                    select(Message.sequence_number).where(
                        Message.message_id == pivot_message_id
                    )
                )
            ).scalar_one_or_none()
            if pivot_seq is None:
                return set()
            ids = (
                await session.execute(
                    select(Message.message_id, Message.turn_id)
                    .where(Message.agent_id == agent_id)
                    .where(Message.sequence_number >= pivot_seq)
                )
            ).all()
            # Return (message_ids, turn_ids) as a dict for convenience
            message_ids = {row[0] for row in ids}
            turn_ids = {row[1] for row in ids if row[1]}
            return {"message_ids": message_ids, "turn_ids": turn_ids}

    async def get_messages_from_pivot(
        self, agent_id: str, pivot_message_id: str
    ) -> List[Message]:
        """获取从 pivot 开始（含）到 agent 最后一条消息的完整消息（用于收集 patches）"""
        async with db_manager.get_session() as session:
            pivot_seq = (
                await session.execute(
                    select(Message.sequence_number).where(
                        Message.message_id == pivot_message_id
                    )
                )
            ).scalar_one_or_none()
            if pivot_seq is None:
                return []
            return list(
                (
                    await session.execute(
                        select(Message)
                        .where(Message.agent_id == agent_id)
                        .where(Message.sequence_number >= pivot_seq)
                        .order_by(Message.sequence_number)
                    )
                )
                .scalars()
                .all()
            )

    async def find_pivot_message_id(
        self, agent_id: str, target_message_id: str, level: str
    ) -> Optional[str]:
        """通过 SQL 查找 pivot message_id"""
        async with db_manager.get_session() as session:
            # 获取目标消息的 turn_id 和 data
            target_row = (
                await session.execute(
                    select(Message.turn_id, Message.data).where(
                        Message.message_id == target_message_id
                    )
                )
            ).first()
            if not target_row:
                return None
            target_turn_id, target_data = target_row

            if level == "turn":
                # 找该 turn 的 TURN_START 消息
                pivot = (
                    await session.execute(
                        select(Message.message_id)
                        .where(Message.turn_id == target_turn_id)
                        .where(Message.agent_id == agent_id)
                        .where(Message.message_type == MessageType.TURN_START)
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if not pivot:
                    pivot = target_message_id  # fallback
            else:  # level == "step"
                step_id = (target_data or {}).get("step_id")
                if step_id:
                    pivot = (
                        await session.execute(
                            select(Message.message_id)
                            .where(Message.turn_id == target_turn_id)
                            .where(Message.agent_id == agent_id)
                            .where(Message.message_type == MessageType.STEP_START)
                            .where(func.json_extract(Message.data, "$.step_id") == step_id)
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                else:
                    pivot = target_message_id  # fallback
                if not pivot:
                    pivot = target_message_id  # fallback
            return pivot

    async def get_last_agent_response_id(self, agent_id: str) -> Optional[str]:
        """获取 agent 最后一条 AGENT_RESPONSE 的 message_id"""
        async with db_manager.get_session() as session:
            result = (
                await session.execute(
                    select(Message.message_id)
                    .where(Message.agent_id == agent_id)
                    .where(Message.message_type == MessageType.AGENT_RESPONSE)
                    .where(Message.reverted == False)
                    .order_by(Message.sequence_number.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if result:
                return result
            # Fallback: last message of any type
            return (
                await session.execute(
                    select(Message.message_id)
                    .where(Message.agent_id == agent_id)
                    .where(Message.reverted == False)
                    .order_by(Message.sequence_number.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def get_message_stats_by_session(self, session_id: str) -> Dict[str, Any]:
        """获取会话的消息统计信息

        Returns:
            包含以下字段的字典:
            - total_messages: 消息总数
            - messages_by_type: 按消息类型分组的数量统计
            - tool_call_errors: 工具调用错误数量
        """
        async with db_manager.get_session() as session:
            total_messages = await self.count(filters={"session_id": session_id})

            type_stats_statement = (
                select(Message.message_type, func.count(Message.message_id))
                .where(Message.session_id == session_id)
                .group_by(Message.message_type)
            )
            type_stats_result = await session.exec(type_stats_statement)
            type_stats_rows = type_stats_result.all()

            messages_by_type = {}
            for msg_type, count in type_stats_rows:
                messages_by_type[str(msg_type)] = count

            tool_error_statement = select(Message).where(
                and_(
                    Message.session_id == session_id,
                    Message.message_type == MessageType.TOOL_CALL,
                )
            )
            tool_calls_result = await session.exec(tool_error_statement)
            tool_call_messages = tool_calls_result.scalars().all()

            tool_call_errors = 0
            for msg in tool_call_messages:
                # 检查data字段中是否包含错误信息
                data = msg.data or {}
                is_error = data.get("status") == "error"
                if is_error:
                    tool_call_errors += 1

            return {
                "total_messages": total_messages,
                "messages_by_type": messages_by_type,
                "tool_call_errors": tool_call_errors,
            }

    async def update_message(
        self, message_id: str, updates: Dict[str, Any]
    ) -> Optional[Message]:
        """更新消息

        Args:
            message_id: 消息ID
            updates: 更新字段字典

        Returns:
            更新后的消息，如果消息不存在则返回None
        """
        return await self.update(message_id, **updates)

    async def search_messages(
        self,
        session_id: str,
        keyword: Optional[str] = None,
        message_type: Optional[str] = None,
        sender_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        order: str = "desc",
        skip: int = 0,
        limit: int = 50,
        ignore_reverted: bool = True,
    ) -> Tuple[List[Message], int]:
        """搜索会话中的消息，支持关键词和多个字段筛选

        Args:
            session_id: 会话ID（必填）
            keyword: 搜索关键词，匹配 data 字段中的内容
            message_type: 按消息类型过滤
            sender_id: 按发送者ID过滤
            tool_name: 按工具名称过滤（匹配 data->>'tool_name'）
            skip: 分页偏移
            limit: 每页数量
            ignore_reverted: 是否忽略已回滚的消息

        Returns:
            (消息列表, 总数)
        """
        async with db_manager.get_session() as session:
            stmt = select(Message).where(Message.session_id == session_id)

            if ignore_reverted:
                stmt = stmt.where(Message.reverted == False)  # noqa: E712

            if message_type:
                stmt = stmt.where(Message.message_type == message_type)

            if sender_id:
                stmt = stmt.where(
                    or_(Message.sender_id == sender_id, Message.agent_id == sender_id)
                )

            # 关键词搜索：将 data 字段转为文本后 LIKE 匹配
            if keyword:
                keyword_like = f"%{keyword}%"
                stmt = stmt.where(
                    or_(
                        cast(Message.data, String).ilike(keyword_like),
                        Message.message_type.ilike(keyword_like),
                        Message.sender_id.ilike(keyword_like),
                        Message.agent_id.ilike(keyword_like),
                    )
                )

            # 工具名称搜索：SQLite JSON1 扩展
            if tool_name:
                tool_like = f"%{tool_name}%"
                stmt = stmt.where(
                    func.json_extract(Message.data, "$.tool_name").ilike(tool_like)
                )

            # 总数
            count_stmt = select(func.count()).select_from(stmt.subquery())
            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0

            # 排序 & 分页
            sort_expr = (
                "sequence_number asc" if order == "asc" else "sequence_number desc"
            )
            stmt = stmt.order_by(text(sort_expr))
            stmt = stmt.offset(skip).limit(limit)

            result = await session.execute(stmt)
            messages = list(result.scalars().all())

            return messages, total

    async def get_distinct_tool_names(self, session_id: str) -> List[str]:
        """获取会话中所有不同的工具名称"""
        async with db_manager.get_session() as session:
            stmt = (
                select(func.distinct(func.json_extract(Message.data, "$.tool_name")))
                .where(Message.session_id == session_id)
                .where(Message.message_type == MessageType.TOOL_CALL)
                .where(Message.reverted == False)  # noqa: E712
                .where(func.json_extract(Message.data, "$.tool_name").isnot(None))
            )
            result = await session.execute(stmt)
            names = [row[0] for row in result.all() if row[0]]
            return sorted(names)


class AgentConfigService(BaseService[AgentConfig]):
    """AgentConfig Service类"""

    def __init__(self):
        super().__init__(AgentConfig)

    async def create_config(
        self, session_id: str, name: str, config_content: str
    ) -> AgentConfig:
        """创建新配置"""
        config_id = uuid.uuid4().hex
        return await self.create(
            config_id=config_id,
            session_id=session_id,
            name=name,
            config_content=config_content,
            created_at=datetime.now(timezone.utc),
        )

    async def get_configs_by_session(self, session_id: str) -> List[AgentConfig]:
        """根据会话ID获取配置"""
        return await self.get_batch(filters={"session_id": session_id})


class AgentService(BaseService[Agent]):
    """Agent Service类"""

    def __init__(self):
        super().__init__(Agent)

    async def create_agent(
        self,
        agent_id: str,
        config_id: str,
        session_id: str,
        name: str,
        role: str,
    ) -> Agent:
        """创建新Agent"""
        return await self.create(
            agent_id=agent_id,
            config_id=config_id,
            session_id=session_id,
            name=name,
            role=role,
            created_at=datetime.now(timezone.utc),
        )

    async def get_agents_by_session(self, session_id: str) -> List[Agent]:
        """根据会话ID获取Agent"""
        return await self.get_batch(filters={"session_id": session_id})

    async def update_agent_status(self, agent_id: str, status: str) -> bool:
        """更新 Agent 运行状态到数据库

        Args:
            agent_id: Agent ID
            status: 运行状态 (idle/running/disconnected)

        Returns:
            是否更新成功
        """
        agent = await self.update(agent_id, agent_status=status)
        return agent is not None


# 全局Service实例
session_service = SessionService()
turn_service = TurnService()
message_service = MessageService()
agent_config_service = AgentConfigService()
agent_service = AgentService()


def get_session_service() -> SessionService:
    """获取SessionService实例"""
    return session_service


def get_turn_service() -> TurnService:
    """获取TurnService实例"""
    return turn_service


def get_message_service() -> MessageService:
    """获取MessageService实例"""
    return message_service


def get_agent_config_service() -> AgentConfigService:
    """获取AgentConfigService实例"""
    return agent_config_service


def get_agent_service() -> AgentService:
    """获取AgentService实例"""
    return agent_service


class JobService(BaseService[ScheduledJob]):
    """调度任务Service类"""

    def __init__(self):
        super().__init__(ScheduledJob)

    async def create_job(
        self,
        job_id: str,
        name: str,
        job_type: JobType,
        trigger_type: str,
        trigger_config: Dict[str, Any],
        content: str,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> ScheduledJob:
        """创建新任务"""
        now = datetime.now(timezone.utc)
        return await self.create(
            job_id=job_id,
            name=name,
            job_type=job_type,
            status=JobStatus.ACTIVE,
            trigger_type=trigger_type,
            trigger_config=trigger_config,
            content=content,
            session_id=session_id,
            agent_id=agent_id,
            created_at=now,
            updated_at=now,
        )

    async def get_active_jobs(
        self, session_id: Optional[str] = None
    ) -> List[ScheduledJob]:
        """获取活跃任务"""
        filters = {"status": JobStatus.ACTIVE}
        if session_id:
            filters["session_id"] = session_id
        return await self.get_batch(filters=filters, order_by="created_at")

    async def get_jobs_by_session(self, session_id: str) -> List[ScheduledJob]:
        """根据会话ID获取任务"""
        return await self.get_batch(
            filters={"session_id": session_id}, order_by="created_at"
        )

    async def update_job_status(self, job_id: str, status: JobStatus) -> bool:
        """更新任务状态"""
        job = await self.update(job_id, status=status, updated_at=datetime.now(timezone.utc))
        return job is not None

    async def update_next_run_time(
        self, job_id: str, next_run_time: Optional[datetime]
    ) -> bool:
        """更新下次执行时间"""
        job = await self.update(
            job_id, next_run_time=next_run_time, updated_at=datetime.now(timezone.utc)
        )
        return job is not None

    async def pause_job(self, job_id: str) -> bool:
        """暂停任务"""
        return await self.update_job_status(job_id, JobStatus.PAUSED)

    async def resume_job(self, job_id: str) -> bool:
        """恢复任务"""
        return await self.update_job_status(job_id, JobStatus.ACTIVE)

    async def cancel_job(self, job_id: str) -> bool:
        """取消任务"""
        return await self.update_job_status(job_id, JobStatus.CANCELLED)

    async def complete_job(self, job_id: str) -> bool:
        """标记任务完成（一次性任务）"""
        return await self.update_job_status(job_id, JobStatus.COMPLETED)


class JobExecutionService(BaseService[JobExecution]):
    """任务执行记录Service类"""

    def __init__(self):
        super().__init__(JobExecution)

    async def create_execution(
        self, job_id: str, success: bool, result: Optional[str] = None
    ) -> JobExecution:
        """创建执行记录"""
        execution_id = f"exec_{uuid.uuid4().hex}"
        return await self.create(
            execution_id=execution_id,
            job_id=job_id,
            success=success,
            result=result,
            executed_at=datetime.now(timezone.utc),
        )

    async def get_executions_by_job(
        self, job_id: str, limit: int = 10
    ) -> List[JobExecution]:
        """根据任务ID获取执行记录"""
        async with db_manager.get_session() as session:
            statement = (
                select(JobExecution)
                .where(JobExecution.job_id == job_id)
                .order_by(JobExecution.executed_at.desc())
                .limit(limit)
            )
            result = await session.exec(statement)
            return result.scalars().all()

    async def get_recent_executions(self, limit: int = 50) -> List[JobExecution]:
        """获取最近的执行记录"""
        async with db_manager.get_session() as session:
            statement = (
                select(JobExecution)
                .order_by(JobExecution.executed_at.desc())
                .limit(limit)
            )
            result = await session.exec(statement)
            return result.scalars().all()


# 全局Service实例
job_service = JobService()
job_execution_service = JobExecutionService()


def get_job_service() -> JobService:
    """获取JobService实例"""
    return job_service


def get_job_execution_service() -> JobExecutionService:
    """获取JobExecutionService实例"""
    return job_execution_service


class TaskCommentService(BaseService[TaskComment]):
    """任务评论Service类"""

    def __init__(self):
        super().__init__(TaskComment)

    async def get_comments_by_task(self, task_id: str) -> List[TaskComment]:
        """根据任务ID获取评论"""
        return await self.get_batch(filters={"task_id": task_id}, order_by="created_at")

    async def get_comments_by_author(self, author: str) -> List[TaskComment]:
        """根据作者获取评论"""
        return await self.get_batch(filters={"author": author}, order_by="created_at")


class TaskService(BaseService[Task]):
    """任务Service类"""

    def __init__(self):
        super().__init__(Task)

    def _get_id_field_name(self) -> str:
        """重写ID字段名获取方法"""
        return "task_id"

    async def create_task(
        self,
        name: str,
        description: str,
        priority: TaskPriority = TaskPriority.MEDIUM,
        parent_id: Optional[str] = None,
        assignee: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        details: Optional[str] = None,
        context_files: Optional[List[str]] = None,
        context_links: Optional[List[str]] = None,
        context_notes: Optional[str] = None,
        acceptance_criteria: Optional[List[str]] = None,
        report: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Task:
        """创建新任务"""
        now = datetime.now(timezone.utc)
        return await self.create(
            name=name,
            description=description,
            session_id=session_id,
            parent_id=parent_id,
            status=TaskStatus.PENDING,
            priority=priority,
            assignee=assignee,
            dependencies=dependencies,
            details=details,
            acceptance_criteria=acceptance_criteria,
            context_files=context_files,
            context_links=context_links,
            context_notes=context_notes,
            report=report,
            created_at=now,
            updated_at=now,
        )

    async def get_tasks_by_session(
        self, session_id: str, status: Optional[TaskStatus] = None
    ) -> List[Task]:
        """根据会话ID获取任务"""
        filters = {"session_id": session_id}
        if status:
            filters["status"] = status
        return await self.get_batch(filters=filters, order_by="created_at desc")

    async def get_tasks_by_status(
        self, session_id: str, status: TaskStatus
    ) -> List[Task]:
        """根据状态获取任务"""
        return await self.get_batch(
            filters={"session_id": session_id, "status": status},
            order_by="created_at desc",
        )

    async def get_tasks_by_assignee(self, session_id: str, assignee: str) -> List[Task]:
        """根据分配对象获取任务"""
        return await self.get_batch(
            filters={"session_id": session_id, "assignee": assignee},
            order_by="created_at desc",
        )

    async def get_child_tasks(self, parent_id: str) -> List[Task]:
        """获取子任务"""
        return await self.get_batch(
            filters={"parent_id": parent_id}, order_by="created_at desc"
        )

    async def get_root_tasks(self, session_id: Optional[str] = None) -> List[Task]:
        """获取根任务（没有父任务的任务）"""
        async with db_manager.get_session() as session:
            statement = select(Task).where(Task.parent_id.is_(None))

            if session_id:
                statement = statement.where(Task.session_id == session_id)

            statement = statement.order_by(Task.created_at)
            result = await session.exec(statement)
            return result.scalars().all()

    async def update_task(
        self,
        task_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        priority: Optional[TaskPriority] = None,
        assignee: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        details: Optional[str] = None,
        context_files: Optional[List[str]] = None,
        context_links: Optional[List[str]] = None,
        context_notes: Optional[str] = None,
        acceptance_criteria: Optional[List[str]] = None,
        report: Optional[str] = None,
    ) -> Optional[Task]:
        """更新任务"""
        update_data = {}
        if name is not None:
            update_data["name"] = name
        if description is not None:
            update_data["description"] = description
        if status is not None:
            update_data["status"] = status
        if priority is not None:
            update_data["priority"] = priority
        if assignee is not None:
            update_data["assignee"] = assignee
        if dependencies is not None:
            update_data["dependencies"] = dependencies
        if details is not None:
            update_data["details"] = details
        if acceptance_criteria is not None:
            update_data["acceptance_criteria"] = acceptance_criteria
        if context_files is not None:
            update_data["context_files"] = context_files
        if context_links is not None:
            update_data["context_links"] = context_links
        if context_notes is not None:
            update_data["context_notes"] = context_notes
        if report is not None:
            update_data["report"] = report

        if update_data:
            update_data["updated_at"] = datetime.now(timezone.utc)

        return await self.update(task_id, **update_data)

    async def search_tasks(
        self, query: str, session_id: Optional[str] = None
    ) -> List[Task]:
        """搜索任务（按名称和描述），使用 SQL LIKE 进行模糊匹配"""
        async with db_manager.get_session() as session:
            like_pattern = f"%{query}%"
            statement = (
                select(Task)
                .where(
                    or_(
                        Task.name.ilike(like_pattern),
                        Task.description.ilike(like_pattern),
                        Task.details.ilike(like_pattern),
                    )
                )
            )
            if session_id:
                statement = statement.where(Task.session_id == session_id)
            statement = statement.order_by(Task.created_at)

            result = await session.exec(statement)
            return list(result.scalars().all())

    async def add_comment(
        self, task_id: str, author: str, content: str
    ) -> Optional[TaskComment]:
        """为任务添加评论"""
        # 验证任务存在
        task = await self.get(task_id)
        if not task:
            return None

        comment_service = TaskCommentService()
        comment = await comment_service.create(
            task_id=task_id,
            author=author,
            content=content,
            created_at=datetime.now(timezone.utc),
        )

        # 更新任务的updated_at
        await self.update(task_id, updated_at=datetime.now(timezone.utc))

        return comment

    async def get_task_with_comments(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务及其所有评论"""
        task = await self.get(task_id)
        if not task:
            return None

        comment_service = TaskCommentService()
        comments = await comment_service.get_comments_by_task(task_id)
        return {"task": task, "comments": comments}


# 全局Service实例
task_service = TaskService()
task_comment_service = TaskCommentService()


def get_task_service() -> TaskService:
    """获取TaskService实例"""
    return task_service


def get_task_comment_service() -> TaskCommentService:
    """获取TaskCommentService实例"""
    return task_comment_service
