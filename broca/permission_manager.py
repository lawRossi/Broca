"""
Permission Manager Module

This module handles permission requests and responses for agents, including:
- Permission request management (general + tool-specific)
- Permission response handling
- Session-level permission decisions (for tool permission system)
- Permission timeout management
- Permission logging and persistence
"""

import asyncio
import uuid
from typing import Any, Dict, Optional, Tuple

from broca.logging_config import get_logger
from broca.session import Message, MessageRole, MessageType, SessionManager

logger = get_logger(__name__)


class PermissionManager:
    """
    Permission Manager for agent operations

    Handles permission requests and responses, separated from agent.py
    to reduce complexity and improve modularity.

    Two types of permission requests:
    - General (request_permission): For existing flows (e.g. dangerous code check).
      Returns bool. Uses request_type="general".
    - Tool (request_tool_permission): For the new tool permission system.
      Returns (bool, session_action). Uses request_type="tool".
    """

    def __init__(
        self,
        communicator: Any,
        session_manager: SessionManager,
    ):
        """
        Initialize the permission manager

        Args:
            communicator: Communication interface for sending messages
            session_manager: Session manager for persistence
        """
        self.communicator = communicator
        self.session_manager = session_manager

        # Permission request tracking
        self._permission_requests: Dict[str, Dict] = {}
        self._permission_lock = asyncio.Lock()

        # State variables
        self.turn_id: Optional[str] = None
        self.agent_id: Optional[str] = None
        self.session_id: Optional[str] = None

    def set_state(
        self,
        turn_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        """
        Set permission manager state variables

        Args:
            turn_id: Current turn ID
            agent_id: Agent ID
            session_id: Session ID
        """
        self.turn_id = turn_id
        self.agent_id = agent_id
        self.session_id = session_id

    async def request_permission(self, message: str) -> bool:
        """
        Ask for user permission via communication channel (general flow).

        Used by existing flows like dangerous code checks in execute_code.
        Frontend shows Allow/Deny buttons (request_type="general").

        Args:
            message: Permission request message

        Returns:
            True if permission is granted, False otherwise
        """
        granted, _ = await self._request_permission_impl(
            message=message, request_type="general"
        )
        return granted

    async def request_tool_permission(self, message: str) -> Tuple[bool, Optional[str]]:
        """
        Ask for user permission for tool execution (tool permission flow).

        Used by the new tool permission system when a tool is configured as "ask".
        Frontend shows 4 options: Allow Once / Session Allow / Deny Once / Session Deny.
        Supports session-level decisions.

        Args:
            message: Permission request message

        Returns:
            Tuple of (granted: bool, session_action: Optional[str])
            - granted: True if permission is granted, False otherwise
            - session_action: None (once only), "allow" (session allow), "forbid" (session forbid)
        """
        return await self._request_permission_impl(
            message=message, request_type="tool"
        )

    async def _request_permission_impl(
        self, message: str, request_type: str = "general"
    ) -> Tuple[bool, Optional[str]]:
        """
        Internal implementation for permission requests.

        Args:
            message: Permission request message
            request_type: "general" (existing flow) or "tool" (tool permission system)

        Returns:
            Tuple of (granted: bool, session_action: Optional[str])
        """
        # Generate unique request ID
        request_id = str(uuid.uuid4())

        # Create event for waiting for response
        response_event = asyncio.Event()

        # Register the permission request
        async with self._permission_lock:
            self._permission_requests[request_id] = {
                "event": response_event,
                "granted": None,
                "session_action": None,
            }

        try:
            # Send permission request with request_type
            await self.communicator.send_permission_request(
                message=message,
                request_id=request_id,
                request_type=request_type,
                subscription=self.session_id,
            )

            # Log permission request to database
            await self._log_permission_request(message, request_id, request_type)

            # Wait for response with timeout
            try:
                await asyncio.wait_for(response_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                logger.warning(f"Permission request {request_id} timed out")
                await self._log_permission_timeout(request_id)
                return False, None

            # Get the response result
            async with self._permission_lock:
                request_data = self._permission_requests.get(request_id, {})
                granted = request_data.get("granted", False) or False
                session_action = request_data.get("session_action")
                await self._log_permission_response(
                    request_id, granted, session_action
                )
                return granted, session_action

        except Exception as e:
            logger.error(f"Failed to send permission request: {e}")
            await self._log_permission_error(e)
            return False, None
        finally:
            # Clean up the request
            await self._cleanup_permission_request(request_id)

    async def handle_permission_response(self, message: Message):
        """
        Handle permission response from communication channel

        Args:
            message: Permission response message
        """
        granted = message.data.get("granted", False)
        request_id = message.data.get("request_id")
        session_action = message.data.get("session_action")

        # Find the matching permission request
        async with self._permission_lock:
            if request_id and request_id in self._permission_requests:
                request_data = self._permission_requests[request_id]
                request_data["granted"] = granted
                if session_action is not None:
                    request_data["session_action"] = session_action
                request_data["event"].set()

                logger.info(
                    f"Permission request {request_id}: "
                    f"{'granted' if granted else 'denied'}"
                    f"{', session_action=' + str(session_action) if session_action else ''}"
                )
            else:
                logger.warning(
                    f"Received permission response for unknown request_id: {request_id}"
                )

    async def _log_permission_request(
        self, message: str, request_id: str, request_type: str = "general"
    ):
        """
        Log permission request to database

        Args:
            message: Permission request message
            request_id: Permission request ID
            request_type: Type of permission request
        """
        try:
            await self.session_manager.save_message(
                role=MessageRole.AGENT,
                content=message,
                message_type=MessageType.PERMISSION_REQUEST,
                turn_id=self.turn_id,
                agent_id=self.agent_id,
                data={"request_id": request_id, "request_type": request_type},
            )
        except Exception as save_error:
            logger.error(f"Failed to save permission request: {save_error}")

    async def _log_permission_response(
        self,
        request_id: str,
        granted: bool,
        session_action: Optional[str] = None,
    ):
        """
        Log permission response to database

        Args:
            request_id: Permission request ID
            granted: Whether permission was granted
            session_action: Optional session-level action
        """
        try:
            data = {"request_id": request_id, "granted": granted}
            if session_action:
                data["session_action"] = session_action
            await self.session_manager.save_message(
                role=MessageRole.AGENT,
                content=f"Permission request {request_id}: "
                f"{'granted' if granted else 'denied'}"
                f"{', session=' + session_action if session_action else ''}",
                message_type=MessageType.PERMISSION_RESPONSE,
                turn_id=self.turn_id,
                agent_id=self.agent_id,
                data=data,
            )
        except Exception as save_error:
            logger.error(f"Failed to save permission response: {save_error}")

    async def _log_permission_timeout(self, request_id: str):
        """
        Log permission timeout to database

        Args:
            request_id: Permission request ID
        """
        try:
            await self.session_manager.save_message(
                role=MessageRole.SYSTEM,
                content="Permission request timed out",
                message_type=MessageType.ERROR,
                turn_id=self.turn_id,
                agent_id=self.agent_id,
                data={"request_id": request_id},
            )
        except Exception as save_error:
            logger.error(f"Failed to save permission timeout: {save_error}")

    async def _log_permission_error(self, error: Exception):
        """
        Log permission error to database

        Args:
            error: Exception that occurred
        """
        try:
            await self.session_manager.save_message(
                role=MessageRole.SYSTEM,
                content=f"Failed to send permission request: {error}",
                message_type=MessageType.ERROR,
                turn_id=self.turn_id,
                agent_id=self.agent_id,
            )
        except Exception as save_error:
            logger.error(f"Failed to save permission error: {save_error}")

    async def _cleanup_permission_request(self, request_id: str):
        """
        Clean up permission request from tracking

        Args:
            request_id: Permission request ID to clean up
        """
        async with self._permission_lock:
            self._permission_requests.pop(request_id, None)

    def get_pending_requests_count(self) -> int:
        """
        Get number of pending permission requests

        Returns:
            Number of pending permission requests
        """
        return len(self._permission_requests)

    async def clear_pending_requests(self):
        """
        Clear all pending permission requests

        This is useful when resetting the agent or handling disconnections
        """
        async with self._permission_lock:
            self._permission_requests.clear()

    async def reset(self):
        """
        Reset permission manager state

        Clears all state variables and pending requests
        """
        await self.clear_pending_requests()
        self.turn_id = None
        self.agent_id = None
        self.session_id = None
