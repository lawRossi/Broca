"""Task 5.6: safe_call supports dynamic details.

Two mechanisms (can be used together or independently):
  1. **Decorator param** — ``details`` accepts ``Callable[[Exception], dict]``,
     receiving the exception to build context-rich details.
  2. **Call-site kwarg** — pass ``_details={"key": "val"}`` at call time;
     overrides decorator-level details and is NOT forwarded to the wrapped
     function.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from broca.errors.exceptions import BrocaError, ToolError
from broca.errors.types import ErrorCode
from broca.errors.utils import safe_call


class TestSafeCallCallableDetails:
    """Decorator-param callable details (receives exception)."""

    def test_callable_details_sync(self) -> None:
        @safe_call(
            error_class=ToolError,
            error_code=ErrorCode.TOOL_ERROR,
            message="failed",
            details=lambda e: {"error": str(e), "type": type(e).__name__},
        )
        def bad() -> None:
            raise ValueError("boom")

        with pytest.raises(ToolError) as exc_info:
            bad()
        assert exc_info.value.info.details == {"error": "boom", "type": "ValueError"}

    @pytest.mark.asyncio
    async def test_callable_details_async(self) -> None:
        @safe_call(
            error_class=ToolError,
            error_code=ErrorCode.TOOL_ERROR,
            message="failed",
            details=lambda e: {"error": str(e)},
        )
        async def bad() -> None:
            raise RuntimeError("async boom")

        with pytest.raises(ToolError) as exc_info:
            await bad()
        assert exc_info.value.info.details == {"error": "async boom"}

    def test_static_details_still_works(self) -> None:
        @safe_call(
            error_class=ToolError,
            error_code=ErrorCode.TOOL_ERROR,
            message="failed",
            details={"static": True},
        )
        def bad() -> None:
            raise ValueError("x")

        with pytest.raises(ToolError) as exc_info:
            bad()
        assert exc_info.value.info.details == {"static": True}

    def test_no_details(self) -> None:
        @safe_call(error_class=ToolError, error_code=ErrorCode.TOOL_ERROR)
        def bad() -> None:
            raise ValueError("x")

        with pytest.raises(ToolError) as exc_info:
            bad()
        assert exc_info.value.info.details is None

    def test_broca_error_passthrough(self) -> None:
        @safe_call(
            error_class=ToolError,
            error_code=ErrorCode.TOOL_ERROR,
            details=lambda e: {"error": str(e)},
        )
        def raises_broca() -> None:
            raise BrocaError(message="original", error_code=ErrorCode.PERMISSION_DENIED)

        with pytest.raises(BrocaError) as exc_info:
            raises_broca()
        assert exc_info.value.message == "original"


class TestSafeCallDetailsKwarg:
    """Call-site ``_details`` kwarg: overrides decorator-level details,
    is NOT forwarded to the wrapped function."""

    def test_details_kwarg_sync(self) -> None:
        @safe_call(
            error_class=ToolError,
            error_code=ErrorCode.TOOL_ERROR,
            message="failed",
            details={"static": 1},
        )
        def bad() -> None:
            raise ValueError("boom")

        with pytest.raises(ToolError) as exc_info:
            bad(_details={"dynamic": 2})
        # Dynamic overrides static
        assert exc_info.value.info.details == {"dynamic": 2}

    @pytest.mark.asyncio
    async def test_details_kwarg_async(self) -> None:
        @safe_call(
            error_class=ToolError,
            error_code=ErrorCode.TOOL_ERROR,
            message="failed",
            details={"static": 1},
        )
        async def bad() -> None:
            raise ValueError("boom")

        with pytest.raises(ToolError) as exc_info:
            await bad(_details={"dynamic": 2})
        assert exc_info.value.info.details == {"dynamic": 2}

    def test_details_kwarg_overrides_callable(self) -> None:
        @safe_call(
            error_class=ToolError,
            error_code=ErrorCode.TOOL_ERROR,
            message="failed",
            details=lambda e: {"from_callable": str(e)},
        )
        def bad() -> None:
            raise ValueError("boom")

        with pytest.raises(ToolError) as exc_info:
            bad(_details={"from_kwarg": True})
        assert exc_info.value.info.details == {"from_kwarg": True}

    def test_details_kwarg_not_forwarded_to_function(self) -> None:
        """``_details`` must NOT be passed to the wrapped function."""
        mock_fn = MagicMock(side_effect=ValueError("boom"))

        @safe_call(
            error_class=ToolError,
            error_code=ErrorCode.TOOL_ERROR,
            message="failed",
        )
        def target(**kwargs: Any) -> None:
            mock_fn(**kwargs)

        with pytest.raises(ToolError):
            target(_details={"x": 1})

        # mock_fn should NOT have received _details
        assert "_details" not in (mock_fn.call_args.kwargs if mock_fn.call_args else {})

    @pytest.mark.asyncio
    async def test_details_kwarg_not_forwarded_async(self) -> None:
        """``_details`` must NOT be passed to the async wrapped function."""
        mock_fn = MagicMock(side_effect=ValueError("boom"))

        @safe_call(
            error_class=ToolError,
            error_code=ErrorCode.TOOL_ERROR,
            message="failed",
        )
        async def target(**kwargs: Any) -> None:
            mock_fn(**kwargs)

        with pytest.raises(ToolError):
            await target(_details={"x": 1})

        assert "_details" not in (mock_fn.call_args.kwargs if mock_fn.call_args else {})

    def test_no_details_kwarg_behavior_unchanged(self) -> None:
        """Without ``_details`` kwarg, decorator-level details are used."""
        @safe_call(
            error_class=ToolError,
            error_code=ErrorCode.TOOL_ERROR,
            message="failed",
            details={"static": True},
        )
        def bad() -> None:
            raise ValueError("x")

        with pytest.raises(ToolError) as exc_info:
            bad()
        assert exc_info.value.info.details == {"static": True}

    def test_details_kwarg_no_decorator_details(self) -> None:
        """``_details`` works even when decorator has no ``details`` param."""
        @safe_call(error_class=ToolError, error_code=ErrorCode.TOOL_ERROR)
        def bad() -> None:
            raise ValueError("x")

        with pytest.raises(ToolError) as exc_info:
            bad(_details={"only": "from-kwarg"})
        assert exc_info.value.info.details == {"only": "from-kwarg"}
