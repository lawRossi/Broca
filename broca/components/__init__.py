"""Component plugin system.

This package defines the ABC interfaces for Broca's core components,
along with the ``ComponentRegistry`` for plugin discovery, resolution,
and scoped instantiation.

Core component interfaces (7):
    - ``ToolExecutor`` — tool execution pipeline
    - ``ContextCompressor`` — token monitoring + compression
    - ``LLMClient`` — LLM API calls
    - ``PermissionProvider`` — permission management
    - ``Communicator`` — communication layer
    - ``LoopEngine`` — execution engine
    - ``AgentFactory`` — agent creation/restoration

Protocols:
    - ``CompressorContext`` — narrow context for compression
    - ``AgentReference`` — narrow context for the execution loop
    - ``PermissionContext`` — narrow context for permission requests
    - ``ExecutionContext`` — narrow context for execution-scoped operations

Loop-engine pluggability layer:
    - ``LLMStrategy`` / ``LLMCallResult`` — how the LLM is called
      (retry/rate-limit/timeout/stream aggregation)
    - ``ToolExecutionStrategy`` — how tool calls are executed (serial/parallel)
    - ``LoopHook`` / ``TurnContext`` / ``StepContext`` — optional lifecycle hooks

Registry:
    - ``ComponentRegistry`` — plugin discovery, resolution, scoped instances
"""

from broca.components.agent_factory import AgentFactory
from broca.components.base import BaseComponent
from broca.components.command_system import CommandSystem
from broca.components.communicator import Communicator
from broca.components.context_compressor import ContextCompressor
from broca.components.errors import (
    ComponentError,
    ComponentNotFoundError,
    ComponentScopeError,
)
from broca.components.llm_client import LLMClient
from broca.components.llm_strategy import LLMCallResult, LLMStrategy
from broca.components.loop_engine import LoopEngine
from broca.components.loop_hook import LoopHook, StepContext, TurnContext
from broca.components.mcp_client import MCPClient
from broca.components.memory_manager import MemoryManager
# Orchestrator is a re-export from broca.orchestration — imported directly
# to avoid circular import (orchestrator → session_manager → components).
# Use: from broca.components.orchestrator import Orchestrator
from broca.components.permission_provider import PermissionProvider
from broca.components.process_manager import ProcessManager
from broca.components.protocols import (
    AgentReference,
    CompressorContext,
    ExecutionContext,
    PermissionContext,
)
from broca.components.registry import ComponentRegistry
from broca.components.revert_service import RevertServiceABC
from broca.components.scheduler import SchedulerABC
from broca.components.session_manager import SessionManager
from broca.components.session_runner import SessionRunner
from broca.components.skill_manager import SkillManager
from broca.components.snapshot_manager import SnapshotManager
from broca.components.task_manager import TaskManager
from broca.components.tool_executor import (
    ToolExecutionOutcome,
    ToolExecutor,
)
from broca.components.tool_manager import ToolManager
from broca.components.tool_strategy import ToolExecutionStrategy

__all__ = [
    # Base
    "BaseComponent",
    # Core ABCs (Phase 1)
    "ToolExecutor",
    "ContextCompressor",
    "LLMClient",
    "PermissionProvider",
    "Communicator",
    "LoopEngine",
    "AgentFactory",
    # Strategy + hook layer (Phase 1 of loop-engine hooks refactor)
    "LLMStrategy",
    "LLMCallResult",
    "ToolExecutionStrategy",
    "LoopHook",
    "TurnContext",
    "StepContext",
    # Support ABCs (Phase 5)
    "MemoryManager",
    "SnapshotManager",
    "SessionManager",
    "SkillManager",
    "ProcessManager",
    "SessionRunner",
    "ToolManager",
    "MCPClient",
    "CommandSystem",
    "TaskManager",
    "SchedulerABC",
    "RevertServiceABC",
    # Data types
    "ToolExecutionOutcome",
    # Protocols
    "CompressorContext",
    "AgentReference",
    "PermissionContext",
    "ExecutionContext",
    # Errors
    "ComponentError",
    "ComponentNotFoundError",
    "ComponentScopeError",
    # Registry
    "ComponentRegistry",
]
