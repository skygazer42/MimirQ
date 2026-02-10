from __future__ import annotations

from pathlib import Path

from PIL import Image as PILImage

from app.core.config import settings
from app.parsing.processors.processor import DocumentProcessorService
from app.storage.object import minio as minio_mod


def _write_test_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = PILImage.new("RGB", (4, 4), color=(255, 0, 0))
    img.save(path, format="PNG")
    img.close()


def test_inline_image_upload_unquotes_percent_escaped_paths(monkeypatch, tmp_path: Path):
    svc = DocumentProcessorService()

    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)

    def fake_upload_image(*, image_data, tenant_id, dataset_id, document_id, chunk_key, extension="jpg"):
        # Use the real img_id format so downstream code stays stable.
        return f"{tenant_id}:{dataset_id}:{document_id}:{chunk_key}"

    monkeypatch.setattr(minio_mod.minio_service, "upload_image", fake_upload_image)

    img_path = tmp_path / "images" / "my image.png"
    _write_test_png(img_path)

    md = "![alt](images/my%20image.png)"
    out, new_ids, idx = svc._upload_inline_images_to_minio(
        markdown_text=md,
        tenant_id="t",
        dataset_id="d",
        document_id="doc",
        cache={},
        start_index=0,
        origin_path=tmp_path / "doc.md",
    )

    assert "images/my%20image.png" not in out
    assert "/api/v1/documents/image-url/" in out
    assert new_ids == ["t:d:doc:asset0"]
    assert idx == 1


def test_inline_image_upload_supports_file_urls(monkeypatch, tmp_path: Path):
    svc = DocumentProcessorService()

    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)

    def fake_upload_image(*, image_data, tenant_id, dataset_id, document_id, chunk_key, extension="jpg"):
        return f"{tenant_id}:{dataset_id}:{document_id}:{chunk_key}"

    monkeypatch.setattr(minio_mod.minio_service, "upload_image", fake_upload_image)

    img_path = tmp_path / "images" / "my image.png"
    _write_test_png(img_path)

    # file:// URL should include percent-escaped spaces.
    file_uri = img_path.as_uri()
    assert file_uri.startswith("file://")
    assert "%20" in file_uri

    md = f"![alt]({file_uri})"
    out, new_ids, idx = svc._upload_inline_images_to_minio(
        markdown_text=md,
        tenant_id="t",
        dataset_id="d",
        document_id="doc",
        cache={},
        start_index=0,
        origin_path=tmp_path / "doc.md",
    )

    assert file_uri not in out
    assert "/api/v1/documents/image-url/" in out
    assert new_ids == ["t:d:doc:asset0"]
    assert idx == 1

