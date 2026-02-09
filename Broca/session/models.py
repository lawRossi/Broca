"""
数据模型定义模块（修复版本）

定义Session、Message、History等数据模型，使用sqlmodel框架。
修复了关系配置问题。
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from sqlmodel import Field, Relationship, SQLModel


class MessageRole(str, Enum):
    """消息角色枚举"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
    AGENT = "agent"


class MessageType(str, Enum):
    """消息类型枚举"""

    COMMAND = "command"
    ERROR = "error"
    PERMISSION_REQUEST = "permission_request"
    PERMISSION_RESPONSE = "permission_response"
    REASONING = "reasoning"
    TEXT = "text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TURN_START = "turn_start"
    TURN_END = "turn_end"


class SessionStatus(str, Enum):
    """会话状态枚举"""

    ACTIVE = "active"
    INACTIVE = "inactive"


class Turn(SQLModel, table=True):
    """
    对话轮次模型

    存储完整的对话轮次信息，用于跟踪和管理多轮对话。
    """

    __tablename__ = "turn"

    session_id: str = Field(
        foreign_key="session.session_id", ondelete="CASCADE", description="关联的会话ID"
    )
    turn_id: str = Field(index=True, primary_key=True, description="轮次ID")
    agent_id: str = Field(
        foreign_key="agent.agent_id", ondelete="CASCADE", description="关联的Agent ID"
    )
    turn_description: Optional[str] = Field(default=None, description="轮次描述")
    sequence_number: int = Field(description="轮次序号")

    # 关联关系
    agent: "Agent" = Relationship(back_populates="turns")
    session: "Session" = Relationship(back_populates="turns")
    messages: List["Message"] = Relationship(
        back_populates="turn", cascade_delete="all"
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="创建时间"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class Session(SQLModel, table=True):
    """
    会话模型

    存储会话的基本信息，包括会话ID、状态、创建时间等。
    """

    __tablename__ = "session"

    session_id: str = Field(index=True, primary_key=True, description="会话唯一标识符")
    status: SessionStatus = Field(default=SessionStatus.ACTIVE, description="会话状态")
    description: Optional[str] = Field(default=None, description="会话描述")

    # 元数据
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="创建时间"
    )

    finished_at: Optional[datetime] = Field(default=None, description="结束时间")

    # 关联关系
    turns: List["Turn"] = Relationship(back_populates="session", cascade_delete="all")
    messages: List["Message"] = Relationship(
        back_populates="session", cascade_delete="all"
    )
    agents: List["Agent"] = Relationship(back_populates="session", cascade_delete="all")
    agent_configs: List["AgentConfig"] = Relationship(
        back_populates="session", cascade_delete="all"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class Message(SQLModel, table=True):
    """
    消息模型

    存储通信消息，包括消息内容、角色、类型等。
    """

    __tablename__ = "message"

    message_id: str = Field(index=True, primary_key=True, description="消息唯一标识符")
    session_id: str = Field(
        foreign_key="session.session_id", ondelete="CASCADE", description="关联的会话ID"
    )
    turn_id: str = Field(
        foreign_key="turn.turn_id", ondelete="CASCADE", description="关联的轮次ID"
    )
    agent_id: str = Field(
        foreign_key="agent.agent_id", ondelete="CASCADE", description="关联的Agent ID"
    )

    # 消息内容
    role: MessageRole = Field(description="消息角色")
    message_type: MessageType = Field(default=MessageType.TEXT, description="消息类型")
    content: Optional[str] = Field(default=None, description="消息内容")

    # 推理内容（用于思维链）
    reasoning_content: Optional[str] = Field(default=None, description="推理内容")

    # 工具调用信息
    tool_calls: Optional[str] = Field(default=None, description="工具调用信息")

    tool_call_id: Optional[str] = Field(default=None, description="工具调用ID")
    tool_name: Optional[str] = Field(default=None, description="工具名称")
    tool_arguments: Optional[str] = Field(default=None, description="工具参数JSON")
    tool_result: Optional[str] = Field(default=None, description="工具执行结果")

    sequence_number: int = Field(description="消息序列号")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="消息时间戳"
    )

    # 关联关系
    session: Session = Relationship(back_populates="messages")
    turn: Turn = Relationship(back_populates="messages")
    agent: "Agent" = Relationship(back_populates="messages")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class AgentConfig(SQLModel, table=True):
    """
    Agent配置模型

    存储Agent配置信息，包括配置名称、配置内容等。
    """

    __tablename__ = "agent_config"

    config_id: str = Field(index=True, primary_key=True, description="配置唯一标识符")
    session_id: str = Field(
        foreign_key="session.session_id", ondelete="CASCADE", description="关联的会话ID"
    )

    name: str = Field(description="配置名称")
    config_content: str = Field(description="配置内容")

    # 元数据
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="创建时间"
    )

    # 关联关系
    session: Session = Relationship(back_populates="agent_configs")
    agents: List["Agent"] = Relationship(back_populates="agent_config")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class Agent(SQLModel, table=True):
    """
    Agent模型

    存储Agent的基本信息，包括Agent ID、状态、创建时间等。
    """

    __tablename__ = "agent"

    agent_id: str = Field(index=True, primary_key=True, description="Agent唯一标识符")
    config_id: str = Field(
        foreign_key="agent_config.config_id",
        ondelete="CASCADE",
        description="关联的配置ID",
    )
    session_id: str = Field(
        foreign_key="session.session_id", ondelete="CASCADE", description="关联的会话ID"
    )

    name: str = Field(description="Agent名称")
    role: str = Field(description="Agent角色")

    # 元数据
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="创建时间"
    )

    # 关联关系
    agent_config: AgentConfig = Relationship(back_populates="agents")
    session: Session = Relationship(back_populates="agents")
    turns: List["Turn"] = Relationship(back_populates="agent")
    messages: List["Message"] = Relationship(
        back_populates="agent", cascade_delete="all"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
