from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.parsing.parsers.etl4llm_parser import Etl4LlmParser


class _FakePixmap:
    def tobytes(self, fmt: str) -> bytes:
        assert fmt == "jpg"
        return b"fake-jpg-bytes"


class _FakePage:
    def get_pixmap(self, *, dpi: int):  # noqa: ANN001
        assert dpi == 144
        return _FakePixmap()


class _FakePdf:
    def __init__(self, page_count: int) -> None:
        self._pages = [_FakePage() for _ in range(page_count)]

    def __iter__(self):
        return iter(self._pages)

    def close(self) -> None:
        return None


def test_etl4llm_parser_falls_back_to_page_images_when_service_returns_empty_result(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "ETL4LLM_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ETL4LLM_API_URL", "http://etl4llm.local/v1/etl4llm/predict", raising=False)
    monkeypatch.setattr(settings, "ETL4LLM_TIMEOUT_SEC", 30, raising=False)
    monkeypatch.setattr(settings, "ETL4LLM_MODE", "partition", raising=False)
    monkeypatch.setattr(settings, "ETL4LLM_FORCE_OCR", True, raising=False)
    monkeypatch.setattr(settings, "ETL4LLM_ENABLE_FORMULA", True, raising=False)
    monkeypatch.setattr(settings, "ETL4LLM_EXTRACT_IMAGES", True, raising=False)
    monkeypatch.setattr(settings, "ETL4LLM_INCLUDE_PAGE_IMAGES_IF_EMPTY", True, raising=False)
    monkeypatch.setattr(settings, "ETL4LLM_PAGE_IMAGE_DPI", 144, raising=False)
    monkeypatch.setattr(settings, "ETL4LLM_PAGE_IMAGE_MAX_PAGES", 2, raising=False)

    parser = Etl4LlmParser()
    monkeypatch.setattr(
        parser,
        "_call_api",
        lambda **_kwargs: {
            "status_code": 200,
            "status_message": "success",
            "text": "",
            "html_text": "",
            "partitions": [],
        },
        raising=True,
    )
    monkeypatch.setattr("app.parsing.parsers.etl4llm_parser.fitz.open", lambda *_args, **_kwargs: _FakePdf(2))

    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%etl4llm-test\n")

    docs = parser.parse(pdf_path, document_id="doc-empty")

    assert len(docs) == 1
    assert docs[0].metadata["parser_backend"] == "etl4llm"
    assert docs[0].metadata["etl4llm_partitions"] == 0
    assert docs[0].metadata["etl4llm_page_images"] == 2
    assert "![page 1](images/page_0001.jpg)" in (docs[0].page_content or "")
    assert "![page 2](images/page_0002.jpg)" in (docs[0].page_content or "")

    artifact_root = Path(str(docs[0].metadata["artifact_dir"]))
    assert (artifact_root / "images" / "page_0001.jpg").read_bytes() == b"fake-jpg-bytes"
    assert (artifact_root / "images" / "page_0002.jpg").read_bytes() == b"fake-jpg-bytes"
