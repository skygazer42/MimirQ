"""
文档解析器业务层封装

提供 LangChain Document 格式输出的解析器集合。
底层调用 deepdoc/parser/ 的实现。
"""

from .base_parser import BaseAdvancedParser

__all__ = ["BaseAdvancedParser"]

# Optional advanced parsers: do not fail import-time if extra dependencies are missing.
try:
    from .mineru_parser import MinerUParser  # noqa: F401
except Exception:  # noqa: BLE001
    MinerUParser = None  # type: ignore[assignment]
else:
    __all__.append("MinerUParser")

try:
    from .docling_parser import DoclingParser  # noqa: F401
except Exception:  # noqa: BLE001
    DoclingParser = None  # type: ignore[assignment]
else:
    __all__.append("DoclingParser")

try:
    from .tcadp_parser import TCADPParser  # noqa: F401
except Exception:  # noqa: BLE001
    TCADPParser = None  # type: ignore[assignment]
else:
    __all__.append("TCADPParser")
