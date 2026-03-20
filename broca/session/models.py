"""
数据模型定义模块（优化版本）

定义Session、Message、History等数据模型，使用sqlmodel框架。
优化了消息模型，统一了字段结构。
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel


class MessageRole(str, Enum):
    """消息角色枚举"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
    AGENT_SYSTEM = "agent_system"
    AGENT = "agent"


class MessageType(str, Enum):
    """统一的消息类型枚举"""

    # 系统消息
    AGENT_SYSTEM_MESSAGE = "agent_system_message"
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    PING = "ping"
    PONG = "pong"
    ERROR = "error"

    # 用户交互消息
    USER_MESSAGE = "user_message"
    AGENT_RESPONSE = "agent_response"
    AGENT_ERROR = "agent_error"
    SYSTEM_MESSAGE = "system_message"

    # 工具执行（合并tool_call和tool_result）
    TOOL_CALL = "tool_call"

    # 任务管理
    TASK_START = "task_start"
    TASK_COMPLETE = "task_complete"
    TASK_ERROR = "task_error"

    # 轮次管理
    TURN_START = "turn_start"
    TURN_END = "turn_end"

    # 订阅和广播
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    BROADCAST = "broadcast"

    # 命令消息
    COMMAND = "command"
    COMMAND_RESULT = "command_result"

    # 权限消息
    PERMISSION_REQUEST = "permission_request"
    PERMISSION_RESPONSE = "permission_response"


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

    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")


class Session(SQLModel, table=True):
    """
    会话模型

    存储会话的基本信息，包括会话ID、状态、创建时间等。
    """

    __tablename__ = "session"

    session_id: str = Field(index=True, primary_key=True, description="会话唯一标识符")
    status: SessionStatus = Field(default=SessionStatus.ACTIVE, description="会话状态")
    description: Optional[str] = Field(default=None, description="会话描述")
    workspace: Optional[str] = Field(default=None, description="工作空间路径")

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")

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
    scheduled_jobs: List["ScheduledJob"] = Relationship(
        back_populates="session", cascade_delete="all"
    )


def generate_message_id() -> str:
    return "msg-" + str(uuid.uuid4())


class Message(SQLModel, table=True):
    """统一的消息模型"""

    __tablename__ = "message"

    # 基础字段
    message_id: str = Field(
        index=True,
        primary_key=True,
        description="消息唯一标识符",
        default_factory=generate_message_id,
    )
    message_type: MessageType = Field(description="消息类型")
    timestamp: datetime = Field(default_factory=datetime.now, description="消息时间戳")

    # 通信字段（可选）
    sender_id: Optional[str] = Field(default=None, description="发送者ID")
    receiver_id: Optional[str] = Field(default=None, description="接收者ID")
    room: Optional[str] = Field(default=None, description="房间ID")
    subscription: Optional[str] = Field(default=None, description="订阅ID")

    # 会话关联字段
    session_id: Optional[str] = Field(
        foreign_key="session.session_id",
        ondelete="CASCADE",
        default=None,
        description="关联的会话ID",
    )
    turn_id: Optional[str] = Field(
        foreign_key="turn.turn_id",
        ondelete="CASCADE",
        default=None,
        description="关联的轮次ID",
    )
    agent_id: Optional[str] = Field(
        foreign_key="agent.agent_id",
        ondelete="CASCADE",
        default=None,
        description="关联的Agent ID",
    )

    # 消息内容
    role: MessageRole = Field(description="消息角色")

    # 数据字段（JSON格式存储，包含content等所有数据）
    data: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default={}),
        description="消息数据（包含content等所有字段）",
    )

    # 序列号（用于排序）
    sequence_number: Optional[int] = Field(default=None, description="消息序列号")

    # 关联关系
    session: Optional["Session"] = Relationship(back_populates="messages")
    turn: Optional["Turn"] = Relationship(back_populates="messages")
    agent: Optional["Agent"] = Relationship(back_populates="messages")


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

    name: Optional[str] = Field(description="配置名称")
    config_content: str = Field(description="配置内容")

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")

    # 关联关系
    session: Session = Relationship(back_populates="agent_configs")
    agents: List["Agent"] = Relationship(back_populates="agent_config")


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

    name: Optional[str] = Field(description="Agent名称")
    role: Optional[str] = Field(description="Agent角色")

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")

    # 关联关系
    agent_config: AgentConfig = Relationship(back_populates="agents")
    session: Session = Relationship(back_populates="agents")
    turns: List["Turn"] = Relationship(back_populates="agent")
    messages: List["Message"] = Relationship(
        back_populates="agent", cascade_delete="all"
    )


