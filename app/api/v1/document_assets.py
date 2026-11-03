import mimetypes
import uuid
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import document_assets as asset_identity
from app.api.dependencies.auth import get_current_account_id_from_headers
from app.api.dependencies.tenant import _preferred_jwt_tenant_id
from app.api.utils.response_headers import set_content_disposition
from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document as DBDocument
from app.rag.core.logging import get_logger
from app.services import dataset_service, document_asset_access
from app.services.document_lifecycle_service import MANUAL_FILE_PATH_PREFIX
from app.services.document_preview_utils import (
    IMAGE_FILE_EXT_JPEG,
    IMAGE_FILE_EXT_WEBP,
)
from app.storage.object.minio import minio_service
from app.storage.object.runtime import is_object_storage_uri, resolve_document_object_reference

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

DOCUMENT_FILE_ACCESS_DENIED_DETAIL = "Document file access denied"
DOCUMENT_FILE_NOT_FOUND_DETAIL = "Document file not found"
IMAGE_NOT_FOUND_DETAIL = "Image not found"
IMAGE_JPEG_MEDIA_TYPE = "image/jpeg"
INVALID_RANGE_HEADER_DETAIL = "Invalid Range header"


def _asset_cache_control(*, max_age: int) -> str:
    del max_age
    return "private, no-store"


def _parse_uuid(value: str) -> UUID:
    return asset_identity._parse_tenant_id(value)


def _asset_request_header_account(request, *, is_production: bool) -> str | None:
    return asset_identity._asset_request_header_account(request, is_production=is_production)


def _asset_request_authorization(request) -> str:
    return asset_identity._asset_request_authorization(request)


async def _resolve_account_id_for_asset_request(request, *, tenant_id: UUID | None = None) -> str | None:
    return await asset_identity._resolve_account_id_for_asset_request(
        request,
        tenant_id=tenant_id,
        authenticator=get_current_account_id_from_headers,
    )


def _get_tenant_id_from_request_if_provided(request) -> UUID | None:
    return asset_identity._explicit_tenant_id(request)


async def _resolve_tenant_id_for_asset_request(
    request,
    *,
    fallback_tenant_id: UUID | None = None,
    conflict_detail: str = "Asset access denied for this tenant",
) -> UUID:
    return await asset_identity._resolve_tenant_id_for_asset_request(
        request,
        fallback_tenant_id=fallback_tenant_id,
        conflict_detail=conflict_detail,
        tenant_resolver=_preferred_jwt_tenant_id,
    )


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


def _authorize_bound_preview_document(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str | None,
    dataset_id: UUID,
    document_id: UUID,
) -> DBDocument | None:
    return document_asset_access.authorize_preview_document(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        document_id=document_id,
    )


def _locate_preview_image_asset(
    *,
    images_dir: Path,
    preview_id: str,
) -> tuple[Path, str] | None:
    images_dir_resolved = images_dir.resolve(strict=False)
    candidates: list[tuple[str, str]] = [
        (".png", "image/png"),
        (".jpg", IMAGE_JPEG_MEDIA_TYPE),
        (IMAGE_FILE_EXT_JPEG, IMAGE_JPEG_MEDIA_TYPE),
        (IMAGE_FILE_EXT_WEBP, "image/webp"),
        (".gif", "image/gif"),
        (".bmp", "image/bmp"),
    ]
    for ext, media_type in candidates:
        file_path = (images_dir / f"{preview_id}{ext}").resolve(strict=False)
        try:
            file_path.relative_to(images_dir_resolved)
        except ValueError:
            continue
        if file_path.exists() and file_path.is_file():
            return file_path, media_type
    return None


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


