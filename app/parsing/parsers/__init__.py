"""
Document parser business layer package.

Keep package import lightweight. Advanced parser wrappers are exposed lazily so
importing `app.parsing.factory` does not pull heavy PDF dependencies such as
PyMuPDF unless a parser is actually constructed.
"""

from __future__ import annotations

from typing import Any

from .base_parser import BaseAdvancedParser

__all__ = ["BaseAdvancedParser", "MinerUParser", "DoclingParser", "TCADPParser", "Etl4LlmParser"]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "MinerUParser": ("app.parsing.parsers.mineru_parser", "MinerUParser"),
    "DoclingParser": ("app.parsing.parsers.docling_parser", "DoclingParser"),
    "TCADPParser": ("app.parsing.parsers.tcadp_parser", "TCADPParser"),
    "Etl4LlmParser": ("app.parsing.parsers.etl4llm_parser", "Etl4LlmParser"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'app.parsing.parsers' has no attribute {name!r}")

    module_name, attr_name = target
    module = __import__(module_name, fromlist=[attr_name])
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
