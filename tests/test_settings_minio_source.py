from __future__ import annotations

from pathlib import Path


def test_settings_endpoint_exposes_minio_config() -> None:
    source = Path("app/api/v1/settings.py").read_text(encoding="utf-8")

    assert "class MinioConfig(BaseModel)" in source
    assert "minio: MinioConfig" in source
    assert "MINIO_ENABLED" in source
    assert "MINIO_ENDPOINT" in source
    assert "MINIO_BUCKET_NAME" in source
    assert "MINIO_DOCUMENTS_ENABLED" in source
    assert "MINIO_IMAGE_MAX_BYTES" in source
