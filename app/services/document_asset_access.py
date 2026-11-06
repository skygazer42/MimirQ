"""Tenant-scoped authorization and lookup for document assets."""

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.rag.core.logging import get_logger
from app.rag.core.metadata import _looks_like_local_image_id
from app.services import dataset_service
from app.services.document_access_service import assert_document_acl_readable, get_document_for_lifecycle
from app.services.document_lifecycle_service import DOC_NOT_FOUND_DETAIL
from app.services.document_preview_legacy import find_legacy_preview_document_ids
from app.services.document_preview_utils import (
    PREVIEW_IMAGE_EXTENSIONS,
    _load_preview_owner_binding,
    _write_preview_owner_binding,
)

logger = get_logger(__name__)
if TYPE_CHECKING:
    from langchain_core.documents import Document
IMAGE_NOT_FOUND_DETAIL = "Image not found"


def authorize_document_asset(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str | None,
    document_id: UUID,
) -> DBDocument:
    document = get_document_for_lifecycle(db, tenant_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)
    dataset: Dataset | None = None
    if account_id is not None and document.dataset_id is not None:
        dataset = dataset_service.get_dataset(db, tenant_id, document.dataset_id)
    assert_document_asset_readable(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
        dataset=dataset,
    )
    return document


def assert_document_asset_readable(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str | None,
    document: DBDocument,
    dataset: Dataset | None = None,
) -> None:
    if account_id is None:
        return
    if document.dataset_id is None:
        dataset_service.ensure_member(db, tenant_id, account_id)
    else:
        dataset = dataset or dataset_service.get_dataset(db, tenant_id, document.dataset_id)
        dataset_service.assert_dataset_readable(db, dataset, account_id)
    assert_document_acl_readable(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
        dataset=dataset,
    )


def authorize_preview_document(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str | None,
    dataset_id: UUID,
    document_id: UUID,
) -> DBDocument | None:
    document = get_document_for_lifecycle(db, tenant_id, document_id)
    if document is None or document.dataset_id != dataset_id:
        return None
    dataset = dataset_service.get_dataset(db, tenant_id, dataset_id) if account_id is not None else None
    assert_document_asset_readable(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
        dataset=dataset,
    )
    return document


def _locate_preview_image(images_dir: Path, preview_id: str) -> Path | None:
    images_dir_resolved = images_dir.resolve(strict=False)
    for extension in PREVIEW_IMAGE_EXTENSIONS:
        path = (images_dir / f"{preview_id}{extension}").resolve(strict=False)
        try:
            path.relative_to(images_dir_resolved)
        except ValueError:
            continue
        if path.is_file():
            return path
    return None


def _legacy_preview_binding(
    *,
    db: Session,
    images_dir: Path,
    tenant_id: UUID,
    account_id: str | None,
    preview_id: str,
) -> dict[str, str] | None:
    if account_id is None:
        return None
    try:
        document_ids = find_legacy_preview_document_ids(db, tenant_id=tenant_id, preview_id=preview_id)
    except Exception:
        logger.warning("Legacy preview image ownership lookup failed: preview_id=%s", preview_id, exc_info=True)
        return None
    if not document_ids:
        return None

    documents = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(document_ids)).all()
    documents_by_id = {document.id: document for document in documents if document.dataset_id is not None}
    dataset_ids = {document.dataset_id for document in documents_by_id.values()}
    datasets = db.query(Dataset).filter(Dataset.tenant_id == tenant_id, Dataset.id.in_(dataset_ids)).all()
    datasets_by_id = {dataset.id: dataset for dataset in datasets}
    readable_datasets: dict[UUID, Dataset | None] = {}

    for document_id in sorted(document_ids, key=str):
        document = documents_by_id.get(document_id)
        if document is None:
            continue
        dataset_id = document.dataset_id
        dataset = readable_datasets.get(dataset_id)
        if dataset_id not in readable_datasets:
            dataset = datasets_by_id.get(dataset_id)
            if dataset is None:
                readable_datasets[dataset_id] = None
                continue
            try:
                dataset_service.assert_dataset_readable(db, dataset, account_id)
            except HTTPException:
                dataset = None
            readable_datasets[dataset_id] = dataset
        if dataset is None:
            continue
        try:
            assert_document_acl_readable(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                document=document,
                dataset=dataset,
            )
        except HTTPException:
            continue

        binding = {
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "document_id": str(document_id),
        }
        if len(document_ids) == 1:
            _write_preview_owner_binding(images_dir=images_dir, preview_id=preview_id, binding=binding)
        return binding
    return None


