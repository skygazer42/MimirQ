from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.parsing.parsers.base_parser import BaseAdvancedParser
from app.parsing.parsers.email_parser import EmailParser, _extract_body


class _ParserForTests(BaseAdvancedParser):
    def _create_parser(self):
        return object()

    def _get_parser_name(self) -> str:
        return "test"

    def _check_parser_installation(self, parser):
        _ = parser
        return True, ""

    def _call_parse_method(self, parser, file_path, binary, callback, **kwargs):
        _ = (parser, file_path, binary, callback, kwargs)
        return [], []


def _reset_backend_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    defaults = {
        "DOCLING_ENABLED": False,
        "ETL4LLM_ENABLED": False,
        "ETL4LLM_API_URL": "",
        "MARKITDOWN_ENABLED": False,
        "DEEPDOC_ENABLED": False,
        "MINERU_ENABLED": False,
        "MINERU_API_TOKEN": "",
        "MINERU_LOCAL_SERVER_URL": "",
        "DEEPSEEK_OCR_ENABLED": False,
        "SILICONFLOW_API_KEY": "",
        "QIANFAN_OCR_ENABLED": False,
        "QIANFAN_OCR_API_URL": "",
        "MAGIC_PDF_ENABLED": False,
        "MAGIC_PDF_API_URL": "",
        "MAGIC_PDF_CLI": "magic-pdf",
        "MAGIC_PDF_MODELS_DIR": "",
    }
    for name, value in defaults.items():
        monkeypatch.setattr(settings, name, value, raising=False)


