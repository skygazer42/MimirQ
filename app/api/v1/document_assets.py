import mimetypes
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from minio.error import S3Error

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES, set_content_disposition
from app.core.async_bridge import run_blocking_in_thread
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import Document as DBDocument
from app.rag.core.logging import get_logger
from app.services import dataset_service, document_asset_access
from app.services.document_lifecycle_service import MANUAL_FILE_PATH_PREFIX
from app.services.document_preview_utils import (
    IMAGE_FILE_EXT_JPEG,
    IMAGE_FILE_EXT_WEBP,
)
from app.storage.object.minio import MinIOService, minio_service
from app.storage.object.runtime import is_object_storage_uri, resolve_document_object_reference

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)

DOCUMENT_FILE_ACCESS_DENIED_DETAIL = "Document file access denied"
DOCUMENT_FILE_NOT_FOUND_DETAIL = "Document file not found"
IMAGE_NOT_FOUND_DETAIL = "Image not found"
IMAGE_JPEG_MEDIA_TYPE = "image/jpeg"
INVALID_RANGE_HEADER_DETAIL = "Invalid Range header"


# Documents and images are per-user; never let a shared cache retain them.
ASSET_CACHE_CONTROL = "private, no-store"


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
        if file_path.is_file():
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

    normalized_media_type = media_type.split(";", 1)[0].strip().lower() if media_type is not None else None
    normalized_suffix = Path(filename).suffix.strip().lower() if filename is not None else None
    if normalized_media_type in _ACTIVE_CONTENT_MEDIA_TYPES or normalized_suffix in _ACTIVE_CONTENT_SUFFIXES:
        return "attachment"
    return "inline"


async def _resolve_document_asset_request_context(request: Request) -> tuple[UUID, str]:
    tenant_id = await get_tenant_id(request)
    account_id = await get_current_account_id(request)
    return tenant_id, account_id


def _quoted_etag(raw_value: str | None) -> str | None:
    etag_raw = raw_value.strip() if raw_value is not None else None
    if not etag_raw:
        return None
    return etag_raw if etag_raw.startswith('"') else f'"{etag_raw}"'


def _asset_response_headers(*, etag: str | None = None, accept_ranges: bool = False) -> dict[str, str]:
    headers = {
        "Cache-Control": ASSET_CACHE_CONTROL,
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }
    if accept_ranges:
        headers["Accept-Ranges"] = "bytes"
    if etag:
        headers["ETag"] = etag
    return headers


def _not_modified_response(*, if_none_match: str | None, etag: str | None) -> Response | None:
    if not etag:
        return None
    if not if_none_match:
        return None
    candidates_etag = [part.strip() for part in if_none_match.split(",") if part.strip()]
    if "*" not in candidates_etag and etag not in candidates_etag:
        return None
    return Response(status_code=304, headers=_asset_response_headers(etag=etag))


def _parse_range_request(*, range_header: str | None, total_size: int) -> tuple[int, int | None, int, dict[str, str]]:
    if not range_header:
        return 0, None, 200, {"Content-Length": str(total_size)}
    if not range_header.lower().startswith("bytes="):
        raise HTTPException(status_code=416, detail=INVALID_RANGE_HEADER_DETAIL)
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
    except ValueError as exc:
        raise HTTPException(status_code=416, detail=INVALID_RANGE_HEADER_DETAIL) from exc
    length = end - offset + 1
    return (
        offset,
        length,
        206,
        {
            "Content-Range": f"bytes {offset}-{offset + length - 1}/{total_size}",
            "Content-Length": str(length),
        },
    )


def _resolve_document_media_type(filename: str | None) -> str:
    if filename is None:
        return "application/octet-stream"
    media_type, _encoding = mimetypes.guess_type(filename)
    return media_type or "application/octet-stream"


