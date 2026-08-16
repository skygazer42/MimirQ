"""
Chunking strategies module.

Exports are resolved lazily so callers can import a specific strategy class
without pulling every strategy module into default startup.
"""

from importlib import import_module

from app.rag.chunking.capabilities import CHUNKER_CLASS_EXPORTS


def __getattr__(name: str):
    target = CHUNKER_CLASS_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


__all__ = list(CHUNKER_CLASS_EXPORTS)
