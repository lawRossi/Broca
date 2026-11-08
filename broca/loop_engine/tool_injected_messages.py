"""Tool-injected context messages (``ToolResult.extra_context_messages``).

A tool may attach extra LLM messages to its result — ``read_image`` builds a
multimodal ``user`` message so the model can "see" the uploaded image.

Ordering rule
-------------
These messages are ``user`` role. If they were appended right after the tool
result that produced them, a batch such as ``[read_image, read_file]`` would
yield::

    assistant(tool_calls=[read_image, read_file])
    tool(read_image result)
    user(image)              <-- splits the tool-result block (invalid)
    tool(read_file result)

Every provider requires the ``tool`` results to follow the assistant
``tool_calls`` message contiguously, so such a history makes the next LLM call
fail. Therefore ``DefaultLoopEngine._process_tool_results`` persists **all**
tool results first and only then flushes the injected messages through
:func:`append_tool_injected_messages`.

The helper lives here (rather than on the engine) to keep ``engine.py``'s
method count flat — see ``test_engine_is_an_orchestrator_not_a_monolith``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from broca.logging_config import get_logger
from broca.session import MessageType
from broca.tools.tool import ToolResult

logger = get_logger(__name__)


async def append_tool_injected_messages(engine: Any, tool_result: ToolResult) -> None:
    """Persist + append ``tool_result.extra_context_messages`` to the context.

    ``engine`` only needs ``session_manager``, ``context``, ``turn_id`` and
    ``agent_id``. Callers must ensure every tool result of the current step has
    already been appended (see the module docstring for why).

    Failures are logged but never raised: a missing image must not kill a turn.
    """
    for extra in tool_result.extra_context_messages or []:
        extra_id = f"msg_{uuid.uuid4().hex[:16]}"
        data = dict(extra.get("data", {}))
        # Tool-injected messages are internal context, never user-visible.
        data["tool_injected"] = True
        try:
            await engine.session_manager.save_message(
                role=extra.get("role", "user"),
                content=json.dumps(extra["llm_message"], ensure_ascii=False),
                message_type=MessageType.USER_MESSAGE,
                turn_id=engine.turn_id,
                agent_id=engine.agent_id,
                data=data,
                message_id=extra_id,
            )
        except Exception as e:
            logger.error(f"Failed to persist tool-injected message: {e}")
            continue
        await engine.context.add_message(extra["llm_message"], extra_id)
