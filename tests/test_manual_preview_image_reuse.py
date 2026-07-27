import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from PIL import Image


def _write_preview_image(root: Path, *, tenant_id: str, image_id: str, binding: dict[str, str]) -> Path:
    images_dir = root / tenant_id / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    image_path = images_dir / f"{image_id}.png"
    Image.new("RGB", (1, 1), color=(255, 255, 255)).save(image_path, format="PNG")
    (images_dir / f"{image_id}.json").write_text(json.dumps(binding), encoding="utf-8")
    return images_dir


def test_manual_preview_reuse_blocks_other_accounts(monkeypatch, tmp_path) -> None:
    import app.api.v1.documents as documents_module

    tenant_id = str(uuid4())
    dataset_id = str(uuid4())
    document_id = str(uuid4())
    image_id = uuid4().hex
    images_dir = _write_preview_image(
        tmp_path,
        tenant_id=tenant_id,
        image_id=image_id,
        binding={"tenant_id": tenant_id, "account_id": "other-account"},
    )

    monkeypatch.setattr(documents_module.settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(
        documents_module.minio_service,
        "upload_image",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("upload_image should not be called")),
        raising=True,
    )

    with pytest.raises(HTTPException) as excinfo:
        documents_module._rewrite_preview_images_to_minio(
            f"![img](/api/v1/documents/image/{image_id})",
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            account_id="current-account",
            images_dir=images_dir,
            local_id_to_img_id={},
            digest_to_img_id={},
            start_index=0,
        )

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == "Preview image cannot be reused for this document"