def _asset_disposition_type(*, inline: bool, filename: str | None, media_type: str | None) -> str:
    if not inline:
        return "attachment"

    normalized_media_type = str(media_type or "").split(";", 1)[0].strip().lower()
    normalized_suffix = Path(str(filename or "")).suffix.strip().lower()
    if normalized_media_type in _ACTIVE_CONTENT_MEDIA_TYPES or normalized_suffix in _ACTIVE_CONTENT_SUFFIXES:
        return "attachment"
    return "inline"


async def _resolve_document_asset_request_context(request: Request) -> tuple[UUID, str | None]:
    tenant_id = await _resolve_tenant_id_for_asset_request(request)
    account_id = await _resolve_account_id_for_asset_request(request, tenant_id=tenant_id)
    return tenant_id, account_id


def _asset_cache_control_value() -> str:
    max_age = max(0, int(settings.ASSET_CACHE_MAX_AGE_SEC or 0))
    return _asset_cache_control(max_age=max_age)


def _quoted_etag(raw_value: str | None) -> str | None:
    etag_raw = str(raw_value or "").strip()
    if not etag_raw:
        return None
    return etag_raw if etag_raw.startswith('"') else f'"{etag_raw}"'


def _asset_response_headers(
    *, cache_control: str, etag: str | None = None, accept_ranges: bool = False
) -> dict[str, str]:
    headers = {
        "Cache-Control": cache_control,
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }
    if accept_ranges:
        headers["Accept-Ranges"] = "bytes"
    if etag:
        headers["ETag"] = etag
    return headers


def _not_modified_response(request: Request, *, etag: str | None, cache_control: str) -> Response | None:
    if not etag:
        return None
    if_none_match = (request.headers.get("if-none-match") or "").strip()
    if not if_none_match:
        return None
    candidates_etag = [part.strip() for part in if_none_match.split(",") if part.strip()]
    if "*" not in candidates_etag and etag not in candidates_etag:
        return None
    return Response(status_code=304, headers=_asset_response_headers(cache_control=cache_control, etag=etag))


def _parse_range_request(
    *, range_header: str, total_size: int, invalid_detail: str
) -> tuple[int, int | None, int, dict[str, str]]:
    if not range_header:
        return 0, None, 200, {"Content-Length": str(total_size)}
    if not range_header.lower().startswith("bytes="):
        raise HTTPException(status_code=416, detail=invalid_detail)
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
            if offset < 0 or end < offset:
                raise ValueError
            if offset >= total_size:
                raise HTTPException(status_code=416, detail="Range not satisfiable")
            end = min(end, total_size - 1)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=416, detail=invalid_detail) from exc
    length = int(end - offset + 1)
    return (
        offset,
        length,
        206,
        {
            "Content-Range": f"bytes {offset}-{offset + length - 1}/{total_size}",
            "Content-Length": str(length),
        },
    )


def _resolve_document_download(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str | None,
    document_id: UUID,
) -> DBDocument:
    if account_id:
        dataset_service.ensure_member(db, tenant_id, account_id)
    return document_asset_access.authorize_document_asset(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        document_id=document_id,
    )


def _resolve_document_media_type(filename: str | None) -> str:
    media_type, _encoding = mimetypes.guess_type(filename or "")
    return media_type or "application/octet-stream"


