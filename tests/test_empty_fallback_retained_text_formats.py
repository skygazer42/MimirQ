import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

from app.parsing.enrich.table_image_algorithms import _bind_ocr_content, _coerce_ocr_line
from app.parsing.parsers.base_parser import BaseAdvancedParser
from app.parsing.preprocess.llm_noise_miner import _normalize_line
from app.parsing.utils.mineru_layout import _as_lines, _extract_block_text


@pytest.fixture
def deepdoc_adapter(monkeypatch):
    # The pure adapter helpers do not invoke the optional DeepDoc backend. Load
    # the entire adapter with only that unused IO port replaced; trio is absent.
    backend = ModuleType("app.deepdoc.parser")
    backend.PdfParser = type("UnusedPdfParser", (), {})
    monkeypatch.setitem(sys.modules, "app.deepdoc.parser", backend)
    path = Path(__file__).resolve().parents[1] / "app/parsing/parsers/deepdoc_parser.py"
    spec = importlib.util.spec_from_file_location("test_retained_deepdoc_adapter", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("value", [0, False])
def test_section_text_coercion_preserves_falsy_scalars(value, deepdoc_adapter):
    assert BaseAdvancedParser._normalize_section(None, value)[0] == str(value)
    assert BaseAdvancedParser._normalize_section(None, (value,))[0] == str(value)
    assert deepdoc_adapter._normalize_pdf_section(value)[0] == str(value)
    assert deepdoc_adapter._normalize_pdf_section((value,))[0] == str(value)
    assert deepdoc_adapter._docx_section_parts([value, (value, None)]) == [str(value), str(value)]
    assert deepdoc_adapter._docx_table_parts([value]) == [str(value)]


@pytest.mark.parametrize("value", [0, False])
def test_ocr_line_coercion_and_cell_binding_preserve_falsy_text(value):
    line = _coerce_ocr_line([[(0, 0), (10, 0), (10, 10), (0, 10)], (value, 0.9)])
    assert line is not None
    assert line["text"] == str(value)
    text_by_cell, _ = _bind_ocr_content(
        cell_boxes={(0, 0): (0, 0, 10, 10)},
        ocr_lines=[{"text": value, "bbox": line["bbox"], "confidence": 0.9}],
        min_overlap=0.1,
    )
    assert text_by_cell[(0, 0)] == [str(value)]


@pytest.mark.parametrize("value", [0, False])
def test_layout_text_coercion_preserves_falsy_content(value):
    assert _as_lines([None, value]) == [str(value)]
    assert _extract_block_text({"text": value}) == str(value)
    assert _extract_block_text({"type": "table", "table_body": value}) == str(value)
    assert _extract_block_text({"type": "code", "code_body": value}) == str(value)
    assert _normalize_line(value) == str(value)


def test_absent_parser_text_keeps_actual_empty_text_format(deepdoc_adapter):
    assert BaseAdvancedParser._normalize_section(None, None)[0] == ""
    assert deepdoc_adapter._normalize_pdf_section(None)[0] == ""
    assert deepdoc_adapter._docx_section_parts([None]) == []
    assert _as_lines([None]) == []
