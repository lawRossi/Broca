"""
Session管理器模块

提供Session管理功能，包括session创建、保存、加载、消息历史管理等功能。
与现有Agent系统集成，实现session持久化和重载能力。
"""

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from .models import Message, MessageRole, MessageType
from .service import (
    AgentConfigService,
    AgentService,
    MessageService,
    SessionService,
    TurnService,
    get_agent_config_service,
    get_agent_service,
    get_message_service,
    get_session_service,
    get_turn_service,
)

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Session管理器

    负责session的创建、保存、加载和管理，与现有Agent系统集成，
    实现session持久化和重载能力。
    """

    def __init__(self):
        """初始化SessionManager"""
        self.session_id: str | None = None
        self._services: Dict[str, Any] = {}
        self._initialized = False
        asyncio.create_task(self.initialize())

    async def initialize(self) -> None:
        """初始化所有service实例"""
        if self._initialized:
            return

        try:
            self._services["session"] = get_session_service()
            self._services["message"] = get_message_service()
            self._services["turn"] = get_turn_service()
            self._services["agent"] = get_agent_service()
            self._services["agent_config"] = get_agent_config_service()

            self._initialized = True
            logger.info("SessionManager initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize SessionManager: {e}")
            raise

    @property
    def session_service(self) -> SessionService:
        """获取SessionService实例"""
        return self._services["session"]

    @property
    def message_service(self) -> MessageService:
        """获取MessageService实例"""
        return self._services["message"]

    @property
    def turn_service(self) -> TurnService:
        """获取TurnService实例"""
        return self._services["turn"]

    @property
    def agent_service(self) -> AgentService:
        """获取AgentService实例"""
        return self._services["agent"]

    @property
    def agent_config_service(self) -> AgentConfigService:
        """获取AgentConfigService实例"""
        return self._services["agent_config"]

    async def create_session(self, description: str | None = None) -> str:
        """
        创建新session

        Args:
            description: 可选的session描述

        Returns:
            新创建的session ID
        """

        session_id = f"session_{uuid.uuid4().hex[:16]}"

        try:
            session = await self.session_service.create_session(
                session_id=session_id,
                description=description,
            )

            self.session_id = session.session_id
            logger.info(f"Created new session: {session_id}")

            return session_id

        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            raise

    async def save_message(
        self,
        role: str,
        content: str,
        message_type: str,
        turn_id: str,
        agent_id: str,
        message_id: str | None = None,
        reasoning_content: str | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        tool_arguments: str | None = None,
        tool_result: str | None = None,
    ) -> Message | None:
        """
        保存消息到数据库

        Args:
            role: 消息角色 (user, assistant, system, tool)
            content: 消息内容
            message_type: 消息类型
            turn_id: 关联的turn ID
            agent_id: 关联的agent ID
            metadata: 额外元数据

        Returns:
            保存的消息数据字典
        """

        if not self.session_id:
            raise ValueError("No session ID provided. Call create_session() first.")

        # 生成消息ID
        message_id = message_id or f"msg_{uuid.uuid4().hex[:16]}"
        if isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)

        try:
            # 获取下一个序列号
            seq_num = await self.message_service.get_next_sequence_number(
                self.session_id
            )

            message = await self.message_service.create_message(
                message_id=message_id,
                session_id=self.session_id,
                turn_id=turn_id,
                agent_id=agent_id,
                role=MessageRole(role),
                content=content,
                message_type=MessageType(message_type),
                reasoning_content=reasoning_content,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_arguments=tool_arguments,
                tool_result=tool_result,
                sequence_number=seq_num,
            )

            return message

        except Exception as e:
            logger.error(f"Failed to save message: {e}")
            return None

    async def get_messages(
        self,
        agent_id: str | None = None,
    ) -> List[Message]:
        """
        获取session中的消息历史

        Args:
            agent_id: 可选的agent ID

        Returns:
            消息数据字典列表
        """
        try:
            if not agent_id:
                if not self.session_id:
                    raise ValueError(
                        "No session ID provided. Call create_session() first."
                    )
                messages = await self.message_service.get_messages_by_session(
                    self.session_id
                )
            else:
                messages = await self.message_service.get_messages_by_agent(agent_id)

            return messages
        except Exception as e:
            logger.error(f"Failed to get messages: {e}")
            return []

    async def start_turn(
        self,
        agent_id: str,
        description: str | None = None,
    ) -> str:
        """
        开始新的对话轮次

        Args:
            agent_id: 关联的agent ID
            description: 可选的turn描述

        Returns:
            新创建的turn ID
        """

        if not self.session_id:
            raise ValueError("No session ID provided. Call create_session() first.")

        # 生成turn ID
        turn_id = f"turn_{uuid.uuid4().hex[:16]}"

        try:
            # 获取下一个序列号
            seq_num = await self.turn_service.get_next_sequence_number(self.session_id)

            # 创建turn
            await self.turn_service.create_turn(
                turn_id=turn_id,
                session_id=self.session_id,
                agent_id=agent_id,
                sequence_number=seq_num,
                turn_description=description,
            )

            await self.save_message(
                role=MessageRole.AGENT,
                content="",
                message_type=MessageType.TURN_START,
                turn_id=turn_id,
                agent_id=agent_id,
            )

            logger.info(f"Started new turn: {turn_id}")

            return turn_id

        except Exception as e:
            logger.error(f"Failed to start turn: {e}")
            raise

    async def end_turn(self, turn_id: str, agent_id: str) -> bool:
        """
        结束指定的turn

        Args:
            turn_id: 要结束的turn ID

        Returns:
            是否成功结束
        """
        if not turn_id:
            logger.warning("No turn ID provided for ending")
            return False

        try:
            await self.save_message(
                role=MessageRole.SYSTEM,
                content="",
                message_type=MessageType.TURN_END,
                turn_id=turn_id,
                agent_id=agent_id,
            )
            logger.info(f"Ended turn: {turn_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to end turn: {e}")
            return False

    async def load_session(self, session_id: str) -> bool:
        """
        加载指定的session

        Args:
            session_id: 要加载的session ID

        Returns:
            是否加载成功
        """
        if not session_id:
            logger.warning("No session ID provided for loading")
            return False

        try:
            # 检查session是否存在
            session = await self.session_service.get(session_id)
            if not session:
                logger.warning(f"Session not found: {session_id}")
                return False

            self.session_id = session_id

            logger.info(f"Loaded session: {session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to load session: {e}")
            return False

    async def close_session(self) -> bool:
        """
        关闭当前session

        Returns:
            是否成功关闭
        """

        if not self.session_id:
            return False

        try:
            # 更新session状态
            await self.session_service.close_session(self.session_id)

            logger.info(f"Session closed: {self.session_id}")
            self.session_id = None

            return True

        except Exception as e:
            logger.error(f"Failed to close session: {e}")
            return False

    async def get_session_info(self) -> Optional[Dict[str, Any]]:
        """
        获取当前session信息

        Returns:
            session信息字典
        """

        if not self.session_id:
            return None

        try:
            session = await self.session_service.get(self.session_id)
            if not session:
                return None

            return {
                "session_id": session.session_id,
                "status": session.status.value,
                "description": session.description,
                "created_at": session.created_at.isoformat(),
                "finished_at": session.finished_at.isoformat()
                if session.finished_at
                else None,
            }

        except Exception as e:
            logger.error(f"Failed to get session info: {e}")
            return None