def _stream_object_storage_document(
    *,
    document: DBDocument,
    tenant_id: UUID,
    request: Request,
    inline: bool,
) -> Response:
    raw_path = str(document.file_path or "").strip()
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
            raise HTTPException(status_code=403, detail=DOCUMENT_FILE_ACCESS_DENIED_DETAIL) from exc
        raise HTTPException(status_code=404, detail="Document file not available") from exc

    try:
        stat = store.stat_object(object_name=ref.object_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Document asset stat failed for %r: %r", ref.object_name[:200], str(exc)[:200])
        raise HTTPException(status_code=404, detail=DOCUMENT_FILE_NOT_FOUND_DETAIL) from exc

    total_size = int(getattr(stat, "size", 0) or 0)
    if total_size <= 0:
        raise HTTPException(status_code=404, detail=DOCUMENT_FILE_NOT_FOUND_DETAIL)
    cache_control = _asset_cache_control_value()
    etag = _quoted_etag(getattr(stat, "etag", ""))
    range_header = (request.headers.get("range") or "").strip()
    if not range_header:
        cached = _not_modified_response(request, etag=etag, cache_control=cache_control)
        if cached is not None:
            return cached
    offset, length, status_code, extra_headers = _parse_range_request(
        range_header=range_header,
        total_size=total_size,
        invalid_detail=INVALID_RANGE_HEADER_DETAIL,
    )
    headers = _asset_response_headers(cache_control=cache_control, etag=etag, accept_ranges=True)
    headers.update(extra_headers)
    media_type = _resolve_document_media_type(document.filename)
    set_content_disposition(
        headers,
        document.filename or "document",
        disposition=_asset_disposition_type(inline=inline, filename=document.filename, media_type=media_type),
    )
    return StreamingResponse(
        store.iter_object_bytes(object_name=ref.object_name, offset=offset, length=length),
        status_code=status_code,
        media_type=media_type,
        headers=headers,
    )


def _serve_local_document_file(*, document: DBDocument, tenant_id: UUID, inline: bool) -> FileResponse:
    path = Path(str(document.file_path or "")).resolve(strict=False)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=DOCUMENT_FILE_NOT_FOUND_DETAIL)
    upload_root = Path(settings.UPLOAD_DIR).resolve(strict=False)
    tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)
    try:
        path.relative_to(tenant_root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=DOCUMENT_FILE_ACCESS_DENIED_DETAIL) from exc
    media_type = _resolve_document_media_type(path.name)
    return FileResponse(
        path,
        media_type=media_type,
        filename=document.filename,
        content_disposition_type=_asset_disposition_type(
            inline=inline,
            filename=document.filename,
            media_type=media_type,
        ),
        headers=_asset_response_headers(cache_control=_asset_cache_control_value()),
    )


def _resolve_preview_binding_for_asset(
    *,
    db: Session,
    images_dir: Path,
    tenant_id: UUID,
    account_id: str | None,
    preview_id: str,
) -> tuple[dict[str, str], bool]:
    return document_asset_access.resolve_preview_binding(
        db=db,
        images_dir=images_dir,
        tenant_id=tenant_id,
        account_id=account_id,
        preview_id=preview_id,
    )


def _assert_preview_binding_access(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str | None,
    preview_binding: dict[str, str],
    legacy_binding_authorized: bool,
) -> None:
    document_asset_access.assert_preview_binding_access(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        binding=preview_binding,
        legacy_authorized=legacy_binding_authorized,
    )


def _file_etag(file_path: Path) -> tuple[Any, str | None]:
    try:
        stat_result = file_path.stat()
    except Exception:
        return None, None
    etag = f'"{int(getattr(stat_result, "st_mtime_ns", 0) or 0):x}-{int(getattr(stat_result, "st_size", 0) or 0):x}"'
    return stat_result, etag


def _tenant_from_image_url_id(img_id: str) -> UUID | None:
    if ":" not in img_id:
        return None
    raw_tenant = (img_id.split(":", 1)[0] or "").strip()
    if not raw_tenant:
        return None
    try:
        return UUID(raw_tenant)
    except Exception:
        return None


def _authorize_image_url_request(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str | None,
    img_id: str,
) -> None:
    document_asset_access.authorize_image_url(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        image_id=img_id,
    )


def _image_object_name(img_id: str) -> str | None:
    extension = "jpg"
    if ":" in img_id:
        try:
            tenant_part, dataset_part, document_part, chunk_key = img_id.split(":", 3)
        except Exception:
            return None
        return f"images/{tenant_part}/{dataset_part}/{document_part}/{chunk_key}.{extension}"
    try:
        dataset_part, chunk_id = img_id.split("-", 1)
    except Exception:
        return None
    return f"images/{dataset_part}/{chunk_id}.{extension}"


