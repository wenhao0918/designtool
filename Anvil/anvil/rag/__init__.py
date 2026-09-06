"""RAG backends — knowledge retrieval abstraction.

Usage:
    from anvil.rag import get_backend
    kb = get_backend()  # Returns configured backend based on ANVIL_RAG_BACKEND
    results = kb.search("material strength steel 40Cr")
"""

import os
import logging
from .base import RAGBackend

_BACKENDS = {}
_DEFAULT_BACKEND = None


def register_backend(name, cls):
    _BACKENDS[name] = cls


def get_backend(name=None):
    """Get the configured RAG backend instance.

    Args:
        name: Backend name (e.g. "ragflow", "local").
              Defaults to ANVIL_RAG_BACKEND env var, or "ragflow".

    Returns:
        RAGBackend instance.
    """
    global _DEFAULT_BACKEND
    name = name or os.environ.get("ANVIL_RAG_BACKEND", "ragflow")

    if _DEFAULT_BACKEND is None or _DEFAULT_BACKEND.__class__.__name__.lower() != name:
        cls = _BACKENDS.get(name)
        if not cls:
            raise ValueError(
                "Unknown RAG backend: %s. Available: %s" % (name, list(_BACKENDS.keys()))
            )
        _DEFAULT_BACKEND = cls()
    return _DEFAULT_BACKEND


def list_backends():
    """List registered backend names."""
    return dict(_BACKENDS)

from .ragflow import RAGFlowBackend
register_backend("ragflow", RAGFlowBackend)
