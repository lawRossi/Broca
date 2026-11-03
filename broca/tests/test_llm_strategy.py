"""Unit tests for ``RetryLLMStrategy`` (Phase 2 of the loop-engine refactor).

Covers the four retry paths (rate limit / other LLMError / timeout / empty
response), abort semantics (no sleep, no retry), the ``on_chunk`` /
``on_error`` callback contracts, and the "no outward dependency" rule.

Golden stream-aggregation coverage lives in ``test_llm_strategy_golden.py``.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from unittest.mock import AsyncMock, patch

import pytest
from litellm.types.utils import ChatCompletionMessageToolCall, Function

from broca.errors import ErrorCode, LLMError
from broca.llm import LiteLLMClient
from broca.loop_engine.strategies.retry_llm import RetryLLMStrategy

STRATEGY_MODULE = "broca.loop_engine.strategies.retry_llm"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class FakeConfig:
    provider = "fake-provider"
    model = "fake-model"

    class _Exec:
        step_max_errors = 3
        llm_retry_delay = 0
        llm_timeout = 5

    def __init__(self) -> None:
        # Per-instance copy: ``_make_strategy(step_max_errors=...)`` must not
        # leak into other tests through a shared class attribute.
        self.execution_config = FakeConfig._Exec()


class ScriptedClient(LiteLLMClient):
    """Real aggregation logic, scripted transport.

    ``script`` is a list of "attempts"; each attempt is either an exception
    instance (raised) or a list of chunks (yielded).
    """

    def __init__(self, script: list) -> None:
        self.input_tokens_used = 7
        self.output_tokens_used = 9
        self._script = list(script)
        self.attempts = 0

    async def get_stream_response(  # type: ignore[override]
        self, provider, model, messages, tools=None, first_chunk_timeout=None, timeout=None
    ):
        self.attempts += 1
        attempt = self._script.pop(0) if self._script else [{"type": "content", "data": "ok"}]
        if isinstance(attempt, BaseException):
            raise attempt
        for chunk in attempt:
            yield chunk
        # Append a usage event (mirrors the real LLMClient behaviour where
        # ``_process_chunk`` yields usage from the provider's final chunk).
        yield {
            "type": "usage",
            "data": {
                "input_tokens": self.input_tokens_used,
                "output_tokens": self.output_tokens_used,
            },
        }


def _tool_call(call_id: str, name: str = "read_file", index: int = 0):
    return ChatCompletionMessageToolCall(
        id=call_id,
        index=index,
        type="function",
        function=Function(name=name, arguments='{"path": "a.py"}'),
    )


async def _make_strategy(script: list, **overrides) -> RetryLLMStrategy:
    strategy = RetryLLMStrategy()
    config = FakeConfig()
    for key, value in overrides.items():
        setattr(config.execution_config, key, value)
    await strategy.initialize(llm_client=ScriptedClient(script), config=config)
    return strategy


def _recorder():
    events: list = []

    async def record(*args):
        events.append(args if len(args) > 1 else args[0])

    return events, record


# ---------------------------------------------------------------------------
# Retry paths
# ---------------------------------------------------------------------------
class TestRateLimitPath:
    @pytest.mark.asyncio
    async def test_rate_limit_then_success(self):
        strategy = await _make_strategy(
            [LLMError("too many", error_code=ErrorCode.LLM_RATE_LIMIT), [{"type": "content", "data": "hi"}]]
        )
        errors, on_error = _recorder()
        with patch(f"{STRATEGY_MODULE}.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            result = await strategy.call([], [], on_error=on_error)

        assert result.success is True
        assert result.message.content == "hi"
        assert mock_sleep.await_count == 1
        assert [(code, severity) for _, code, severity in errors] == [("LLM_RATE_LIMIT", "warning")]

    @pytest.mark.asyncio
    async def test_rate_limit_exhausts_retries_raises(self):
        rate_limit = LLMError("too many", error_code=ErrorCode.LLM_RATE_LIMIT)
        strategy = await _make_strategy([rate_limit] * 10, step_max_errors=2)
        with patch(f"{STRATEGY_MODULE}.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(LLMError) as exc_info:
                await strategy.call([], [])
        # Raised only after exceeding max consecutive rate limits (max + 1).
        assert exc_info.value.error_code == ErrorCode.LLM_RATE_LIMIT
        assert strategy._consecutive_rate_limit_errors == 3

    @pytest.mark.asyncio
    async def test_rate_limit_counter_resets_on_success(self):
        """Migrated from ``test_loop_engine.TestRateLimitRetry``.

        A successful call clears the counter, so the *next* call gets a fresh
        retry budget.
        """
        strategy = await _make_strategy(
            [
                LLMError("too many", error_code=ErrorCode.LLM_RATE_LIMIT),
                LLMError("too many", error_code=ErrorCode.LLM_RATE_LIMIT),
                [{"type": "content", "data": "hi"}],
            ]
        )
        with patch(f"{STRATEGY_MODULE}.asyncio.sleep", new=AsyncMock()):
            await strategy.call([], [])
        assert strategy._consecutive_rate_limit_errors == 0

        # Second call: full budget again → 3 sleeps before the 4th failure raises.
        strategy._llm_client._script = [
            LLMError("too many", error_code=ErrorCode.LLM_RATE_LIMIT)
        ] * 10
        with patch(f"{STRATEGY_MODULE}.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            with pytest.raises(LLMError):
                await strategy.call([], [])
        assert mock_sleep.await_count == 3


class TestLLMErrorPath:
    @pytest.mark.asyncio
    async def test_other_llm_error_retried_then_succeeds(self):
        strategy = await _make_strategy(
            [LLMError("boom", error_code=ErrorCode.LLM_AUTH_ERROR), [{"type": "content", "data": "hi"}]]
        )
        errors, on_error = _recorder()
        with patch(f"{STRATEGY_MODULE}.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            result = await strategy.call([], [], on_error=on_error)

        assert result.success is True
        assert mock_sleep.await_count == 1
        assert [(code, severity) for _, code, severity in errors] == [("LLM_AUTH_ERROR", "error")]

    @pytest.mark.asyncio
    async def test_other_llm_error_exhausts_raises(self):
        """Migrated from ``test_loop_engine.TestRateLimitRetry``: retried
        ``step_max_errors - 1`` times, then raised (no extra sleep)."""
        boom = LLMError("boom", error_code=ErrorCode.LLM_ERROR)
        strategy = await _make_strategy([boom] * 10, step_max_errors=3)
        with patch(f"{STRATEGY_MODULE}.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            with pytest.raises(LLMError):
                await strategy.call([], [])
        assert mock_sleep.await_count == 2
        assert strategy._consecutive_rate_limit_errors == 0


class TestTimeoutPath:
    @pytest.mark.asyncio
    async def test_timeout_retried_then_succeeds(self):
        strategy = await _make_strategy(
            [asyncio.TimeoutError(), [{"type": "content", "data": "hi"}]]
        )
        errors, on_error = _recorder()
        with patch(f"{STRATEGY_MODULE}.asyncio.sleep", new=AsyncMock()):
            result = await strategy.call([], [], on_error=on_error)

        assert result.success is True
        assert [(code, severity) for _, code, severity in errors] == [("LLM_TIMEOUT", "warning")]

    @pytest.mark.asyncio
    async def test_timeout_exhausts_returns_failure(self):
        strategy = await _make_strategy(
            [asyncio.TimeoutError()] * 10, step_max_errors=2
        )
        errors, on_error = _recorder()
        with patch(f"{STRATEGY_MODULE}.asyncio.sleep", new=AsyncMock()):
            result = await strategy.call([], [], on_error=on_error)

        assert result.success is False
        assert result.error_code == "LLM_TIMEOUT"
        assert [severity for _, _, severity in errors] == ["warning", "warning"]


class TestEmptyResponsePath:
    @pytest.mark.asyncio
    async def test_empty_response_retried_then_succeeds(self):
        strategy = await _make_strategy([[], [{"type": "content", "data": "hi"}]])
        errors, on_error = _recorder()
        with patch(f"{STRATEGY_MODULE}.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            result = await strategy.call([], [], on_error=on_error)

        assert result.success is True
        assert mock_sleep.await_count == 1
        assert [(code, severity) for _, code, severity in errors] == [
            ("LLM_EMPTY_RESPONSE", "warning")
        ]

    @pytest.mark.asyncio
    async def test_empty_response_exhausts_returns_failure(self):
        strategy = await _make_strategy([[], [], []], step_max_errors=2)
        errors, on_error = _recorder()
        with patch(f"{STRATEGY_MODULE}.asyncio.sleep", new=AsyncMock()):
            result = await strategy.call([], [], on_error=on_error)

        assert result.success is False
        assert result.error_code == "LLM_EMPTY_RESPONSE"
        assert [(code, severity) for _, code, severity in errors] == [
            ("LLM_EMPTY_RESPONSE", "warning"),
            ("LLM_EMPTY_RESPONSE", "error"),
        ]


class TestUnexpectedExceptionPath:
    @pytest.mark.asyncio
    async def test_generic_exception_retried_then_succeeds(self):
        strategy = await _make_strategy([RuntimeError("kaboom"), [{"type": "content", "data": "hi"}]])
        errors, on_error = _recorder()
        with patch(f"{STRATEGY_MODULE}.asyncio.sleep", new=AsyncMock()):
            result = await strategy.call([], [], on_error=on_error)

        assert result.success is True
        assert [(code, severity) for _, code, severity in errors] == [("LLM_ERROR", "error")]

    @pytest.mark.asyncio
    async def test_generic_exception_exhausts_returns_failure(self):
        strategy = await _make_strategy([RuntimeError("kaboom")] * 10, step_max_errors=2)
        with patch(f"{STRATEGY_MODULE}.asyncio.sleep", new=AsyncMock()):
            result = await strategy.call([], [])
        assert result.success is False
        assert result.error_code == "LLM_ERROR"


class TestErrorNotificationPoints:
    """The six ``on_error`` call sites from the legacy engine are preserved."""

    @pytest.mark.asyncio
    async def test_all_six_notification_points(self):
        observed: list[tuple[str, str]] = []

        async def on_error(message: str, code: str, severity: str) -> None:
            observed.append((code, severity))

        with patch(f"{STRATEGY_MODULE}.asyncio.sleep", new=AsyncMock()):
            # 1 + 2: rate-limit warning, then empty-response warning + error
            s1 = await _make_strategy(
                [LLMError("rl", error_code=ErrorCode.LLM_RATE_LIMIT), [], []],
                step_max_errors=2,
            )
            await s1.call([], [], on_error=on_error)
            # 3: timeout warning
            s2 = await _make_strategy([asyncio.TimeoutError(), [{"type": "content", "data": "x"}]])
            await s2.call([], [], on_error=on_error)
            # 4: other LLMError retry error
            s3 = await _make_strategy(
                [LLMError("auth", error_code=ErrorCode.LLM_AUTH_ERROR), [{"type": "content", "data": "x"}]]
            )
            await s3.call([], [], on_error=on_error)
            # 5: generic exception retry error
            s4 = await _make_strategy([RuntimeError("kaboom"), [{"type": "content", "data": "x"}]])
            await s4.call([], [], on_error=on_error)

        assert observed == [
            ("LLM_RATE_LIMIT", "warning"),  # 限流 warning
            ("LLM_EMPTY_RESPONSE", "warning"),  # 空响应 warning
            ("LLM_EMPTY_RESPONSE", "error"),  # 空响应放弃 error
            ("LLM_TIMEOUT", "warning"),  # 超时 warning
            ("LLM_AUTH_ERROR", "error"),  # 重试 error
            ("LLM_ERROR", "error"),  # 失败 error
        ]


# ---------------------------------------------------------------------------
# Abort semantics
# ---------------------------------------------------------------------------
class TestAbort:
    @pytest.mark.asyncio
    async def test_abort_before_call_returns_immediately(self):
        strategy = await _make_strategy([[{"type": "content", "data": "hi"}]])
        with patch(f"{STRATEGY_MODULE}.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            started = time.perf_counter()
            result = await strategy.call([], [], should_abort=lambda: True)
            elapsed = time.perf_counter() - started

        assert result.aborted is True
        assert result.success is False
        assert elapsed < 0.1
        assert mock_sleep.await_count == 0
        assert strategy._llm_client.attempts == 0

    @pytest.mark.asyncio
    async def test_abort_mid_stream_stops_without_retry(self):
        chunks = [{"type": "content", "data": "a"}, {"type": "content", "data": "b"}]
        strategy = await _make_strategy([chunks])
        state = {"aborted": False}
        events: list[dict] = []

        async def on_chunk(event: dict) -> None:
            events.append(event)
            state["aborted"] = True  # abort right after the first chunk

        with patch(f"{STRATEGY_MODULE}.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            result = await strategy.call(
                [], [], on_chunk=on_chunk, should_abort=lambda: state["aborted"]
            )

        assert result.aborted is True
        assert len(events) == 1
        assert mock_sleep.await_count == 0
        assert strategy._llm_client.attempts == 1

    @pytest.mark.asyncio
    async def test_cancelled_error_maps_to_aborted(self):
        strategy = await _make_strategy([asyncio.CancelledError()])
        result = await strategy.call([], [])
        assert result.aborted is True
        assert result.success is False


# ---------------------------------------------------------------------------
# on_chunk contract
# ---------------------------------------------------------------------------
class TestOnChunkContract:
    @pytest.mark.asyncio
    async def test_only_three_event_types_and_tool_call_dedup(self):
        chunks = [
            {"type": "content", "data": "a"},
            {"type": "reasoning_content", "data": "r"},
            {"type": "tool_call", "data": _tool_call("call_1")},
            {"type": "tool_call", "data": _tool_call("call_1")},
            {"type": "finish", "data": None},
        ]
        strategy = await _make_strategy([chunks])
        events: list[dict] = []

        async def on_chunk(event: dict) -> None:
            events.append(event)

        await strategy.call([], [], on_chunk=on_chunk)

        assert [event["type"] for event in events] == [
            "content",
            "reasoning_content",
            "tool_call",
        ]
        # content events carry index + message_id; tool_call only once per id.
        assert [event["index"] for event in events[:2]] == [0, 1]
        assert all(event["message_id"] for event in events)
        assert events[2]["data"].id == "call_1"


# ---------------------------------------------------------------------------
# Tokens / dependencies
# ---------------------------------------------------------------------------
class TestTokensAndDependencies:
    @pytest.mark.asyncio
    async def test_tokens_are_reported_on_result(self):
        strategy = await _make_strategy([[{"type": "content", "data": "hi"}]])
        result = await strategy.call([], [])
        assert result.input_tokens == 7
        assert result.output_tokens == 9

    def test_no_outward_dependencies(self):
        """The strategy must not depend on communicator / session / context."""
        import ast

        import broca.loop_engine.strategies.retry_llm as module

        tree = ast.parse(inspect.getsource(module))
        forbidden_modules = (
            "broca.communication",
            "broca.context",
            "broca.components.communicator",
            "broca.components.session_manager",
            "broca.session.session_manager",
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden_modules), alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(forbidden_modules), node.module
                if node.module == "broca.session":
                    # Only the id generator is allowed from the session layer.
                    names = {alias.name for alias in node.names}
                    assert names <= {"generate_message_id"}, names

    def test_reset_clears_rate_limit_counter(self):
        strategy = RetryLLMStrategy()
        strategy._consecutive_rate_limit_errors = 5
        strategy.reset()
        assert strategy._consecutive_rate_limit_errors == 0
