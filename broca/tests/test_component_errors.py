"""
Regression tests for ComponentError integration with BrocaError hierarchy.

Verifies that ComponentNotFoundError and ComponentScopeError:
1. Are catchable by `except BrocaError`
2. Have correct default ErrorCode values
3. Maintain backward-compatible import paths
"""

import pytest

from broca.errors import BrocaError, ComponentError, ErrorCode
from broca.components.errors import (
    ComponentError as ComponentErrorFromComponents,
    ComponentNotFoundError,
    ComponentScopeError,
)


class TestComponentErrorInheritance:
    """ComponentError and its subclasses are part of the BrocaError hierarchy."""

    def test_component_error_is_broca_error(self):
        """ComponentError is a subclass of BrocaError."""
        assert issubclass(ComponentError, BrocaError)

    def test_not_found_error_catchable_as_broca_error(self):
        """ComponentNotFoundError can be caught by `except BrocaError`."""
        with pytest.raises(BrocaError):
            raise ComponentNotFoundError("FooTool")

    def test_scope_error_catchable_as_broca_error(self):
        """ComponentScopeError can be caught by `except BrocaError`."""
        with pytest.raises(BrocaError):
            raise ComponentScopeError("missing scope")

    def test_component_error_catchable_as_broca_error(self):
        """Base ComponentError can be caught by `except BrocaError`."""
        with pytest.raises(BrocaError):
            raise ComponentError("generic component error")


class TestComponentErrorCodes:
    """ComponentError subclasses have correct default ErrorCode values."""

    def test_not_found_error_code(self):
        """ComponentNotFoundError has COMPONENT_NOT_FOUND code."""
        err = ComponentNotFoundError("MissingTool")
        assert err.error_code == ErrorCode.COMPONENT_NOT_FOUND

    def test_scope_error_code(self):
        """ComponentScopeError has COMPONENT_SCOPE_ERROR code."""
        err = ComponentScopeError("no scope")
        assert err.error_code == ErrorCode.COMPONENT_SCOPE_ERROR

    def test_base_error_code(self):
        """Base ComponentError has COMPONENT_ERROR code."""
        err = ComponentError("something wrong")
        assert err.error_code == ErrorCode.COMPONENT_ERROR


class TestComponentErrorUserMessage:
    """ComponentError subclasses produce meaningful user messages."""

    def test_scope_error_to_user_message(self):
        """ComponentScopeError.to_user_message() returns a meaningful message."""
        # No custom message → falls back to default_message from ErrorCode
        err = ComponentScopeError()
        msg = err.to_user_message()
        assert msg  # non-empty
        assert "组件作用域错误" in msg  # default_message from ErrorCode

    def test_scope_error_custom_message(self):
        """ComponentScopeError with custom message uses it."""
        err = ComponentScopeError("scope 'abc' is missing")
        msg = err.to_user_message()
        assert "scope 'abc' is missing" in msg

    def test_not_found_error_to_user_message(self):
        """ComponentNotFoundError.to_user_message() includes recovery hint."""
        err = ComponentNotFoundError("MyTool")
        msg = err.to_user_message()
        assert "请检查组件配置" in msg  # recovery_hint


class TestBackwardCompatibleImports:
    """Import paths remain backward-compatible."""

    def test_import_from_components_errors(self):
        """from broca.components.errors import ComponentNotFoundError works."""
        from broca.components.errors import ComponentNotFoundError as CNF

        assert CNF is ComponentNotFoundError

    def test_import_from_broca_errors(self):
        """from broca.errors import ComponentError works."""
        from broca.errors import ComponentError as CE

        assert CE is ComponentError

    def test_components_errors_reexports_base(self):
        """broca.components.errors.ComponentError is the same class as broca.errors.ComponentError."""
        assert ComponentErrorFromComponents is ComponentError
