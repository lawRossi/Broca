"""
Session管理器模块

提供Session管理功能，包括session创建、保存、加载、消息历史管理等功能。
与现有Agent系统集成，实现session持久化和重载能力。
"""

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

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

logger.remove()
logger.add("db.log", level="DEBUG")


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
        self._init_future: Optional[asyncio.Future] = None

    async def _ensure_initialized(self) -> None:
        """确保SessionManager已初始化"""
        if self._initialized:
            return
        if self._init_future is None:
            self._init_future = asyncio.get_event_loop().create_future()
            try:
                await self._initialize()
                self._init_future.set_result(None)
            except Exception as e:
                self._init_future.set_exception(e)
                raise
        else:
            await self._init_future

    async def _initialize(self) -> None:
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
        await self._ensure_initialized()

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
        content: str | None,
        message_type: str,
        turn_id: str,
        agent_id: str,
        message_id: str | None = None,
        data: Dict[str, Any] | None = None,
    ) -> Message | None:
        """
        保存消息到数据库

        Args:
            role: 消息角色 (user, assistant, system, tool)
            content: 消息内容
            message_type: 消息类型
            turn_id: 关联的turn ID
            agent_id: 关联的agent ID
            message_id: 可选的消息ID
            data: 额外的数据字段

        Returns:
            保存的消息数据字典
        """

        if not self.session_id:
            raise ValueError("No session ID provided. Call create_session() first.")

        await self._ensure_initialized()

        # 生成消息ID
        message_id = message_id or f"msg_{uuid.uuid4().hex[:16]}"

        # 构建data字段
        message_data = data or {}
        if content:
            message_data["content"] = content

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
                message_type=MessageType(message_type),
                sequence_number=seq_num,
                data=message_data,
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
                await self._ensure_initialized()
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

        await self._ensure_initialized()

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
            await self._ensure_initialized()
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
            await self._ensure_initialized()
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
            await self._ensure_initialized()
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
            await self._ensure_initialized()
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

    async def save_agent(self, agent: "Agent") -> None:
        if not self.session_id:
            raise ValueError("No session ID provided. Call create_session() first.")
        await self._ensure_initialized()
        agent_config = agent.config
        config_content = agent_config.to_json()
        saved_config = await self.agent_config_service.create_config(
            session_id=self.session_id,
            name=agent_config.config_name,
            config_content=config_content,
        )

        await self.agent_service.create_agent(
            agent_id=agent.agent_id,
            config_id=saved_config.config_id,
            session_id=self.session_id,
            name=agent.name,
            role=agent.role,
        )

    async def get_agents(self) -> List[dict]:
        if not self.session_id:
            return []

        try:
            await self._ensure_initialized()
            agents = await self.agent_service.get_agents_by_session(self.session_id)
            return [agent.dict() for agent in agents]

        except Exception as e:
            logger.error(f"Failed to get agents: {e}")
            return []

    async def get_agent_config(self, agent_id: str) -> dict | None:
        if not self.session_id:
            return None

        try:
            await self._ensure_initialized()
            agent = await self.agent_service.get(agent_id)
            if not agent:
                return None

            config = await self.agent_config_service.get(agent.config_id)
            if not config:
                return None

            config_content = config.dict()["config_content"]
            return json.loads(config_content)

        except Exception as e:
            logger.error(f"Failed to get agent config: {e}")
            return None
