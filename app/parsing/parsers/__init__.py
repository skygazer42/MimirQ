"""
Document parser business layer package.

Keep package import lightweight. Advanced parser wrappers are exposed lazily so
importing `app.parsing.factory` does not pull heavy PDF dependencies such as
PyMuPDF unless a parser is actually constructed. Capability discovery is also
exposed lazily for callers that need parser registry metadata.
"""


from typing import Any

from .base_parser import BaseAdvancedParser

__all__ = [
    "BaseAdvancedParser",
    "MinerUParser",
    "DoclingParser",
    "TCADPParser",
    "Etl4LlmParser",
]


def __getattr__(name: str) -> Any:
    if name == "ParserExport":
        from app.parsing.parsers.registry import ParserExport

        value = ParserExport
    elif name == "ParserBackendFamily":
        from app.parsing.parsers.registry import ParserBackendFamily

        value = ParserBackendFamily
    elif name in {
        "get_parser_capabilities",
        "get_parser_capability",
        "get_parser_backend_capabilities",
        "list_parser_backend_capabilities",
    }:
        from app.parsing.parsers import capabilities as _capabilities

        value = getattr(_capabilities, name)
    elif name in {"get_parser_backend_family", "list_registered_parser_backends"}:
        from app.parsing.parsers import registry as _registry

        value = getattr(_registry, name)
    else:
        from app.parsing.parsers.registry import resolve_parser_export

        value = resolve_parser_export(name)
    globals()[name] = value
    return value
