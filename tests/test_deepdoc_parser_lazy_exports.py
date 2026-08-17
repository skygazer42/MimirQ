
import sys
from types import ModuleType

import pytest

from app.deepdoc import parser


@pytest.mark.parametrize(
    ("export_name", "module_name", "attribute_name"),
    [
        ("PdfParser", "pdf_parser", "IntegratedPipelinePdfParser"),
        ("PlainParser", "pdf_parser", "PlainParser"),
        ("DocxParser", "docx_parser", "IntegratedPipelineDocxParser"),
        ("ExcelParser", "excel_parser", "IntegratedPipelineExcelParser"),
        ("PptParser", "ppt_parser", "IntegratedPipelinePptParser"),
        ("HtmlParser", "html_parser", "IntegratedPipelineHtmlParser"),
        ("JsonParser", "json_parser", "IntegratedPipelineJsonParser"),
        ("MarkdownParser", "markdown_parser", "IntegratedPipelineMarkdownParser"),
        ("TxtParser", "txt_parser", "IntegratedPipelineTxtParser"),
        ("MinerUParser", "mineru_parser", "MinerUParser"),
        ("DoclingParser", "docling_parser", "DoclingParser"),
        ("TCADPParser", "tcadp_parser", "TCADPParser"),
    ],
)
def test_lazy_parser_export_resolves_the_existing_module_contract(
    monkeypatch: pytest.MonkeyPatch,
    export_name: str,
    module_name: str,
    attribute_name: str,
) -> None:
    sentinel = object()
    fake_module = ModuleType(f"app.deepdoc.parser.{module_name}")
    setattr(fake_module, attribute_name, sentinel)
    monkeypatch.setitem(sys.modules, fake_module.__name__, fake_module)

    assert parser.__getattr__(export_name) is sentinel


def test_lazy_parser_export_preserves_unknown_attribute_error() -> None:
    with pytest.raises(
        AttributeError,
        match=r"module 'app\.deepdoc\.parser' has no attribute 'UnknownParser'",
    ):
        parser.__getattr__("UnknownParser")
