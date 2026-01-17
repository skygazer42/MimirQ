from uuid import uuid4

from PIL import Image as PILImage

from app.core.config import settings
from app.parsing.processors.processor import DocumentProcessorService


def test_extract_and_upload_image_path_uploads_and_deletes(monkeypatch, tmp_path):
    import app.parsing.processors.processor as processor_mod

    tenant_id = uuid4()
    upload_dir = tmp_path
    image_path = upload_dir / str(tenant_id) / ".mimirq_parse" / "run" / "images" / "x.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (2, 2), color=(255, 0, 0)).save(image_path, format="PNG")

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(upload_dir), raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MINIO_IMAGE_MAX_BYTES", 0, raising=False)

    called = {"count": 0}

    def _fake_upload_image(*, image_data, tenant_id, dataset_id, document_id, chunk_key, extension):  # noqa: ANN001
        called["count"] += 1
        assert isinstance(image_data, (bytes, bytearray))
        assert len(image_data) > 0
        assert tenant_id == str(tenant_id_val)
        assert chunk_key == "ck"
        assert extension == "jpg"
        return "img-1"

    tenant_id_val = tenant_id
    monkeypatch.setattr(processor_mod.minio_service, "upload_image", _fake_upload_image, raising=True)

    meta = {"doc_type_kwd": "image", "image_path": str(image_path), "chunk_key": "ck"}
    svc = DocumentProcessorService()
    out = svc._extract_and_upload_image_to_minio(
        meta,
        tenant_id=str(tenant_id),
        dataset_id="ds",
        document_id="doc",
        chunk_index=0,
    )

    assert out == "img-1"
    assert called["count"] == 1
    assert "image_path" not in meta
    assert not image_path.exists()


def test_extract_and_upload_image_path_rejects_unsafe_path(monkeypatch, tmp_path):
    import app.parsing.processors.processor as processor_mod

    tenant_id = uuid4()
    upload_dir = tmp_path
    unsafe_path = upload_dir / "outside.png"
    PILImage.new("RGB", (2, 2), color=(0, 255, 0)).save(unsafe_path, format="PNG")

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(upload_dir), raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MINIO_IMAGE_MAX_BYTES", 0, raising=False)

    called = {"count": 0}

    def _fake_upload_image(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        called["count"] += 1
        return "img-1"

    monkeypatch.setattr(processor_mod.minio_service, "upload_image", _fake_upload_image, raising=True)

    meta = {"doc_type_kwd": "image", "image_path": str(unsafe_path), "chunk_key": "ck"}
    svc = DocumentProcessorService()
    out = svc._extract_and_upload_image_to_minio(
        meta,
        tenant_id=str(tenant_id),
        dataset_id="ds",
        document_id="doc",
        chunk_index=0,
    )

    assert out is None
    assert called["count"] == 0
    assert "image_path" not in meta
    assert unsafe_path.exists()


def test_extract_and_upload_image_path_enforces_size_limit(monkeypatch, tmp_path):
    import app.parsing.processors.processor as processor_mod

    tenant_id = uuid4()
    upload_dir = tmp_path
    image_path = upload_dir / str(tenant_id) / "images" / "x.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (30, 30), color=(0, 0, 255)).save(image_path, format="PNG")

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(upload_dir), raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MINIO_IMAGE_MAX_BYTES", 10, raising=False)

    called = {"count": 0}

    def _fake_upload_image(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        called["count"] += 1
        return "img-1"

    monkeypatch.setattr(processor_mod.minio_service, "upload_image", _fake_upload_image, raising=True)

    meta = {"doc_type_kwd": "image", "image_path": str(image_path), "chunk_key": "ck"}
    svc = DocumentProcessorService()
    out = svc._extract_and_upload_image_to_minio(
        meta,
        tenant_id=str(tenant_id),
        dataset_id="ds",
        document_id="doc",
        chunk_index=0,
    )

    assert out is None
    assert called["count"] == 0
    assert "image_path" not in meta
    assert not image_path.exists()
