import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from langchain_core.documents import Document

from app.parsing.factory import ParserFactory

EXPECTED_PARSER_EXPORTS = [
    "BaseAdvancedParser",
    "MinerUParser",
    "DoclingParser",
    "TCADPParser",
    "Etl4LlmParser",
]

EXPECTED_BACKEND_ALIASES = {
    "pymupdf": "basic",
    "fitz": "basic",
    "magic-pdf": "magicpdf",
    "magicpdf": "magicpdf",
    "deepseek-ocr": "deepseek_ocr",
    "deepseekocr": "deepseek_ocr",
    "qianfan-ocr": "qianfan_ocr",
    "qianfanocr": "qianfan_ocr",
    "textin": "textin",
    "textin-xparse": "textin",
    "textinxparse": "textin",
    "etl4llm": "etl4llm",
    "etl-4llm": "etl4llm",
    "pandoc": "pandoc",
    "pan-doc": "pandoc",
    "marker": "marker",
    "marker-pdf": "marker",
    "paddle-vl": "paddle_vl",
    "paddleocr-vl": "paddle_vl",
    "paddleocrvl": "paddle_vl",
    "glm-ocr": "glm_ocr",
    "glmocr": "glm_ocr",
    "col-pali": "colpali",
    "colpali": "colpali",
    "col-qwen": "colpali",
    "colqwen": "colpali",
    "olmocr": "olmocr",
    "olm-ocr": "olmocr",
    "olmocr-pdf": "olmocr",
    "bisheng-unstructured": "etl4llm",
    "bishengunstructured": "etl4llm",
    "bisheng": "etl4llm",
}

EXPECTED_PDF_BACKENDS = [
    "auto",
    "basic",
    "colpali",
    "deepdoc",
    "deepseek_ocr",
    "docling",
    "etl4llm",
    "glm_ocr",
    "magicpdf",
    "marker",
    "markitdown",
    "mineru",
    "olmocr",
    "paddle_vl",
    "qianfan_ocr",
    "textin",
]

EXPECTED_NON_PDF_BACKENDS = [
    "audio",
    "auto",
    "colpali",
    "csv",
    "deepdoc",
    "docling",
    "docx",
    "email",
    "excel",
    "html",
    "image",
    "json",
    "markitdown",
    "pandoc",
    "pptx",
    "textin",
    "video",
]

EXPECTED_PDF_FALLBACK_BACKENDS = [
    "deepdoc",
    "deepseek_ocr",
    "docling",
    "etl4llm",
    "glm_ocr",
    "magicpdf",
    "marker",
    "mineru",
    "olmocr",
    "paddle_vl",
    "qianfan_ocr",
    "textin",
]

EXPECTED_DOCX_FALLBACK_BACKENDS = ["deepdoc", "docling", "textin"]

EXPECTED_EXPORT_CAPABILITIES = [
    {
        "export_name": "MinerUParser",
        "module_name": "app.parsing.parsers.mineru_parser",
        "class_name": "MinerUParser",
        "backend_name": "mineru",
    },
    {
        "export_name": "DoclingParser",
        "module_name": "app.parsing.parsers.docling_parser",
        "class_name": "DoclingParser",
        "backend_name": "docling",
    },
    {
        "export_name": "TCADPParser",
        "module_name": "app.parsing.parsers.tcadp_parser",
        "class_name": "TCADPParser",
        "backend_name": "tcadp",
    },
    {
        "export_name": "Etl4LlmParser",
        "module_name": "app.parsing.parsers.etl4llm_parser",
        "class_name": "Etl4LlmParser",
        "backend_name": "etl4llm",
    },
]

EXPECTED_DEFAULT_BACKENDS = {
    "auto",
    "audio",
    "basic",
    "csv",
    "docx",
    "email",
    "excel",
    "html",
    "image",
    "json",
    "markdown",
    "markitdown",
    "pptx",
    "text",
    "video",
}

EXPECTED_OPTIONAL_BACKENDS = {
    "deepdoc",
    "deepseek_ocr",
    "docling",
    "etl4llm",
    "glm_ocr",
    "magicpdf",
    "marker",
    "mineru",
    "olmocr",
    "paddle_vl",
    "pandoc",
    "qianfan_ocr",
    "textin",
}

EXPECTED_EXPERIMENTAL_BACKENDS = {"colpali"}


def _run_python_snippet(snippet: str) -> dict[str, object]:
    env = {**os.environ, "PYTHONWARNINGS": "ignore::FutureWarning"}
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(snippet)],
        capture_output=True,
        check=True,
        env=env,
        text=True,
    )
    return json.loads(result.stdout.strip())