def _stream_object_asset(
    *,
    store: MinIOService,
    object_name: str,
    media_type: str,
    range_header: str | None,
    if_none_match: str | None,
    not_found_detail: str,
    filename: str | None = None,
    inline: bool = True,
) -> Response:
    try:
        stat = store.stat_object(object_name=object_name)
    except S3Error as exc:
        if exc.code != "NoSuchKey":
            raise
        logger.warning("Asset stat failed for %r: %r", object_name[:200], str(exc)[:200], exc_info=True)
        raise HTTPException(status_code=404, detail=not_found_detail) from exc

    total_size = stat.size
    if total_size <= 0:
        raise HTTPException(status_code=404, detail=not_found_detail)
    etag = _quoted_etag(stat.etag)
    if range_header is not None:
        range_header = range_header.strip()
    if not range_header:
        cached = _not_modified_response(if_none_match=if_none_match, etag=etag)
        if cached is not None:
            return cached
    offset, length, status_code, extra_headers = _parse_range_request(range_header=range_header, total_size=total_size)
    headers = _asset_response_headers(etag=etag, accept_ranges=True)
    headers.update(extra_headers)
    if filename is not None:
        set_content_disposition(
            headers,
            filename,
            disposition=_asset_disposition_type(inline=inline, filename=filename, media_type=media_type),
        )
    return StreamingResponse(
        store.iter_object_bytes(object_name=object_name, offset=offset, length=length),
        status_code=status_code,
        media_type=media_type,
        headers=headers,
    )


def _stream_object_storage_document(
    *,
    document: DBDocument,
    tenant_id: UUID,
    range_header: str | None,
    if_none_match: str | None,
    inline: bool,
) -> Response:
    raw_path = document.file_path.strip()
    try:
        store, ref = resolve_document_object_reference(
            raw_path,
            tenant_id=tenant_id,
            dataset_id=document.dataset_id,
            document_id=document.id,
            file_type=document.file_type,
            document_metadata=dict(document.doc_metadata or {}),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Object storage is disabled") from exc
    except ValueError as exc:
        if str(exc) in {"object_bucket_denied", "object_key_denied"}:
            raise HTTPException(status_code=403, detail=DOCUMENT_FILE_ACCESS_DENIED_DETAIL) from exc
        raise HTTPException(status_code=404, detail="Document file not available") from exc

    media_type = _resolve_document_media_type(document.filename)
    return _stream_object_asset(
        store=store,
        object_name=ref.object_name,
        media_type=media_type,
        filename=document.filename or "document",
        inline=inline,
        range_header=range_header,
        if_none_match=if_none_match,
        not_found_detail=DOCUMENT_FILE_NOT_FOUND_DETAIL,
    )


def _serve_local_document_file(*, document: DBDocument, tenant_id: UUID, inline: bool) -> FileResponse:
    path = Path(document.file_path).resolve(strict=False)
    if not path.is_file():
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
        headers=_asset_response_headers(),
    )


def _tenant_from_image_url_id(img_id: str) -> UUID | None:
    if ":" not in img_id:
        return None
    raw_tenant = (img_id.split(":", 1)[0]).strip()
    if not raw_tenant:
        return None
    try:
        return UUID(raw_tenant)
    except ValueError:
        return None


def _image_object_name(img_id: str) -> str | None:
    extension = "jpg"
    if ":" in img_id:
        try:
            tenant_part, dataset_part, document_part, chunk_key = img_id.split(":", 3)
        except ValueError:
            return None
        return f"images/{tenant_part}/{dataset_part}/{document_part}/{chunk_key}.{extension}"
    try:
        dataset_part, chunk_id = img_id.split("-", 1)
    except ValueError:
        return None
    return f"images/{dataset_part}/{chunk_id}.{extension}"


def _prepare_document_download(
    *,
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    inline: bool,
    range_header: str | None,
    if_none_match: str | None,
) -> Response:
    with SessionLocal() as db:
        dataset_service.ensure_member(db, tenant_id, account_id)
        document = document_asset_access.authorize_document_asset(
            db=db, tenant_id=tenant_id, account_id=account_id, document_id=document_id
        )
        raw_path = document.file_path.strip()
        if not raw_path or raw_path.startswith(MANUAL_FILE_PATH_PREFIX):
            raise HTTPException(status_code=404, detail="Document file not available")
        if is_object_storage_uri(raw_path):
            return _stream_object_storage_document(
                document=document,
                tenant_id=tenant_id,
                inline=inline,
                range_header=range_header,
                if_none_match=if_none_match,
            )
        return _serve_local_document_file(document=document, tenant_id=tenant_id, inline=inline)


