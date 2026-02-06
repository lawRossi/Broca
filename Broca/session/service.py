"""
Service类实现模块

为Session、Turn、Message、Agent、AgentConfig等数据模型提供Service类
实现CRUD操作和业务逻辑。
"""

from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar

from sqlalchemy import select
from sqlmodel import SQLModel, and_

from .database import db_manager
from .models import (
    Agent,
    AgentConfig,
    Message,
    MessageRole,
    MessageType,
    Session,
    SessionStatus,
    Turn,
)

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
        # 特殊处理：Session -> session_id, Turn -> turn_id, 等等
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
            # 使用scalars()获取模型实例而不是Row对象
            return result.scalars().first()

    async def get_all(
        self, skip: int = 0, limit: int = 100, filters: Optional[Dict[str, Any]] = None
    ) -> List[T]:
        """获取所有记录，支持分页和过滤"""
        async with db_manager.get_session() as session:
            statement = select(self.model_class).offset(skip).limit(limit)

            if filters:
                conditions = []
                for key, value in filters.items():
                    if hasattr(self.model_class, key):
                        conditions.append(getattr(self.model_class, key) == value)
                if conditions:
                    statement = statement.where(and_(*conditions))

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

    async def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """统计记录数量"""
        async with db_manager.get_session() as session:
            statement = select(self.model_class)

            if filters:
                conditions = []
                for key, value in filters.items():
                    if hasattr(self.model_class, key):
                        conditions.append(getattr(self.model_class, key) == value)
                if conditions:
                    statement = statement.where(and_(*conditions))

            result = await session.exec(statement)
            return len(result.scalars().all())


