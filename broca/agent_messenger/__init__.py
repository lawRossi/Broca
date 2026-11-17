"""Agent-to-agent messaging primitives (data models, call chain, audit).

The concrete messenger implementation lives in
``broca.agent_messenger.messenger`` (``DefaultAgentMessenger``), registered
via ``broca.components.defaults``.
"""

from broca.agent_messenger.message_models import AgentCommunication

__all__ = ["AgentCommunication"]
