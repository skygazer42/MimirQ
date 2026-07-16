"""
RAG Middleware System

This module provides a three-layer middleware system for RAG pipelines:

1. @before_model - Pre-processing hooks before LLM calls
2. @after_model - Post-processing hooks after LLM calls
3. @wrap_model_call - Wrapping hooks around LLM calls (error handling, retry, etc.)

Additionally:
- @dynamic_prompt - Dynamic prompt injection middleware

Usage:
    from app.rag.middleware import before_model, after_model, wrap_model_call

    @before_model
    def inject_context(state):
        state["messages"].insert(0, SystemMessage(...))
        return state

    @after_model
    def log_response(state, response):
        logger.info(f"Response: {response}")
        return response

    @wrap_model_call
    def error_handler(func):
        async def wrapper(state, *args, **kwargs):
            try:
                return await func(state, *args, **kwargs)
            except RateLimitError:
                # Fallback logic
                ...
        return wrapper
"""

from app.rag.middleware.agent_logging import AgentExecutionLoggingMiddleware
from app.rag.middleware.base import (
    AgentMiddlewareChain,
    MiddlewareChain,
    MiddlewareRegistry,
    ToolMiddlewareChain,
    after_agent,
    after_model,
    after_tool_call,
    apply_middlewares,
    before_agent,
    before_model,
    before_tool_call,
    dynamic_prompt,
    wrap_model_call,
    wrap_tool_call,
)
from app.rag.middleware.pii import PIIMiddleware
from app.rag.middleware.tool_logging import ToolCallLoggingMiddleware

__all__ = [
    # Decorators
    "before_model",
    "after_model",
    "wrap_model_call",
    "dynamic_prompt",
    "before_tool_call",
    "after_tool_call",
    "wrap_tool_call",
    "before_agent",
    "after_agent",
    # Registry and Chain
    "MiddlewareRegistry",
    "MiddlewareChain",
    "ToolMiddlewareChain",
    "AgentMiddlewareChain",
    "apply_middlewares",
    # PII
    "PIIMiddleware",
    # Tool logging
    "ToolCallLoggingMiddleware",
    # Agent logging
    "AgentExecutionLoggingMiddleware",
]
