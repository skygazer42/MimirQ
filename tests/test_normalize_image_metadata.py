from __future__ import annotations


def test_normalize_image_metadata_derives_minio_url_from_img_id():
    from app.rag.core.metadata import normalize_image_metadata

    img_id = "00000000-0000-0000-0000-000000000000:11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222:asset0"
    meta = {"img_id": img_id}
    out = normalize_image_metadata(meta)

    assert out["img_id"] == img_id
    assert out["image_id"] == img_id
    assert out["image_url"] == f"/api/v1/documents/image-url/{img_id}"
    assert out["img_url"] == f"/api/v1/documents/image-url/{img_id}"


def test_normalize_image_metadata_derives_local_url_from_image_id():
    from app.rag.core.metadata import normalize_image_metadata

    image_id = "0123456789abcdef0123456789abcdef"
    meta = {"image_id": image_id}
    out = normalize_image_metadata(meta)

    assert out["image_id"] == image_id
    assert out["img_id"] == image_id
    assert out["image_url"] == f"/api/v1/documents/image/{image_id}"
    assert out["img_url"] == f"/api/v1/documents/image/{image_id}"


def test_normalize_image_metadata_does_not_override_existing_url():
    from app.rag.core.metadata import normalize_image_metadata

    meta = {"img_id": "not-a-minio-id", "image_url": "https://example.test/x.png"}
    out = normalize_image_metadata(meta)

    assert out["image_url"] == "https://example.test/x.png"
    assert out["img_url"] == "https://example.test/x.png"


def test_normalize_image_metadata_mirrors_img_url_to_image_url():
    from app.rag.core.metadata import normalize_image_metadata

    meta = {"img_url": "/api/v1/documents/image-url/x:y:z:0"}
    out = normalize_image_metadata(meta)

    assert out["img_url"] == "/api/v1/documents/image-url/x:y:z:0"
    assert out["image_url"] == "/api/v1/documents/image-url/x:y:z:0"

