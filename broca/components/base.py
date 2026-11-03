"""Base component class for all plugin interfaces."""

from __future__ import annotations


class BaseComponent:
    """Base class for all component interfaces.

    Provides a unified lifecycle contract:
    - ``initialize(**deps)``: idempotent hook called by the composition root
      (``Agent.create()``) in topological order to inject runtime dependencies.
    - ``shutdown()``: optional cleanup, only needed by components that hold
      persistent resources (e.g. ``Communicator``, ``SessionRunner``,
      ``ProcessManager``).

    The registry (``ComponentRegistry.get()``) is responsible for **construction**
    only.  Runtime dependencies (agent, session, communicator) are always injected
    via ``initialize()`` — never via constructor arguments.
    """

    async def initialize(self, **deps) -> None:
        """Inject runtime dependencies.

        This method must be **idempotent** — calling it multiple times must not
        produce side-effects.

        Args:
            **deps: Component-specific keyword arguments.  The exact set depends
                on each concrete interface (see its ``initialize`` override).
        """

    async def shutdown(self) -> None:
        """Release resources held by this component.

        Only components that need cleanup should override this method.
        The default implementation is a no-op.
        """
