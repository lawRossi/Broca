"""Error types for the component plugin system.

Note: ComponentError base class is defined in `broca.errors.exceptions` for
uniform integration with the BrocaError hierarchy. Re-exported here for
backward-compatible import paths.
"""

from broca.errors.exceptions import ComponentError  # noqa: F401
from broca.errors.types import ErrorCode


class ComponentNotFoundError(ComponentError):
    """Raised when no implementation can be resolved for a component interface."""
    default_error_code = ErrorCode.COMPONENT_NOT_FOUND


class ComponentScopeError(ComponentError):
    """Raised when a scope_key is required but missing for a scoped component."""
    default_error_code = ErrorCode.COMPONENT_SCOPE_ERROR
