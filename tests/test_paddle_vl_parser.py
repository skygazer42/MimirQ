from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.parsing.parsers.paddle_vl_parser import PaddleVLParser
from app.parsing.utils.zip_processor import ZipImageProcessor


class _DummyZipResponse:
    def __init__(self, zip_bytes: bytes) -> None:
        self.status_code = 200
        self.headers = {"content-type": "application/zip"}
        self.content = zip_bytes
        self.text = ""


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "paddlevl"


def _read_fixture_zip(name: str) -> bytes:
    path = (FIXTURES_DIR / name).resolve()
    if not path.exists():
        raise FileNotFoundError(str(path))
    return path.read_bytes()


def test_paddle_vl_parser_zip_minio_disabled_strips_image_refs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "PADDLE_VL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_API_URL", "http://paddlevl.local/convert", raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_TIMEOUT_SEC", 3, raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", False, raising=False)

    zip_bytes = _read_fixture_zip("paddlevl_lite_output.zip")

    parser = PaddleVLParser()
    monkeypatch.setattr(parser, "_post_multipart", lambda **_kwargs: _DummyZipResponse(zip_bytes), raising=True)

    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake\n")

    docs = parser.parse(pdf_path, dataset_id="ds1", document_id="doc1")
    assert len(docs) == 1
    assert docs[0].metadata["element_kind"] == "paragraph"
    assert docs[0].metadata["element_text"] == docs[0].page_content
    assert docs[0].metadata["element_attributes"]["source_content_type"] == "text"
    assert docs[0].metadata["element_attributes"]["source_doc_type"] == "paragraph"

    asset_base_dir = str(docs[0].metadata.get("asset_base_dir") or "")
    assert asset_base_dir
    asset_root = Path(asset_base_dir)
    assert (asset_root / "result.md").exists()
    assert (asset_root / "images").exists()

    normalized_md = (asset_root / "result.md").read_text(encoding="utf-8", errors="ignore")
    assert "hello" in normalized_md
    assert "images/image_001.png" in normalized_md
    assert 'src="images/image_002.jpg"' in normalized_md

    content = docs[0].page_content or ""
    assert "hello" in content
    assert "![" not in content
    assert "<img" not in content.lower()


def test_paddle_vl_parser_zip_doc_parser_fixture_normalizes_and_strips_refs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "PADDLE_VL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_API_URL", "http://paddlevl.local/convert", raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_TIMEOUT_SEC", 3, raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", False, raising=False)

    zip_bytes = _read_fixture_zip("paddlevl_doc_parser_output.zip")

    parser = PaddleVLParser()
    monkeypatch.setattr(parser, "_post_multipart", lambda **_kwargs: _DummyZipResponse(zip_bytes), raising=True)

    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake\n")

    docs = parser.parse(pdf_path, dataset_id="ds1", document_id="doc1")
    assert len(docs) == 1
    assert docs[0].metadata["element_kind"] == "paragraph"
    assert docs[0].metadata["element_text"] == docs[0].page_content
    assert docs[0].metadata["element_attributes"]["source_content_type"] == "text"
    assert docs[0].metadata["element_attributes"]["source_doc_type"] == "paragraph"

    asset_base_dir = str(docs[0].metadata.get("asset_base_dir") or "")
    assert asset_base_dir
    asset_root = Path(asset_base_dir)
    assert (asset_root / "result.md").exists()
    assert (asset_root / "images").exists()

    normalized_md = (asset_root / "result.md").read_text(encoding="utf-8", errors="ignore")
    assert "# Parsed" in normalized_md
    assert "images/image_001.png" in normalized_md
    assert 'src="images/image_002.jpg"' in normalized_md

    content = docs[0].page_content or ""
    assert "Parsed" in content
    assert "![" not in content
    assert "<img" not in content.lower()


def test_paddle_vl_parser_zip_minio_enabled_uses_zip_processor(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "PADDLE_VL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_API_URL", "http://paddlevl.local/convert", raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_TIMEOUT_SEC", 3, raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)

    zip_bytes = _read_fixture_zip("paddlevl_lite_output.zip")

    called: dict[str, object] = {}

    def _fake_process_zip_with_images(zip_path: Path, dataset_id: str, document_id: str, tenant_id=None):  # noqa: ANN001
        called["zip_path"] = zip_path
        called["dataset_id"] = dataset_id
        called["document_id"] = document_id
        called["tenant_id"] = tenant_id
        return {"markdown": "hello ![](https://minio.local/images/p1.png)", "images": [], "image_count": 1}

    monkeypatch.setattr(ZipImageProcessor, "process_zip_with_images", _fake_process_zip_with_images, raising=True)

    parser = PaddleVLParser()
    monkeypatch.setattr(parser, "_post_multipart", lambda **_kwargs: _DummyZipResponse(zip_bytes), raising=True)

    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake\n")

    docs = parser.parse(pdf_path, dataset_id="ds1", document_id="doc1", tenant_id="t1")
    assert len(docs) == 1
    assert docs[0].metadata["element_kind"] == "paragraph"
    assert docs[0].metadata["element_text"] == docs[0].page_content
    assert docs[0].metadata["element_attributes"]["source_content_type"] == "text"
    assert docs[0].metadata["element_attributes"]["source_doc_type"] == "paragraph"
    assert docs[0].page_content == "hello ![](https://minio.local/images/p1.png)"

    assert called.get("dataset_id") == "ds1"
    assert called.get("document_id") == "doc1"
    assert called.get("tenant_id") == "t1"


class _TimeoutThenZipSession:
    def __init__(self, zip_bytes: bytes) -> None:
        self.zip_bytes = zip_bytes
        self.calls: list[str] = []

    def post(self, url: str, *, files: dict[str, object], data: dict[str, object], timeout: float):
        self.calls.append(url)
        if len(self.calls) == 1:
            raise __import__("requests").exceptions.ReadTimeout(f"timeout for {url}")
        return _DummyZipResponse(self.zip_bytes)


def test_paddle_vl_parser_retries_localhost_when_service_alias_times_out(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "PADDLE_VL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_API_URL", "http://mimirq-paddlevl:9030/convert", raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_TIMEOUT_SEC", 3, raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", False, raising=False)

    parser = PaddleVLParser()
    parser._session = _TimeoutThenZipSession(_read_fixture_zip("paddlevl_doc_parser_output.zip"))

    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake\n")

    docs = parser.parse(pdf_path)

    assert docs and "Parsed" in (docs[0].page_content or "")
    assert parser._session.calls == [
        "http://mimirq-paddlevl:9030/convert",
        "http://127.0.0.1:9030/convert",
    ]


def test_paddle_vl_parser_retries_service_alias_when_localhost_times_out(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "PADDLE_VL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_API_URL", "http://127.0.0.1:9030/convert", raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_TIMEOUT_SEC", 3, raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", False, raising=False)

    parser = PaddleVLParser()
    parser._session = _TimeoutThenZipSession(_read_fixture_zip("paddlevl_doc_parser_output.zip"))

    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake\n")

    docs = parser.parse(pdf_path)

    assert docs and "Parsed" in (docs[0].page_content or "")
    assert parser._session.calls == [
        "http://127.0.0.1:9030/convert",
        "http://mimirq-paddlevl:9030/convert",
    ]
