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
    "MinerUParser",
    "DoclingParser",
    "TCADPParser",
]

_MISSING = object()


def _integrated_parser_export(name: str) -> Any:
    if name == "PdfParser":
        from .pdf_parser import IntegratedPipelinePdfParser as PdfParser

        return PdfParser
    if name == "PlainParser":
        from .pdf_parser import PlainParser

        return PlainParser
    if name == "DocxParser":
        from .docx_parser import IntegratedPipelineDocxParser as DocxParser

        return DocxParser
    if name == "ExcelParser":
        from .excel_parser import IntegratedPipelineExcelParser as ExcelParser

        return ExcelParser
    if name == "PptParser":
        from .ppt_parser import IntegratedPipelinePptParser as PptParser

        return PptParser
    if name == "HtmlParser":
        from .html_parser import IntegratedPipelineHtmlParser as HtmlParser

        return HtmlParser
    return _MISSING


def _additional_parser_export(name: str) -> Any:
    if name == "JsonParser":
        from .json_parser import IntegratedPipelineJsonParser as JsonParser

        return JsonParser
    if name == "MarkdownParser":
        from .markdown_parser import IntegratedPipelineMarkdownParser as MarkdownParser

        return MarkdownParser
    if name == "TxtParser":
        from .txt_parser import IntegratedPipelineTxtParser as TxtParser

        return TxtParser
    if name == "MinerUParser":
        from .mineru_parser import MinerUParser

        return MinerUParser
    if name == "DoclingParser":
        from .docling_parser import DoclingParser

        return DoclingParser
    if name == "TCADPParser":
        from .tcadp_parser import TCADPParser

        return TCADPParser
    return _MISSING


def __getattr__(name: str) -> Any:  # pragma: no cover
    """
    Lazy exports.

    DeepDoc supports multiple formats, but some optional parsers pull in extra
    dependencies. Import them on-demand so PDF parsing can work even if other
    format dependencies are missing.
    """
    export = _integrated_parser_export(name)
    if export is _MISSING:
        export = _additional_parser_export(name)
    if export is not _MISSING:
        return export

    raise AttributeError(f"module 'app.deepdoc.parser' has no attribute {name!r}")