def resolve_preview_binding(
    *,
    db: Session,
    images_dir: Path,
    tenant_id: UUID,
    account_id: str | None,
    preview_id: str,
) -> tuple[Mapping[str, str | None], bool]:
    binding: Mapping[str, str | None] | None = _load_preview_owner_binding(images_dir=images_dir, preview_id=preview_id)
    legacy_authorized = False
    if binding is None:
        binding = _legacy_preview_binding(
            db=db,
            images_dir=images_dir,
            tenant_id=tenant_id,
            account_id=account_id,
            preview_id=preview_id,
        )
        legacy_authorized = binding is not None
    if binding is None or binding.get("tenant_id") != str(tenant_id):
        raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL)
    return binding, legacy_authorized


def resolve_preview_image(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str | None,
    image_id: str,
) -> Path:
    try:
        preview_id = UUID(image_id).hex
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL) from exc

    images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    image_path = _locate_preview_image(images_dir, preview_id)
    if image_path is None:
        raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL)

    binding, legacy_authorized = resolve_preview_binding(
        db=db,
        images_dir=images_dir,
        tenant_id=tenant_id,
        account_id=account_id,
        preview_id=preview_id,
    )
    assert_preview_binding_access(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        binding=binding,
        legacy_authorized=legacy_authorized,
    )
    return image_path


def assert_preview_binding_access(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str | None,
    binding: Mapping[str, str | None],
    legacy_authorized: bool,
) -> None:
    bound_account_id = binding.get("account_id")
    if bound_account_id:
        if account_id is None or bound_account_id != account_id:
            raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL)
        return

    try:
        document_id = UUID(binding["document_id"])
        dataset_id = UUID(binding["dataset_id"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL) from exc
    if not legacy_authorized:
        document = authorize_preview_document(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            document_id=document_id,
        )
        if document is None:
            raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL)


def authorize_image_url(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str | None,
    image_id: str,
) -> None:
    if ":" in image_id:
        try:
            tenant_part, dataset_part, document_part, _chunk_key = image_id.split(":", 3)
            image_tenant_id = UUID(tenant_part)
            dataset_id = UUID(dataset_part)
            document_id = UUID(document_part)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL) from exc
        if image_tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL)
        document = authorize_document_asset(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            document_id=document_id,
        )
        if document.dataset_id is not None and document.dataset_id != dataset_id:
            raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL)
        return

    try:
        dataset_id = UUID(image_id.split("-", 1)[0])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL) from exc
    if account_id is not None:
        dataset = dataset_service.get_dataset(db, tenant_id, dataset_id)
        dataset_service.assert_dataset_readable(db, dataset, account_id)


def filter_authorized_image_evidence(
    *, db: Session, tenant_id: UUID, account_id: str, candidates: Iterable["Document"], max_images: int
) -> list["Document"]:
    """Trim editable image references using the same ownership checks as asset requests."""
    allowed: list["Document"] = []
    seen: set[str] = set()
    for doc in candidates:
        if len(allowed) >= max_images:
            break
        reference = str(doc.metadata.get("img_id") or doc.metadata.get("image_id") or "").strip()
        if not reference or reference in seen:
            continue
        seen.add(reference)
        try:
            if _looks_like_local_image_id(reference):
                resolve_preview_image(db=db, tenant_id=tenant_id, account_id=account_id, image_id=reference)
            else:
                authorize_image_url(db=db, tenant_id=tenant_id, account_id=account_id, image_id=reference)
        except HTTPException as exc:
            if exc.status_code in {403, 404}:
                continue
            raise
        allowed.append(doc)
    return allowed


__all__ = [
    "filter_authorized_image_evidence",
    "assert_document_asset_readable",
    "assert_preview_binding_access",
    "authorize_document_asset",
    "authorize_image_url",
    "authorize_preview_document",
    "resolve_preview_binding",
    "resolve_preview_image",
]
