"""Error types for the component plugin system."""


class ComponentError(Exception):
    """Base error for component-related failures."""


class ComponentNotFoundError(ComponentError):
    """Raised when no implementation can be resolved for a component interface."""


class ComponentScopeError(ComponentError):
    """Raised when a scope_key is required but missing for a scoped component."""
