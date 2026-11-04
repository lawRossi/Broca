"""
Regression test: LLM exception mapping table produces correct ErrorCode for each exception type.

Verifies:
  - Ordering constraint: subclasses before superclasses in _EXCEPTION_MAP
  - Unit-level: each exception maps to the correct ErrorCode
  - Integration: get_stream_response() end-to-end (acompletion raises → LLMError)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broca.errors import ErrorCode, LLMError
from broca.llm import _EXCEPTION_MAP, LiteLLMClient

# Import litellm exception types
from litellm.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    BudgetExceededError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    InvalidRequestError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)


def _make_client():
    with patch("broca.configs.resolve_llm_config_path", return_value="/tmp/fake.json"), \
         patch("builtins.open", return_value=MagicMock(
            __enter__=MagicMock(return_value=None),
            __exit__=MagicMock(return_value=False),
        )), \
         patch("json.load", return_value={"providers": {}, "defaults": {}}):
        return LiteLLMClient()


class TestExceptionMapOrdering:
    """Subclasses must appear before their superclasses in _EXCEPTION_MAP."""

    def test_context_window_before_bad_request(self):
        """ContextWindowExceededError must come before BadRequestError."""
        idx_ctx = next(
            i for i, (t, _, _) in enumerate(_EXCEPTION_MAP)
            if t is ContextWindowExceededError
        )
        idx_br = next(
            i for i, (t, _, _) in enumerate(_EXCEPTION_MAP)
            if t is BadRequestError
        )
        assert idx_ctx < idx_br

    def test_content_policy_before_bad_request(self):
        idx_cp = next(
            i for i, (t, _, _) in enumerate(_EXCEPTION_MAP)
            if t is ContentPolicyViolationError
        )
        idx_br = next(
            i for i, (t, _, _) in enumerate(_EXCEPTION_MAP)
            if t is BadRequestError
        )
        assert idx_cp < idx_br

    def test_timeout_before_api_connection(self):
        idx_to = next(
            i for i, (t, _, _) in enumerate(_EXCEPTION_MAP)
            if t is Timeout
        )
        idx_ac = next(
            i for i, (t, _, _) in enumerate(_EXCEPTION_MAP)
            if t is APIConnectionError
        )
        assert idx_to < idx_ac


class TestExceptionClassification:
    """Each exception type maps to the correct ErrorCode."""

    @pytest.mark.parametrize(
        "exc_type, expected_code, exc_msg",
        [
            (ContextWindowExceededError, ErrorCode.LLM_CONTEXT_WINDOW_EXCEEDED, "context window"),
            (ContentPolicyViolationError, ErrorCode.LLM_ERROR, "content policy"),
            (Timeout, ErrorCode.LLM_TIMEOUT, "timeout"),
            (AuthenticationError, ErrorCode.LLM_AUTH_ERROR, "auth"),
            (BudgetExceededError, ErrorCode.LLM_QUOTA_EXCEEDED, "budget"),
            (RateLimitError, ErrorCode.LLM_RATE_LIMIT, "rate limit"),
            (InternalServerError, ErrorCode.LLM_SERVICE_UNAVAILABLE, "500"),
            (ServiceUnavailableError, ErrorCode.LLM_SERVICE_UNAVAILABLE, "503"),
            (APIConnectionError, ErrorCode.LLM_SERVICE_UNAVAILABLE, "connection"),
        ],
    )
    def test_exception_maps_to_correct_code(self, exc_type, expected_code, exc_msg):
        """Each specific exception maps to its designated ErrorCode."""
        if exc_type is BudgetExceededError:
            exc = BudgetExceededError(current_cost=100.0, max_budget=50.0, message=exc_msg)
        else:
            exc = exc_type(message=exc_msg, model="test", llm_provider="openai")

        for t, code, prefix in _EXCEPTION_MAP:
            if isinstance(exc, t):
                assert code == expected_code, (
                    f"{exc_type.__name__} matched {t.__name__} "
                    f"(expected {expected_code.name}, got {code.name})"
                )
                break
        else:
            pytest.fail(f"{exc_type.__name__} not found in _EXCEPTION_MAP")

    def test_context_window_not_shadowed_by_bad_request(self):
        """ContextWindowExceededError must NOT be matched by BadRequestError."""
        exc = ContextWindowExceededError(message="context too large", model="test", llm_provider="openai")
        matched = None
        for t, code, _ in _EXCEPTION_MAP:
            if isinstance(exc, t):
                matched = (t, code)
                break
        assert matched is not None
        assert matched[0] is ContextWindowExceededError
        assert matched[1] == ErrorCode.LLM_CONTEXT_WINDOW_EXCEEDED

    def test_content_policy_not_shadowed_by_bad_request(self):
        """ContentPolicyViolationError must NOT be matched by BadRequestError."""
        exc = ContentPolicyViolationError(message="policy violation", model="test", llm_provider="openai")
        matched = None
        for t, code, _ in _EXCEPTION_MAP:
            if isinstance(exc, t):
                matched = (t, code)
                break
        assert matched is not None
        assert matched[0] is ContentPolicyViolationError

    def test_classify_request_error_model_not_found(self):
        """InvalidRequestError with 'model not found' → LLM_INVALID_MODEL."""
        client = _make_client()
        exc = InvalidRequestError(
            message="Model gpt-99 not found",
            model="gpt-99",
            llm_provider="openai",
        )
        err = client._classify_request_error(exc, "openai", "gpt-99", "test")
        assert err.info.code == ErrorCode.LLM_INVALID_MODEL

    def test_classify_request_error_auth_key(self):
        """BadRequestError with 'api key' keyword → LLM_AUTH_ERROR."""
        client = _make_client()
        exc = BadRequestError(
            message="Invalid API key provided",
            model="gpt-4",
            llm_provider="openai",
        )
        err = client._classify_request_error(exc, "openai", "gpt-4", "LLM error")
        assert err.info.code == ErrorCode.LLM_AUTH_ERROR


@pytest.mark.asyncio
class TestGetStreamResponseIntegration:
    """Integration: acompletion raises → get_stream_response wraps into correct LLMError.

    Exercises the full exception path inside ``get_stream_response()``:
    acompletion raises → except block matches via _EXCEPTION_MAP (or
    InvalidRequestError handler) → correct LLMError is raised.
    """

    @staticmethod
    def _make_client_with_config() -> LiteLLMClient:
        """Client with a valid provider/model in config so get_stream_response
        passes the validation checks and reaches acompletion."""
        client = _make_client()
        client.config = {
            "openai": {
                "base_url": "http://localhost:9999",
                "api_key": "test-key",
                "models": {
                    "gpt-4": {
                        "model": "gpt-4",
                        "temperature": 0.7,
                        "meta": {},
                    }
                },
            }
        }
        return client

    @staticmethod
    async def _trigger_stream_error(client: LiteLLMClient, exc: Exception) -> LLMError:
        """Mock acompletion to raise *exc*, consume get_stream_response,
        and return the raised LLMError."""
        with patch("broca.llm.acompletion", AsyncMock(side_effect=exc)):
            stream = client.get_stream_response(
                "openai", "gpt-4", [],
                first_chunk_timeout=10,
                timeout=30,
            )
            with pytest.raises(LLMError) as exc_info:
                await stream.__anext__()
            return exc_info.value.value if hasattr(exc_info.value, "value") else exc_info.value

    @pytest.mark.parametrize(
        "exc_factory, expected_code",
        [
            (
                lambda: Timeout(message="timeout", model="gpt-4", llm_provider="openai"),
                ErrorCode.LLM_TIMEOUT,
            ),
            (
                lambda: AuthenticationError(message="bad key", model="gpt-4", llm_provider="openai"),
                ErrorCode.LLM_AUTH_ERROR,
            ),
            (
                lambda: RateLimitError(message="rate limited", model="gpt-4", llm_provider="openai"),
                ErrorCode.LLM_RATE_LIMIT,
            ),
            (
                lambda: ContextWindowExceededError(message="too long", model="gpt-4", llm_provider="openai"),
                ErrorCode.LLM_CONTEXT_WINDOW_EXCEEDED,
            ),
            (
                lambda: APIConnectionError(message="conn failed", model="gpt-4", llm_provider="openai"),
                ErrorCode.LLM_SERVICE_UNAVAILABLE,
            ),
            (
                lambda: InternalServerError(message="500", model="gpt-4", llm_provider="openai"),
                ErrorCode.LLM_SERVICE_UNAVAILABLE,
            ),
        ],
    )
    async def test_acompletion_exception_maps_to_code(
        self, exc_factory, expected_code
    ):
        """Each litellm exception from acompletion → correct LLMError.error_code."""
        client = self._make_client_with_config()
        exc = exc_factory()

        with patch("broca.llm.acompletion", AsyncMock(side_effect=exc)):
            stream = client.get_stream_response(
                "openai", "gpt-4", [],
                first_chunk_timeout=10,
                timeout=30,
            )
            with pytest.raises(LLMError) as exc_info:
                await stream.__anext__()

        err = exc_info.value
        assert err.info.code == expected_code, (
            f"Expected {expected_code.name}, got {err.info.code.name}"
        )

    async def test_content_policy_via_stream(self):
        """ContentPolicyViolationError through get_stream_response → LLM_ERROR."""
        client = self._make_client_with_config()
        exc = ContentPolicyViolationError(
            message="content policy violation",
            model="gpt-4",
            llm_provider="openai",
        )

        with patch("broca.llm.acompletion", AsyncMock(side_effect=exc)):
            stream = client.get_stream_response(
                "openai", "gpt-4", [],
                first_chunk_timeout=10,
                timeout=30,
            )
            with pytest.raises(LLMError) as exc_info:
                await stream.__anext__()

        assert exc_info.value.info.code == ErrorCode.LLM_ERROR
        # Message should mention content safety
        assert "内容安全策略" in exc_info.value.message

    async def test_invalid_request_model_not_found_via_stream(self):
        """InvalidRequestError (model not found) through get_stream_response
        → LLM_INVALID_MODEL (via _classify_request_error, not _EXCEPTION_MAP)."""
        client = self._make_client_with_config()
        exc = InvalidRequestError(
            message="Model gpt-99 not found",
            model="gpt-99",
            llm_provider="openai",
        )

        with patch("broca.llm.acompletion", AsyncMock(side_effect=exc)):
            stream = client.get_stream_response(
                "openai", "gpt-4", [],
                first_chunk_timeout=10,
                timeout=30,
            )
            with pytest.raises(LLMError) as exc_info:
                await stream.__anext__()

        assert exc_info.value.info.code == ErrorCode.LLM_INVALID_MODEL

    async def test_unknown_exception_falls_back_to_llm_error(self):
        """Unrecognized exception → LLMError with generic LLM_ERROR code."""
        client = self._make_client_with_config()

        with patch("broca.llm.acompletion", AsyncMock(side_effect=RuntimeError("mystery"))):
            stream = client.get_stream_response(
                "openai", "gpt-4", [],
                first_chunk_timeout=10,
                timeout=30,
            )
            with pytest.raises(LLMError) as exc_info:
                await stream.__anext__()

        assert exc_info.value.info.code == ErrorCode.LLM_ERROR
