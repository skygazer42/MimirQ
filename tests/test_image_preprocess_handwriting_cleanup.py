from __future__ import annotations

from pathlib import Path

import requests

from app.core.config import settings
from app.parsing.preprocess.image_preprocess import preprocess_image_document


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, content: bytes = b"processed") -> None:
        self.status_code = status_code
        self.content = content


def test_image_preprocess_records_handwriting_cleanup_warning_when_model_missing(
    tmp_path: Path, monkeypatch
) -> None:
    img = tmp_path / "handwritten-note.png"
    img.write_bytes(b"fake")

    monkeypatch.setattr(settings, "IMAGE_PREPROCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ORIENTATION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DESKEW_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "HANDWRITING_CLEANUP_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "HANDWRITING_CLEANUP_BACKEND", "local", raising=False)
    monkeypatch.setattr(settings, "HANDWRITING_CLEANUP_MODEL_PATH", "", raising=False)

    out = preprocess_image_document(input_path=img, document_id="doc-handwriting", pdf_quality=None)

    assert out.changed is False
    assert out.output_path == str(img)
    assert "handwriting_cleanup_model_missing" in (out.warnings or [])
    assert any(
        step.id == "handwriting_cleanup" and step.applied is True and step.changed is False and step.note == "missing_model_path"
        for step in (out.steps or [])
    )


def test_image_preprocess_applies_handwriting_cleanup_via_http_backend(tmp_path: Path, monkeypatch) -> None:
    img = tmp_path / "handwritten-note.png"
    img.write_bytes(b"before")

    def _fake_post(*_args, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return _FakeResponse(content=b"after")

    monkeypatch.setattr(requests, "post", _fake_post)
    monkeypatch.setattr(settings, "IMAGE_PREPROCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ORIENTATION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DESKEW_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "HANDWRITING_CLEANUP_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "HANDWRITING_CLEANUP_BACKEND", "http", raising=False)
    monkeypatch.setattr(settings, "HANDWRITING_CLEANUP_API_URL", "http://example/handwriting-cleanup", raising=False)
    monkeypatch.setattr(settings, "HANDWRITING_CLEANUP_TIMEOUT_SEC", 30, raising=False)

    out = preprocess_image_document(input_path=img, document_id="doc-handwriting", pdf_quality=None)

    assert out.changed is True
    assert Path(out.output_path).read_bytes() == b"after"
    assert any(
        step.id == "handwriting_cleanup" and step.applied is True and step.changed is True and step.note == "cleanup_ok"
        for step in (out.steps or [])
    )


def test_image_preprocess_applies_handwriting_cleanup_via_heuristic_backend(tmp_path: Path, monkeypatch) -> None:
    from PIL import Image

    img = tmp_path / "handwritten-note.png"
    Image.new("RGB", (8, 8), color=(180, 180, 180)).save(img)

    monkeypatch.setattr(settings, "IMAGE_PREPROCESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ORIENTATION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DESKEW_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "WATERMARK_REMOVAL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "HANDWRITING_CLEANUP_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "HANDWRITING_CLEANUP_BACKEND", "heuristic", raising=False)

    out = preprocess_image_document(input_path=img, document_id="doc-handwriting", pdf_quality=None)

    assert out.changed is True
    assert out.output_path != str(img)
    assert Path(out.output_path).exists()
    assert any(
        step.id == "handwriting_cleanup" and step.applied is True and step.changed is True and step.note == "cleanup_ok"
        for step in (out.steps or [])
    )