def test_manual_preview_reuse_allows_same_target_binding_upload(monkeypatch, tmp_path) -> None:
    import app.api.v1.documents as documents_module

    tenant_id = str(uuid4())
    dataset_id = str(uuid4())
    document_id = str(uuid4())
    image_id = uuid4().hex
    images_dir = _write_preview_image(
        tmp_path,
        tenant_id=tenant_id,
        image_id=image_id,
        binding={
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "document_id": document_id,
        },
    )

    monkeypatch.setattr(documents_module.settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(
        documents_module.minio_service,
        "upload_image",
        lambda **_kwargs: f"{tenant_id}:{dataset_id}:{document_id}:asset0",
        raising=True,
    )

    text, img_ids, next_index = documents_module._rewrite_preview_images_to_minio(
        f"![img](/api/v1/documents/image/{image_id})",
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
        account_id="different-editor",
        images_dir=images_dir,
        local_id_to_img_id={},
        digest_to_img_id={},
        start_index=0,
    )

    assert img_ids == [f"{tenant_id}:{dataset_id}:{document_id}:asset0"]
    assert "/api/v1/documents/image-url/" in text
    assert next_index == 1


def test_manual_preview_reuse_promotes_current_owner_binding_when_minio_disabled(monkeypatch, tmp_path) -> None:
    import app.api.v1.documents as documents_module

    tenant_id = str(uuid4())
    dataset_id = str(uuid4())
    document_id = str(uuid4())
    image_id = uuid4().hex
    images_dir = _write_preview_image(
        tmp_path,
        tenant_id=tenant_id,
        image_id=image_id,
        binding={"tenant_id": tenant_id, "account_id": "preview-owner"},
    )

    monkeypatch.setattr(documents_module.settings, "MINIO_ENABLED", False, raising=False)

    text, img_ids, next_index = documents_module._rewrite_preview_images_to_minio(
        f"![img](/api/v1/documents/image/{image_id})",
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
        account_id="preview-owner",
        images_dir=images_dir,
        local_id_to_img_id={},
        digest_to_img_id={},
        start_index=4,
    )

    assert text == f"![img](/api/v1/documents/image/{image_id})"
    assert img_ids == []
    assert next_index == 4
    assert json.loads((images_dir / f"{image_id}.json").read_text(encoding="utf-8")) == {
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "document_id": document_id,
    }


def test_manual_preview_reuse_validates_local_refs_alongside_minio_refs(monkeypatch, tmp_path) -> None:
    import app.api.v1.documents as documents_module

    tenant_id = str(uuid4())
    dataset_id = str(uuid4())
    document_id = str(uuid4())
    image_id = uuid4().hex
    images_dir = _write_preview_image(
        tmp_path,
        tenant_id=tenant_id,
        image_id=image_id,
        binding={"tenant_id": tenant_id, "account_id": "other-account"},
    )
    existing_id = f"{tenant_id}:{dataset_id}:{document_id}:asset0"
    content = (
        f"![stored](/api/v1/documents/image-url/{existing_id})\n"
        f"![preview](/api/v1/documents/image/{image_id})"
    )

    monkeypatch.setattr(documents_module.settings, "MINIO_ENABLED", True, raising=False)

    with pytest.raises(HTTPException) as excinfo:
        documents_module._rewrite_preview_images_to_minio(
            content,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            account_id="current-account",
            images_dir=images_dir,
            local_id_to_img_id={},
            digest_to_img_id={},
            start_index=0,
        )

    assert excinfo.value.status_code == 403


def test_manual_preview_reuse_fails_closed_when_binding_promotion_cannot_persist(monkeypatch, tmp_path) -> None:
    import app.api.v1.documents as documents_module

    tenant_id = str(uuid4())
    dataset_id = str(uuid4())
    document_id = str(uuid4())
    image_id = uuid4().hex
    images_dir = _write_preview_image(
        tmp_path,
        tenant_id=tenant_id,
        image_id=image_id,
        binding={"tenant_id": tenant_id, "account_id": "preview-owner"},
    )

    monkeypatch.setattr(documents_module.settings, "MINIO_ENABLED", False, raising=False)
    monkeypatch.setattr(documents_module, "_promote_preview_owner_binding", lambda **_kwargs: False)

    with pytest.raises(HTTPException) as excinfo:
        documents_module._rewrite_preview_images_to_minio(
            f"![img](/api/v1/documents/image/{image_id})",
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            account_id="preview-owner",
            images_dir=images_dir,
            local_id_to_img_id={},
            digest_to_img_id={},
        )

    assert excinfo.value.status_code == 403


def test_preview_owner_binding_rejects_mixed_account_and_document_scope(tmp_path) -> None:
    from app.services.document_preview_utils import _load_preview_owner_binding

    tenant_id = str(uuid4())
    dataset_id = str(uuid4())
    document_id = str(uuid4())
    image_id = uuid4().hex
    images_dir = _write_preview_image(
        tmp_path,
        tenant_id=tenant_id,
        image_id=image_id,
        binding={
            "tenant_id": tenant_id,
            "dataset_id": dataset_id,
            "document_id": document_id,
            "account_id": "preview-owner",
        },
    )

    assert _load_preview_owner_binding(images_dir=images_dir, preview_id=image_id) is None


def test_manual_preview_reuse_claims_legacy_reference_for_same_document(monkeypatch, tmp_path) -> None:
    import app.api.v1.documents as documents_module

    tenant_id = str(uuid4())
    dataset_id = str(uuid4())
    document_id = str(uuid4())
    image_id = uuid4().hex
    images_dir = tmp_path / tenant_id / "images"
    images_dir.mkdir(parents=True)
    Image.new("RGB", (1, 1), color=(255, 255, 255)).save(images_dir / f"{image_id}.png", format="PNG")

    monkeypatch.setattr(documents_module.settings, "MINIO_ENABLED", False, raising=False)
    monkeypatch.setattr(
        documents_module,
        "legacy_preview_ref_belongs_to_document",
        lambda *_args, **_kwargs: True,
        raising=True,
    )

    text, img_ids, next_index = documents_module._rewrite_preview_images_to_minio(
        f"![img](/api/v1/documents/image/{image_id})",
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_id=document_id,
        account_id="editor",
        images_dir=images_dir,
        local_id_to_img_id={},
        digest_to_img_id={},
        db=object(),
    )

    assert text.endswith(f"/{image_id})")
    assert img_ids == []
    assert next_index == 0
    assert json.loads((images_dir / f"{image_id}.json").read_text(encoding="utf-8")) == {
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "document_id": document_id,
    }


def test_legacy_preview_lookup_requires_an_exact_image_reference() -> None:
    from app.models.document import DocumentChunk
    from app.services.document_preview_legacy import find_legacy_preview_document_ids

    tenant_id = uuid4()
    image_id = uuid4()
    chunk_document_id = uuid4()
    false_positive_document_id = uuid4()
    parsed_document_id = uuid4()

    class _Query:
        def __init__(self, rows) -> None:  # noqa: ANN001
            self.rows = rows

        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
            return self

        def limit(self, _limit: int):  # noqa: ANN201
            return self

        def all(self):  # noqa: ANN201
            return list(self.rows)

    class _DB:
        def query(self, *columns):  # noqa: ANN002, ANN201
            if columns[0].class_ is DocumentChunk:
                return _Query(
                    [
                        (chunk_document_id, f"![ok](/api/v1/documents/image/{image_id.hex})"),
                        (false_positive_document_id, f"/api/v1/documents/image/{image_id.hex}suffix"),
                    ]
                )
            return _Query(
                [
                    (
                        parsed_document_id,
                        "",
                        f'<img src="/api/v1/documents/image/{image_id}">',
                    )
                ]
            )

    assert find_legacy_preview_document_ids(
        _DB(),
        tenant_id=tenant_id,
        preview_id=image_id.hex,
    ) == {chunk_document_id, parsed_document_id}
