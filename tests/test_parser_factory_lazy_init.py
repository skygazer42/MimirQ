from __future__ import annotations

import importlib.util
import sys

import pytest


def test_parser_factory_lazy_imports_pdf_parser():
    if importlib.util.find_spec("fitz") is None:
        pytest.skip("PyMuPDF (fitz) not installed")

    sys.modules.pop("fitz", None)

    import app.parsing.factory as factory

    assert "fitz" not in sys.modules

    parser_factory = factory.get_parser_factory()
    assert "fitz" not in sys.modules

    parser_factory._get_pdf_parser("basic")
    assert "fitz" in sys.modules
