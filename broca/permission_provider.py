"""DefaultPermissionProvider — merged implementation of PermissionManager + ToolPermissionManager.

Implements the ``PermissionProvider`` ABC by combining:
- Interactive permission requests (from ``PermissionManager``):
  request_permission, request_tool_permission, handle_permission_response,
  logging to session DB, timeout management.
- Tool permission config (from ``ToolPermissionManager``):
  get_permission, set_session_override, clear_session_overrides,
  get_all_permissions, config file loading.

The old ``set_state()`` pattern is replaced:
- ``agent_id`` / ``session_id`` are injected via ``initialize()``.
- ``turn_id`` is updated via ``set_turn_id()`` (called by Agent at turn start).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from broca.components.permission_provider import PermissionProvider
from broca.logging_config import get_logger
from broca.session import Message, MessageRole, MessageType, SessionManager

logger = get_logger(__name__)

VALID_PERMISSIONS = {"allow", "ask", "forbidden"}


class DefaultPermissionProvider(PermissionProvider):
    """Merged permission provider (PermissionManager + ToolPermissionManager).

    Construction: no-arg (per plan).  Runtime dependencies are injected
    via ``initialize()``.
    """

    def __init__(self) -> None:
        # Permission request tracking (from PermissionManager)
        self._permission_requests: Dict[str, Dict] = {}
        self._permission_lock = asyncio.Lock()

        # State variables (set via initialize / set_turn_id)
        self._communicator: Any = None
        self._session_manager: Optional[SessionManager] = None
        self._permission_request_timeout: int = 90
        self._agent_id: Optional[str] = None
        self._session_id: Optional[str] = None
        self.turn_id: Optional[str] = None

        # Tool permission config (from ToolPermissionManager)
        self._default_permissions: Dict[str, str] = {}
        self._session_overrides: Dict[str, str] = {}

        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(
        self,
        communicator: Any,
        session_manager: SessionManager,
        config: Any,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Inject runtime dependencies.

        Args:
            communicator: For sending permission request/response messages.
            session_manager: For logging permission events.
            config: Agent configuration.
            agent_id: Agent identifier (fixed per agent instance).
            session_id: Session identifier (fixed per agent instance).
        """
        if self._initialized and self._communicator is communicator:
            return

        self._communicator = communicator
        self._session_manager = session_manager
        self._agent_id = agent_id
        self._session_id = session_id

        # Read timeout from execution config
        exec_cfg = getattr(config, "execution_config", None)
        self._permission_request_timeout = getattr(
            exec_cfg, "permission_request_timeout", 90
        )

        # Load tool permission config (from ToolPermissionManager logic)
        workspace = getattr(config, "workspace", None)
        self._load_permission_config(workspace)

        self._initialized = True

    def set_turn_id(self, turn_id: Optional[str]) -> None:
        """Update the current turn_id (called at turn start)."""
        self.turn_id = turn_id

    # ------------------------------------------------------------------
    # Backward-compat (deprecated)
    # ------------------------------------------------------------------

    @property
    def communicator(self) -> Any:
        """Deprecated: use _communicator. Kept for test compat."""
        return self._communicator

    @property
    def session_manager(self) -> Optional[SessionManager]:
        """Deprecated: use _session_manager. Kept for test compat."""
        return self._session_manager

    @property
    def agent_id(self) -> Optional[str]:
        return self._agent_id

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    def set_state(
        self,
        turn_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Deprecated: use set_turn_id(). Kept for backward compat."""
        if turn_id is not None:
            self.turn_id = turn_id
        if agent_id is not None:
            self._agent_id = agent_id
        if session_id is not None:
            self._session_id = session_id

    # ------------------------------------------------------------------
    # Interactive permission requests (from PermissionManager)
    # ------------------------------------------------------------------

    async def request_permission(self, message: str) -> bool:
        """Ask for user permission (general flow). Returns True if granted."""
        granted, _ = await self._request_permission_impl(
            message=message, request_type="general"
        )
        return granted

    async def request_tool_permission(
        self, tool_name: str, arguments: str | None = None
    ) -> Tuple[bool, Optional[str]]:
        """Ask for tool execution permission. Returns (granted, session_action).

        Builds the user-facing message internally, including argument
        truncation for readability.
        """
        detail = f"工具 `{tool_name}` 需要你授权。"
        if arguments:
            arg_str = str(arguments)
            if len(arg_str) > 500:
                arg_str = arg_str[:500] + f"…(truncated, {len(arg_str)} chars)"
            detail += f"\n参数: {arg_str}"
        return await self._request_permission_impl(
            message=detail, request_type="tool"
        )

    async def _request_permission_impl(
        self, message: str, request_type: str = "general"
    ) -> Tuple[bool, Optional[str]]:
        """Internal permission request implementation."""
        request_id = str(uuid.uuid4())
        response_event = asyncio.Event()

        async with self._permission_lock:
            self._permission_requests[request_id] = {
                "event": response_event,
                "granted": None,
                "session_action": None,
            }

        try:
            await self._communicator.send_permission_request(
                message=message,
                request_id=request_id,
                request_type=request_type,
                subscription=self._session_id,
                turn_id=self.turn_id,
            )

            await self._log_permission_request(message, request_id, request_type)

            try:
                await asyncio.wait_for(
                    response_event.wait(), timeout=self._permission_request_timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"Permission request {request_id} timed out")
                await self._log_permission_timeout(request_id)
                return False, None

            async with self._permission_lock:
                request_data = self._permission_requests.get(request_id, {})
                granted = request_data.get("granted", False) or False
                session_action = request_data.get("session_action")
                await self._log_permission_response(request_id, granted, session_action)
                return granted, session_action

        except Exception as e:
            logger.error(f"Failed to send permission request: {e}")
            await self._log_permission_error(e)
            return False, None
        finally:
            await self._cleanup_permission_request(request_id)

    async def handle_permission_response(self, message: Message) -> None:
        """Handle permission response from communication channel."""
        granted = message.data.get("granted", False)
        request_id = message.data.get("request_id")
        session_action = message.data.get("session_action")

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

    # ------------------------------------------------------------------
    # Tool permission levels (from ToolPermissionManager)
    # ------------------------------------------------------------------

    def get_permission(self, tool_name: str) -> str:
        """Get effective permission for a tool.

        Priority: session override → configured default → "allow".
        """
        if tool_name in self._session_overrides:
            return self._session_overrides[tool_name]
        return self._default_permissions.get(tool_name, "allow")

    def set_session_override(self, tool_name: str, permission: str) -> None:
        """Set a session-level permission override."""
        if permission not in {"allow", "forbidden"}:
            from broca.errors import ValidationError

            raise ValidationError(
                f"Session override must be 'allow' or 'forbidden', got '{permission}'"
            )
        self._session_overrides[tool_name] = permission
        logger.info(f"Session override set: {tool_name} -> {permission}")

    def clear_session_overrides(self) -> None:
        """Clear all session-level permission overrides."""
        self._session_overrides.clear()
        logger.debug("All session-level permission overrides cleared")

    def get_all_permissions(self) -> Dict[str, str]:
        """Get all effective permissions (includes session overrides)."""
        result = dict(self._default_permissions)
        result.update(self._session_overrides)
        return result

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def get_pending_requests_count(self) -> int:
        """Number of pending permission requests."""
        return len(self._permission_requests)

    async def clear_pending_requests(self) -> None:
        """Clear all pending permission requests."""
        async with self._permission_lock:
            self._permission_requests.clear()

    async def reset(self) -> None:
        """Reset permission provider state."""
        await self.clear_pending_requests()
        self.turn_id = None
        self.clear_session_overrides()

    # ------------------------------------------------------------------
    # Internal: config loading (from ToolPermissionManager)
    # ------------------------------------------------------------------

    def _load_permission_config(self, workspace: Optional[str] = None) -> None:
        """Load tool permission configuration from disk.

        Loading order (stop at first found):
        1. {workspace}/.broca/tool_permission_config.json
        2. ~/.broca/configs/tool_permission_config.json
        3. Neither exists → all tools default to "allow"
        """
        self._default_permissions = {}

        if workspace:
            workspace_config = Path(workspace) / ".broca" / "tool_permission_config.json"
            if workspace_config.exists():
                self._parse_config_file(workspace_config)
                logger.info(
                    f"Loaded tool permissions from workspace config: {workspace_config}"
                )
                return

        global_config = Path.home() / ".broca" / "configs" / "tool_permission_config.json"
        if global_config.exists():
            self._parse_config_file(global_config)
            logger.info(
                f"Loaded tool permissions from global config: {global_config}"
            )
            return

        logger.info("No tool permission config found, all tools default to 'allow'")

    def _parse_config_file(self, config_path: Path) -> None:
        """Parse a single config file and load permissions."""
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
            tools = data.get("tools", {})
            for tool_name, permission in tools.items():
                permission_str = str(permission).lower().strip()
                if permission_str in VALID_PERMISSIONS:
                    self._default_permissions[tool_name] = permission_str
                else:
                    logger.warning(
                        f"Invalid permission '{permission}' for tool '{tool_name}' "
                        f"in {config_path}. Valid values: {', '.join(VALID_PERMISSIONS)}"
                    )
        except Exception as e:
            logger.error(
                f"Failed to load tool permission config from {config_path}: {e}"
            )

    # ------------------------------------------------------------------
    # Internal: logging (from PermissionManager)
    # ------------------------------------------------------------------

    async def _log_permission_request(
        self, message: str, request_id: str, request_type: str = "general"
    ) -> None:
        try:
            await self._session_manager.save_message(
                role=MessageRole.AGENT,
                content=message,
                message_type=MessageType.PERMISSION_REQUEST,
                turn_id=self.turn_id,
                agent_id=self._agent_id,
                data={"request_id": request_id, "request_type": request_type},
            )
        except Exception as save_error:
            logger.error(f"Failed to save permission request: {save_error}")

    async def _log_permission_response(
        self, request_id: str, granted: bool, session_action: Optional[str] = None
    ) -> None:
        try:
            data = {"request_id": request_id, "granted": granted}
            if session_action:
                data["session_action"] = session_action
            await self._session_manager.save_message(
                role=MessageRole.AGENT,
                content=f"Permission request {request_id}: "
                f"{'granted' if granted else 'denied'}"
                f"{', session=' + session_action if session_action else ''}",
                message_type=MessageType.PERMISSION_RESPONSE,
                turn_id=self.turn_id,
                agent_id=self._agent_id,
                data=data,
            )
        except Exception as save_error:
            logger.error(f"Failed to save permission response: {save_error}")

    async def _log_permission_timeout(self, request_id: str) -> None:
        try:
            await self._session_manager.save_message(
                role=MessageRole.SYSTEM,
                content="Permission request timed out",
                message_type=MessageType.ERROR,
                turn_id=self.turn_id,
                agent_id=self._agent_id,
                data={"request_id": request_id},
            )
        except Exception as save_error:
            logger.error(f"Failed to save permission timeout: {save_error}")

    async def _log_permission_error(self, error: Exception) -> None:
        try:
            await self._session_manager.save_message(
                role=MessageRole.SYSTEM,
                content=f"Failed to send permission request: {error}",
                message_type=MessageType.ERROR,
                turn_id=self.turn_id,
                agent_id=self._agent_id,
            )
        except Exception as save_error:
            logger.error(f"Failed to save permission error: {save_error}")

    async def _cleanup_permission_request(self, request_id: str) -> None:
        async with self._permission_lock:
            self._permission_requests.pop(request_id, None)
