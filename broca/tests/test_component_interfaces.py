"""Component interface signature compatibility tests.

Verifies that the ABC method signatures in ``broca/components/`` are
compatible with the **existing implementation classes** that already have
concrete implementations (Phase 1 only covers 5 of 7 interfaces —
``ToolExecutor`` and ``ContextCompressor`` implementation classes are
created in Phase 2/3 respectively, so they are skipped here).

For the 5 testable interfaces, we use ``inspect.signature`` to compare
ABC abstract method parameter names against the existing implementation
parameter names.  The implementation is allowed to have **extra
parameters with default values** (e.g. internal tuning knobs), but must
not be missing any ABC parameter.
"""

from __future__ import annotations

import inspect
import pytest


# ---------------------------------------------------------------------------
# Helper: check that every ABC abstract method param exists in the
# implementation (by name), allowing the impl to have extra params with
# default values.
# ---------------------------------------------------------------------------


def _check_method_compatibility(abc_cls, impl_cls, method_name, label=""):
    """Assert that ``abc_cls.method_name`` parameters are a subset of
    ``impl_cls.method_name`` parameters (by name).

    Extra parameters in the implementation are allowed **only** if they
    have default values.
    """
    abc_method = getattr(abc_cls, method_name, None)
    impl_method = getattr(impl_cls, method_name, None)

    if abc_method is None:
        pytest.fail(f"[{label}] ABC {abc_cls.__name__} has no '{method_name}'")
    if impl_method is None:
        pytest.fail(f"[{label}] Impl {impl_cls.__name__} has no '{method_name}'")

    abc_sig = inspect.signature(abc_method)
    impl_sig = inspect.signature(impl_method)

    abc_params = set(abc_sig.parameters.keys()) - {"self"}
    impl_params = set(impl_sig.parameters.keys()) - {"self"}

    missing = abc_params - impl_params
    assert not missing, (
        f"[{label}] {abc_cls.__name__}.{method_name} parameters "
        f"{missing} not found in {impl_cls.__name__}.{method_name} "
        f"(impl has {impl_params})"
    )

    # Check that extra params in impl have default values
    for param_name in impl_params - abc_params:
        param = impl_sig.parameters[param_name]
        assert param.default is not inspect.Parameter.empty, (
            f"[{label}] Extra param '{param_name}' in "
            f"{impl_cls.__name__}.{method_name} must have a default value"
        )


def _check_properties(abc_cls, impl_cls, label=""):
    """Check that all ABC properties exist on the implementation."""
    for name in dir(abc_cls):
        if name.startswith("_"):
            continue
        abc_attr = getattr(abc_cls, name, None)
        if isinstance(abc_attr, property):
            impl_attr = getattr(impl_cls, name, None)
            assert impl_attr is not None, (
                f"[{label}] {abc_cls.__name__} has property '{name}' "
                f"but {impl_cls.__name__} does not"
            )


# ---------------------------------------------------------------------------
# Fixtures: lazy-import existing implementation classes
# ---------------------------------------------------------------------------


