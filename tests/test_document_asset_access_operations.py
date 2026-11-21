import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request


def _request(*, query: str = "", headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/documents/asset",
            "query_string": query.encode(),
            "headers": raw_headers,
        }
    )


def test_document_asset_authorization_uses_shared_acl_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.documents import asset_access as document_asset_access

    tenant_id = uuid4()
    document = type(
        "DocumentFixture",
        (),
        {"id": uuid4(), "tenant_id": tenant_id, "dataset_id": uuid4(), "owner_id": "account-1"},
    )()
    dataset = type("DatasetFixture", (), {"id": document.dataset_id, "tenant_id": tenant_id})()
    acl_calls: list[dict[str, object]] = []

    class Query:
        def filter(self, *_args):
            return self

        def first(self):
            return document

    class DB:
        def query(self, _model):
            return Query()

    monkeypatch.setattr(document_asset_access.dataset_service, "get_dataset", lambda *_args: dataset)
    monkeypatch.setattr(document_asset_access.dataset_service, "assert_dataset_readable", lambda *_args: None)
    monkeypatch.setattr(
        document_asset_access,
        "assert_document_acl_readable",
        lambda *_args, **kwargs: acl_calls.append(kwargs),
    )

    result = document_asset_access.authorize_document_asset(
        db=DB(),
        tenant_id=tenant_id,
        account_id="account-1",
        document_id=document.id,
    )

    assert result is document
    assert acl_calls[0]["document"] is document
    assert acl_calls[0]["dataset"] is dataset


def test_preview_image_resolution_requires_matching_ephemeral_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services.documents import asset_access as document_asset_access

    tenant_id = uuid4()
    image_id = uuid4().hex
    images_dir = tmp_path / str(tenant_id) / "images"
    images_dir.mkdir(parents=True)
    image_path = images_dir / f"{image_id}.png"
    image_path.write_bytes(b"preview")
    (images_dir / f"{image_id}.json").write_text(
        json.dumps({"tenant_id": str(tenant_id), "account_id": "preview-owner"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(document_asset_access.settings, "UPLOAD_DIR", str(tmp_path))

    with pytest.raises(HTTPException) as caught:
        document_asset_access.resolve_preview_image(
            db=object(),
            tenant_id=tenant_id,
            account_id="other-account",
            image_id=image_id,
        )
    assert caught.value.status_code == 404

    assert (
        document_asset_access.resolve_preview_image(
            db=object(),
            tenant_id=tenant_id,
            account_id="preview-owner",
            image_id=image_id,
        )
        == image_path
    )
