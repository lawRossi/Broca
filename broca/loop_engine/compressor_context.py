"""Backward-compat re-export.

The implementation now lives in ``broca.components.compressor_context_factory``
(review 6.4).  This module is kept so that any external code still importing
from the old path continues to work.

.. deprecated::
    Use ``from broca.components.compressor_context_factory import
    build_compressor_context`` instead.
"""

from broca.components.compressor_context_factory import (  # noqa: F401
    build_compressor_context,
)

__all__ = ["build_compressor_context"]
