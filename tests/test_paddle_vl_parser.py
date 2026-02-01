from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.core.config import settings
from app.parsing.parsers.paddle_vl_parser import PaddleVLParser
from app.parsing.utils.zip_processor import ZipImageProcessor


class _DummyZipResponse:
    def __init__(self, zip_bytes: bytes) -> None:
        self.status_code = 200
        self.headers = {"content-type": "application/zip"}
        self.content = zip_bytes
        self.text = ""


def _make_zip_bytes(files: dict[str, bytes | str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in files.items():
            data = payload.encode("utf-8") if isinstance(payload, str) else payload
            zf.writestr(name, data)
    return buffer.getvalue()


def test_paddle_vl_parser_zip_minio_disabled_strips_image_refs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "PADDLE_VL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_API_URL", "http://paddlevl.local/convert", raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_TIMEOUT_SEC", 3, raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", False, raising=False)

    zip_bytes = _make_zip_bytes(
        {
            "nested/doc.md": "hello\n\n![a](../imgs/p1.png)\n<img src=\"../imgs/p2.jpg\">\n",
            "imgs/p1.png": b"png",
            "imgs/p2.jpg": b"jpg",
        }
    )

    parser = PaddleVLParser()
    monkeypatch.setattr(parser, "_post_multipart", lambda **_kwargs: _DummyZipResponse(zip_bytes), raising=True)

    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake\n")

    docs = parser.parse(pdf_path, dataset_id="ds1", document_id="doc1")
    assert len(docs) == 1
    content = docs[0].page_content or ""
    assert "hello" in content
    assert "![" not in content
    assert "<img" not in content.lower()


def test_paddle_vl_parser_zip_minio_enabled_uses_zip_processor(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "PADDLE_VL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_API_URL", "http://paddlevl.local/convert", raising=False)
    monkeypatch.setattr(settings, "PADDLE_VL_TIMEOUT_SEC", 3, raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)

    zip_bytes = _make_zip_bytes({"doc.md": "hello\n\n![a](imgs/p1.png)\n", "imgs/p1.png": b"png"})

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
    assert docs[0].page_content == "hello ![](https://minio.local/images/p1.png)"

    assert called.get("dataset_id") == "ds1"
    assert called.get("document_id") == "doc1"
    assert called.get("tenant_id") == "t1"

