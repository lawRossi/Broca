"""
Agent Communicator Module

This module integrates Socket.io communication with the Agent system,
replacing command-line interaction with multi-endpoint communication.
"""

import asyncio
import logging
from typing import Optional

from .socketio_client import SocketIOClient
from .message_types import MessageProtocol

logger = logging.getLogger(__name__)


class AgentCommunicator(SocketIOClient):
    """
    Agent Communicator - Integrates Socket.io with Agent system

    This class provides a communication interface for agents,
    replacing command-line interaction with Socket.io-based communication.
    """

    def __init__(self, agent_id: str, server_url: str = "http://localhost:8000",
                 client_type: str = "agent"):
        """
        Initialize Agent Communicator

        Args:
            agent_id: Unique identifier for the agent
            server_url: Socket.io server URL
            client_type: Client type (agent, cli, browser, etc.)
        """
        self.agent_id = agent_id

        # Initialize parent SocketIOClient
        super().__init__(
            server_url=server_url,
            client_type=client_type,
            client_id=agent_id,
            auto_reconnect=True
        )

        # Message queue for synchronous interaction
        self.message_queue: asyncio.Queue = asyncio.Queue()

        # Setup event handlers
        self._setup_event_handlers()

        logger.info(f"AgentCommunicator initialized for agent {agent_id}")

    async def send_task_start(self, task_id: str, task_description: str,
                             receiver_id: Optional[str] = None,
                             room: Optional[str] = None,
                             subscription: Optional[str] = None) -> str:
        """Send task start message"""
        message = MessageProtocol.create_task_start(
            task_id=task_id,
            task_description=task_description,
            sender_id=self.client_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription
        )
        return await self.send_message(message)

    async def send_task_complete(self, task_id: str, result: Optional[str] = None,
                                 receiver_id: Optional[str] = None,
                                 room: Optional[str] = None,
                                 subscription: Optional[str] = None) -> str:
        """Send task complete message"""
        message = MessageProtocol.create_task_complete(
            task_id=task_id,
            result=result,
            sender_id=self.client_id,
            receiver_id=receiver_id,
            room=room,
            subscription=subscription
        )
        return await self.send_message(message)

    async def send_to_user(self, user_id: str, content: str):
        """Send message to specific user"""
        await self.send_user_message(
            content=content,
            receiver_id=user_id
        )

    async def send_to_room(self, room: str, content: str):
        """Send message to room"""
        await self.send_user_message(
            content=content,
            room=room
        )

    async def send_to_subscription(self, subscription: str, content: str):
        """Send message to subscription"""
        await self.send_user_message(
            content=content,
            subscription=subscription
        )
