"""
LangSmith Studio integration for observability and tracing.

Provides comprehensive tracing capabilities for RAG workflows:
- Automatic trace collection
- Custom span annotations
- Metadata tagging
- Evaluation integration

Usage:
    from app.rag.tracing.langsmith import setup_tracing, trace_rag_query

    # Setup tracing at application startup
    setup_tracing()

    # Use decorator for tracing
    @trace_rag_query
    async def answer_question(query: str) -> str:
        ...
"""


import functools
import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import uuid4

from app.core.config import settings
from app.core.optional_deps import require_dependency
from app.rag.core.logging import get_logger

logger = get_logger("rag.tracing.langsmith")


# Configuration
LANGSMITH_API_KEY = getattr(settings, "LANGSMITH_API_KEY", "")
LANGSMITH_PROJECT = getattr(settings, "LANGSMITH_PROJECT", "mimirq")
LANGSMITH_ENDPOINT = getattr(settings, "LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
LANGSMITH_TRACING_ENABLED = getattr(settings, "LANGSMITH_TRACING_ENABLED", False)

# Import langsmith if tracing is enabled
LangSmithClient = None  # type: ignore
if LANGSMITH_TRACING_ENABLED:
    langsmith_module = require_dependency("langsmith", feature="langsmith_tracing", pip_name="langsmith")
    LangSmithClient = getattr(langsmith_module, "Client", None)  # type: ignore[assignment]
    if LangSmithClient is None:
        raise RuntimeError("langsmith.Client missing (unsupported langsmith version)")


# Type variable for decorators
F = TypeVar("F", bound=Callable)


@dataclass
class SpanContext:
    """Context for a trace span."""
    run_id: str = field(default_factory=lambda: str(uuid4()))
    parent_id: str | None = None
    name: str = ""
    run_type: str = "chain"
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    error: str | None = None

    @property
    def duration_ms(self) -> float | None:
        """Calculate duration in milliseconds."""
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000


class TracingClient:
    """
    Client for LangSmith tracing.

    Handles trace collection and submission to LangSmith.
    """

    def __init__(
        self,
        api_key: str | None = None,
        project: str | None = None,
        endpoint: str | None = None,
    ):
        """
        Initialize the tracing client.

        Args:
            api_key: LangSmith API key
            project: Project name
            endpoint: API endpoint
        """
        self.api_key = api_key or LANGSMITH_API_KEY
        self.project = project or LANGSMITH_PROJECT
        self.endpoint = endpoint or LANGSMITH_ENDPOINT
        self._enabled = bool(self.api_key) and LANGSMITH_TRACING_ENABLED and LangSmithClient is not None
        self._client = None
        self._current_spans: dict[str, SpanContext] = {}

    @property
    def enabled(self) -> bool:
        """Check if tracing is enabled."""
        return self._enabled

    def _get_client(self) -> Any:
        """Get or create LangSmith client."""
        if self._client is not None:
            return self._client

        if not self._enabled:
            return None

        if LangSmithClient is None:
            return None

        self._client = LangSmithClient(
            api_key=self.api_key,
            api_url=self.endpoint,
        )
        logger.info("LangSmith client initialized")
        return self._client

    def start_span(
        self,
        name: str,
        run_type: str = "chain",
        inputs: dict[str, Any] | None = None,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> SpanContext:
        """
        Start a new trace span.

        Args:
            name: Span name
            run_type: Type of run (chain, llm, retriever, tool)
            inputs: Input data
            parent_id: Parent span ID
            metadata: Additional metadata
            tags: Tags for filtering

        Returns:
            Span context
        """
        span = SpanContext(
            name=name,
            run_type=run_type,
            inputs=inputs or {},
            parent_id=parent_id,
            metadata=metadata or {},
            tags=tags or [],
        )

        self._current_spans[span.run_id] = span

        if self._enabled:
            self._submit_start(span)

        return span

    def end_span(
        self,
        span: SpanContext,
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """
        End a trace span.

        Args:
            span: Span context
            outputs: Output data
            error: Error message if failed
        """
        span.end_time = time.time()
        span.outputs = outputs or {}
        span.error = error

        if self._enabled:
            self._submit_end(span)

        self._current_spans.pop(span.run_id, None)

    def _submit_start(self, span: SpanContext) -> None:
        """Submit span start to LangSmith."""
        client = self._get_client()
        if client is None:
            return

        try:
            client.create_run(
                name=span.name,
                run_type=span.run_type,
                inputs=span.inputs,
                id=span.run_id,
                parent_run_id=span.parent_id,
                project_name=self.project,
                tags=span.tags,
                extra={"metadata": span.metadata},
            )
        except Exception as e:
            logger.debug("Failed to submit span start: %s", e)

    def _submit_end(self, span: SpanContext) -> None:
        """Submit span end to LangSmith."""
        client = self._get_client()
        if client is None:
            return

        try:
            client.update_run(
                run_id=span.run_id,
                outputs=span.outputs,
                error=span.error,
                end_time=datetime.now(UTC).replace(tzinfo=None),
            )
        except Exception as e:
            logger.debug("Failed to submit span end: %s", e)

    @contextmanager
    def trace(
        self,
        name: str,
        run_type: str = "chain",
        inputs: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ):
        """
        Context manager for tracing.

        Args:
            name: Span name
            run_type: Type of run
            inputs: Input data
            metadata: Additional metadata
            tags: Tags for filtering

        Yields:
            Span context
        """
        span = self.start_span(
            name=name,
            run_type=run_type,
            inputs=inputs,
            metadata=metadata,
            tags=tags,
        )

        try:
            yield span
            self.end_span(span, outputs=span.outputs)
        except Exception as e:
            self.end_span(span, error=str(e))
            raise

    @asynccontextmanager
    async def atrace(
        self,
        name: str,
        run_type: str = "chain",
        inputs: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ):
        """
        Async context manager for tracing.

        Args:
            name: Span name
            run_type: Type of run
            inputs: Input data
            metadata: Additional metadata
            tags: Tags for filtering

        Yields:
            Span context
        """
        span = self.start_span(
            name=name,
            run_type=run_type,
            inputs=inputs,
            metadata=metadata,
            tags=tags,
        )

        try:
            yield span
            self.end_span(span, outputs=span.outputs)
        except Exception as e:
            self.end_span(span, error=str(e))
            raise


# ============================================================================
# Global Client
# ============================================================================


_tracing_client: TracingClient | None = None


def get_tracing_client() -> TracingClient:
    """Get or create the global tracing client."""
    global _tracing_client
    if _tracing_client is None:
        _tracing_client = TracingClient()
    return _tracing_client


def setup_tracing(
    api_key: str | None = None,
    project: str | None = None,
) -> None:
    """
    Setup LangSmith tracing.

    Call this at application startup to configure tracing.

    Args:
        api_key: LangSmith API key
        project: Project name
    """
    global _tracing_client

    # Set environment variables for LangChain auto-tracing
    if api_key:
        os.environ["LANGCHAIN_API_KEY"] = api_key
    elif LANGSMITH_API_KEY:
        os.environ["LANGCHAIN_API_KEY"] = LANGSMITH_API_KEY

    if project:
        os.environ["LANGCHAIN_PROJECT"] = project
    elif LANGSMITH_PROJECT:
        os.environ["LANGCHAIN_PROJECT"] = LANGSMITH_PROJECT

    if LANGSMITH_TRACING_ENABLED:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_ENDPOINT"] = LANGSMITH_ENDPOINT

    _tracing_client = TracingClient(
        api_key=api_key,
        project=project,
    )

    if _tracing_client.enabled:
        logger.info("LangSmith tracing enabled for project: %s", _tracing_client.project)
    else:
        logger.debug("LangSmith tracing not enabled")


# ============================================================================
# Decorators
# ============================================================================


def trace_function(
    name: str | None = None,
    run_type: str = "chain",
    tags: list[str] | None = None,
) -> Callable[[F], F]:
    """
    Decorator for tracing synchronous functions.

    Args:
        name: Span name (defaults to function name)
        run_type: Type of run
        tags: Tags for filtering

    Returns:
        Decorated function
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            client = get_tracing_client()
            span_name = name or func.__name__

            with client.trace(
                name=span_name,
                run_type=run_type,
                inputs={"args": str(args)[:500], "kwargs": str(kwargs)[:500]},
                tags=tags,
            ) as span:
                result = func(*args, **kwargs)
                span.outputs = {"result": str(result)[:1000]}
                return result

        return wrapper  # type: ignore

    return decorator


def trace_async_function(
    name: str | None = None,
    run_type: str = "chain",
    tags: list[str] | None = None,
) -> Callable[[F], F]:
    """
    Decorator for tracing async functions.

    Args:
        name: Span name (defaults to function name)
        run_type: Type of run
        tags: Tags for filtering

    Returns:
        Decorated function
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            client = get_tracing_client()
            span_name = name or func.__name__

            async with client.atrace(
                name=span_name,
                run_type=run_type,
                inputs={"args": str(args)[:500], "kwargs": str(kwargs)[:500]},
                tags=tags,
            ) as span:
                result = await func(*args, **kwargs)
                span.outputs = {"result": str(result)[:1000]}
                return result

        return wrapper  # type: ignore

    return decorator


def trace_rag_query(func: F) -> F:
    """
    Decorator for tracing RAG query functions.

    Automatically captures query, context, and answer.

    Args:
        func: Function to trace

    Returns:
        Decorated function
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        client = get_tracing_client()

        # Extract query from args/kwargs
        query = kwargs.get("query") or kwargs.get("question")
        if not query and args:
            query = args[0] if isinstance(args[0], str) else None

        async with client.atrace(
            name="rag_query",
            run_type="chain",
            inputs={"query": query or "unknown"},
            tags=["rag", "query"],
            metadata={"function": func.__name__},
        ) as span:
            result = await func(*args, **kwargs)

            # Extract answer from result
            answer = None
            if isinstance(result, str):
                answer = result
            elif isinstance(result, dict):
                answer = result.get("answer") or result.get("response")

            span.outputs = {
                "answer": answer[:1000] if answer else None,
                "result_type": type(result).__name__,
            }

            return result

    return wrapper  # type: ignore


def trace_retrieval(func: F) -> F:
    """
    Decorator for tracing retrieval functions.

    Args:
        func: Function to trace

    Returns:
        Decorated function
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        client = get_tracing_client()

        query = kwargs.get("query")
        if not query and args:
            query = args[0] if isinstance(args[0], str) else None

        async with client.atrace(
            name="retrieval",
            run_type="retriever",
            inputs={"query": query or "unknown"},
            tags=["retrieval"],
        ) as span:
            result = await func(*args, **kwargs)

            # Count documents
            doc_count = len(result) if isinstance(result, list) else 0

            span.outputs = {
                "document_count": doc_count,
            }

            return result

    return wrapper  # type: ignore


def trace_llm_call(func: F) -> F:
    """
    Decorator for tracing LLM calls.

    Args:
        func: Function to trace

    Returns:
        Decorated function
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        client = get_tracing_client()

        async with client.atrace(
            name="llm_call",
            run_type="llm",
            inputs={
                "model": kwargs.get("model", "unknown"),
                "prompt_length": len(str(kwargs.get("prompt", "")))
            },
            tags=["llm"],
        ) as span:
            result = await func(*args, **kwargs)

            # Extract response
            response = None
            if hasattr(result, "content"):
                response = result.content
            elif isinstance(result, str):
                response = result

            span.outputs = {
                "response_length": len(response) if response else 0,
            }

            return result

    return wrapper  # type: ignore


# ============================================================================
# Utility Functions
# ============================================================================


def add_feedback(
    run_id: str,
    score: float,
    key: str = "user_feedback",
    comment: str | None = None,
) -> bool:
    """
    Add feedback to a trace run.

    Args:
        run_id: Run ID to add feedback to
        score: Feedback score (0.0 to 1.0)
        key: Feedback key
        comment: Optional comment

    Returns:
        True if successful
    """
    client = get_tracing_client()
    if not client.enabled:
        return False

    try:
        ls_client = client._get_client()
        if ls_client is None:
            return False

        ls_client.create_feedback(
            run_id=run_id,
            key=key,
            score=score,
            comment=comment,
        )
        return True
    except Exception as e:
        logger.exception("Failed to add feedback: %s", e)
        return False


def get_run_url(run_id: str) -> str | None:
    """
    Get the LangSmith URL for a run.

    Args:
        run_id: Run ID

    Returns:
        URL string or None
    """
    client = get_tracing_client()
    if not client.enabled:
        return None

    return f"{LANGSMITH_ENDPOINT}/o/default/projects/p/{LANGSMITH_PROJECT}/r/{run_id}"
