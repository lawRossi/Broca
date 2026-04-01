"""
Agent Communicator Module

This module integrates Socket.io communication with the Agent system,
replacing command-line interaction with multi-endpoint communication.
"""

import asyncio
from typing import Optional

from loguru import logger

from broca.session.models import Message, MessageProtocol, MessageRole, MessageType

from .socketio_client import SocketIOClient


class AgentCommunicator(SocketIOClient):
    """
    Agent Communicator - Integrates Socket.io with Agent system

    This class provides a communication interface for agents,
    replacing command-line interaction with Socket.io-based communication.
    """

    def __init__(
        self,
        agent_id: str,
        server_url: str = "http://localhost:6868",
        client_type: str = "agent",
    ):
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
            auto_reconnect=True,
        )

        # Message queue for synchronous interaction
        self.message_queue: asyncio.Queue = asyncio.Queue()

        # Setup event handlers
        self._setup_event_handlers()

        logger.info(f"AgentCommunicator initialized for agent {agent_id}")

    # async def send_to_user(self, user_id: str, content: str):
    #     """Send message to specific user"""
    #     await self.send_user_message(content=content, receiver_id=user_id)

    # async def send_to_room(self, room: str, content: str):
    #     """Send message to room"""
    #     await self.send_user_message(content=content, room=room)

    # async def send_to_subscription(self, subscription: str, content: str):
    #     """Send message to subscription"""
    #     await self.send_user_message(content=content, subscription=subscription)
