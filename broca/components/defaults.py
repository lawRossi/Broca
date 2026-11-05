"""Default component implementations and scope mappings.

This module is the **single source of truth** for:
- Which default implementation class to use for each interface.
- What scope each component has (singleton / per-agent / per-session / transient).
- How entry point names map to interface types.

**Phase 1** populates only the 7 core components.  The remaining 16
components are added incrementally in Phase 5 / Phase 6.

> **Invariants** (tested in ``test_components_registry.py``):
> - ``COMPONENT_SCOPES`` entries must match the plan's "组件作用域与
>   生命周期契约" table exactly.
> - ``ENTRY_POINT_NAMES`` keys must be valid entry point names (lowercase,
>   underscores).
"""

from __future__ import annotations

from broca.components.agent_factory import AgentFactory
from broca.components.command_system import CommandSystem
from broca.components.communicator import Communicator
from broca.components.context_compressor import ContextCompressor
from broca.components.decision_provider import DecisionProvider
from broca.components.llm_client import LLMClient
from broca.components.loop_engine import LoopEngine
from broca.components.mcp_client import MCPClient
from broca.components.memory_manager import MemoryManager
from broca.components.orchestrator import Orchestrator
from broca.components.permission_provider import PermissionProvider
from broca.components.process_manager import ProcessManager
from broca.components.revert_service import RevertServiceABC
from broca.components.scheduler import SchedulerABC
from broca.components.session_manager import SessionManager
from broca.components.session_runner import SessionRunner
from broca.components.skill_manager import SkillManager
from broca.components.snapshot_manager import SnapshotManager
from broca.components.task_manager import TaskManager
from broca.components.tool_executor import ToolExecutor
from broca.components.tool_manager import ToolManager

# ---------------------------------------------------------------------------
# Default implementation mapping
# ---------------------------------------------------------------------------
# Phase 1: 7 core components.
# The values are **lazy-import strings** to avoid circular imports at module
# load time.  The actual classes are resolved by ``ComponentRegistry.resolve()``
# only when needed.

# Mapping: interface → fully qualified "module:ClassName"
_DEFAULT_IMPLS: dict[type, str] = {
    LLMClient: "broca.llm:LiteLLMClient",
    DecisionProvider: "broca.decision:DecisionClient",
    PermissionProvider: "broca.permission_provider:DefaultPermissionProvider",
    Communicator: "broca.communication.socketio_client:SocketIOClient",
    LoopEngine: "broca.loop_engine:DefaultLoopEngine",
    AgentFactory: "broca.agent_manager:DefaultAgentFactory",
    ToolExecutor: "broca.tools.executor:DefaultToolExecutor",
    ContextCompressor: "broca.context_compressor:SessionMemoryCompressor",
    MemoryManager: "broca.persistent_memory.manager:SubAgentMemoryManager",
    SnapshotManager: "broca.snapshot.manager:GitSnapshotManager",
    SessionManager: "broca.session.session_manager:SQLSessionManager",
    SkillManager: "broca.skill.skill_manager:FileSkillManager",
    ProcessManager: "broca.process_manager:LocalProcessManager",
    Orchestrator: "broca.orchestration.orchestrator:Orchestrator",
    SessionRunner: "broca.session_runner.manager:IPCSessionRunner",
    ToolManager: "broca.tools.tool_manager:AutoDiscoverToolManager",
    MCPClient: "broca.tools.mcp_client:StdMCPClient",
    CommandSystem: "broca.commands.manager:FileCommandSystem",
    TaskManager: "broca.task_manager:DBTaskManager",
    SchedulerABC: "broca.scheduler:Scheduler",
    RevertServiceABC: "broca.session.revert_service:SessionRevertService",
}


def _build_default_implementations() -> dict[type, type]:
    """Build the interface → default implementation class mapping.

    For interfaces that already have a concrete implementation in the codebase,
    we import and return that class.  For interfaces whose default implementation
    is the ABC itself (ToolExecutor, ContextCompressor — concrete impls come in
    Phase 2/3), we return the ABC as a placeholder.
    """
    import importlib

    result: dict[type, type] = {}
    for interface, ref in _DEFAULT_IMPLS.items():
        try:
            if ":" in ref:
                mod_path, cls_name = ref.rsplit(":", 1)
            else:
                mod_path, cls_name = ref.rsplit(".", 1)
            mod = importlib.import_module(mod_path)
            result[interface] = getattr(mod, cls_name)
        except ImportError:
            # Default impl not yet available (e.g. ToolExecutor/ContextCompressor
            # concrete classes come in Phase 2/3).  Fall back to the ABC itself.
            result[interface] = interface
    return result


DEFAULT_IMPLEMENTATIONS: dict[type, type] = _build_default_implementations()

# ---------------------------------------------------------------------------
# Component scope mapping
# ---------------------------------------------------------------------------
# Must match the plan's "组件作用域与生命周期契约" table exactly.
# Phase 1: 7 core components.  Phase 5 will add the remaining 16.

COMPONENT_SCOPES: dict[type, str] = {
    ToolExecutor: "per-agent",
    ContextCompressor: "per-agent",
    LLMClient: "singleton",
    DecisionProvider: "singleton",
    PermissionProvider: "per-agent",
    Communicator: "per-agent",
    LoopEngine: "per-agent",
    AgentFactory: "singleton",
    MemoryManager: "per-agent",
    SnapshotManager: "per-agent",
    SessionManager: "per-session",
    SkillManager: "singleton",
    ProcessManager: "singleton",
    Orchestrator: "singleton",
    SessionRunner: "singleton",
    ToolManager: "per-agent",
    MCPClient: "per-agent",
    CommandSystem: "per-agent",
    TaskManager: "per-session",
    SchedulerABC: "singleton",
    RevertServiceABC: "per-agent",
}

# ---------------------------------------------------------------------------
# Entry point name → interface mapping
# ---------------------------------------------------------------------------
# Used by ``ComponentRegistry.discover_plugins()`` to resolve ``ep.name``
# to the corresponding interface type.

ENTRY_POINT_NAMES: dict[str, type] = {
    "tool_executor": ToolExecutor,
    "context_compressor": ContextCompressor,
    "llm_client": LLMClient,
    "decision_provider": DecisionProvider,
    "permission_provider": PermissionProvider,
    "communicator": Communicator,
    "loop_engine": LoopEngine,
    "agent_factory": AgentFactory,
    "memory_manager": MemoryManager,
    "snapshot_manager": SnapshotManager,
    "session_manager": SessionManager,
    "skill_manager": SkillManager,
    "process_manager": ProcessManager,
    "orchestrator": Orchestrator,
    "session_runner": SessionRunner,
    "tool_manager": ToolManager,
    "mcp_client": MCPClient,
    "command_system": CommandSystem,
    "task_manager": TaskManager,
    "scheduler": SchedulerABC,
    "revert_service": RevertServiceABC,
}
