from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.parsing.parsers.magic_pdf_parser import MagicPDFParser


class _JsonResponse:
    status_code = 200
    headers = {"content-type": "application/json"}
    text = ""
    content = b"{}"

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _DummySession:
    def __init__(self, response: _JsonResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, *, files: dict[str, object], data: dict[str, object], timeout: float):  # noqa: ANN001
        self.calls.append({"url": url, "files": files, "data": data, "timeout": timeout})
        return self.response


def test_magicpdf_parser_uses_service_mode_when_api_url_is_configured(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "MAGIC_PDF_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_API_URL", "http://mimirq-magicpdf:2095/convert", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_REQUEST_TIMEOUT_SEC", 12, raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_METHOD", "ocr", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_LANG", "ch", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_DEBUG", True, raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_DEVICE_MODE", "cuda", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_KEEP_ARTIFACTS", True, raising=False)

    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%magicpdf-service\n")

    parser = MagicPDFParser()
    parser._session = _DummySession(
        _JsonResponse(
            {
                "markdown": "# service markdown",
                "artifact_dir": "/srv/magicpdf/artifacts/job-1",
                "asset_base_dir": "/srv/magicpdf/artifacts/job-1/images",
                "method": "ocr",
                "elapsed_sec": 1.23,
            }
        )
    )

    docs = parser.parse(pdf_path, dataset_id="dataset-1", document_id="doc-1")

    assert docs and docs[0].page_content == "# service markdown"
    metadata = docs[0].metadata
    assert metadata["parser_backend"] == "magicpdf"
    assert metadata["artifact_dir"] == "/srv/magicpdf/artifacts/job-1"
    assert metadata["asset_base_dir"] == "/srv/magicpdf/artifacts/job-1/images"
    assert metadata["magicpdf_method"] == "ocr"
    assert metadata["dataset_id"] == "dataset-1"
    assert metadata["magicpdf_elapsed_sec"] == 1.23

    assert parser._session.calls == [
        {
            "url": "http://mimirq-magicpdf:2095/convert",
            "files": {
                "file": ("input.pdf", b"%PDF-1.4\n%magicpdf-service\n", "application/pdf"),
            },
            "data": {
                "method": "ocr",
                "lang": "ch",
                "debug": "true",
                "device_mode": "cuda",
                "keep_artifacts": "true",
                "document_id": "doc-1",
            },
            "timeout": 12.0,
        }
    ]


def test_magicpdf_service_mode_defaults_to_cuda_when_device_mode_is_unset(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "MAGIC_PDF_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_API_URL", "http://mimirq-magicpdf:2095/convert", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_REQUEST_TIMEOUT_SEC", 12, raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_METHOD", "auto", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_LANG", "", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_DEBUG", False, raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_DEVICE_MODE", "", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_KEEP_ARTIFACTS", False, raising=False)

    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%magicpdf-service\n")

    parser = MagicPDFParser()
    parser._session = _DummySession(_JsonResponse({"markdown": "# service markdown"}))

    parser.parse(pdf_path)

    assert parser._session.calls[0]["data"]["device_mode"] == "cuda"