def _prepare_preview_image(
    *,
    image_id: str,
    tenant_id: UUID,
    account_id: str,
    if_none_match: str | None,
) -> Response:
    with SessionLocal() as db:
        dataset_service.ensure_member(db, tenant_id, account_id)
        images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
        try:
            safe_id = UUID(image_id).hex
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL) from exc
        image_asset = _locate_preview_image_asset(images_dir=images_dir, preview_id=safe_id)
        if image_asset is None:
            raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL)
        file_path, media_type = image_asset
        preview_binding, legacy_binding_authorized = document_asset_access.resolve_preview_binding(
            db=db,
            images_dir=images_dir,
            tenant_id=tenant_id,
            account_id=account_id,
            preview_id=safe_id,
        )
        document_asset_access.assert_preview_binding_access(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            binding=preview_binding,
            legacy_authorized=legacy_binding_authorized,
        )
        stat_result = file_path.stat()
        etag = f'"{stat_result.st_mtime_ns:x}-{stat_result.st_size:x}"'
        cached = _not_modified_response(if_none_match=if_none_match, etag=etag)
        if cached is not None:
            return cached
        return FileResponse(
            file_path,
            media_type=media_type,
            headers=_asset_response_headers(etag=etag),
            stat_result=stat_result,
            content_disposition_type="inline",
        )


def _prepare_image_url(
    *,
    img_id: str,
    tenant_id: UUID,
    account_id: str,
    range_header: str | None,
    if_none_match: str | None,
) -> Response:
    with SessionLocal() as db:
        dataset_service.ensure_member(db, tenant_id, account_id)
        document_asset_access.authorize_image_url(db=db, tenant_id=tenant_id, account_id=account_id, image_id=img_id)
        object_name = _image_object_name(img_id)
        if not object_name:
            raise HTTPException(status_code=404, detail=IMAGE_NOT_FOUND_DETAIL)
        return _stream_object_asset(
            store=minio_service,
            object_name=object_name,
            media_type=IMAGE_JPEG_MEDIA_TYPE,
            range_header=range_header,
            if_none_match=if_none_match,
            not_found_detail=IMAGE_NOT_FOUND_DETAIL,
        )


@router.get("/{document_id}/download")
async def download_document(
    document_id: UUID,
    request: Request,
    inline: bool = True,
) -> Response:
    """Download or preview a document in the current account and workspace."""
    tenant_id, account_id = await _resolve_document_asset_request_context(request)
    return await run_blocking_in_thread(
        _prepare_document_download,
        document_id=document_id,
        tenant_id=tenant_id,
        account_id=account_id,
        inline=inline,
        range_header=request.headers.get("range"),
        if_none_match=request.headers.get("if-none-match"),
    )


@router.get("/image/{image_id}")
async def get_image(
    image_id: str,
    request: Request,
) -> Response:
    """
    Return stored image by image_id.
    Standard path: {UPLOAD_DIR}/{tenant_id}/images/{image_id}(.png|.jpg|.jpeg|.webp|.gif|.bmp)
    """
    tenant_id, account_id = await _resolve_document_asset_request_context(request)
    return await run_blocking_in_thread(
        _prepare_preview_image,
        image_id=image_id,
        tenant_id=tenant_id,
        account_id=account_id,
        if_none_match=request.headers.get("if-none-match"),
    )


@router.get("/image-url/{img_id}")
async def get_image_url(
    img_id: str,
    request: Request,
) -> Response:
    """
    Get MinIO image bytes by img_id.
    """
    if not settings.MINIO_ENABLED:
        raise HTTPException(status_code=503, detail="MinIO is disabled; cannot retrieve image URL")
    tenant_in_img = _tenant_from_image_url_id(img_id)
    tenant_id = await get_tenant_id(request)
    if tenant_in_img is not None and tenant_in_img != tenant_id:
        raise HTTPException(status_code=403, detail="Image access denied for this tenant")

    account_id = await get_current_account_id(request)

    return await run_blocking_in_thread(
        _prepare_image_url,
        img_id=img_id,
        tenant_id=tenant_id,
        account_id=account_id,
        range_header=request.headers.get("range"),
        if_none_match=request.headers.get("if-none-match"),
    )
