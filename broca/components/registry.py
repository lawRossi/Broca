"""ComponentRegistry — unified plugin discovery, resolution, and scoped instantiation.

The registry is the central mechanism for:
1. **Discovery**: Finding third-party plugins via ``importlib.metadata.entry_points``.
2. **Resolution**: Selecting the implementation class for a given interface
   (priority: override > discovered plugin > default).
3. **Scoped instantiation**: Caching instances by ``(interface, scope_key)``
   so that per-agent components are never shared across agents.

**Lazy-loading hard constraint**: ``discover_plugins()`` only enumerates
``EntryPoint`` objects and **never calls ``ep.load()``**.  The actual
module import (``ep.load()``) happens only in ``resolve()`` and only for
the specific interface being resolved.  This ensures unused plugin modules
never enter ``sys.modules``.
"""

from __future__ import annotations

import importlib.metadata
from typing import Any, Literal, Optional

from broca.logging_config import get_logger

from broca.components.errors import ComponentNotFoundError, ComponentScopeError

logger = get_logger(__name__)

ComponentScope = Literal["singleton", "per-agent", "per-session", "transient"]


class ComponentRegistry:
    """Component registry — manages plugin discovery, resolution, and scoped instantiation."""

    _instance: Optional["ComponentRegistry"] = None

    def __init__(self) -> None:
        self._overrides: dict[type, type] = {}
        self._discovered: dict[type, type] = {}
        self._defaults: dict[type, type] = {}
        # Populated by register_defaults()
        self._scopes: dict[type, ComponentScope] = {}
        # Populated by defaults.ENTRY_POINT_NAMES
        self._name_to_interface: dict[str, type] = {}
        # Interface → EntryPoint (not yet loaded)
        self._entry_points: dict[type, Any] = {}
        # Sentinel: plugins discovered only once
        self._plugins_discovered: bool = False
        # Cache key = (interface, scope_key); singleton uses None as scope_key
        self._instances: dict[tuple[type, str | None], Any] = {}

    # ------------------------------------------------------------------
    # Singleton access
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "ComponentRegistry":
        """Get the global singleton ``ComponentRegistry`` instance."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance.register_defaults()
        return cls._instance

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_defaults(self) -> None:
        """Register built-in default implementations + scope mappings + entry point names."""
        from broca.components.defaults import (
            COMPONENT_SCOPES,
            DEFAULT_IMPLEMENTATIONS,
            ENTRY_POINT_NAMES,
        )

        self._defaults = dict(DEFAULT_IMPLEMENTATIONS)
        self._scopes = dict(COMPONENT_SCOPES)
        self._name_to_interface = dict(ENTRY_POINT_NAMES)

    def set_override(self, interface: type, impl: type) -> None:
        """Manually set an override for a specific interface (e.g. in tests)."""
        self._overrides[interface] = impl

    # ------------------------------------------------------------------
    # Plugin discovery (lazy — never calls ep.load())
    # ------------------------------------------------------------------

    def discover_plugins(self) -> None:
        """Discover third-party plugins via entry points.

        Only enumerates and caches ``EntryPoint`` objects.  **Never calls
        ``ep.load()``** (lazy-loading hard constraint).  The actual load
        happens in ``resolve()`` when a specific interface is first needed.

        Idempotent: repeated calls are no-ops (``_plugins_discovered`` sentinel).
        """
        if self._plugins_discovered:
            return
        try:
            eps = importlib.metadata.entry_points(group="broca.components")
        except Exception as e:
            logger.warning(f"Failed to enumerate entry points: {e}")
            self._plugins_discovered = True
            return

        for ep in eps:
            interface = self._name_to_interface.get(ep.name)
            if interface:
                self._entry_points[interface] = ep
                logger.debug(
                    f"Discovered plugin entry point: {ep.name} → {ep.value} "
                    f"(not loaded)"
                )
        self._plugins_discovered = True

    # ------------------------------------------------------------------
    # Config overrides
    # ------------------------------------------------------------------

    def load_config_overrides(self, workspace: str | None) -> None:
        """Load ``components.json`` configuration overrides.

        Priority (highest to lowest):
        1. ``BROCA_COMPONENTS_CONFIG`` env var (explicit path)
        2. ``{workspace}/.broca/components.json``
        3. ``~/.broca/components.json``

        File format::

            {
                "tool_executor": "my_package.executor:SandboxToolExecutor",
                "llm_client": "my_package.llm:LocalLLMClient"
            }

        On parse failure (bad JSON, unknown key, import error) the override
        is **skipped with a warning** — the default implementation is used.
        This ensures a broken config never prevents Agent startup.
        """
        import json
        import os
        from pathlib import Path

        # Collect candidate config paths in priority order
        config_paths: list[Path] = []

        # 1. From configs.json (components_config field)
        try:
            from broca.configs import get_configs
            cfg_path = get_configs().components_config
            if cfg_path:
                p = Path(cfg_path).expanduser()
                if p.exists():
                    config_paths.append(p)
        except Exception:
            pass

        # 2. Workspace-level
        if workspace:
            ws_config = Path(workspace) / ".broca" / "components.json"
            if ws_config.exists():
                config_paths.append(ws_config)

        # 3. Global (~/.broca)
        global_config = Path.home() / ".broca" / "components.json"
        if global_config.exists():
            config_paths.append(global_config)

        for config_path in config_paths:
            try:
                with open(config_path) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(
                    f"Failed to parse components config {config_path}: {e}. "
                    f"Using defaults."
                )
                continue

            for key, value in data.items():
                interface = self._name_to_interface.get(key)
                if interface is None:
                    logger.warning(
                        f"Unknown component key '{key}' in {config_path}. "
                        f"Available: {list(self._name_to_interface.keys())}"
                    )
                    continue

                try:
                    impl_cls = self._resolve_module_class(value)
                    self._overrides[interface] = impl_cls
                    logger.info(
                        f"Component override loaded: {key} → {value} "
                        f"(from {config_path})"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to load component '{key}' = '{value}' "
                        f"from {config_path}: {e}. Using default."
                    )

    @staticmethod
    def _resolve_module_class(value: str) -> type:
        """Resolve a ``"module:ClassName"`` or ``"module.ClassName"`` string
        to the actual class.

        Supports both ``pkg.mod:Class`` and ``pkg.mod.Class`` formats.
        """
        # Try "pkg.mod:Class" first
        if ":" in value:
            module_path, class_name = value.rsplit(":", 1)
        else:
            # "pkg.mod.Class" → split on last dot
            last_dot = value.rfind(".")
            if last_dot == -1:
                raise ValueError(
                    f"Cannot parse component reference '{value}'. "
                    f"Expected 'module:Class' or 'module.Class'."
                )
            module_path = value[:last_dot]
            class_name = value[last_dot + 1 :]

        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        if not isinstance(cls, type):
            raise TypeError(
                f"'{value}' resolved to {type(cls).__name__}, expected a class"
            )
        return cls

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(self, interface: type) -> type:
        """Resolve the implementation class for an interface.

        Priority: override > discovered (lazy ``ep.load()``) > default.

        **Lazy loading**: ``ep.load()`` is called **only** when this specific
        interface has a plugin entry point and is being resolved for the
        first time.  The result is cached in ``_discovered`` so subsequent
        calls don't re-import.

        Raises:
            ComponentNotFoundError: If no implementation is found.
        """
        # 1. Explicit override (config file / manual)
        if interface in self._overrides:
            return self._overrides[interface]

        # 2. Previously discovered (already loaded)
        if interface in self._discovered:
            return self._discovered[interface]

        # 3. Lazy-load from entry point (first resolve only)
        ep = self._entry_points.get(interface)
        if ep is not None:
            loaded = ep.load()
            self._discovered[interface] = loaded
            logger.info(
                f"Loaded plugin for {interface.__name__}: {ep.value}"
            )
            return loaded

        # 4. Default implementation
        if interface in self._defaults:
            return self._defaults[interface]

        raise ComponentNotFoundError(
            f"No implementation found for {interface.__name__}"
        )

    # ------------------------------------------------------------------
    # Scoped instantiation
    # ------------------------------------------------------------------

    def get(
        self,
        interface: type,
        scope_key: str | None = None,
        **kwargs,
    ) -> Any:
        """Get a component instance by interface, respecting its scope.

        - ``singleton`` → cache key = ``(interface, None)``
        - ``per-agent`` / ``per-session`` → cache key = ``(interface, scope_key)``;
          raises ``ComponentScopeError`` if ``scope_key`` is missing.
        - ``transient`` → no cache, new instance every call.

        ``**kwargs`` are passed to the constructor **only on first creation**;
        on cache hit they are ignored (debug log emitted).
        """
        scope = self._scopes.get(interface, "singleton")

        if scope in ("per-agent", "per-session") and scope_key is None:
            raise ComponentScopeError(
                f"{interface.__name__} is scoped '{scope}', scope_key is required"
            )

        if scope == "transient":
            return self.resolve(interface)(**kwargs)

        cache_key: tuple[type, str | None] = (
            interface,
            scope_key if scope != "singleton" else None,
        )

        if cache_key in self._instances:
            if kwargs:
                logger.debug(
                    f"{interface.__name__} cache hit, kwargs ignored: {kwargs}"
                )
            return self._instances[cache_key]

        impl_cls = self.resolve(interface)
        instance = impl_cls(**kwargs)
        self._instances[cache_key] = instance
        return instance

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def release(self, scope_key: str) -> None:
        """Release all per-agent / per-session instances under a scope_key.

        Called by ``Agent.disconnect()`` to prevent instance accumulation
        in long-running web servers.
        """
        keys_to_remove = [
            k for k in self._instances if k[1] == scope_key
        ]
        for k in keys_to_remove:
            self._instances.pop(k, None)
        if keys_to_remove:
            logger.debug(
                f"Released {len(keys_to_remove)} instance(s) for scope_key={scope_key!r}"
            )

    def reset(self) -> None:
        """Clear all cached instances, overrides, and discovery state.

        Intended for **test isolation** — call in fixture teardown to
        prevent state leaking between tests.
        """
        self._instances.clear()
        self._overrides.clear()
        self._discovered.clear()
        self._entry_points.clear()
        self._plugins_discovered = False
