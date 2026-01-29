"""
Document parser business layer wrapper

Provides parser collection with LangChain Document format output.
Underlying calls to deepdoc/parser/ implementations.
"""

from .base_parser import BaseAdvancedParser

__all__ = ["BaseAdvancedParser"]

# Optional advanced parsers: do not fail import-time if extra dependencies are missing.
try:
    from .mineru_parser import MinerUParser  # noqa: F401
except ImportError:  # pragma: no cover
    MinerUParser = None  # type: ignore[assignment]
else:
    __all__.append("MinerUParser")

try:
    from .docling_parser import DoclingParser  # noqa: F401
except ImportError:  # pragma: no cover
    DoclingParser = None  # type: ignore[assignment]
else:
    __all__.append("DoclingParser")

try:
    from .tcadp_parser import TCADPParser  # noqa: F401
except ImportError:  # pragma: no cover
    TCADPParser = None  # type: ignore[assignment]
else:
    __all__.append("TCADPParser")

try:
    from .etl4llm_parser import Etl4LlmParser  # noqa: F401
except ImportError:  # pragma: no cover
    Etl4LlmParser = None  # type: ignore[assignment]
else:
    __all__.append("Etl4LlmParser")
