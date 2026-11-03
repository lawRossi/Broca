"""Orchestrator ABC — re-export from broca.orchestration.

The Orchestrator ABC is defined in ``broca/orchestration/orchestrator.py``
and re-exported here for consistent access via ``broca.components``.
"""

from __future__ import annotations

from broca.orchestration.orchestrator import Orchestrator

__all__ = ["Orchestrator"]
