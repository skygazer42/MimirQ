#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

from __future__ import annotations

from typing import Any

__all__ = [
    "PdfParser",
    "PlainParser",
    "DocxParser",
    "ExcelParser",
    "PptParser",
    "HtmlParser",
    "JsonParser",
    "MarkdownParser",
    "TxtParser",
]


def __getattr__(name: str) -> Any:  # pragma: no cover
    """
    Lazy exports.

    DeepDoc supports multiple formats, but some optional parsers pull in extra
    dependencies. Import them on-demand so PDF parsing can work even if other
    format dependencies are missing.
    """
    if name == "PdfParser":
        from .pdf_parser import RAGFlowPdfParser as PdfParser

        return PdfParser
    if name == "PlainParser":
        from .pdf_parser import PlainParser

        return PlainParser
    if name == "DocxParser":
        from .docx_parser import RAGFlowDocxParser as DocxParser

        return DocxParser
    if name == "ExcelParser":
        from .excel_parser import RAGFlowExcelParser as ExcelParser

        return ExcelParser
    if name == "PptParser":
        from .ppt_parser import RAGFlowPptParser as PptParser

        return PptParser
    if name == "HtmlParser":
        from .html_parser import RAGFlowHtmlParser as HtmlParser

        return HtmlParser
    if name == "JsonParser":
        from .json_parser import RAGFlowJsonParser as JsonParser

        return JsonParser
    if name == "MarkdownParser":
        from .markdown_parser import RAGFlowMarkdownParser as MarkdownParser

        return MarkdownParser
    if name == "TxtParser":
        from .txt_parser import RAGFlowTxtParser as TxtParser

        return TxtParser

    raise AttributeError(f"module 'app.ai.deepdoc.parser' has no attribute {name!r}")
