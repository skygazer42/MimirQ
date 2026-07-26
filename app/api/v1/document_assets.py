
import importlib
import mimetypes
import uuid
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.utils.response_headers import set_content_disposition
from app.core.config import settings
from app.core.database import get_db
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.rag.core.logging import get_logger
from app.services.dataset_service import DatasetService
from app.storage.object.runtime import is_object_storage_uri, resolve_document_object_reference

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)

_ACTIVE_CONTENT_MEDIA_TYPES = {
    "application/ecmascript",
    "application/javascript",
    "application/x-javascript",
    "application/xhtml+xml",
    "application/xml",
    "image/svg+xml",
    "text/css",
    "text/html",
    "text/javascript",
    "text/xml",
}
_ACTIVE_CONTENT_SUFFIXES = {
    ".css",
    ".htm",
    ".html",
    ".js",
    ".mjs",
    ".svg",
    ".svgz",
    ".xhtml",
    ".xml",
}


def _documents_module() -> Any:
    return importlib.import_module("app.api.v1.documents")


def _asset_disposition_type(*, inline: bool, filename: str | None, media_type: str | None) -> str:
    if not inline:
        return "attachment"

    normalized_media_type = str(media_type or "").split(";", 1)[0].strip().lower()
    normalized_suffix = Path(str(filename or "")).suffix.strip().lower()
    if normalized_media_type in _ACTIVE_CONTENT_MEDIA_TYPES or normalized_suffix in _ACTIVE_CONTENT_SUFFIXES:
        return "attachment"
    return "inline"


