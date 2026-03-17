"""
RAG core utilities (shared, dependency-light).

This package intentionally keeps import-time side effects minimal. Exported
symbols are resolved lazily so callers can import a specific submodule without
dragging in heavier text / HTTP / model dependencies from unrelated helpers.
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS: dict[str, tuple[str, str]] = {
    "Command": ("app.rag.core.command", "Command"),
    "CommandProcessor": ("app.rag.core.command", "CommandProcessor"),
    "Interrupt": ("app.rag.core.command", "Interrupt"),
    "NodeReturn": ("app.rag.core.command", "NodeReturn"),
    "Send": ("app.rag.core.command", "Send"),
    "interrupt": ("app.rag.core.command", "interrupt"),
    "AIError": ("app.rag.core.errors", "AIError"),
    "ConfigError": ("app.rag.core.errors", "ConfigError"),
    "ExtractError": ("app.rag.core.errors", "ExtractError"),
    "LLMError": ("app.rag.core.errors", "LLMError"),
    "LLMTimeoutError": ("app.rag.core.errors", "LLMTimeoutError"),
    "LoadError": ("app.rag.core.errors", "LoadError"),
    "PromptError": ("app.rag.core.errors", "PromptError"),
    "SearchError": ("app.rag.core.errors", "SearchError"),
    "get_logger": ("app.rag.core.logging", "get_logger"),
    "setup_logging": ("app.rag.core.logging", "setup_logging"),
    "estimate_tokens": ("app.rag.core.text", "estimate_tokens"),
}


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)
