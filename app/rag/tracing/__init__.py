"""
RAG Tracing module.

Provides observability and tracing capabilities for RAG workflows.
"""

from app.rag.tracing.langsmith import (
    SpanContext,
    TracingClient,
    add_feedback,
    get_run_url,
    get_tracing_client,
    setup_tracing,
    trace_async_function,
    trace_function,
    trace_llm_call,
    trace_rag_query,
    trace_retrieval,
)

__all__ = [
    # Types
    "SpanContext",
    "TracingClient",
    # Functions
    "get_tracing_client",
    "setup_tracing",
    # Decorators
    "trace_function",
    "trace_async_function",
    "trace_rag_query",
    "trace_retrieval",
    "trace_llm_call",
    # Utilities
    "add_feedback",
    "get_run_url",
]