def test_parsers_package_export_names_are_stable() -> None:
    import app.parsing.parsers as parsers

    assert parsers.__all__ == EXPECTED_PARSER_EXPORTS


def test_parser_backend_aliases_are_stable() -> None:
    from app.parsing.backends import _BACKEND_ALIASES

    assert _BACKEND_ALIASES == EXPECTED_BACKEND_ALIASES


def test_parser_factory_supported_backend_sets_are_stable() -> None:
    assert sorted(ParserFactory.SUPPORTED_PDF_BACKENDS) == EXPECTED_PDF_BACKENDS
    assert sorted(ParserFactory.SUPPORTED_NON_PDF_BACKENDS) == EXPECTED_NON_PDF_BACKENDS
    assert sorted(ParserFactory.PDF_ADVANCED_FALLBACK_BACKENDS) == EXPECTED_PDF_FALLBACK_BACKENDS
    assert sorted(ParserFactory.DOCX_ADVANCED_FALLBACK_BACKENDS) == EXPECTED_DOCX_FALLBACK_BACKENDS


def test_parser_capability_discovery_is_stable() -> None:
    import app.parsing.parsers as parsers

    capabilities = parsers.get_parser_capabilities()
    assert [
        {
            "export_name": item.export_name,
            "module_name": item.module_name,
            "class_name": item.class_name,
            "backend_name": item.backend_name,
        }
        for item in capabilities
    ] == EXPECTED_EXPORT_CAPABILITIES


def test_parser_capability_lookup_returns_expected_item() -> None:
    import app.parsing.parsers as parsers

    capability = parsers.get_parser_capability("DoclingParser")
    assert capability is not None
    assert capability.export_name == "DoclingParser"
    assert capability.backend_name == "docling"
    assert parsers.get_parser_capability("MissingParser") is None


def test_parser_backend_capability_discovery_covers_factory_supported_backends() -> None:
    import app.parsing.parsers as parsers

    families = {
        item["resolved_backend"]: item
        for item in parsers.list_parser_backend_capabilities()
    }

    assert set(families) == (
        EXPECTED_DEFAULT_BACKENDS
        | EXPECTED_OPTIONAL_BACKENDS
        | EXPECTED_EXPERIMENTAL_BACKENDS
    )

    supported_pdf = {
        name
        for name, item in families.items()
        if item["supports_pdf"] and item["user_selectable"] and not item["implicit_only"]
    }
    supported_non_pdf = {
        name
        for name, item in families.items()
        if item["supports_non_pdf"] and item["user_selectable"] and not item["implicit_only"]
    }
    pdf_fallback = {
        name
        for name in EXPECTED_PDF_FALLBACK_BACKENDS
        if name in families
    }
    docx_fallback = {
        name
        for name in EXPECTED_DOCX_FALLBACK_BACKENDS
        if name in families
    }

    assert supported_pdf == set(ParserFactory.SUPPORTED_PDF_BACKENDS)
    assert supported_non_pdf == set(ParserFactory.SUPPORTED_NON_PDF_BACKENDS)
    assert pdf_fallback == set(ParserFactory.PDF_ADVANCED_FALLBACK_BACKENDS)
    assert docx_fallback == set(ParserFactory.DOCX_ADVANCED_FALLBACK_BACKENDS)


