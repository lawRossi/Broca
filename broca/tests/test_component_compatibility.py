"""Component compatibility verification tests.

Parametrized over all (interface, default_impl) pairs in
``DEFAULT_IMPLEMENTATIONS`` to verify:
- issubclass relationship
- No unimplemented abstract methods
- Signature compatibility (ABC params ⊆ impl params)
- ComponentRegistry.resolve consistency
- Valid scope values
- Key set consistency between DEFAULT_IMPLEMENTATIONS and COMPONENT_SCOPES
"""

from __future__ import annotations

import inspect
import pytest

from broca.components.defaults import (
    COMPONENT_SCOPES,
    DEFAULT_IMPLEMENTATIONS,
    ENTRY_POINT_NAMES,
)
from broca.components.registry import ComponentRegistry

VALID_SCOPES = {"singleton", "per-agent", "per-session", "transient"}


def _get_test_id(interface_cls):
    return interface_cls.__name__


#: Interfaces whose default implementation is a *different* class.
#:
#: Self-mapped interfaces (``impl is iface``, e.g. ``Orchestrator``) are excluded
#: from the issubclass / abstract-method / signature checks: with ``impl is iface``
#: those assertions are trivially true, so parametrizing over them only produced
#: permanently-skipped tests. ``test_registry_resolve`` / ``test_scope_valid``
#: still cover every key.
SUBCLASS_CHECKED = [
    iface for iface, impl in DEFAULT_IMPLEMENTATIONS.items() if impl is not iface
]
SUBCLASS_CHECKED_IDS = [_get_test_id(i) for i in SUBCLASS_CHECKED]


def _get_abstractmethod_params(abc_cls: type) -> dict[str, set[str]]:
    """For each abstract method, get the set of parameter names (excluding **kwargs and properties)."""
    result = {}
    for name in abc_cls.__abstractmethods__:
        method = getattr(abc_cls, name, None)
        if method is None:
            continue
        # Skip properties (not callable)
        if isinstance(method, property):
            continue
        try:
            sig = inspect.signature(method)
        except (TypeError, ValueError):
            continue
        params = set()
        for p_name, p in sig.parameters.items():
            if p_name == "self":
                continue
            # Skip **kwargs (VAR_KEYWORD) - they accept anything
            if p.kind == inspect.Parameter.VAR_KEYWORD:
                continue
            params.add(p_name)
        result[name] = params
    return result


def _get_impl_method_params(impl_cls: type, method_name: str) -> set[str]:
    """Get parameter names for a method on the implementation class (excluding **kwargs)."""
    method = getattr(impl_cls, method_name, None)
    if method is None or isinstance(method, property):
        return set()
    try:
        sig = inspect.signature(method)
    except (TypeError, ValueError):
        return set()
    return {
        name
        for name, p in sig.parameters.items()
        if name != "self"
        and p.kind != inspect.Parameter.VAR_KEYWORD
    }


class TestComponentCompatibility:
    """Parametrized compatibility checks for all registered components."""

    @pytest.mark.parametrize(
        "interface_cls",
        SUBCLASS_CHECKED,
        ids=SUBCLASS_CHECKED_IDS,
    )
    def test_issubclass(self, interface_cls):
        """Default impl must be a subclass of the interface ABC."""
        impl_cls = DEFAULT_IMPLEMENTATIONS[interface_cls]
        assert issubclass(impl_cls, interface_cls), (
            f"{impl_cls.__name__} is not a subclass of {interface_cls.__name__}"
        )

    @pytest.mark.parametrize(
        "interface_cls",
        SUBCLASS_CHECKED,
        ids=SUBCLASS_CHECKED_IDS,
    )
    def test_no_abstract_methods(self, interface_cls):
        """Default impl must have no unimplemented abstract methods."""
        impl_cls = DEFAULT_IMPLEMENTATIONS[interface_cls]
        abstract = impl_cls.__abstractmethods__
        assert abstract == frozenset(), (
            f"{impl_cls.__name__} has unimplemented abstract methods: {abstract}"
        )

    @pytest.mark.parametrize(
        "interface_cls",
        SUBCLASS_CHECKED,
        ids=SUBCLASS_CHECKED_IDS,
    )
    def test_signature_compatibility(self, interface_cls):
        """ABC abstract method params must be subset of impl method params.

        The impl may have additional params (with defaults) but must accept
        all params that the ABC declares.
        """
        impl_cls = DEFAULT_IMPLEMENTATIONS[interface_cls]

        abc_params = _get_abstractmethod_params(interface_cls)

        for method_name, abc_param_set in abc_params.items():
            if not abc_param_set:
                continue
            impl_param_set = _get_impl_method_params(impl_cls, method_name)
            missing = abc_param_set - impl_param_set
            # Allow **kwargs to cover any missing params
            impl_method = getattr(impl_cls, method_name, None)
            if impl_method is not None:
                sig = inspect.signature(impl_method)
                has_var_kw = any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                )
                if has_var_kw:
                    continue
            assert not missing, (
                f"{impl_cls.__name__}.{method_name}() missing params "
                f"{missing} required by {interface_cls.__name__}"
            )

    @pytest.mark.parametrize(
        "interface_cls",
        list(DEFAULT_IMPLEMENTATIONS.keys()),
        ids=[_get_test_id(i) for i in DEFAULT_IMPLEMENTATIONS.keys()],
    )
    def test_registry_resolve(self, interface_cls, fresh_registry):
        """ComponentRegistry.resolve must return the same class as defaults.py."""
        resolved = fresh_registry.resolve(interface_cls)
        expected = DEFAULT_IMPLEMENTATIONS[interface_cls]
        assert resolved is expected, (
            f"Registry resolved {resolved.__name__} but defaults.py expects "
            f"{expected.__name__}"
        )

    @pytest.mark.parametrize(
        "interface_cls",
        list(COMPONENT_SCOPES.keys()),
        ids=[_get_test_id(i) for i in COMPONENT_SCOPES.keys()],
    )
    def test_scope_valid(self, interface_cls):
        """COMPONENT_SCOPES value must be a valid scope string."""
        scope = COMPONENT_SCOPES[interface_cls]
        assert scope in VALID_SCOPES, (
            f"Invalid scope '{scope}' for {interface_cls.__name__}"
        )


class TestComponentRegistryConsistency:
    """Cross-cutting consistency checks."""

    def test_key_sets_match(self):
        """DEFAULT_IMPLEMENTATIONS and COMPONENT_SCOPES must have identical keys."""
        assert set(DEFAULT_IMPLEMENTATIONS.keys()) == set(COMPONENT_SCOPES.keys()), (
            f"Key mismatch:\n"
            f"  only in DEFAULT_IMPLEMENTATIONS: "
            f"{set(DEFAULT_IMPLEMENTATIONS.keys()) - set(COMPONENT_SCOPES.keys())}\n"
            f"  only in COMPONENT_SCOPES: "
            f"{set(COMPONENT_SCOPES.keys()) - set(DEFAULT_IMPLEMENTATIONS.keys())}"
        )

    def test_entry_point_names_cover_all(self):
        """Every interface in COMPONENT_SCOPES must have an entry point name."""
        missing = set(COMPONENT_SCOPES.values() and COMPONENT_SCOPES.keys()) - set(
            ENTRY_POINT_NAMES.values()
        )
        assert not missing, (
            f"Interfaces without entry point names: "
            f"{[i.__name__ for i in missing]}"
        )
