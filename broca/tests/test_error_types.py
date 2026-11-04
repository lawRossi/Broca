"""
Regression tests for ErrorInfo.from_exception() traceback capture fix.

Bug: Previously `traceback.format_exc()` was used, which captures the current
call stack (i.e. the stack of `from_exception` itself) rather than the original
exception's stack. Fixed by using `traceback.format_exception(type(cause), cause, cause.__traceback__)`.
"""

import pytest

from broca.errors import ErrorCode, ToolError
from broca.errors.types import ErrorInfo


def _raise_in_helper():
    """A helper function whose name appears in the traceback."""
    raise ValueError("original error from helper")


class TestErrorInfoFromException:
    """Tests for ErrorInfo.from_exception() traceback correctness."""

    def test_traceback_contains_original_exception_frame(self):
        """traceback_str should contain the frame where the exception was raised."""
        try:
            _raise_in_helper()
        except ValueError as e:
            info = ErrorInfo.from_exception(
                code=ErrorCode.TOOL_ERROR,
                message="Tool failed",
                cause=e,
            )

        assert info.traceback_str is not None
        # The traceback should contain the helper function's name
        assert "_raise_in_helper" in info.traceback_str
        # Should NOT just be the from_exception call stack
        # (the key regression: old code would show `from_exception` frames only)
        assert "test_error_types" in info.traceback_str

    def test_traceback_contains_file_path(self):
        """traceback_str should contain the source file path of the raising function."""
        try:
            _raise_in_helper()
        except ValueError as e:
            info = ErrorInfo.from_exception(
                code=ErrorCode.TOOL_ERROR,
                cause=e,
            )

        assert info.traceback_str is not None
        # Should contain this test file's path
        assert "test_error_types" in info.traceback_str

    def test_traceback_none_when_no_cause(self):
        """When cause=None, traceback_str should be None."""
        info = ErrorInfo.from_exception(
            code=ErrorCode.TOOL_ERROR,
            message="No cause",
            cause=None,
        )
        assert info.traceback_str is None

    def test_broca_error_cause_traceback(self):
        """BrocaError(cause=e) should preserve the original exception's traceback."""

        def _raise_custom():
            raise RuntimeError("custom runtime error")

        try:
            _raise_custom()
        except RuntimeError as original:
            tool_error = ToolError(
                "Tool execution failed",
                cause=original,
            )

        assert tool_error.info.traceback_str is not None
        # Should contain the _raise_custom frame
        assert "_raise_custom" in tool_error.info.traceback_str
        # Should contain this file
        assert "test_error_types" in tool_error.info.traceback_str

    def test_cause_msg_stored(self):
        """cause_msg should contain the string representation of the cause."""
        caught_exc = None
        try:
            _raise_in_helper()
        except ValueError as e:
            caught_exc = e
            info = ErrorInfo.from_exception(
                code=ErrorCode.TOOL_ERROR,
                cause=e,
            )

        assert info.cause_msg == "original error from helper"
        assert info.cause_exc is caught_exc

    def test_cause_exc_stored(self):
        """cause_exc should hold the original exception object."""
        try:
            _raise_in_helper()
        except ValueError as e:
            info = ErrorInfo.from_exception(
                code=ErrorCode.TOOL_ERROR,
                cause=e,
            )

        assert isinstance(info.cause_exc, ValueError)
