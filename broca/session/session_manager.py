"""
Session管理器模块

提供Session管理功能，包括session创建、保存、加载、消息历史管理等功能。
与现有Agent系统集成，实现session持久化和重载能力。
"""

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional

from litellm import Message as LLMMessage

from broca.logging_config import get_logger
from broca.session.models import Message, MessageRole, MessageType
from broca.session.service import (
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
from broca.tools.tool import ToolResult

logger = get_logger(__name__)


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
        # 编排执行 ID（由 CrewOrchestratorRunner 设置，消息保存时自动注入）
        self.current_execution_id: Optional[str] = None

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

    async def create_session(
        self, description: str | None = None, workspace: str | None = None
    ) -> str:
        """
        创建新session

        Args:
            description: 可选的session描述
            workspace: 可选的工作空间路径

        Returns:
            新创建的session ID
        """
        await self._ensure_initialized()

        session_id = f"session_{uuid.uuid4().hex[:16]}"

        try:
            session = await self.session_service.create_session(
                session_id=session_id,
                description=description,
                workspace=workspace,
            )

            self.session_id = session.session_id
            logger.info(f"Created new session: {session_id}, workspace: {workspace}")

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
    ) -> bool:
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
            return False

        try:
            await self._ensure_initialized()

            message_id = message_id or f"msg_{uuid.uuid4().hex[:16]}"
            message_data = data or {}

            if content:
                message_data["content"] = content

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
                # 编排执行 ID：仅编排运行时设置，普通会话为 None
                execution_id=self.current_execution_id,
            )

            return message is not None

        except Exception as e:
            logger.error(f"Failed to save message: {e}")
            return False

    async def get_messages(
        self, agent_id: str | None = None, ignore_reverted: bool = True
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
                    self.session_id, ignore_reverted=ignore_reverted
                )
            else:
                await self._ensure_initialized()
                messages = await self.message_service.get_messages_by_agent(
                    agent_id, ignore_reverted=ignore_reverted
                )

            return messages
        except Exception as e:
            logger.error(f"Failed to get messages: {e}")
            return []

    async def start_turn(
        self,
        agent_id: str,
        description: str | None = None,
    ) -> str | None:
        """
        开始新的对话轮次

        Args:
            agent_id: 关联的agent ID
            description: 可选的turn描述

        Returns:
            新创建的turn ID
        """

        if not self.session_id:
            return None

        try:
            await self._ensure_initialized()
            turn_id = f"turn_{uuid.uuid4().hex[:16]}"
            seq_num = await self.turn_service.get_next_sequence_number(self.session_id)

            turn = await self.turn_service.create_turn(
                turn_id=turn_id,
                session_id=self.session_id,
                agent_id=agent_id,
                sequence_number=seq_num,
                turn_description=description,
            )
            if not turn:
                return None

            if not await self.save_message(
                role=MessageRole.AGENT,
                content="",
                message_type=MessageType.TURN_START,
                turn_id=turn_id,
                agent_id=agent_id,
            ):
                return None

            logger.info(f"Started new turn: {turn_id}")

            return turn_id

        except Exception as e:
            logger.error(f"Failed to start turn: {e}")
            return None

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
            logger.info(f"Ended turn: {turn_id}")
            return await self.save_message(
                role=MessageRole.SYSTEM,
                content="",
                message_type=MessageType.TURN_END,
                turn_id=turn_id,
                agent_id=agent_id,
            )
        except Exception as e:
            logger.error(f"Failed to end turn: {e}")
            return False

    async def get_session(self, session_id: str):
        """
        获取会话

        Args:
            session_id: 会话ID

        Returns:
            会话对象或None
        """
        try:
            await self._ensure_initialized()
            return await self.session_service.get(session_id)
        except Exception as e:
            logger.error(f"Failed to get session: {e}")
            return None

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
                "description": session.description,
                "workspace": session.workspace,
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

    async def save_agent_response(
        self,
        response: LLMMessage,
        turn_id: str | None,
        agent_id: str | None,
        step_id: str | None,
        message_id: str | None,
    ) -> bool:
        if not turn_id or not agent_id:
            return False

        msg_content = json.dumps(response.json(), ensure_ascii=False)
        data = {"step_id": step_id}
        return await self.save_message(
            role=MessageRole.ASSISTANT,
            content=msg_content,
            message_type=MessageType.AGENT_RESPONSE,
            turn_id=turn_id,
            agent_id=agent_id,
            data=data,
            message_id=message_id,
        )

    async def save_turn_end(
        self, turn_id: str | None, agent_id: str | None, message: str | None
    ) -> bool:
        if not turn_id or not agent_id:
            return False

        return await self.save_message(
            role=MessageRole.SYSTEM,
            content=message,
            message_type=MessageType.TURN_END,
            turn_id=turn_id,
            agent_id=agent_id,
        )

    async def save_tool_call(
        self,
        turn_id: str | None,
        agent_id: str | None,
        tool_call: Any,
        tool_result: ToolResult,
        step_id: str | None,
        message_id: str | None,
    ) -> bool:
        if not turn_id or not agent_id:
            return False

        tool_call_result = {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": tool_result.content,
        }

        # 构建data字典
        data = {
            "content": json.dumps(tool_call_result, ensure_ascii=False),
            "tool_name": tool_call.function.name,
            "arguments": tool_call.function.arguments,
            "result": tool_result.content,
            "status": tool_result.status,
            "step_id": step_id,
        }

        # 添加step_id（如果存在）
        if hasattr(tool_result, "data") and tool_result.data:
            step_id = tool_result.data.get("step_id")
            if step_id:
                data["step_id"] = step_id

        return await self.save_message(
            role=MessageRole.TOOL,
            content=None,
            message_type=MessageType.TOOL_CALL,
            turn_id=turn_id,
            agent_id=agent_id,
            data=data,
            message_id=message_id,
        )

    async def batch_update_messages(self, message_ids, **kwargs) -> bool:
        service = self.message_service
        return await service.update_batch(message_ids, **kwargs) == len(message_ids)

    async def batch_update_turns(self, turn_ids, **kwargs) -> bool:
        """批量更新 turn 状态"""
        service = self.turn_service
        return await service.update_batch(turn_ids, **kwargs) == len(turn_ids)

    async def mark_messages_as_truncated(
        self, agent_id: str, pivot_message_id: str
    ) -> int:
        messages = await self.get_messages(agent_id=agent_id)
        message_ids_to_mark = []
        turn_id = None
        for message in messages:
            if message.message_id == pivot_message_id:
                turn_id = message.turn_id
            if turn_id is None:
                message_ids_to_mark.append(message.message_id)
            else:
                if message.turn_id == turn_id:
                    message_ids_to_mark.append(message.message_id)
                else:
                    break

        count = await self.message_service.update_batch(message_ids_to_mark, is_truncated=True)
        return count
