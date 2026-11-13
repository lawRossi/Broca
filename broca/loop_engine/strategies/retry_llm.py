"""Default LLM strategy: retry + rate limit + timeout + empty response + streaming.

Migrated from the former monolithic engine (removed in Phase 5):
``_call_llm_with_retry`` / ``_send_llm_error`` / ``_call_llm_streaming`` /
``_process_content_chunk`` / ``_process_tool_call_chunk`` / ``_finalize_llm_response``.

The strategy owns retry policy and stream aggregation only.  Everything
outward-facing goes through the ``on_chunk`` / ``on_error`` callbacks, so the
strategy never touches communicator / session_manager / context / agent_ref.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

from broca.components.llm_strategy import LLMCallResult, LLMStrategy
from broca.errors import ErrorCode, LLMError
from broca.logging_config import get_logger
from broca.session import generate_message_id

if TYPE_CHECKING:
    from broca.components.llm_client import LLMClient

logger = get_logger(__name__)

OnChunk = Callable[[dict], Awaitable[None]]
OnError = Callable[[str, str, str], Awaitable[None]]
ShouldAbort = Callable[[], bool]


class RetryLLMStrategy(LLMStrategy):
    """Default LLM strategy: retries, rate limiting, timeouts, empty responses.

    Retry policy (identical to the legacy engine):

    - Rate limit (``LLM_RATE_LIMIT``): wait and retry, at most
      ``step_max_errors`` consecutive times; the counter resets on success.
    - Other ``LLMError``: retried with the same parameters, re-raised once
      ``step_max_errors`` is reached (error code preserved for the caller).
    - Timeout / unexpected exception: retried with the same parameters,
      ``LLMCallResult(success=False)`` once exhausted.
    - Empty response (call succeeded but aggregation is empty): soft failure —
      warning + retry, gives up after ``step_max_errors`` consecutive times
      without touching the rate-limit counter.
    - ``should_abort()`` is checked before every retry iteration and before
      every chunk; it returns ``aborted=True`` immediately (no sleep, no retry).
    """

    name = "retry_llm"

    def __init__(self) -> None:
        self._llm_client: Optional["LLMClient"] = None
        self._config: Any = None
        self._max_errors: int = 3
        self._retry_delay: float = 5
        self._timeout: float = 300
        self._consecutive_rate_limit_errors: int = 0

    async def initialize(self, *, llm_client: "LLMClient", config: Any) -> None:
        """Inject dependencies and resolve retry parameters.

        Priority: explicit ``AgentConfig`` attribute > ``execution_config`` >
        built-in default (``AgentConfig`` normally has no agent-level override
        for these three, so ``execution_config`` wins in practice).
        """
        self._llm_client = llm_client
        self._config = config
        exec_cfg = getattr(config, "execution_config", None)
        self._max_errors = _resolve(config, exec_cfg, "step_max_errors", 3)
        self._retry_delay = _resolve(config, exec_cfg, "llm_retry_delay", 5)
        self._timeout = _resolve(config, exec_cfg, "llm_timeout", 300)

    @property
    def _provider(self) -> str:
        """Read the target from the config on every call.

        Deliberately *not* snapshotted in ``initialize()``: agents are cached
        and reused across turns, so a config change (agent sidebar) or a sub
        agent that must follow the main agent's LLM choice only has to update
        ``AgentConfig.provider`` / ``.model``.
        """
        return getattr(self._config, "provider", "")

    @property
    def _model(self) -> str:
        """See :attr:`_provider`."""
        return getattr(self._config, "model", "")

    def reset(self) -> None:
        """Reset the consecutive rate-limit counter."""
        self._consecutive_rate_limit_errors = 0

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def call(
        self,
        history: list,
        tools: list[dict],
        *,
        on_chunk: Optional[OnChunk] = None,
        on_error: Optional[OnError] = None,
        should_abort: Optional[ShouldAbort] = None,
    ) -> LLMCallResult:
        """Call the LLM with retries; see class docstring for the policy."""
        errors = 0
        empty_retries = 0

        while errors < self._max_errors:
            if should_abort is not None and should_abort():
                logger.info("Agent execution aborted during LLM call")
                return LLMCallResult(success=False, aborted=True, error_code="ABORTED")

            try:
                result = await asyncio.wait_for(
                    self._stream_once(history, tools, on_chunk, should_abort),
                    timeout=self._timeout,
                )
                if result.aborted:
                    # Aborted mid-stream: no sleep, no retry.
                    logger.info("Agent execution aborted during LLM call")
                    return result
                if result.message is None:
                    # Call succeeded but aggregation is empty (soft failure).
                    empty_retries += 1
                    if empty_retries >= self._max_errors:
                        logger.error(
                            f"LLM returned empty response {empty_retries} "
                            "consecutive times, giving up"
                        )
                        await self._notify(
                            on_error,
                            "LLM 连续返回空响应，已停止重试",
                            "LLM_EMPTY_RESPONSE",
                            "error",
                        )
                        return LLMCallResult(
                            success=False,
                            error_code="LLM_EMPTY_RESPONSE",
                            error_message="LLM returned empty response",
                        )
                    logger.warning(
                        f"LLM returned empty response ({empty_retries}/"
                        f"{self._max_errors}), retrying in {self._retry_delay}s"
                    )
                    await self._notify(
                        on_error,
                        f"LLM 返回空响应，{self._retry_delay} 秒后自动重试 "
                        f"({empty_retries}/{self._max_errors})...",
                        "LLM_EMPTY_RESPONSE",
                        "warning",
                    )
                    await asyncio.sleep(self._retry_delay)
                    continue

                # Success: reset the consecutive rate-limit counter.
                if self._consecutive_rate_limit_errors:
                    self._consecutive_rate_limit_errors = 0
                return result

            except LLMError as e:
                if e.error_code == ErrorCode.LLM_RATE_LIMIT:
                    self._consecutive_rate_limit_errors += 1
                    if self._consecutive_rate_limit_errors > self._max_errors:
                        logger.error(
                            "LLM rate limited "
                            f"{self._consecutive_rate_limit_errors} consecutive "
                            "times, aborting turn"
                        )
                        raise
                    logger.warning(
                        f"LLM rate limited ({self._consecutive_rate_limit_errors}/"
                        f"{self._max_errors}), retrying in {self._retry_delay}s"
                    )
                    await self._notify(
                        on_error,
                        f"请求频率过高，{self._retry_delay} 秒后自动重试 "
                        f"({self._consecutive_rate_limit_errors}/{self._max_errors})...",
                        "LLM_RATE_LIMIT",
                        "warning",
                    )
                    await asyncio.sleep(self._retry_delay)
                    continue

                errors += 1
                logger.error(f"LLM error ({e.error_code}): {e}")
                if errors == self._max_errors:
                    logger.error("Too many LLM errors, aborting...")
                    raise
                await self._notify(
                    on_error,
                    "LLM 调用失败，正在重试...",
                    e.error_code.value,
                    "error",
                )
                await asyncio.sleep(self._retry_delay)

            except asyncio.TimeoutError:
                errors += 1
                logger.error("LLM call timed out")
                await self._notify(
                    on_error, "LLM 调用超时，自动重试中...", "LLM_TIMEOUT", "warning"
                )
                if errors < self._max_errors:
                    continue
                return LLMCallResult(
                    success=False,
                    error_code="LLM_TIMEOUT",
                    error_message="LLM call timed out",
                )

            except asyncio.CancelledError:
                # Intentional semantic change (plan Task 2.1 step 4): real
                # cancellation is reported as an abort, so callers treat
                # "cancelled" and "user aborted" uniformly.
                logger.info("Agent execution cancelled by user during LLM call")
                return LLMCallResult(success=False, aborted=True, error_code="ABORTED")

            except Exception as e:
                errors += 1
                logger.error(f"LLM call failed: {e}")
                if errors == self._max_errors:
                    logger.error("Too many LLM errors, aborting...")
                    return LLMCallResult(
                        success=False,
                        error_code="LLM_ERROR",
                        error_message=str(e),
                    )
                await self._notify(
                    on_error, "LLM 调用失败，正在重试...", "LLM_ERROR", "error"
                )
                await asyncio.sleep(self._retry_delay)

        # Fallback: reached when ``_max_errors`` is 0 (loop body never executes)
        # or when all retry iterations were ``continue``d until the counter
        # exhausted.  In practice this is rare — most error branches either
        # ``raise`` (LLMError) or ``return`` a specific LLMCallResult.
        return LLMCallResult(
            success=False, error_code="LLM_ERROR", error_message="Too many LLM errors"
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _stream_once(
        self,
        history: list,
        tools: list[dict],
        on_chunk: Optional[OnChunk],
        should_abort: Optional[ShouldAbort],
    ) -> LLMCallResult:
        """One streaming attempt: aggregate chunks and emit ``on_chunk`` events."""
        content_chunks: list[Any] = []
        tool_call_chunks: list[Any] = []
        sent: set[str] = set()
        message_id = generate_message_id()
        index = 0
        # Token usage captured from the stream itself (review 2.6): reading
        # from the LLMClient's shared instance attributes would be
        # cross-contaminated when multiple agents call LLM concurrently on
        # the same singleton client.
        usage: dict = {"input_tokens": 0, "output_tokens": 0}

        async for chunk in self._llm_client.get_stream_response(
            self._provider, self._model, history, tools
        ):
            if should_abort is not None and should_abort():
                return LLMCallResult(
                    success=False, aborted=True, error_code="ABORTED"
                )

            chunk_type = chunk.get("type")
            if chunk_type == "usage":
                # Internal event: capture token counts, never broadcast.
                usage = chunk.get("data", usage)
            elif chunk_type in ("content", "reasoning_content"):
                content_chunks.append(chunk)
                if on_chunk is not None:
                    await on_chunk({**chunk, "index": index, "message_id": message_id})
                index += 1
            elif chunk_type == "tool_call":
                tool_call = chunk.get("data")
                tool_call_chunks.append(tool_call)
                tool_call_id = getattr(tool_call, "id", None)
                function = getattr(tool_call, "function", None)
                if (
                    tool_call_id
                    and function is not None
                    and getattr(function, "name", None)
                    and tool_call_id not in sent
                ):
                    if on_chunk is not None:
                        await on_chunk(
                            {
                                "type": "tool_call",
                                "data": tool_call,
                                "message_id": message_id,
                            }
                        )
                    sent.add(tool_call_id)

        message = self._llm_client.aggregate_message(content_chunks, tool_call_chunks)
        if message is not None:
            # Attach the message_id so downstream code can reuse it.
            setattr(message, "message_id", message_id)

        return LLMCallResult(
            message=message,
            message_id=message_id,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            success=message is not None,
            error_code="" if message is not None else "LLM_EMPTY_RESPONSE",
        )

    @staticmethod
    async def _notify(
        on_error: Optional[OnError], message: str, code: str, severity: str
    ) -> None:
        """Forward an error notification to the engine (if a handler is set)."""
        if on_error is not None:
            await on_error(message, code, severity)


def _resolve(config: Any, exec_cfg: Any, name: str, default: Any) -> Any:
    """Resolve a numeric execution parameter.

    Priority: explicit ``AgentConfig`` attribute > ``execution_config`` >
    built-in default (plan Task 2.3).  Non-numeric values (``None``, stray
    mocks) are skipped so a malformed config never breaks the retry loop.
    """
    for source in (config, exec_cfg):
        value = getattr(source, name, None)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return default
