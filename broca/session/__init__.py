"""
Session管理模块

提供session管理功能，包括：
- Session管理（创建、加载、关闭）
- 消息历史管理
- Turn管理
- Agent配置管理
- 与现有Agent系统的集成
- 数据库迁移管理（Alembic集成）
"""

from .db_migration import (
    DatabaseMigrationManager,
    handle_migration_command,
    migration_manager,
)
from .models import (
    Agent,
    AgentConfig,
    Message,
    MessageProtocol,
    MessageRole,
    MessageType,
    Session,
    Task,
    TaskComment,
    TaskPriority,
    TaskStatus,
    Turn,
    generate_message_id,
)
from .service import (
    AgentConfigService,
    AgentService,
    BaseService,
    MessageService,
    SessionService,
    TaskCommentService,
    TaskService,
    TurnService,
    get_agent_config_service,
    get_agent_service,
    get_message_service,
    get_session_service,
    get_task_comment_service,
    get_task_service,
    get_turn_service,
)
from .session_manager import (
    SessionManager,
)

__all__ = [
    # Models
    "Agent",
    "AgentConfig",
    "Message",
    "MessageProtocol",
    "MessageRole",
    "MessageType",
    "Session",
    "Task",
    "TaskComment",
    "TaskPriority",
    "TaskStatus",
    "Turn",
    "generate_message_id",
    # Services
    "BaseService",
    "SessionService",
    "TurnService",
    "MessageService",
    "AgentService",
    "AgentConfigService",
    "TaskService",
    "TaskCommentService",
    "get_session_service",
    "get_turn_service",
    "get_message_service",
    "get_agent_service",
    "get_agent_config_service",
    "get_task_service",
    "get_task_comment_service",
    # Session Manager
    "SessionManager",
    # Database Migration
    "DatabaseMigrationManager",
    "migration_manager",
    "handle_migration_command",
]