@router.get("/{document_id}/download", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def download_document(
    document_id: uuid.UUID,
    request: Request,
    inline: bool = True,
    *,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Download (or inline-preview) a document file.

    JWT-authenticated requests must supply an Authorization header.
    Tenant selection may still be provided via header or query parameter.
    """
    docs_mod = _documents_module()
    tenant_id = await docs_mod._resolve_tenant_id_for_asset_request(request)
    account_id = await docs_mod._resolve_account_id_for_asset_request(request, tenant_id=tenant_id)

    # Best-effort permission check: allow anonymous in local/dev header mode.
    if account_id:
        DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=docs_mod.DOC_NOT_FOUND_DETAIL)

    dataset: Dataset | None = None
    if document.dataset_id and account_id:
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
    if account_id:
        docs_mod._assert_document_acl_readable(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            document=document,
            dataset=dataset,
        )

    raw_path = str(document.file_path or "").strip()
    if not raw_path or raw_path.startswith(docs_mod.MANUAL_FILE_PATH_PREFIX):
        raise HTTPException(status_code=404, detail="Document file not available")

    if is_object_storage_uri(raw_path):
        try:
            store, ref = resolve_document_object_reference(
                raw_path,
                tenant_id=tenant_id,
                dataset_id=document.dataset_id,
                document_id=document.id,
                file_type=document.file_type,
                document_metadata=dict(getattr(document, "doc_metadata", None) or {}),
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Object storage is disabled") from exc
        except ValueError as exc:
            if str(exc) in {"object_bucket_denied", "object_key_denied"}:
                raise HTTPException(status_code=403, detail=docs_mod.DOCUMENT_FILE_ACCESS_DENIED_DETAIL) from exc
            raise HTTPException(status_code=404, detail="Document file not available") from exc

        try:
            stat = store.stat_object(object_name=ref.object_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Document asset stat failed for %r: %r", ref.object_name[:200], str(exc)[:200])
            raise HTTPException(status_code=404, detail=docs_mod.DOCUMENT_FILE_NOT_FOUND_DETAIL) from exc

        total_size = int(getattr(stat, "size", 0) or 0)
        if total_size <= 0:
            raise HTTPException(status_code=404, detail=docs_mod.DOCUMENT_FILE_NOT_FOUND_DETAIL)

        max_age = max(0, int(getattr(settings, "ASSET_CACHE_MAX_AGE_SEC", 0) or 0))
        cache_control = docs_mod._asset_cache_control(max_age=max_age)

        etag_raw = str(getattr(stat, "etag", "") or "").strip()
        etag = f"\"{etag_raw}\"" if etag_raw and not etag_raw.startswith("\"") else (etag_raw or None)

        range_header = (request.headers.get("range") or "").strip()
        offset = 0
        length: int | None = None
        status_code = 200
        headers: dict[str, str] = {
            "Cache-Control": cache_control,
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Accept-Ranges": "bytes",
            **({"ETag": etag} if etag else {}),
        }

        if etag and not range_header:
            if_none_match = (request.headers.get("if-none-match") or "").strip()
            if if_none_match:
                candidates_etag = [part.strip() for part in if_none_match.split(",") if part.strip()]
                if "*" in candidates_etag or etag in candidates_etag:
                    headers_304 = {
                        "ETag": etag,
                        "Cache-Control": cache_control,
                        "Referrer-Policy": "no-referrer",
                        "X-Content-Type-Options": "nosniff",
                    }
                    return Response(status_code=304, headers=headers_304)

        if range_header.lower().startswith("bytes="):
            spec = range_header[6:].strip()
            if "," in spec:
                raise HTTPException(status_code=416, detail="Multiple ranges not supported")
            start_s, end_s = (spec.split("-", 1) + [""])[:2]
            try:
                if start_s == "":
                    suffix = int(end_s)
                    if suffix <= 0:
                        raise ValueError
                    offset = max(0, total_size - suffix)
                    end = total_size - 1
                else:
                    offset = int(start_s)
                    end = int(end_s) if end_s else (total_size - 1)
                    if offset < 0:
                        raise ValueError
                    if end < offset:
                        raise ValueError
                    if offset >= total_size:
                        raise HTTPException(status_code=416, detail="Range not satisfiable")
                    end = min(end, total_size - 1)
                length = int(end - offset + 1)
                status_code = 206
                headers["Content-Range"] = f"bytes {offset}-{offset + length - 1}/{total_size}"
                headers["Content-Length"] = str(length)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=416, detail=docs_mod.INVALID_RANGE_HEADER_DETAIL) from exc
        else:
            headers["Content-Length"] = str(total_size)

        media_type, _encoding = mimetypes.guess_type(document.filename)
        if not media_type:
            media_type = "application/octet-stream"

        disposition = _asset_disposition_type(
            inline=inline,
            filename=document.filename,
            media_type=media_type,
        )
        set_content_disposition(headers, document.filename or "document", disposition=disposition)

        return StreamingResponse(
            store.iter_object_bytes(object_name=ref.object_name, offset=offset, length=length),
            status_code=status_code,
            media_type=media_type,
            headers=headers,
        )

    path = Path(raw_path).resolve(strict=False)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=docs_mod.DOCUMENT_FILE_NOT_FOUND_DETAIL)

    upload_root = Path(settings.UPLOAD_DIR).resolve(strict=False)
    tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)
    try:
        path.relative_to(tenant_root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=docs_mod.DOCUMENT_FILE_ACCESS_DENIED_DETAIL) from exc

    media_type, _encoding = mimetypes.guess_type(path.name)
    if not media_type:
        media_type = "application/octet-stream"

    max_age = max(0, int(getattr(settings, "ASSET_CACHE_MAX_AGE_SEC", 0) or 0))
    cache_control = docs_mod._asset_cache_control(max_age=max_age)

    headers = {
        "Cache-Control": cache_control,
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }

    return FileResponse(
        path,
        media_type=media_type,
        filename=document.filename,
        content_disposition_type=_asset_disposition_type(
            inline=inline,
            filename=document.filename,
            media_type=media_type,
        ),
        headers=headers,
    )


@router.get("/image/{image_id}", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_image(
    image_id: str,
    request: Request,
    *,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Return stored image by image_id.
    Standard path: {UPLOAD_DIR}/{tenant_id}/images/{image_id}(.png|.jpg|.jpeg|.webp|.gif|.bmp)
    """
    docs_mod = _documents_module()
    tenant_id = await docs_mod._resolve_tenant_id_for_asset_request(request)
    account_id = await docs_mod._resolve_account_id_for_asset_request(request, tenant_id=tenant_id)

    if account_id:
        DatasetService.ensure_member(db, tenant_id, account_id)
    images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    try:
        safe_id = uuid.UUID(image_id).hex
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=docs_mod.IMAGE_NOT_FOUND_DETAIL) from exc

    images_dir_resolved = images_dir.resolve(strict=False)

    candidates: list[tuple[str, str]] = [
        (".png", "image/png"),
        (".jpg", docs_mod.IMAGE_JPEG_MEDIA_TYPE),
        (docs_mod.IMAGE_FILE_EXT_JPEG, docs_mod.IMAGE_JPEG_MEDIA_TYPE),
        (docs_mod.IMAGE_FILE_EXT_WEBP, "image/webp"),
        (".gif", "image/gif"),
        (".bmp", "image/bmp"),
    ]

    for ext, media_type in candidates:
        file_path = (images_dir / f"{safe_id}{ext}").resolve(strict=False)
        try:
            file_path.relative_to(images_dir_resolved)
        except ValueError:
            continue
        if file_path.exists() and file_path.is_file():
            max_age = max(0, int(getattr(settings, "ASSET_CACHE_MAX_AGE_SEC", 0) or 0))
            cache_control = docs_mod._asset_cache_control(max_age=max_age)
            try:
                stat_result = file_path.stat()
            except Exception:
                stat_result = None

            etag: str | None = None
            if stat_result is not None:
                etag = (
                    f"\"{int(getattr(stat_result, 'st_mtime_ns', 0) or 0):x}-"
                    f"{int(getattr(stat_result, 'st_size', 0) or 0):x}\""
                )

            if etag:
                if_none_match = (request.headers.get("if-none-match") or "").strip()
                if if_none_match:
                    candidates_etag = [part.strip() for part in if_none_match.split(",") if part.strip()]
                    if "*" in candidates_etag or etag in candidates_etag:
                        return Response(
                            status_code=304,
                            headers={
                                "ETag": etag,
                                "Cache-Control": cache_control,
                                "Referrer-Policy": "no-referrer",
                                "X-Content-Type-Options": "nosniff",
                            },
                        )
            return FileResponse(
                file_path,
                media_type=media_type,
                headers={
                    "Cache-Control": cache_control,
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                    **({"ETag": etag} if etag else {}),
                },
                stat_result=stat_result,
                content_disposition_type="inline",
            )

    raise HTTPException(status_code=404, detail=docs_mod.IMAGE_NOT_FOUND_DETAIL)


@router.get("/image-url/{img_id}", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_image_url(
    img_id: str,
    request: Request,
    *,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Get MinIO image bytes by img_id.
    """
    docs_mod = _documents_module()
    if not settings.MINIO_ENABLED:
        raise HTTPException(status_code=503, detail="MinIO is disabled; cannot retrieve image URL")

    def _tenant_from_img_id(val: str) -> UUID | None:
        if ":" not in val:
            return None
        raw_tenant = (val.split(":", 1)[0] or "").strip()
        if not raw_tenant:
            return None
        try:
            return UUID(raw_tenant)
        except Exception:
            return None

    tenant_in_img = _tenant_from_img_id(img_id)
    tenant_id = await docs_mod._resolve_tenant_id_for_asset_request(
        request,
        fallback_tenant_id=tenant_in_img,
        conflict_detail="Image access denied for this tenant",
    )

    account_id = await docs_mod._resolve_account_id_for_asset_request(
        request,
        tenant_id=tenant_id,
    )

    if account_id:
        DatasetService.ensure_member(db, tenant_id, account_id)

    if ":" in img_id:
        try:
            _tenant_part, dataset_part, document_part, _chunk_key = img_id.split(":", 3)
            dataset_uuid = UUID(dataset_part)
            document_uuid = UUID(document_part)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=404, detail=docs_mod.IMAGE_NOT_FOUND_DETAIL) from exc

        document = (
            db.query(DBDocument)
            .filter(DBDocument.id == document_uuid, DBDocument.tenant_id == tenant_id)
            .first()
        )
        if not document:
            raise HTTPException(status_code=404, detail=docs_mod.IMAGE_NOT_FOUND_DETAIL)
        if document.dataset_id and document.dataset_id != dataset_uuid:
            raise HTTPException(status_code=404, detail=docs_mod.IMAGE_NOT_FOUND_DETAIL)
        dataset: Dataset | None = None
        if document.dataset_id and account_id:
            dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
            DatasetService.assert_dataset_readable(db, dataset, account_id)
        if account_id:
            docs_mod._assert_document_acl_readable(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                document=document,
                dataset=dataset,
            )
    else:
        try:
            dataset_part = img_id.split("-", 1)[0]
            dataset_uuid = UUID(dataset_part)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=404, detail=docs_mod.IMAGE_NOT_FOUND_DETAIL) from exc
        if account_id:
            dataset = DatasetService.get_dataset(db, tenant_id, dataset_uuid)
            DatasetService.assert_dataset_readable(db, dataset, account_id)

    extension = "jpg"
    object_name: str | None = None
    if ":" in img_id:
        try:
            tenant_part, dataset_part, document_part, chunk_key = img_id.split(":", 3)
            object_name = f"images/{tenant_part}/{dataset_part}/{document_part}/{chunk_key}.{extension}"
        except Exception:
            object_name = None
    else:
        try:
            dataset_part, chunk_id = img_id.split("-", 1)
            object_name = f"images/{dataset_part}/{chunk_id}.{extension}"
        except Exception:
            object_name = None

    if not object_name:
        raise HTTPException(status_code=404, detail=docs_mod.IMAGE_NOT_FOUND_DETAIL)

    try:
        stat = docs_mod.minio_service.stat_object(object_name=object_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Image asset stat failed for %r: %r", object_name[:200], str(exc)[:200])
        raise HTTPException(status_code=404, detail=docs_mod.IMAGE_NOT_FOUND_DETAIL) from exc

    total_size = int(getattr(stat, "size", 0) or 0)
    if total_size <= 0:
        raise HTTPException(status_code=404, detail=docs_mod.IMAGE_NOT_FOUND_DETAIL)

    max_age = max(0, int(getattr(settings, "ASSET_CACHE_MAX_AGE_SEC", 0) or 0))
    cache_control = docs_mod._asset_cache_control(max_age=max_age)

    etag_raw = str(getattr(stat, "etag", "") or "").strip()
    etag = f"\"{etag_raw}\"" if etag_raw and not etag_raw.startswith("\"") else (etag_raw or None)

    range_header = (request.headers.get("range") or "").strip()
    if etag and not range_header:
        if_none_match = (request.headers.get("if-none-match") or "").strip()
        if if_none_match:
            candidates_etag = [part.strip() for part in if_none_match.split(",") if part.strip()]
            if "*" in candidates_etag or etag in candidates_etag:
                headers_304 = {
                    "ETag": etag,
                    "Cache-Control": cache_control,
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                }
                return Response(status_code=304, headers=headers_304)

    offset = 0
    length: int | None = None
    status_code = 200
    headers: dict[str, str] = {
        "Cache-Control": cache_control,
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "Accept-Ranges": "bytes",
        **({"ETag": etag} if etag else {}),
    }

    if range_header:
        if not range_header.lower().startswith("bytes="):
            raise HTTPException(status_code=416, detail=docs_mod.INVALID_RANGE_HEADER_DETAIL)
        spec = range_header[6:].strip()
        if "," in spec:
            raise HTTPException(status_code=416, detail="Multiple ranges not supported")
        start_s, end_s = (spec.split("-", 1) + [""])[:2]
        try:
            if start_s == "":
                suffix = int(end_s)
                if suffix <= 0:
                    raise ValueError
                offset = max(0, total_size - suffix)
                end = total_size - 1
            else:
                offset = int(start_s)
                end = int(end_s) if end_s else (total_size - 1)
                if offset < 0:
                    raise ValueError
                if end < offset:
                    raise ValueError
                if offset >= total_size:
                    raise HTTPException(status_code=416, detail="Range not satisfiable")
                end = min(end, total_size - 1)
            length = int(end - offset + 1)
            status_code = 206
            headers["Content-Range"] = f"bytes {offset}-{offset + length - 1}/{total_size}"
            headers["Content-Length"] = str(length)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=416, detail=docs_mod.INVALID_RANGE_HEADER_DETAIL) from exc
    else:
        headers["Content-Length"] = str(total_size)

    return StreamingResponse(
        docs_mod.minio_service.iter_object_bytes(object_name=object_name, offset=offset, length=length),
        status_code=status_code,
        media_type=docs_mod.IMAGE_JPEG_MEDIA_TYPE,
        headers=headers,
    )