def test_parser_backend_capability_discovery_reports_tiers_and_aliases() -> None:
    import app.parsing.parsers as parsers

    etl4llm = parsers.get_parser_backend_capabilities("bisheng-unstructured")
    colpali = parsers.get_parser_backend_capabilities("col-qwen")
    basic = parsers.get_parser_backend_capabilities("pymupdf")
    text = parsers.get_parser_backend_capabilities("text")
    auto = parsers.get_parser_backend_capabilities(None)
    unknown = parsers.get_parser_backend_capabilities("unknown-backend")

    assert etl4llm == {
        "requested_backend": "bisheng-unstructured",
        "resolved_backend": "etl4llm",
        "aliases": ["etl4llm", "etl-4llm", "bisheng-unstructured", "bishengunstructured", "bisheng"],
        "tier": "optional",
        "category": "service",
        "supports_pdf": True,
        "supports_non_pdf": False,
        "user_selectable": True,
        "implicit_only": False,
        "default": False,
        "optional": True,
        "experimental": False,
        "lazy_modules": ["app.parsing.parsers.etl4llm_parser"],
    }
    assert colpali == {
        "requested_backend": "col-qwen",
        "resolved_backend": "colpali",
        "aliases": ["colpali", "col-pali", "col-qwen", "colqwen"],
        "tier": "experimental",
        "category": "vision",
        "supports_pdf": True,
        "supports_non_pdf": True,
        "user_selectable": True,
        "implicit_only": False,
        "default": False,
        "optional": False,
        "experimental": True,
        "lazy_modules": ["app.parsing.parsers.colpali_parser"],
    }
    assert basic == {
        "requested_backend": "pymupdf",
        "resolved_backend": "basic",
        "aliases": ["basic", "pymupdf", "fitz"],
        "tier": "default",
        "category": "pdf_local",
        "supports_pdf": True,
        "supports_non_pdf": False,
        "user_selectable": True,
        "implicit_only": False,
        "default": True,
        "optional": False,
        "experimental": False,
        "lazy_modules": ["app.parsing.parsers.pdf_parser"],
    }
    assert text == {
        "requested_backend": "text",
        "resolved_backend": "text",
        "aliases": ["text"],
        "tier": "default",
        "category": "builtin",
        "supports_pdf": False,
        "supports_non_pdf": True,
        "user_selectable": False,
        "implicit_only": True,
        "default": True,
        "optional": False,
        "experimental": False,
        "lazy_modules": ["app.parsing.parsers.text_parser"],
    }
    assert auto["resolved_backend"] == "auto"
    assert auto["default"] is True
    assert auto["lazy_modules"] == []
    assert unknown == {
        "requested_backend": "unknown-backend",
        "resolved_backend": None,
        "aliases": [],
        "tier": "experimental",
        "category": "unknown",
        "supports_pdf": False,
        "supports_non_pdf": False,
        "user_selectable": False,
        "implicit_only": False,
        "default": False,
        "optional": False,
        "experimental": True,
        "lazy_modules": [],
    }


def test_parsers_package_missing_attribute_error_is_stable() -> None:
    import app.parsing.parsers as parsers

    with pytest.raises(AttributeError) as exc_info:
        parsers.MissingParser  # type: ignore[attr-defined]

    assert str(exc_info.value) == "module 'app.parsing.parsers' has no attribute 'MissingParser'"


def test_parser_factory_rejects_unsupported_pdf_backend_with_current_message() -> None:
    factory = ParserFactory()

    with pytest.raises(ValueError) as exc_info:
        factory.resolve_backend(".pdf", "unknown-backend")

    assert str(exc_info.value) == (
        "Unsupported parser backend 'unknown-backend'. "
        f"Supported backends: {EXPECTED_PDF_BACKENDS}"
    )


def test_parser_factory_rejects_disabled_docling_backend_with_current_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.parsing import factory as factory_module

    monkeypatch.setattr(factory_module.settings, "DOCLING_ENABLED", False, raising=False)
    factory = ParserFactory()

    with pytest.raises(ValueError) as exc_info:
        factory.resolve_backend(".pdf", "docling")

    assert str(exc_info.value) == "Docling parser is not enabled. Please set DOCLING_ENABLED=True."


def test_parser_factory_requires_external_docling_service_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.parsing import factory as factory_module

    monkeypatch.setattr(factory_module.settings, "DOCLING_ENABLED", True, raising=False)
    monkeypatch.setattr(factory_module.settings, "DOCLING_API_URL", "", raising=False)

    with pytest.raises(ValueError, match="requires DOCLING_API_URL"):
        ParserFactory().resolve_backend(".pdf", "docling")


def test_parser_factory_rejects_disabled_mineru_backend_with_current_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.parsing import factory as factory_module

    monkeypatch.setattr(factory_module.settings, "MINERU_ENABLED", False, raising=False)
    monkeypatch.setattr(factory_module.settings, "MINERU_API_TOKEN", "", raising=False)
    monkeypatch.setattr(factory_module.settings, "MINERU_LOCAL_SERVER_URL", "", raising=False)
    factory = ParserFactory()

    with pytest.raises(ValueError) as exc_info:
        factory.resolve_backend(".pdf", "mineru")

    assert str(exc_info.value) == (
        "MinerU parser is not enabled. Please set MINERU_ENABLED=True and configure "
        "MINERU_API_TOKEN (online) or MINERU_LOCAL_SERVER_URL (local ZIP mode)."
    )


def test_parser_factory_rejects_docling_for_unsupported_non_pdf_extension() -> None:
    factory = ParserFactory()

    with pytest.raises(ValueError) as exc_info:
        factory.resolve_backend(".csv", "docling")

    assert str(exc_info.value) == "docling backend currently supports only .docx (non-PDF)"