def _get_impl_classes():
    """Import the 5 existing implementation classes that Phase 1
    ABCs should be compatible with.

    - LLMClient → broca.llm.LLMClient
    - PermissionProvider → broca.permission_manager.PermissionManager
      + broca.tools.tool_permission_manager.ToolPermissionManager
      (merged; we test both against the relevant subset)
    - Communicator → broca.communication.socketio_client.SocketIOClient
    - LoopEngine → broca.loop_engine.LoopEngine
    - AgentFactory → broca.agent_manager.AgentFactory
    """
    from broca.agent_manager import AgentFactory as ImplAgentFactory
    from broca.communication.socketio_client import (
        SocketIOClient as ImplCommunicator,
    )
    from broca.llm import LLMClient as ImplLLMClient
    from broca.loop_engine import DefaultLoopEngine as ImplLoopEngine
    from broca.permission_manager import PermissionManager as ImplPermissionManager
    from broca.tools.tool_permission_manager import (
        ToolPermissionManager as ImplToolPermissionManager,
    )

    return {
        "LLMClient": ImplLLMClient,
        "PermissionManager": ImplPermissionManager,
        "ToolPermissionManager": ImplToolPermissionManager,
        "Communicator": ImplCommunicator,
        "LoopEngine": ImplLoopEngine,
        "AgentFactory": ImplAgentFactory,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLLMClientCompatibility:
    """Verify LLMClient ABC is compatible with broca.llm.LLMClient."""

    def test_get_stream_response(self):
        from broca.components.llm_client import LLMClient as ABC

        impl = _get_impl_classes()["LLMClient"]
        _check_method_compatibility(
            ABC, impl, "get_stream_response", label="LLMClient"
        )

    def test_aggregate_message(self):
        from broca.components.llm_client import LLMClient as ABC

        impl = _get_impl_classes()["LLMClient"]
        _check_method_compatibility(
            ABC, impl, "aggregate_message", label="LLMClient"
        )

    def test_config_property(self):
        from broca.llm import LiteLLMClient

        # 'config' is an instance attribute set in __init__ (not on ABC).
        # Verify the class source includes self.config assignment.
        import inspect

        source = inspect.getsource(LiteLLMClient.__init__)
        assert "self.config" in source


class TestPermissionProviderCompatibility:
    """Verify PermissionProvider ABC is compatible with the merged
    PermissionManager + ToolPermissionManager."""

    def test_request_permission(self):
        from broca.components.permission_provider import (
            PermissionProvider as ABC,
        )

        impl = _get_impl_classes()["PermissionManager"]
        _check_method_compatibility(
            ABC, impl, "request_permission", label="PermissionProvider"
        )

    def test_request_tool_permission(self):
        from broca.components.permission_provider import (
            PermissionProvider as ABC,
        )

        impl = _get_impl_classes()["PermissionManager"]
        _check_method_compatibility(
            ABC, impl, "request_tool_permission", label="PermissionProvider"
        )

    def test_get_permission(self):
        from broca.components.permission_provider import (
            PermissionProvider as ABC,
        )

        # get_permission is on ToolPermissionManager
        impl = _get_impl_classes()["ToolPermissionManager"]
        _check_method_compatibility(
            ABC, impl, "get_permission", label="PermissionProvider"
        )

    def test_set_session_override(self):
        from broca.components.permission_provider import (
            PermissionProvider as ABC,
        )

        impl = _get_impl_classes()["ToolPermissionManager"]
        _check_method_compatibility(
            ABC, impl, "set_session_override", label="PermissionProvider"
        )

    def test_clear_session_overrides(self):
        from broca.components.permission_provider import (
            PermissionProvider as ABC,
        )

        impl = _get_impl_classes()["ToolPermissionManager"]
        _check_method_compatibility(
            ABC, impl, "clear_session_overrides", label="PermissionProvider"
        )


class TestCommunicatorCompatibility:
    """Verify Communicator ABC is compatible with SocketIOClient."""

    def test_agent_id_property(self):
        from broca.components.communicator import Communicator as ABC

        # In Phase 4.3, agent_id was changed from @property to a plain
        # attribute annotation on the ABC.  Verify it's declared.
        assert "agent_id" in ABC.__annotations__ or hasattr(ABC, "agent_id")

    def test_connect(self):
        from broca.components.communicator import Communicator as ABC

        impl = _get_impl_classes()["Communicator"]
        _check_method_compatibility(ABC, impl, "connect", label="Communicator")

    def test_disconnect(self):
        from broca.components.communicator import Communicator as ABC

        impl = _get_impl_classes()["Communicator"]
        _check_method_compatibility(ABC, impl, "disconnect", label="Communicator")

    def test_is_connected(self):
        from broca.components.communicator import Communicator as ABC

        impl = _get_impl_classes()["Communicator"]
        _check_method_compatibility(
            ABC, impl, "is_connected", label="Communicator"
        )

    def test_send_message(self):
        from broca.components.communicator import Communicator as ABC

        impl = _get_impl_classes()["Communicator"]
        _check_method_compatibility(
            ABC, impl, "send_message", label="Communicator"
        )

    def test_send_tool_call(self):
        from broca.components.communicator import Communicator as ABC

        impl = _get_impl_classes()["Communicator"]
        _check_method_compatibility(
            ABC, impl, "send_tool_call", label="Communicator"
        )

    def test_send_error(self):
        from broca.components.communicator import Communicator as ABC

        impl = _get_impl_classes()["Communicator"]
        _check_method_compatibility(ABC, impl, "send_error", label="Communicator")


class TestLoopEngineCompatibility:
    """Verify LoopEngine ABC is compatible with broca.loop_engine.LoopEngine."""

    def test_execute(self):
        from broca.components.loop_engine import LoopEngine as ABC

        impl = _get_impl_classes()["LoopEngine"]
        _check_method_compatibility(ABC, impl, "execute", label="LoopEngine")

    def test_abort(self):
        from broca.components.loop_engine import LoopEngine as ABC

        impl = _get_impl_classes()["LoopEngine"]
        _check_method_compatibility(ABC, impl, "abort", label="LoopEngine")

    def test_reset(self):
        from broca.components.loop_engine import LoopEngine as ABC

        impl = _get_impl_classes()["LoopEngine"]
        _check_method_compatibility(ABC, impl, "reset", label="LoopEngine")


class TestAgentFactoryCompatibility:
    """Verify AgentFactory ABC is compatible with broca.agent_manager.AgentFactory."""

    def test_create_agent(self):
        from broca.components.agent_factory import AgentFactory as ABC

        impl = _get_impl_classes()["AgentFactory"]
        _check_method_compatibility(
            ABC, impl, "create_agent", label="AgentFactory"
        )

    def test_restore_agents_from_session(self):
        from broca.components.agent_factory import AgentFactory as ABC

        impl = _get_impl_classes()["AgentFactory"]
        _check_method_compatibility(
            ABC, impl, "restore_agents_from_session", label="AgentFactory"
        )


# ---------------------------------------------------------------------------
# Import smoke test
# ---------------------------------------------------------------------------


class TestComponentImports:
    """Verify all component interfaces can be imported."""

    def test_import_all_abc(self):
        from broca.components import (
            AgentFactory,
            Communicator,
            ContextCompressor,
            LLMClient,
            LoopEngine,
            PermissionProvider,
            ToolExecutor,
        )

        assert AgentFactory is not None
        assert Communicator is not None
        assert ContextCompressor is not None
        assert LLMClient is not None
        assert LoopEngine is not None
        assert PermissionProvider is not None
        assert ToolExecutor is not None

    def test_import_protocols(self):
        from broca.components import (
            AgentReference,
            CompressorContext,
            ExecutionContext,
            PermissionContext,
        )

        assert AgentReference is not None
        assert CompressorContext is not None
        assert ExecutionContext is not None
        assert PermissionContext is not None

    def test_import_errors(self):
        from broca.components import (
            ComponentError,
            ComponentNotFoundError,
            ComponentScopeError,
        )

        assert issubclass(ComponentNotFoundError, ComponentError)
        assert issubclass(ComponentScopeError, ComponentError)

    def test_tool_executor_execute_tool_signature(self):
        """Verify ToolExecutor.execute_tool has the required params."""
        from broca.components.tool_executor import ToolExecutor

        sig = inspect.signature(ToolExecutor.execute_tool)
        params = set(sig.parameters.keys()) - {"self"}

        assert "tool_name" in params
        assert "arguments" in params
        assert "tool_call_id" in params
        assert "context" in params
        assert "tool" in params
        assert "allowed_tools" in params

        # allowed_tools must have a default (per-run, optional)
        assert sig.parameters["allowed_tools"].default is not inspect.Parameter.empty

    def test_tool_executor_initialize_signature(self):
        """Verify ToolExecutor.initialize params match the contract:
        (tool_mapping, permission_provider, config, communicator) —
        NO allowed_tools."""
        from broca.components.tool_executor import ToolExecutor

        sig = inspect.signature(ToolExecutor.initialize)
        params = set(sig.parameters.keys()) - {"self"}

        assert "tool_mapping" in params
        assert "permission_provider" in params
        assert "config" in params
        assert "communicator" in params
        # allowed_tools must NOT be in initialize
        assert "allowed_tools" not in params

    def test_context_compressor_no_force_compress(self):
        """ContextCompressor must NOT have an abstract force_compress method."""
        from broca.components.context_compressor import ContextCompressor

        abstract_methods = ContextCompressor.__abstractmethods__
        assert "force_compress" not in abstract_methods, (
            "ContextCompressor must not have abstract force_compress; "
            "use check_and_compress(force=True) instead"
        )

    def test_agent_reference_turn_id_readable_writable(self):
        """AgentReference Protocol must declare turn_id with getter and setter."""
        from broca.components.protocols import AgentReference

        # turn_id is declared as a @property with a setter in the Protocol,
        # so it won't appear in __annotations__.  Check the class's
        # __dict__ for the property descriptor.
        cls_dict = AgentReference.__dict__
        assert "turn_id" in cls_dict, (
            "AgentReference must define turn_id as a property (in class __dict__)"
        )
        turn_id_prop = cls_dict["turn_id"]
        # A property with a setter has both fget and fset
        assert turn_id_prop.fget is not None, "turn_id must have a getter"
        assert turn_id_prop.fset is not None, "turn_id must have a setter"

    def test_agent_reference_last_context_length(self):
        """AgentReference must have last_context_length."""
        from broca.components.protocols import AgentReference

        annotations = AgentReference.__annotations__
        assert "last_context_length" in annotations, (
            "AgentReference must annotate last_context_length"
        )
