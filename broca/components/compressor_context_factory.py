"""Compressor context factory.

Builds a ``CompressorContext`` protocol implementation from agent-level
dependencies.  Two consumers:

* ``CompressionMemoryHook`` (via ``functools.partial``)
* the ``/compact`` command

The returned object satisfies the ``CompressorContext`` protocol defined in
``broca.components.protocols``.

Moved from ``broca/loop_engine/compressor_context.py`` to colocate the
factory with the protocol definition (review 6.4) and to eliminate the
reverse dependency ``commands → loop_engine``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from broca.components.protocols import CompressorContext


class _CompressorContextAdapter:
    """Lightweight adapter satisfying the ``CompressorContext`` protocol."""

    def __init__(
        self,
        *,
        agent_ref: Any,
        config: Any,
        communicator: Any,
        session_manager: Any,
        agent_id: str,
        session_id: str,
    ):
        self.agent_id = agent_id
        self.session_id = session_id
        self.communicator = communicator
        self.session_manager = session_manager
        self.last_context_length = getattr(agent_ref, "last_context_length", None)
        self._agent_ref = agent_ref
        self._config = config

    @property
    def compact_config(self):
        return self._config.compact_config

    @property
    def provider(self) -> str:
        return self._agent_ref.config.provider

    @property
    def model(self) -> str:
        return self._agent_ref.config.model

    @property
    def workspace(self) -> Optional[str]:
        return self._config.workspace


def build_compressor_context(
    *,
    agent_ref: Any,
    config: Any,
    communicator: Any,
    session_manager: Any,
    agent_id: str,
    session_id: str,
) -> "CompressorContext":
    """Build a ``CompressorContext`` for ``ContextCompressor``.

    Logic migrated verbatim from the former engine method; ``provider`` /
    ``model`` stay lazy properties so config changes are picked up.
    """
    return _CompressorContextAdapter(
        agent_ref=agent_ref,
        config=config,
        communicator=communicator,
        session_manager=session_manager,
        agent_id=agent_id,
        session_id=session_id,
    )
