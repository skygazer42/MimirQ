"""
RAG core utilities (shared, dependency-light).

This package intentionally keeps import-time side effects minimal. Exported
symbols are resolved lazily so callers can import a specific submodule without
dragging in heavier text / HTTP / model dependencies from unrelated helpers.
"""


from importlib import import_module

_MODULE_COMMAND = "app.rag.core.command"
_MODULE_ERRORS = "app.rag.core.errors"

_EXPORTS: dict[str, tuple[str, str]] = {
    "Command": (_MODULE_COMMAND, "Command"),
    "CommandProcessor": (_MODULE_COMMAND, "CommandProcessor"),
    "Interrupt": (_MODULE_COMMAND, "Interrupt"),
    "NodeReturn": (_MODULE_COMMAND, "NodeReturn"),
    "Send": (_MODULE_COMMAND, "Send"),
    "interrupt": (_MODULE_COMMAND, "interrupt"),
    "AIError": (_MODULE_ERRORS, "AIError"),
    "ConfigError": (_MODULE_ERRORS, "ConfigError"),
    "ExtractError": (_MODULE_ERRORS, "ExtractError"),
    "LLMError": (_MODULE_ERRORS, "LLMError"),
    "LLMTimeoutError": (_MODULE_ERRORS, "LLMTimeoutError"),
    "LoadError": (_MODULE_ERRORS, "LoadError"),
    "PromptError": (_MODULE_ERRORS, "PromptError"),
    "SearchError": (_MODULE_ERRORS, "SearchError"),
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
