"""
数据模型定义模块（优化版本）

定义Session、Message、History等数据模型，使用sqlmodel框架。
优化了消息模型，统一了字段结构。
"""

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict
from sqlalchemy import JSON, Column, Integer, String
from sqlalchemy import ForeignKey as SA_ForeignKey
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

    USER_MESSAGE = "user_message"
    AGENT_RESPONSE = "agent_response"
    AGENT_ERROR = "agent_error"
    SYSTEM_MESSAGE = "system_message"

    AGENT_QUERY = "agent_query"
    USER_ANSWER = "user_answer"

    # 工具执行（合并tool_call和tool_result）
    TOOL_CALL = "tool_call"

    # 任务管理
    TASK_START = "task_start"
    TASK_COMPLETE = "task_complete"
    TASK_ERROR = "task_error"

    # 轮次管理
    TURN_START = "turn_start"
    TURN_END = "turn_end"

    # Step管理（用于undo/redo）
    STEP_START = "step_start"
    STEP_END = "step_end"

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


class SessionCategory(str, Enum):
    """会话分类枚举"""

    NORMAL = "normal"                # 普通会话：创建内置 Agent
    AGENT_ORCHESTRATION = "agent-orchestration"  # Agent 编排会话：不创建内置 Agent，只加载自定义 Agent


class Session(SQLModel, table=True):
    """
    会话模型

    存储会话的基本信息，包括会话ID、状态、创建时间等。
    """

    __tablename__ = "session"

    session_id: str = Field(index=True, primary_key=True, description="会话唯一标识符")
    description: Optional[str] = Field(default=None, description="会话描述")
    workspace: Optional[str] = Field(default=None, description="工作空间路径")
    category: str = Field(
        default=SessionCategory.NORMAL,
        sa_column=Column(String, server_default="normal", nullable=False),
        description="会话分类：normal（普通）/ agent-orchestration（Agent 编排）",
    )

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
    tasks: List["Task"] = Relationship(back_populates="session", cascade_delete="all")
    crew_executions: List["CrewExecution"] = Relationship(
        back_populates="session", cascade_delete="all"
    )


# ============================================================================
# Session Runner 相关模型
# ============================================================================