def _configure_etl4llm(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    defaults = {
        "ETL4LLM_ENABLED": True,
        "ETL4LLM_API_URL": "http://etl4llm",
        "ETL4LLM_TIMEOUT_SEC": 120,
        "ETL4LLM_MODE": "partition",
        "ETL4LLM_FORCE_OCR": False,
        "ETL4LLM_ENABLE_FORMULA": True,
        "ETL4LLM_EXTRACT_IMAGES": True,
        "ETL4LLM_FILTER_PAGE_HEADER_FOOTER": False,
        "ETL4LLM_INCLUDE_PAGE_IMAGES_IF_EMPTY": True,
        "ETL4LLM_PAGE_IMAGE_DPI": 144,
        "ETL4LLM_PAGE_IMAGE_MAX_PAGES": 2,
    }
    defaults.update(overrides)
    for name, value in defaults.items():
        monkeypatch.setattr(settings, name, value, raising=False)


def _configure_magicpdf(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    defaults = {
        "MAGIC_PDF_CLI": "magic-pdf",
        "MAGIC_PDF_API_URL": "",
        "MAGIC_PDF_REQUEST_TIMEOUT_SEC": 600,
        "MAGIC_PDF_TIMEOUT_SEC": 600,
        "MAGIC_PDF_DEBUG": False,
        "MAGIC_PDF_LANG": "",
        "MAGIC_PDF_METHOD": "auto",
        "MINERU_TOOLS_CONFIG_JSON": "",
        "MAGIC_PDF_MODELS_DIR": "",
        "MAGIC_PDF_DEVICE_MODE": "cpu",
        "MAGIC_PDF_FORMULA_ENABLED": False,
        "MINIO_ENABLED": True,
    }
    defaults.update(overrides)
    for name, value in defaults.items():
        monkeypatch.setattr(settings, name, value, raising=False)


def test_base_advanced_parser_characterizes_section_and_table_document_order() -> None:
    parser = _ParserForTests()
    base_metadata = {"source": "sample.pdf", "parser": "test"}

    section_docs = parser._convert_sections_to_documents(
        [
            ("Heading", "text"),
            ("x = y", "equation", "@@2-3\t1\t2\t3\t4##"),
            "Trailing paragraph",
        ],
        base_metadata,
    )
    table_docs = parser._convert_tables_to_documents(
        [((object(), ["A", "B"]), [(0, 10, 20, 30, 40)])],
        base_metadata,
    )

    assert [doc.metadata["content_type"] for doc in section_docs] == ["text", "equation"]
    assert section_docs[0].page_content == "Heading\n\nTrailing paragraph"
    assert section_docs[1].page_content == "x = y@@2-3\t1\t2\t3\t4##"
    assert section_docs[1].metadata["positions"] == [(1, 1.0, 2.0, 3.0, 4.0), (2, 1.0, 2.0, 3.0, 4.0)]
    assert section_docs[1].metadata["element_page"] == 2
    assert section_docs[1].metadata["element_bbox"] == {"x0": 1, "x1": 2, "y0": 3, "y1": 4}

    assert [doc.metadata["content_type"] for doc in table_docs] == ["table", "image"]
    assert table_docs[0].page_content == "A\nB"
    assert table_docs[1].page_content == "A\nB"
    assert table_docs[1].metadata["positions"] == [(0, 10, 20, 30, 40)]
    assert "image" in table_docs[1].metadata


def test_extract_body_prefers_plain_text_and_skips_attachments() -> None:
    message = EmailMessage()
    message.set_content("Plain body")
    message.add_alternative("<p>HTML <b>body</b></p>", subtype="html")
    message.add_attachment(b"ignored", maintype="application", subtype="octet-stream", filename="skip.bin")

    body, meta = _extract_body(message)

    assert body == "Plain body"
    assert meta == {"body_content_type": "text/plain", "warnings": []}


def test_email_parser_characterizes_markdown_and_html_fallback(tmp_path: Path) -> None:
    message = EmailMessage()
    message["Subject"] = "Weekly update"
    message["From"] = "alice@example.com"
    message["To"] = "team@example.com"
    message["Cc"] = "ops@example.com"
    message["Date"] = "Mon, 01 Jan 2024 10:00:00 +0000"
    message.add_alternative("<div><p>Hello <b>team</b></p></div>", subtype="html")

    path = tmp_path / "sample.eml"
    path.write_bytes(message.as_bytes())

    document = EmailParser().parse(path)[0]

    assert document.page_content == (
        "# Weekly update\n\n"
        "- From: alice@example.com\n"
        "- To: team@example.com\n"
        "- Cc: ops@example.com\n"
        "- Date: Mon, 01 Jan 2024 10:00:00 +0000\n\n"
        "---\n\n"
        "Hello  team\n"
    )
    assert document.metadata == {
        "source": "sample.eml",
        "file_type": "eml",
        "parser_backend": "email",
        "email_subject": "Weekly update",
        "email_body_content_type": "text/html",
        "email_warnings": [],
    }


@pytest.mark.parametrize(
    ("quality", "requested", "settings_overrides", "magicpdf_available", "expected"),
    [
        ({}, "magic-pdf", {}, False, "magicpdf"),
        (
            {"score": 0.92, "text_quality_score": 0.7, "page_count": 6, "is_scanned": False},
            None,
            {"DOCLING_ENABLED": False, "ETL4LLM_ENABLED": True, "ETL4LLM_API_URL": "http://etl4llm"},
            False,
            "etl4llm",
        ),
        (
            {"score": 0.61, "text_quality_score": 0.12, "page_count": 12, "is_scanned": True},
            None,
            {},
            False,
            "basic",
        ),
        (
            {"score": 0.4, "text_quality_score": 0.0, "page_count": 9, "is_scanned": True},
            None,
            {
                "DEEPSEEK_OCR_ENABLED": True,
                "SILICONFLOW_API_KEY": "token",
                "QIANFAN_OCR_ENABLED": True,
                "QIANFAN_OCR_API_URL": "http://qianfan",
            },
            False,
            "deepseek_ocr",
        ),
        (
            {"score": 0.68, "text_quality_score": 0.45, "page_count": 3, "is_scanned": False},
            None,
            {"DOCLING_ENABLED": True},
            False,
            "basic",
        ),
        (
            {"score": 0.7, "text_quality_score": 0.2, "page_count": 10, "is_scanned": False},
            None,
            {"DOCLING_ENABLED": False, "MAGIC_PDF_ENABLED": True},
            True,
            "magicpdf",
        ),
    ],
)
def test_choose_pdf_backend_characterizes_precedence(
    monkeypatch: pytest.MonkeyPatch,
    quality: dict[str, object],
    requested: str | None,
    settings_overrides: dict[str, object],
    magicpdf_available: bool,
    expected: str,
) -> None:
    from app.parsing import routing

    _reset_backend_settings(monkeypatch)
    for name, value in settings_overrides.items():
        monkeypatch.setattr(settings, name, value, raising=False)
    monkeypatch.setattr(routing, "magicpdf_service_configured", lambda _value=None: False, raising=True)
    monkeypatch.setattr(
        routing,
        "resolve_magicpdf_models_dir",
        lambda _value=None: "/models" if magicpdf_available else None,
        raising=True,
    )
    monkeypatch.setattr(
        routing,
        "resolve_cli_command",
        lambda _value: "/usr/bin/magic-pdf" if magicpdf_available else None,
        raising=True,
    )

    assert routing.choose_pdf_backend(quality, requested) == expected


def test_etl4llm_merge_partitions_characterizes_spacing_and_shifted_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.parsing.parsers.etl4llm_parser import Etl4LlmParser

    _configure_etl4llm(monkeypatch, ETL4LLM_FILTER_PAGE_HEADER_FOOTER=True)
    parser = Etl4LlmParser()

    merged, meta = parser._merge_partitions(
        partitions=[
            {"type": "page_header", "text": "skip me"},
            {
                "type": "title",
                "text": "Title",
                "metadata": {
                    "extra_data": {"indexes": [[0, 5]], "types": ["title"], "pages": [1], "bboxes": [[1, 2, 3, 4]]}
                },
            },
            {
                "type": "table",
                "text": "|A|B|",
                "metadata": {
                    "extra_data": {"indexes": [[0, 5]], "types": ["table"], "pages": [1], "bboxes": [[5, 6, 7, 8]]}
                },
            },
            {
                "type": "image",
                "text": "service image",
                "element_id": "img-1",
                "metadata": {
                    "extra_data": {"indexes": [[0, 14]], "types": ["image"], "pages": [2], "bboxes": [[9, 10, 11, 12]]}
                },
            },
        ],
        image_map={"img-1": "images/img-1.png"},
    )

    assert merged == "Title\n\n\n|A|B|\n\n![](images/img-1.png)"
    assert meta == {
        "bboxes": [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]],
        "pages": [1, 1, 2],
        "indexes": [[0, 5], [6, 11], [13, 27]],
        "types": ["title", "table", "image"],
    }


def test_etl4llm_parse_characterizes_page_image_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.parsing.parsers.etl4llm_parser import Etl4LlmParser

    class _FakePixmap:
        def tobytes(self, fmt: str) -> bytes:
            assert fmt == "jpg"
            return b"jpg-bytes"

    class _FakePage:
        def get_pixmap(self, *, dpi: int) -> _FakePixmap:
            assert dpi == 144
            return _FakePixmap()

    class _FakePdf:
        def __iter__(self):
            return iter([_FakePage(), _FakePage()])

        def close(self) -> None:
            return None

    _configure_etl4llm(monkeypatch, ETL4LLM_PAGE_IMAGE_DPI=144, ETL4LLM_PAGE_IMAGE_MAX_PAGES=1)
    parser = Etl4LlmParser()
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(parser, "_call_api", lambda **_kwargs: {"partitions": [], "text": "Merged text"}, raising=True)
    monkeypatch.setattr("app.parsing.parsers.etl4llm_parser.fitz.open", lambda _path: _FakePdf())

    document = parser.parse(pdf_path, document_id="doc-1")[0]

    assert document.page_content == "![page 1](images/page_0001.jpg)\n\nMerged text"
    assert document.metadata["etl4llm_page_images"] == 1
    assert document.metadata["asset_base_dir"].endswith(".etl4llm/doc-1")
    assert (Path(document.metadata["asset_base_dir"]) / "images" / "page_0001.jpg").read_bytes() == b"jpg-bytes"


def test_magicpdf_parse_prefers_service_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.parsing.parsers.magic_pdf_parser import MagicPDFParser

    _configure_magicpdf(monkeypatch, MAGIC_PDF_API_URL="http://magicpdf")
    parser = MagicPDFParser()
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    expected = [Document(page_content="service markdown", metadata={"parser_backend": "magicpdf"})]
    called: list[tuple[Path, str | None, str | None]] = []

    def _parse_service(file_path: Path, *, dataset_id: str | None, document_id: str | None) -> list[Document]:
        called.append((file_path, dataset_id, document_id))
        return expected

    monkeypatch.setattr(parser, "_parse_service", _parse_service, raising=True)
    monkeypatch.setattr(
        parser, "_ensure_cli", lambda: (_ for _ in ()).throw(AssertionError("CLI path should not run")), raising=True
    )

    documents = parser.parse(pdf_path, dataset_id="ds-1", document_id="doc-1")

    assert documents == expected
    assert called == [(pdf_path, "ds-1", "doc-1")]


def test_magicpdf_parse_characterizes_local_markdown_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.parsing.parsers import magic_pdf_parser

    artifact_root = tmp_path / "artifacts" / "run-1"
    pdf_path = tmp_path / "sample.pdf"
    config_path = tmp_path / "magic-pdf.json"
    pdf_path.write_bytes(b"%PDF-1.4")
    config_path.write_text("{}", encoding="utf-8")

    _configure_magicpdf(monkeypatch, MINIO_ENABLED=False, MAGIC_PDF_LANG="en", MAGIC_PDF_METHOD="ocr")
    parser = magic_pdf_parser.MagicPDFParser()
    monkeypatch.setattr(parser, "_ensure_cli", lambda: "/usr/bin/magic-pdf", raising=True)
    monkeypatch.setattr(parser, "_resolve_method", lambda: "ocr", raising=True)
    monkeypatch.setattr(parser, "_ensure_tools_config", lambda _artifact_root: config_path, raising=True)
    monkeypatch.setattr(parser, "_build_artifact_root", lambda _file_path, _document_id: artifact_root, raising=True)

    def _run_resolved_cli(cmd, **kwargs):
        _ = kwargs
        expected_md = artifact_root / "run-1" / "ocr" / "run-1.md"
        expected_md.parent.mkdir(parents=True, exist_ok=True)
        expected_md.write_text("alpha\n![img](images/a.png)\n<img src='images/b.png'>\nomega\n", encoding="utf-8")
        return SimpleNamespace(stdout="ok")

    monkeypatch.setattr(magic_pdf_parser, "run_resolved_cli", _run_resolved_cli, raising=True)

    document = parser.parse(pdf_path, document_id="doc-1")[0]

    assert "![img]" not in document.page_content
    assert "<img" not in document.page_content
    assert "alpha" in document.page_content
    assert "omega" in document.page_content
    assert document.metadata == {
        "source": "sample.pdf",
        "file_type": "pdf",
        "parser_backend": "magicpdf",
        "asset_base_dir": str(artifact_root / "run-1" / "ocr"),
        "artifact_dir": str(artifact_root),
        "magicpdf_method": "ocr",
        "magicpdf_lang": "en",
    }


@pytest.mark.asyncio
async def test_run_subprocess_worker_characterizes_timeout_termination_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.parsing import subprocess_runner

    class _RunningProcess:
        pid = 321
        returncode = None

    process = _RunningProcess()
    terminated = False
    monotonic_values = iter([0.0, 10.0, 10.0, 10.0])

    async def _spawn(*_args, **_kwargs):
        return process

    async def _sleep(_delay: float) -> None:
        return None

    async def _terminate(target, **_kwargs) -> None:
        nonlocal terminated
        assert target is process
        terminated = True
        target.returncode = -15

    monkeypatch.setattr(subprocess_runner, "_get_subprocess_workdir", lambda **_kwargs: tmp_path)
    monkeypatch.setattr(subprocess_runner.asyncio, "create_subprocess_exec", _spawn)
    monkeypatch.setattr(subprocess_runner.asyncio, "sleep", _sleep)
    monkeypatch.setattr(subprocess_runner.time, "monotonic", lambda: next(monotonic_values, 10.0))
    monkeypatch.setattr(subprocess_runner, "_terminate_process_group", _terminate)

    with pytest.raises(subprocess_runner.SubprocessWorkerError, match="worker_timeout"):
        await subprocess_runner.run_subprocess_worker(
            tenant_id=uuid4(),
            payload={"document_id": "doc-1"},
            timeout_sec=5,
        )

    assert terminated is True
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_run_subprocess_worker_preserves_log_tail_when_result_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.parsing import subprocess_runner

    class _FinishedProcess:
        pid = 654
        returncode = 0

    async def _spawn(*_args, **kwargs):
        stdout = kwargs["stdout"]
        stdout.write(b"worker output\n")
        stdout.flush()
        return _FinishedProcess()

    monkeypatch.setattr(subprocess_runner, "_get_subprocess_workdir", lambda **_kwargs: tmp_path)
    monkeypatch.setattr(subprocess_runner.asyncio, "create_subprocess_exec", _spawn)

    with pytest.raises(subprocess_runner.SubprocessWorkerError) as exc_info:
        await subprocess_runner.run_subprocess_worker(
            tenant_id=uuid4(),
            payload={"document_id": "doc-2"},
        )

    assert "worker_did_not_write_result" in str(exc_info.value)
    assert exc_info.value.log_tail == "worker output"
    assert list(tmp_path.iterdir()) == []
