"""Communicator hook — front-end broadcasts for turn/step lifecycle events.

Migrated from ``DefaultLoopEngine`` (``_broadcast_step_message``,
``_broadcast_user_message``, ``_send_turn_error_notification`` and the
``send_turn_end`` half of ``_save_and_broadcast_turn_end``).

Ownership rules (see plan "关键设计决策"):

* ``turn_start`` is broadcast **only** here — the engine's ``_start_turn()``
  must not broadcast it (M13).
* Turn-end broadcast happens in ``on_turn_finalized`` so it always runs
  **after** ``session_manager.save_turn_end``.  ``on_turn_end`` stays
  state-computation only and is *not* implemented here.
* LLM streaming chunks are **not** broadcast here; the engine's ``on_chunk``
  handler does that.

``config.interactive == False`` turns every callback into a no-op.
"""

from __future__ import annotations

from typing import Any, Optional

from broca.components.loop_engine import ExecutionStatus
from broca.components.loop_hook import LoopHook, StepContext, TurnContext
from broca.logging_config import get_logger
from broca.session import MessageProtocol

logger = get_logger(__name__)


class LifecycleBroadcastHook(LoopHook):
    """Broadcast turn/step lifecycle events and error notifications to subscribers.

    Handles **low-frequency** lifecycle markers only (turn_start, step_start/end,
    turn_finalized).  High-frequency streaming chunks (per-token) and per-tool-result
    broadcasts remain in the engine (see ``_make_chunk_handler`` /
    ``process_tool_call_result``).
    """

    name = "lifecycle_broadcast"

    def __init__(
        self,
        communicator: Optional[Any] = None,
        config: Any = None,
        session_id: str = "",
    ):
        self._communicator = communicator
        self._config = config
        self._session_id = session_id or ""

    @property
    def _enabled(self) -> bool:
        return bool(getattr(self._config, "interactive", False)) and (
            self._communicator is not None
        )

    @property
    def _tracks_snapshots(self) -> bool:
        """Legacy parity (review m3): is there a STEP_START row to pair with?

        The legacy engine only broadcast ``step_start`` when snapshot tracking
        actually ran (``_capture_step_start`` returned early without a snapshot
        manager), so the event and the DB row always existed together.  Keep
        that pairing instead of emitting a ``step_start`` with no persisted row.
        """
        if not getattr(self._config, "enable_snapshot_tracking", True):
            return False
        return bool(getattr(self._config, "workspace", "") or "")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def on_turn_start(self, ctx: TurnContext) -> None:
        if not self._enabled:
            return
        await self._send_turn_start(ctx)
        await self._broadcast_user_message(ctx)

    async def on_step_start(self, ctx: StepContext) -> None:
        if not self._enabled or not self._tracks_snapshots:
            return
        message = MessageProtocol.create_step_start(
            step_id=ctx.step_id, snapshot_hash=ctx.step_start_snapshot
        )
        await self._broadcast_step_message(message, ctx)

    async def on_step_end(self, ctx: StepContext) -> None:
        if not self._enabled:
            return
        message = MessageProtocol.create_step_end(
            step_id=ctx.step_id,
            snapshot_hash=ctx.step_end_snapshot,
            patch=ctx.step_patch,
        )
        await self._broadcast_step_message(message, ctx)

    async def on_turn_finalized(self, ctx: TurnContext) -> None:
        """Broadcast ``turn_end`` (and the error notification) after persistence."""
        if not self._enabled or ctx.result is None:
            return

        result = ctx.result
        try:
            await self._communicator.send_turn_end(
                turn_id=ctx.turn_id,
                result=result.status.value,
                message_id=ctx.data.get("turn_end_message_id"),
                subscription=self._session_id,
                changed_files=result.data.get("changed_files"),
            )
        except Exception as e:
            logger.warning(f"Failed to broadcast turn end: {e}")

        if result.status != ExecutionStatus.COMPLETED:
            await self._send_turn_error_notification(ctx)

    # ------------------------------------------------------------------
    # Broadcast helpers
    # ------------------------------------------------------------------

    async def _send_turn_start(self, ctx: TurnContext) -> None:
        try:
            await self._communicator.send_turn_start(
                turn_id=ctx.turn_id,
                turn_description=(
                    f"Processing user message: {ctx.user_message.get('content')}"
                ),
                subscription=self._session_id,
            )
        except Exception as e:
            logger.warning(f"Failed to broadcast turn start: {e}")

    async def _broadcast_user_message(self, ctx: TurnContext) -> None:
        """Broadcast the persisted user message (skipped for agent-sourced turns).

        Uses ``raw_input`` (plain text) as the broadcast ``content`` so the
        front-end always receives a string.  When ``parse_message`` builds
        multimodal content (image/video) the ``content`` field is a **list**
        of OpenAI-style parts — sending that to the UI renders as
        ``[object Object]``.
        """
        if not ctx.message_id or ctx.from_agent:
            return
        try:
            # Prefer raw_input (always a plain-text string after the
            # parse_message fix); fall back to extracting text parts when
            # content is a multimodal list.
            content = ctx.raw_input or ""
            if not content:
                raw = ctx.user_message.get("content", "")
                if isinstance(raw, list):
                    content = "".join(
                        part.get("text", "")
                        for part in raw
                        if isinstance(part, dict) and part.get("type") == "text"
                    )
                else:
                    content = raw
            message = MessageProtocol.create_user_message(
                content=content,
                sender_id=ctx.sender_id,
                subscription=self._session_id,
                turn_id=ctx.turn_id,
                agent_id=ctx.agent_id,
                message_id=ctx.message_id,
            )
            if ctx.files:
                message.data["files"] = ctx.files
            if ctx.raw_input:
                message.data["raw_input"] = ctx.raw_input
            await self._communicator.send_message(message)
        except Exception as e:
            logger.warning(f"Failed to broadcast user message: {e}")

    async def _broadcast_step_message(self, message, ctx: StepContext) -> None:
        message.session_id = ctx.session_id
        message.turn_id = ctx.turn_id
        message.agent_id = ctx.agent_id
        message.subscription = self._session_id
        try:
            await self._communicator.send_message(message)
        except Exception as e:
            logger.warning(f"Failed to broadcast step message: {e}")

    async def _send_turn_error_notification(self, ctx: TurnContext) -> None:
        """Structured error notification for non-completed turns."""
        error_info = {
            "code": "EXECUTION_ERROR",
            "severity": "error",
            "message": ctx.data.get("turn_end_message") or "Turn failed",
            "recovery_hint": None,
            "details": {"status": ctx.result.status.value},
            "cause": None,
            "traceback": None,
        }
        try:
            await self._communicator.send_error(
                error_info=error_info, subscription=self._session_id
            )
        except Exception as e:
            logger.warning(f"Failed to broadcast turn error notification: {e}")