class SessionRunner(SQLModel, table=True):
    """
    Runner 进程记录模型

    存储 Session Runner 子进程的持久化信息，用于 Web 重启后恢复。
    """

    __tablename__ = "session_runner"

    runner_id: str = Field(primary_key=True, description="Runner 唯一标识符")
    session_id: str = Field(
        foreign_key="session.session_id",
        sa_column_kwargs={"unique": True},
        ondelete="CASCADE",
        description="关联的 Session ID",
    )
    pid: Optional[int] = Field(default=None, description="进程 ID")
    status: str = Field(
        default="starting", description="进程状态：starting/alive/error/dead"
    )
    ipc_address: Optional[str] = Field(default=None, description="IPC 地址")
    ipc_family: Optional[str] = Field(default=None, description="IPC 协议族")
    started_at: Optional[datetime] = Field(default=None, description="启动时间")
    last_heartbeat: Optional[datetime] = Field(default=None, description="最后心跳时间")
    restart_count: int = Field(
        default=0,
        sa_column=Column(Integer, server_default="0", nullable=False),
        description="重启次数",
    )
    resource_info: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="资源使用信息（JSON）",
    )
    error_message: Optional[str] = Field(default=None, description="错误信息")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")


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
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="消息时间戳"
    )

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

    # 撤销状态（用于undo/redo）
    reverted: bool = Field(
        default=False,
        sa_column=Column(Integer, server_default="0", nullable=False),
        description="是否已回滚",
    )

    # 压缩状态（策略A：工具结果已过期）
    is_expired: bool = Field(
        default=False,
        sa_column=Column(Integer, server_default="0", nullable=False),
        description="工具调用结果是否已过期（策略A）",
    )

    # 压缩状态（策略B：被 session memory 截断）
    is_truncated: bool = Field(
        default=False,
        sa_column=Column(Integer, server_default="0", nullable=False),
        description="消息是否已被 session memory 截断（策略B）",
    )

    # 关联关系
    session: Optional["Session"] = Relationship(back_populates="messages")
    turn: Optional["Turn"] = Relationship(back_populates="messages")
    agent: Optional["Agent"] = Relationship(back_populates="messages")

    # Pydantic v2 配置：确保 datetime 序列化为带时区的 ISO 格式
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: (
                v.astimezone(timezone.utc).isoformat()
                if v.tzinfo is not None
                else v.isoformat() + "+00:00"
            )
        }
    )


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

    # LLM使用统计
    total_input_tokens: int = Field(
        default=0,
        sa_column=Column(Integer, server_default="0", nullable=False),
        description="累计输入token数",
    )
    total_output_tokens: int = Field(
        default=0,
        sa_column=Column(Integer, server_default="0", nullable=False),
        description="累计输出token数",
    )
    total_llm_calls: int = Field(
        default=0,
        sa_column=Column(Integer, server_default="0", nullable=False),
        description="LLM调用次数",
    )
    last_context_length: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
        description="最后一次调用的上下文长度",
    )

    # Agent 运行状态（由 Runner 进程通过心跳同步）
    agent_status: str = Field(
        default="disconnected",
        sa_column=Column(String, server_default="disconnected", nullable=False),
        description="Agent 运行状态：idle/running/disconnected",
    )

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")

    # 关联关系
    agent_config: AgentConfig = Relationship(back_populates="agents")
    session: Session = Relationship(back_populates="agents")
    turns: List["Turn"] = Relationship(back_populates="agent")
    messages: List["Message"] = Relationship(
        back_populates="agent", cascade_delete="all"
    )
    scheduled_jobs: List["ScheduledJob"] = Relationship(
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
        content: str | None, reasoning_content: str | None, index: int = 0, **kwargs
    ) -> Message:
        """创建Agent响应"""
        data = kwargs.pop("data", {})
        data["content"] = json.dumps(
            {
                "content": content,
                "reasoning_content": reasoning_content,
                "index": index,
            },
            ensure_ascii=False,
        )

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
            data={
                "task_id": task_id,
                "task_description": task_description,
                "assigner": kwargs.get("sender_id"),
            },
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

    @staticmethod
    def create_step_start(step_id: str, snapshot_hash: str, **kwargs) -> Message:
        """创建Step开始消息（用于undo/redo）"""
        return Message(
            message_type=MessageType.STEP_START,
            role=MessageRole.AGENT,
            data={
                "step_id": step_id,
                "snapshot_hash": snapshot_hash,
            },
            **kwargs,
        )

    @staticmethod
    def create_step_end(
        step_id: str,
        snapshot_hash: str,
        patch: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Message:
        """创建Step结束消息（用于undo/redo）"""
        data = {
            "step_id": step_id,
            "snapshot_hash": snapshot_hash,
        }
        if patch:
            data["patch"] = patch
        return Message(
            message_type=MessageType.STEP_END,
            role=MessageRole.AGENT,
            data=data,
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

    # 关联字段（可选）
    session_id: Optional[str] = Field(
        foreign_key="session.session_id",
        ondelete="SET NULL",
        default=None,
        description="关联的会话ID",
    )
    agent_id: Optional[str] = Field(
        foreign_key="agent.agent_id",
        ondelete="SET NULL",
        default=None,
        description="关联的Agent ID（用于指定执行任务的Agent）",
    )

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")
    next_run_time: Optional[datetime] = Field(default=None, description="下次执行时间")

    # 关联关系
    session: Optional["Session"] = Relationship(back_populates="scheduled_jobs")
    agent: Optional["Agent"] = Relationship(back_populates="scheduled_jobs")
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


# ============================================================================
# Task 管理相关模型
# ============================================================================


class TaskStatus(str, Enum):
    """任务状态枚举"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class TaskPriority(str, Enum):
    """任务优先级枚举"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def generate_task_id() -> str:
    """生成任务ID"""
    return "task-" + str(uuid.uuid4())


def generate_comment_id() -> str:
    """生成评论ID"""
    return "comment-" + str(uuid.uuid4())


class TaskComment(SQLModel, table=True):
    """任务评论模型"""

    __tablename__ = "task_comment"

    comment_id: str = Field(
        primary_key=True,
        description="评论唯一标识符",
        default_factory=generate_comment_id,
    )
    task_id: str = Field(
        foreign_key="task.task_id", ondelete="CASCADE", description="关联的任务ID"
    )
    author: str = Field(description="评论作者")
    content: str = Field(description="评论内容")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")

    # 关联关系
    task: "Task" = Relationship(back_populates="comments")


class Task(SQLModel, table=True):
    """
    任务模型

    存储任务的基本信息，包括任务名称、描述、状态、优先级等。
    对应原有的 Task 和 TaskMetadata 的组合。
    """

    __tablename__ = "task"

    task_id: str = Field(
        index=True,
        primary_key=True,
        description="任务唯一标识符",
        default_factory=generate_task_id,
    )
    name: str = Field(description="任务名称")
    description: str = Field(description="任务描述")

    # 会话关联
    session_id: Optional[str] = Field(
        foreign_key="session.session_id",
        ondelete="CASCADE",
        default=None,
        description="关联的会话ID",
    )

    # 从 TaskMetadata 扁平化过来的字段
    parent_id: Optional[str] = Field(
        foreign_key="task.task_id",
        ondelete="SET NULL",
        default=None,
        description="父任务ID",
    )
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="任务状态")
    priority: TaskPriority = Field(
        default=TaskPriority.MEDIUM, description="任务优先级"
    )
    assignee: Optional[str] = Field(default=None, description="任务分配对象")

    # 可选字段
    details: Optional[str] = Field(default=None, description="详细描述")
    acceptance_criteria: Optional[List[str]] = Field(
        sa_column=Column(JSON, nullable=True, default=None), description="验收标准列表"
    )
    context_files: Optional[List[str]] = Field(
        sa_column=Column(JSON, nullable=True, default=None), description="关联文件列表"
    )
    context_links: Optional[List[str]] = Field(
        sa_column=Column(JSON, nullable=True, default=None), description="关联链接列表"
    )
    context_notes: Optional[str] = Field(default=None, description="上下文笔记")
    report: Optional[str] = Field(default=None, description="任务报告")

    # 依赖关系（JSON 数组存储）
    dependencies: Optional[List[str]] = Field(
        sa_column=Column(JSON, nullable=True, default=None),
        description="依赖任务ID列表",
    )

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

    # 关联关系
    session: Optional["Session"] = Relationship(back_populates="tasks")
    parent: Optional["Task"] = Relationship(
        back_populates="children",
        sa_relationship_kwargs={"remote_side": "Task.task_id"},
    )
    children: List["Task"] = Relationship(back_populates="parent", cascade_delete="all")
    comments: List[TaskComment] = Relationship(
        back_populates="task", cascade_delete="all"
    )

    def update_timestamp(self):
        """更新更新时间戳"""
        self.updated_at = datetime.now()


# ============================================================================
# 编排执行相关模型
# ============================================================================


class CrewExecutionStatus(str, Enum):
    """编排执行状态枚举"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class CrewExecution(SQLModel, table=True):
    """
    编排执行记录模型

    存储编排（Crew）的完整执行信息，支持断点恢复和状态查询。
    """

    __tablename__ = "crew_execution"

    execution_id: str = Field(
        index=True, primary_key=True, description="执行唯一标识符"
    )
    session_id: str = Field(
        foreign_key="session.session_id",
        ondelete="CASCADE",
        description="关联的会话ID",
    )
    crew_name: str = Field(description="Crew 名称")
    orchestrator_type: str = Field(description="编排器类型（pipeline/supervisor-worker/等）")
    yaml_content: str = Field(
        sa_column=Column(String, nullable=False),
        description="Crew 配置的 YAML/JSON 内容",
    )
    status: CrewExecutionStatus = Field(
        default=CrewExecutionStatus.PENDING,
        description="执行状态",
    )
    error_message: Optional[str] = Field(
        default=None,
        sa_column=Column(String, nullable=True),
        description="错误信息",
    )
    result_json: Optional[str] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="执行结果（JSON）",
    )
    phases_json: Optional[str] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="阶段执行记录（JSON）",
    )
    started_at: datetime = Field(
        default_factory=datetime.now, description="开始时间"
    )
    completed_at: Optional[datetime] = Field(
        default=None, description="完成时间"
    )

    # 关联关系
    session: Optional["Session"] = Relationship(back_populates="crew_executions")
    blackboard_entries: List["BlackboardEntry"] = Relationship(
        back_populates="crew_execution", cascade_delete="all"
    )


class BlackboardEntry(SQLModel, table=True):
    """
    黑板条目持久化模型

    存储编排执行期间黑板的状态变更记录。
    """

    __tablename__ = "blackboard_entry"

    entry_id: str = Field(
        index=True, primary_key=True, description="条目唯一标识符",
        default_factory=lambda: "bb-" + uuid.uuid4().hex[:16],
    )
    execution_id: str = Field(
        foreign_key="crew_execution.execution_id",
        ondelete="CASCADE",
        description="关联的执行ID",
    )
    key: str = Field(description="黑板键名")
    value_json: Optional[str] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="黑板值（JSON）",
    )
    version: int = Field(default=0, description="版本号")
    producer: str = Field(default="system", description="写入者")
    event_type: str = Field(
        default="created", description="事件类型：created/updated/deleted"
    )
    created_at: datetime = Field(
        default_factory=datetime.now, description="创建时间"
    )

    # 关联关系
    crew_execution: CrewExecution = Relationship(back_populates="blackboard_entries")
