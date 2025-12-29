"""
文档解析器业务层封装

提供 LangChain Document 格式输出的解析器集合。
底层调用 deepdoc/parser/ 的实现。
"""

from .base_parser import BaseAdvancedParser
from .mineru_parser import MinerUParser
from .docling_parser import DoclingParser
from .tcadp_parser import TCADPParser

__all__ = [
    "BaseAdvancedParser",
    "MinerUParser",
    "DoclingParser",
    "TCADPParser",
]
