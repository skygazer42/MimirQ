"""
RAG Tracing module.

Provides observability and tracing capabilities for RAG workflows.
"""

from app.rag.tracing.langsmith import (
    SpanContext,
    TracingClient,
    get_tracing_client,
    setup_tracing,
)

__all__ = [
    # Types
    "SpanContext",
    "TracingClient",
    # Functions
    "get_tracing_client",
    "setup_tracing",
]
