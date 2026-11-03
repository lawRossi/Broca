"""Dead-loop hook — step-end detection of repeated identical tool calls.

Migrated from ``DefaultLoopEngine._detect_dead_loop`` /
``_extract_tool_call_signatures`` / ``_normalize_arguments``.

Detection semantics (unchanged from legacy): signatures are **flattened** into
one list; a step with two tool calls contributes two signatures.  When the last
``window`` signatures are all identical, the step is flagged ``DEAD_LOOP``.
Therefore "window" counts *signatures*, not steps.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

from broca.components.loop_engine import ExecutionStatus
from broca.components.loop_hook import LoopHook, StepContext
from broca.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_DEAD_LOOP_WINDOW = 3


class DeadLoopHook(LoopHook):
    """Flag ``ctx.status = DEAD_LOOP`` when the same tool call repeats."""

    name = "dead_loop"

    def __init__(self, window: int = DEFAULT_DEAD_LOOP_WINDOW):
        self._window = (
            window
            if isinstance(window, int) and not isinstance(window, bool) and window > 0
            else DEFAULT_DEAD_LOOP_WINDOW
        )
        self._signatures: List[str] = []

    async def on_step_end(self, ctx: StepContext) -> None:
        self._signatures.extend(self._extract_tool_call_signatures(ctx.tool_calls))
        if len(self._signatures) < self._window:
            return
        last_n = self._signatures[-self._window :]
        if all(sig == last_n[0] for sig in last_n[1:]):
            logger.warning(
                f"Dead loop detected: last {self._window} tool calls are identical "
                f"({self._signatures[-1]})"
            )
            ctx.status = ExecutionStatus.DEAD_LOOP

    def reset(self) -> None:
        self._signatures.clear()

    # ------------------------------------------------------------------
    # Signature helpers (legacy static methods)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_tool_call_signatures(tool_calls: List[Any]) -> List[str]:
        """One ``name(normalized_args)`` signature per tool call."""
        signatures = []
        for tc in tool_calls:
            name = tc.function.name
            args = tc.function.arguments
            normalized_args = DeadLoopHook._normalize_arguments(args)
            signatures.append(f"{name}({normalized_args})")
        return signatures

    @staticmethod
    def _normalize_arguments(args_str: Optional[str]) -> str:
        """Sort JSON keys so key order can't defeat detection."""
        if not args_str:
            return ""
        stripped = args_str.strip()
        if not stripped:
            return ""
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return json.dumps(parsed, sort_keys=True, ensure_ascii=False)
            elif isinstance(parsed, list):
                return json.dumps(parsed, ensure_ascii=False)
            return str(parsed)
        except (json.JSONDecodeError, ValueError):
            return stripped