def _stream_minio_image(*, request: Request, object_name: str) -> Response:
    try:
        stat = minio_service.stat_object(object_name=object_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Image asset stat failed for %r: %r", object_name[:200], str(exc)[:200])
        raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL) from exc
    total_size = int(getattr(stat, "size", 0) or 0)
    if total_size <= 0:
        raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL)
    cache_control = _asset_cache_control_value()
    etag = _quoted_etag(getattr(stat, "etag", ""))
    range_header = (request.headers.get("range") or "").strip()
    if not range_header:
        cached = _not_modified_response(request, etag=etag, cache_control=cache_control)
        if cached is not None:
            return cached
    offset, length, status_code, extra_headers = _parse_range_request(
        range_header=range_header,
        total_size=total_size,
        invalid_detail=INVALID_RANGE_HEADER_DETAIL,
    )
    headers = _asset_response_headers(cache_control=cache_control, etag=etag, accept_ranges=True)
    headers.update(extra_headers)
    return StreamingResponse(
        minio_service.iter_object_bytes(object_name=object_name, offset=offset, length=length),
        status_code=status_code,
        media_type=IMAGE_JPEG_MEDIA_TYPE,
        headers=headers,
    )


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
    tenant_id, account_id = await _resolve_document_asset_request_context(request)
    document = _resolve_document_download(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        document_id=document_id,
    )
    raw_path = str(document.file_path or "").strip()
    if not raw_path or raw_path.startswith(MANUAL_FILE_PATH_PREFIX):
        raise HTTPException(status_code=404, detail="Document file not available")
    if is_object_storage_uri(raw_path):
        return _stream_object_storage_document(
            document=document,
            tenant_id=tenant_id,
            request=request,
            inline=inline,
        )
    return _serve_local_document_file(document=document, tenant_id=tenant_id, inline=inline)


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
    tenant_id, account_id = await _resolve_document_asset_request_context(request)
    if account_id:
        dataset_service.ensure_member(db, tenant_id, account_id)
    images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
    try:
        safe_id = uuid.UUID(image_id).hex
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL) from exc

    image_asset = _locate_preview_image_asset(images_dir=images_dir, preview_id=safe_id)
    if image_asset is None:
        raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL)
    file_path, media_type = image_asset
    preview_binding, legacy_binding_authorized = _resolve_preview_binding_for_asset(
        db=db,
        images_dir=images_dir,
        tenant_id=tenant_id,
        account_id=account_id,
        preview_id=safe_id,
    )
    _assert_preview_binding_access(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        preview_binding=preview_binding,
        legacy_binding_authorized=legacy_binding_authorized,
    )
    cache_control = _asset_cache_control_value()
    stat_result, etag = _file_etag(file_path)
    cached = _not_modified_response(request, etag=etag, cache_control=cache_control)
    if cached is not None:
        return cached
    return FileResponse(
        file_path,
        media_type=media_type,
        headers=_asset_response_headers(cache_control=cache_control, etag=etag),
        stat_result=stat_result,
        content_disposition_type="inline",
    )


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
    if not settings.MINIO_ENABLED:
        raise HTTPException(status_code=503, detail="MinIO is disabled; cannot retrieve image URL")
    tenant_in_img = _tenant_from_image_url_id(img_id)
    tenant_id = await _resolve_tenant_id_for_asset_request(
        request,
        fallback_tenant_id=tenant_in_img,
        conflict_detail="Image access denied for this tenant",
    )

    account_id = await _resolve_account_id_for_asset_request(
        request,
        tenant_id=tenant_id,
    )

    if account_id:
        dataset_service.ensure_member(db, tenant_id, account_id)
    _authorize_image_url_request(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        img_id=img_id,
    )
    object_name = _image_object_name(img_id)
    if not object_name:
        raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL)
    return _stream_minio_image(request=request, object_name=object_name)