# 消息协议辅助类
class MessageProtocol:
    """消息协议处理类"""

    @staticmethod
    def create_user_message(content: str, **kwargs) -> Message:
        """创建用户消息"""
        data = kwargs.pop("data", {})
        data["content"] = content

        return Message(
            message_type=MessageType.USER_MESSAGE,
            role=MessageRole.USER,
            data=data,
            **kwargs,
        )

    @staticmethod
    def create_agent_response(
        content: str | None, reasoning_content: str | None, **kwargs
    ) -> Message:
        """创建Agent响应"""
        data = kwargs.pop("data", {})
        data["content"] = content
        data["reasoning_content"] = reasoning_content
        return Message(
            message_type=MessageType.AGENT_RESPONSE,
            role=MessageRole.ASSISTANT,
            data=data,
            **kwargs,
        )

    @staticmethod
    def create_tool_call(
        tool_name: str,
        arguments: Dict[str, Any],
        tool_call_id: str,
        result: Optional[str] = None,
        status: Optional[bool] = None,
        **kwargs,
    ) -> Message:
        """创建工具调用消息"""
        data = kwargs.pop("data", {})
        data.update(
            {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "arguments": arguments,
            }
        )
        if result is not None:
            data["result"] = result
            data["status"] = status

        return Message(
            message_type=MessageType.TOOL_CALL,
            role=MessageRole.TOOL,
            data=data,
            **kwargs,
        )

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> Message:
        """从字典创建消息"""
        # 处理工具消息类型转换
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        # message_type = data.get("message_type")
        # if message_type in ["tool_call", "tool_result"]:
        #     data["message_type"] = "tool_call"
        #     if "data" not in data:
        #         data["data"] = {}
        #     if message_type == "tool_call":
        #         data["data"]["action"] = "call"
        #     else:
        #         data["data"]["action"] = "result"

        return Message(**data)

    @staticmethod
    def to_dict(message: Message) -> Dict[str, Any]:
        """将消息转换为字典"""
        result = {
            "message_id": message.message_id,
            "message_type": message.message_type,
            "timestamp": message.timestamp.isoformat(),
            "role": message.role,
            "data": message.data,
        }

        # 可选字段
        optional_fields = [
            "sender_id",
            "receiver_id",
            "room",
            "subscription",
            "error_code",
            "session_id",
            "turn_id",
            "agent_id",
            "sequence_number",
        ]

        for field in optional_fields:
            value = getattr(message, field, None)
            if value is not None:
                result[field] = value

        return result

    @staticmethod
    def create_turn_start(turn_id: str, turn_description: str, **kwargs) -> Message:
        """创建轮次开始消息"""
        return Message(
            message_type=MessageType.TURN_START,
            role=MessageRole.AGENT,
            data={"turn_id": turn_id, "turn_description": turn_description},
            **kwargs,
        )

    @staticmethod
    def create_turn_end(
        turn_id: str,
        result: Optional[str] = None,
        turn_description: Optional[str] = None,
        **kwargs,
    ) -> Message:
        """创建轮次结束消息"""
        data = {"turn_id": turn_id}
        if result:
            data["result"] = result
        if turn_description:
            data["turn_description"] = turn_description
        return Message(
            message_type=MessageType.TURN_END,
            role=MessageRole.AGENT,
            data=data,
            **kwargs,
        )

    @staticmethod
    def create_command(
        command: str, arguments: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Message:
        """创建命令消息"""
        data = {"command": command}
        if arguments:
            data["arguments"] = arguments
        return Message(
            message_type=MessageType.COMMAND,
            role=MessageRole.SYSTEM,
            data=data,
            **kwargs,
        )

    @staticmethod
    def create_permission_request(
        message: str, request_id: Optional[str] = None, **kwargs
    ) -> Message:
        """创建权限请求消息"""
        data = {"message": message}
        if request_id:
            data["request_id"] = request_id
        return Message(
            message_type=MessageType.PERMISSION_REQUEST,
            role=MessageRole.SYSTEM,
            data=data,
            **kwargs,
        )

    @staticmethod
    def create_permission_response(
        granted: bool, request_id: Optional[str] = None, **kwargs
    ) -> Message:
        """创建权限响应消息"""
        data = {"granted": granted}
        if request_id is not None:
            data["request_id"] = request_id
        return Message(
            message_type=MessageType.PERMISSION_RESPONSE,
            role=MessageRole.SYSTEM,
            data=data,
            **kwargs,
        )

    @staticmethod
    def create_subscribe(subscription: str, **kwargs) -> Message:
        """创建订阅消息"""
        return Message(
            message_type=MessageType.SUBSCRIBE,
            role=MessageRole.SYSTEM,
            subscription=subscription,
            **kwargs,
        )

    @staticmethod
    def create_unsubscribe(subscription: str, **kwargs) -> Message:
        """创建取消订阅消息"""
        return Message(
            message_type=MessageType.UNSUBSCRIBE,
            role=MessageRole.SYSTEM,
            subscription=subscription,
            **kwargs,
        )

    @staticmethod
    def create_agent_system_message(content: str, **kwargs) -> Message:
        """创建Agent系统消息"""
        return Message(
            message_type=MessageType.AGENT_SYSTEM_MESSAGE,
            role=MessageRole.AGENT_SYSTEM,
            data={"content": content},
            **kwargs,
        )

    @staticmethod
    def create_error_message(
        content: str, error_code: str | None = None, **kwargs
    ) -> Message:
        """创建错误消息"""
        return Message(
            message_type=MessageType.ERROR,
            role=MessageRole.AGENT_SYSTEM,
            data={"content": content, "error_code": error_code},
            **kwargs,
        )

    @staticmethod
    def create_broadcast(
        content: str, subscription: Optional[str] = None, **kwargs
    ) -> Message:
        """创建广播消息"""
        return Message(
            message_type=MessageType.BROADCAST,
            role=MessageRole.SYSTEM,
            data={"content": content},
            subscription=subscription,
            **kwargs,
        )

    @staticmethod
    def create_task_start(task_id: str, task_description: str, **kwargs) -> Message:
        """创建任务开始消息"""
        return Message(
            message_type=MessageType.TASK_START,
            role=MessageRole.AGENT,
            data={"task_id": task_id, "task_description": task_description},
            **kwargs,
        )

    @staticmethod
    def create_task_complete(
        task_id: str, result: Optional[str] = None, **kwargs
    ) -> Message:
        """创建任务完成消息"""
        data = {"task_id": task_id}
        if result:
            data["result"] = result
        return Message(
            message_type=MessageType.TASK_COMPLETE,
            role=MessageRole.AGENT,
            data=data,
            **kwargs,
        )

    @staticmethod
    def create_task_error(
        task_id: str, error_message: str, error_code: str | None = None, **kwargs
    ) -> Message:
        """创建任务错误消息"""
        return Message(
            message_type=MessageType.TASK_ERROR,
            role=MessageRole.AGENT,
            data={"task_id": task_id, "error_code": error_code},
            **kwargs,
        )


# ============================================================================
# 调度器相关模型
# ============================================================================


class JobType(str, Enum):
    """任务类型枚举"""

    REMINDER = "reminder"  # 提醒任务
    COMMAND = "command"  # 命令执行任务


class JobStatus(str, Enum):
    """任务状态枚举"""

    ACTIVE = "active"  # 任务活跃
    PAUSED = "paused"  # 任务暂停
    COMPLETED = "completed"  # 任务完成（一次性任务）
    CANCELLED = "cancelled"  # 任务取消


class ScheduledJob(SQLModel, table=True):
    """调度任务模型（简化版）"""

    __tablename__ = "scheduled_job"

    # 基础字段
    job_id: str = Field(primary_key=True, description="任务唯一标识符")
    name: str = Field(description="任务名称")
    job_type: JobType = Field(description="任务类型")
    status: JobStatus = Field(default=JobStatus.ACTIVE, description="任务状态")

    # 触发器配置（保持与现有cron工具兼容）
    trigger_type: str = Field(description="触发器类型：cron, interval, date")
    trigger_config: Dict[str, Any] = Field(
        sa_column=Column(JSON, nullable=False, default={}),
        description="触发器配置（JSON格式）",
    )

    # 执行内容
    content: str = Field(description="执行内容（消息或命令）")

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")
    next_run_time: Optional[datetime] = Field(default=None, description="下次执行时间")

    # 会话关联（可选）
    session_id: Optional[str] = Field(
        foreign_key="session.session_id",
        ondelete="SET NULL",
        default=None,
        description="关联的会话ID",
    )

    # 关联关系
    session: Optional["Session"] = Relationship(back_populates="scheduled_jobs")
    executions: List["JobExecution"] = Relationship(
        back_populates="job", cascade_delete="all"
    )


class JobExecution(SQLModel, table=True):
    """任务执行记录模型（简化版）"""

    __tablename__ = "job_execution"

    execution_id: str = Field(primary_key=True, description="执行记录唯一标识符")
    job_id: str = Field(
        foreign_key="scheduled_job.job_id",
        ondelete="CASCADE",
        description="关联的任务ID",
    )

    executed_at: datetime = Field(default_factory=datetime.now, description="执行时间")
    success: bool = Field(description="是否成功")
    result: Optional[str] = Field(default=None, description="执行结果")

    # 关联关系
    job: ScheduledJob = Relationship(back_populates="executions")