def test_parser_factory_pdf_fallback_contract_is_stable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    factory = ParserFactory()
    pdf_path = tmp_path / "fallback.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    class _BasicParser:
        def parse(self, _file_path: Path) -> list[Document]:
            return [Document(page_content="basic fallback", metadata={})]

    def _parse_backend_documents(**kwargs):  # noqa: ANN003, ANN202
        backend = kwargs["backend"]
        if backend == "docling":
            raise RuntimeError("primary parser failed")
        raise AssertionError(f"Unexpected backend: {backend}")

    monkeypatch.setattr(factory, "resolve_backend", lambda *_args, **_kwargs: "docling")
    monkeypatch.setattr(factory, "_parse_backend_documents", _parse_backend_documents)
    monkeypatch.setattr(factory, "_get_pdf_parser", lambda backend: _BasicParser() if backend == "basic" else None)

    documents, backend, provenance = factory.parse_with_provenance(pdf_path)

    assert backend == "basic"
    assert [doc.page_content for doc in documents] == ["basic fallback"]
    assert documents[0].metadata["parser_backend"] == "basic"
    assert provenance["resolved_backend"] == "basic"
    assert provenance["attempts"][0]["backend"] == "docling"
    assert provenance["attempts"][0]["ok"] is False
    assert provenance["attempts"][1]["backend"] == "basic"
    assert provenance["attempts"][1]["ok"] is True
    assert provenance["attempts"][1]["fallback_from"] == "docling"


def test_parser_factory_docx_fallback_contract_is_stable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    factory = ParserFactory()
    docx_path = tmp_path / "fallback.docx"
    docx_path.write_bytes(b"docx-bytes")

    class _MarkItDownParser:
        def parse(self, _file_path: Path) -> list[Document]:
            return [Document(page_content="markitdown fallback", metadata={})]

    def _parse_backend_documents(**kwargs):  # noqa: ANN003, ANN202
        backend = kwargs["backend"]
        if backend == "docling":
            raise RuntimeError("primary parser failed")
        raise AssertionError(f"Unexpected backend: {backend}")

    monkeypatch.setattr(factory, "resolve_backend", lambda *_args, **_kwargs: "docling")
    monkeypatch.setattr(factory, "_parse_backend_documents", _parse_backend_documents)
    monkeypatch.setattr(factory, "_try_docx_pandoc_fallback", lambda _file_path: None)
    monkeypatch.setattr(factory, "_get_markitdown_parser", lambda: _MarkItDownParser())

    documents, backend = factory.parse(docx_path, allow_fallback=True)

    assert backend == "markitdown"
    assert [doc.page_content for doc in documents] == ["markitdown fallback"]
    assert documents[0].metadata["parser_backend"] == "markitdown"


def test_importing_parsers_package_keeps_default_import_surface_light() -> None:
    payload = _run_python_snippet(
        """
        import json
        import sys

        before = set(sys.modules)
        import app.parsing.parsers as parsers  # noqa: F401
        after = set(sys.modules)
        added = sorted(name for name in after - before if name.startswith("app.parsing.parsers"))
        print(json.dumps({"added": added}))
        """
    )

    assert payload == {
        "added": [
            "app.parsing.parsers",
            "app.parsing.parsers.base_parser",
        ]
    }


def test_parser_capability_discovery_is_lazy() -> None:
    payload = _run_python_snippet(
        """
        import json
        import sys

        before = set(sys.modules)
        import app.parsing.parsers as parsers
        after_import = set(sys.modules)
        capabilities = parsers.get_parser_capabilities()
        after_capabilities = set(sys.modules)
        print(
            json.dumps(
                {
                    "after_import": sorted(
                        name for name in after_import - before if name.startswith("app.parsing.parsers")
                    ),
                    "after_capabilities": sorted(
                        name for name in after_capabilities - after_import if name.startswith("app.parsing.parsers")
                    ),
                    "exports": [item.export_name for item in capabilities],
                }
            )
        )
        """
    )

    assert payload == {
        "after_import": [
            "app.parsing.parsers",
            "app.parsing.parsers.base_parser",
        ],
        "after_capabilities": [
            "app.parsing.parsers.capabilities",
            "app.parsing.parsers.registry",
        ],
        "exports": [item["export_name"] for item in EXPECTED_EXPORT_CAPABILITIES],
    }