class SessionService(BaseService[Session]):
    """Session Service类"""

    def __init__(self):
        super().__init__(Session)

    async def create_session(
        self, session_id: str, description: Optional[str] = None
    ) -> Session:
        """创建新会话"""
        return await self.create(
            session_id=session_id,
            status=SessionStatus.ACTIVE,
            description=description,
            created_at=datetime.utcnow(),
        )

    async def get_active_sessions(self) -> List[Session]:
        """获取所有活跃会话"""
        return await self.get_all(filters={"status": SessionStatus.ACTIVE})

    async def get_session_by_status(self, status: SessionStatus) -> List[Session]:
        """根据状态获取会话"""
        return await self.get_all(filters={"status": status})

    async def close_session(self, session_id: str) -> Optional[Session]:
        """关闭会话"""
        return await self.update(
            session_id,
            status=SessionStatus.INACTIVE,
            finished_at=datetime.utcnow(),
        )

    async def get_session_with_turns(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话及其所有轮次"""
        session = await self.get(session_id)
        if not session:
            return None

        turn_service = TurnService()
        turns = await turn_service.get_turns_by_session(session_id)

        return {
            "session": session,
            "turns": turns,
        }

    async def get_session_with_messages(
        self, session_id: str
    ) -> Optional[Dict[str, Any]]:
        """获取会话及其所有消息"""
        session = await self.get(session_id)
        if not session:
            return None

        message_service = MessageService()
        messages = await message_service.get_messages_by_session(session_id)

        return {
            "session": session,
            "messages": messages,
        }

    async def get_session_with_agents(
        self, session_id: str
    ) -> Optional[Dict[str, Any]]:
        """获取会话及其所有Agent"""
        session = await self.get(session_id)
        if not session:
            return None

        agent_service = AgentService()
        agents = await agent_service.get_agents_by_session(session_id)

        return {
            "session": session,
            "agents": agents,
        }


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
    ) -> Turn:
        """创建新轮次"""
        return await self.create(
            turn_id=turn_id,
            session_id=session_id,
            agent_id=agent_id,
            sequence_number=sequence_number,
            turn_description=turn_description,
            created_at=datetime.utcnow(),
        )

    async def get_turns_by_session(self, session_id: str) -> List[Turn]:
        """根据会话ID获取轮次"""
        return await self.get_all(filters={"session_id": session_id})

    async def get_turns_by_agent(self, agent_id: str) -> List[Turn]:
        """根据Agent ID获取轮次"""
        return await self.get_all(filters={"agent_id": agent_id})

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

    async def get_turn_with_messages(self, turn_id: str) -> Optional[Dict[str, Any]]:
        """获取轮次及其所有消息"""
        turn = await self.get(turn_id)
        if not turn:
            return None

        message_service = MessageService()
        messages = await message_service.get_messages_by_turn(turn_id)

        return {
            "turn": turn,
            "messages": messages,
        }

    async def get_next_sequence_number(self, session_id: str) -> int:
        """获取下一个轮次序列号"""
        latest_turn = await self.get_latest_turn(session_id)
        if latest_turn:
            return latest_turn.sequence_number + 1
        return 1


class MessageService(BaseService[Message]):
    """Message Service类"""

    def __init__(self):
        super().__init__(Message)

    async def create_message(
        self,
        message_id: str,
        session_id: str,
        turn_id: str,
        agent_id: str,
        role: MessageRole,
        content: Optional[str] = None,
        message_type: MessageType = MessageType.TEXT,
        reasoning_content: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        tool_arguments: Optional[str] = None,
        tool_result: Optional[str] = None,
        sequence_number: int = 1,
    ) -> Message:
        """创建新消息"""
        return await self.create(
            message_id=message_id,
            session_id=session_id,
            turn_id=turn_id,
            agent_id=agent_id,
            role=role,
            content=content,
            message_type=message_type,
            reasoning_content=reasoning_content,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            tool_result=tool_result,
            sequence_number=sequence_number,
            timestamp=datetime.utcnow(),
        )

    async def get_messages_by_session(self, session_id: str) -> List[Message]:
        """根据会话ID获取消息"""
        return await self.get_all(filters={"session_id": session_id})

    async def get_messages_by_turn(self, turn_id: str) -> List[Message]:
        """根据轮次ID获取消息"""
        return await self.get_all(filters={"turn_id": turn_id})

    async def get_messages_by_agent(self, agent_id: str) -> List[Message]:
        """根据Agent ID获取消息"""
        return await self.get_all(filters={"agent_id": agent_id})

    async def get_messages_by_role(
        self, session_id: str, role: MessageRole
    ) -> List[Message]:
        """根据会话ID和角色获取消息"""
        async with db_manager.get_session() as session:
            statement = select(Message).where(
                and_(
                    Message.session_id == session_id,
                    Message.role == role,
                )
            )
            result = await session.exec(statement)
            return result.scalars().all()

    async def get_messages_by_type(
        self, session_id: str, message_type: MessageType
    ) -> List[Message]:
        """根据会话ID和消息类型获取消息"""
        async with db_manager.get_session() as session:
            statement = select(Message).where(
                and_(
                    Message.session_id == session_id,
                    Message.message_type == message_type,
                )
            )
            result = await session.exec(statement)
            return result.scalars().all()

    async def get_conversation_history(
        self, session_id: str, limit: int = 50
    ) -> List[Message]:
        """获取会话历史消息"""
        async with db_manager.get_session() as session:
            statement = (
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.sequence_number.asc())
                .limit(limit)
            )
            result = await session.exec(statement)
            return result.scalars().all()

    async def get_next_sequence_number(self, session_id: str) -> int:
        """获取下一个消息序列号"""
        async with db_manager.get_session() as session:
            statement = (
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.sequence_number.desc())
                .limit(1)
            )
            result = await session.exec(statement)
            latest_message = result.scalars().first()
            if latest_message:
                return latest_message.sequence_number + 1
            return 1


class AgentConfigService(BaseService[AgentConfig]):
    """AgentConfig Service类"""

    def __init__(self):
        super().__init__(AgentConfig)

    async def create_config(
        self, config_id: str, session_id: str, name: str, config_content: str
    ) -> AgentConfig:
        """创建新配置"""
        return await self.create(
            config_id=config_id,
            session_id=session_id,
            name=name,
            config_content=config_content,
            created_at=datetime.utcnow(),
        )

    async def get_configs_by_session(self, session_id: str) -> List[AgentConfig]:
        """根据会话ID获取配置"""
        return await self.get_all(filters={"session_id": session_id})

    async def get_config_by_name(
        self, session_id: str, name: str
    ) -> Optional[AgentConfig]:
        """根据会话ID和名称获取配置"""
        async with db_manager.get_session() as session:
            statement = select(AgentConfig).where(
                and_(
                    AgentConfig.session_id == session_id,
                    AgentConfig.name == name,
                )
            )
            result = await session.exec(statement)
            return result.scalars().first()


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
            created_at=datetime.utcnow(),
        )

    async def get_agents_by_session(self, session_id: str) -> List[Agent]:
        """根据会话ID获取Agent"""
        return await self.get_all(filters={"session_id": session_id})

    async def get_agents_by_config(self, config_id: str) -> List[Agent]:
        """根据配置ID获取Agent"""
        return await self.get_all(filters={"config_id": config_id})

    async def get_agent_with_turns(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """获取Agent及其所有轮次"""
        agent = await self.get(agent_id)
        if not agent:
            return None

        turn_service = TurnService()
        turns = await turn_service.get_turns_by_agent(agent_id)

        return {
            "agent": agent,
            "turns": turns,
        }

    async def get_agent_with_messages(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """获取Agent及其所有消息"""
        agent = await self.get(agent_id)
        if not agent:
            return None

        message_service = MessageService()
        messages = await message_service.get_messages_by_agent(agent_id)

        return {
            "agent": agent,
            "messages": messages,
        }


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
