"""
Session管理模块

提供session管理功能，包括：
- Session管理（创建、加载、关闭）
- 消息历史管理
- Turn管理
- Agent配置管理
- 与现有Agent系统的集成
"""

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
from .service import (
    AgentConfigService,
    AgentService,
    BaseService,
    MessageService,
    SessionService,
    TurnService,
    get_agent_config_service,
    get_agent_service,
    get_message_service,
    get_session_service,
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
    "MessageRole",
    "MessageType",
    "Session",
    "SessionStatus",
    "Turn",
    # Services
    "BaseService",
    "SessionService",
    "TurnService",
    "MessageService",
    "AgentService",
    "AgentConfigService",
    "get_session_service",
    "get_turn_service",
    "get_message_service",
    "get_agent_service",
    "get_agent_config_service",
    # Session Manager
    "SessionManager",
]