def test_parser_backend_capability_discovery_is_lazy() -> None:
    payload = _run_python_snippet(
        """
        import json
        import sys

        before = set(sys.modules)
        import app.parsing.parsers as parsers
        after_import = set(sys.modules)
        capabilities = parsers.list_parser_backend_capabilities()
        after_capabilities = set(sys.modules)
        print(
            json.dumps(
                {
                    "after_import": sorted(
                        name for name in after_import - before if name.startswith("app.parsing.parsers")
                    ),
                    "after_capabilities": sorted(
                        name for name in after_capabilities - after_import if name.startswith("app.parsing.parsers")
                    ),
                    "count": len(capabilities),
                    "resolved_backends": [item["resolved_backend"] for item in capabilities],
                }
            )
        )
        """
    )

    assert payload == {
        "after_import": [
            "app.parsing.parsers",
            "app.parsing.parsers.base_parser",
        ],
        "after_capabilities": [
            "app.parsing.parsers.capabilities",
            "app.parsing.parsers.registry",
        ],
        "count": 29,
        "resolved_backends": [
            "auto",
            "basic",
            "marker",
            "paddle_vl",
            "glm_ocr",
            "olmocr",
            "qianfan_ocr",
            "textin",
            "mineru",
            "deepdoc",
            "deepseek_ocr",
            "etl4llm",
            "markitdown",
            "docling",
            "magicpdf",
            "colpali",
            "pandoc",
            "excel",
            "docx",
            "pptx",
            "html",
            "csv",
            "json",
            "email",
            "image",
            "audio",
            "video",
            "text",
            "markdown",
        ],
    }


def test_parser_factory_and_backend_capability_discovery_do_not_import_implementations_in_fresh_interpreter() -> None:
    payload = _run_python_snippet(
        """
        import importlib
        import json
        import sys

        parser_modules = [
            "app.parsing.parsers.pdf_parser",
            "app.parsing.parsers.marker_parser",
            "app.parsing.parsers.paddle_vl_parser",
            "app.parsing.parsers.glm_ocr_parser",
            "app.parsing.parsers.olmocr_parser",
            "app.parsing.parsers.qianfan_ocr_parser",
            "app.parsing.parsers.textin_parser",
            "app.parsing.parsers.mineru_parser",
            "app.parsing.parsers.deepdoc_parser",
            "app.parsing.parsers.deepseek_ocr_parser",
            "app.parsing.parsers.etl4llm_parser",
            "app.parsing.parsers.markitdown_parser",
            "app.parsing.parsers.docling_parser",
            "app.parsing.parsers.magic_pdf_parser",
            "app.parsing.parsers.colpali_parser",
            "app.parsing.parsers.pandoc_parser",
            "app.parsing.parsers.excel_parser",
            "app.parsing.parsers.docx_parser",
            "app.parsing.parsers.pptx_parser",
            "app.parsing.parsers.html_parser",
            "app.parsing.parsers.csv_parser",
            "app.parsing.parsers.json_parser",
            "app.parsing.parsers.email_parser",
            "app.parsing.parsers.image_parser",
            "app.parsing.parsers.audio_parser",
            "app.parsing.parsers.video_parser",
            "app.parsing.parsers.tcadp_parser",
        ]
        for name in parser_modules:
            sys.modules.pop(name, None)
        importlib.import_module("app.parsing.factory")
        from app.parsing.parsers import list_parser_backend_capabilities

        list_parser_backend_capabilities()
        print(json.dumps([name for name in parser_modules if name in sys.modules]))
        """
    )

    assert payload == []


def test_parser_export_resolution_loads_only_requested_parser_module() -> None:
    payload = _run_python_snippet(
        """
        import json
        import sys

        before = set(sys.modules)
        import app.parsing.parsers as parsers
        after_import = set(sys.modules)
        parser_cls = parsers.TCADPParser
        after_attr = set(sys.modules)
        print(
            json.dumps(
                {
                    "after_import": sorted(
                        name for name in after_import - before if name.startswith("app.parsing.parsers")
                    ),
                    "after_attr": sorted(
                        name for name in after_attr - after_import if name.startswith("app.parsing.parsers")
                    ),
                    "class_name": parser_cls.__name__,
                }
            )
        )
        """
    )

    assert payload == {
        "after_import": [
            "app.parsing.parsers",
            "app.parsing.parsers.base_parser",
        ],
        "after_attr": [
            "app.parsing.parsers.registry",
            "app.parsing.parsers.tcadp_parser",
        ],
        "class_name": "TCADPParser",
    }
