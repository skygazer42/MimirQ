"""Acquire document sources and read their external URL/HTML metadata."""

import contextlib
import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException

from app.api.schemas.document_ingestion import LocalHtmlIngestRequest, UrlUploadRequest
from app.api.utils.upload import _sanitize_filename, compute_file_hash
from app.api.utils.url_ingest import DownloadedURL, URLDownloadOptions, download_url_to_path
from app.core.async_bridge import run_blocking_in_thread
from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.preprocessing.html_canonical import extract_canonical_url, normalize_url_for_dedup
from app.services.document_source_persistence import SourceFileLease, unlink_source

logger = get_logger("services.document_ingestion_sources")
HTML_FILE_EXTENSION = ".html"


def _parse_datetime_best_effort(raw: str | None) -> datetime | None:
    """
    Best-effort datetime parser for connector source metadata.

    Supports:
    - HTTP-date (e.g. Last-Modified: "Wed, 21 Oct 2015 07:28:00 GMT")
    - ISO 8601 timestamps (e.g. "2026-03-04T10:00:00Z")
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None

    with contextlib.suppress(TypeError, ValueError, OverflowError):
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    with contextlib.suppress(TypeError, ValueError, OverflowError):
        iso = value
        if iso.endswith("Z"):
            iso = iso[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    return None


def _normalize_datetime_utc_iso(raw: str | None) -> str | None:
    dt = _parse_datetime_best_effort(raw)
    if dt is None:
        return None
    return dt.isoformat()


@dataclass
class UrlIngestFile:
    file_id: UUID
    final_path: Path
    file_ext: str
    downloaded: DownloadedURL
    content_type: str | None
    fetched_at_iso: str
    content_sha256: str


@dataclass
class LocalHtmlIngestFile:
    file_id: UUID
    file_path: Path
    file_ext: str
    filename: str
    file_size: int
    fetched_at_iso: str
    content_sha256: str


@dataclass
class UrlSourceMetadata:
    final_url: str
    normalized_requested: str | None
    normalized_final: str | None
    canonical_url: str | None
    normalized_canonical: str | None
    normalized_url: str | None
    last_modified_at: str
    last_modified_source: str
    last_modified_raw: str | None
    etag: str | None


def _ext_from_filename(name: str | None) -> str | None:
    if not name:
        return None
    ext = Path(name).suffix.lower()
    return ext if ext else None


def _ext_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    if content_type in {"text/html"}:
        return HTML_FILE_EXTENSION
    if content_type in {"text/plain"}:
        return ".txt"
    if content_type in {"text/markdown", "text/x-markdown"}:
        return ".md"
    if content_type in {"application/pdf"}:
        return ".pdf"
    if content_type in {"application/json"}:
        return ".json"
    if content_type in {"text/xml", "application/xml", "application/rss+xml", "application/atom+xml"}:
        return ".xml"
    return None


def _assert_allowed_file_ext(file_ext: str) -> str:
    file_ext = file_ext.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400, detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )
    return file_ext


def _resolve_url_file_ext(*, filename: str | None, url: str, content_type: str | None) -> str:
    file_ext = _ext_from_filename(filename)
    if not file_ext:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        file_ext = _ext_from_filename(Path(parsed.path).name)
    if not file_ext:
        file_ext = _ext_from_content_type(content_type)
    if not file_ext:
        if content_type is not None and content_type.startswith("text/"):
            file_ext = ".txt"
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported content-type: {content_type or 'unknown'}")
    return _assert_allowed_file_ext(file_ext)


def _resolve_local_html_file_ext(safe_name: str) -> str:
    file_ext = Path(safe_name).suffix.lower() or HTML_FILE_EXTENSION
    if file_ext == ".htm":
        file_ext = HTML_FILE_EXTENSION
    return _assert_allowed_file_ext(file_ext)


def _finalize_url_download(temp_path: Path, final_path: Path) -> None:
    try:
        temp_path.replace(final_path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to finalize downloaded file: {str(exc)[:120]}") from exc


def _read_html_prefix(path: Path) -> str:
    with path.open("rb") as f:
        return f.read(200_000).decode("utf-8", "ignore")


async def _extract_url_canonical_metadata(
    *,
    content_type: str | None,
    final_path: Path,
    url_final: str,
) -> tuple[str | None, str | None]:
    if not content_type or "html" not in content_type:
        return None, None

    try:
        html_prefix = await run_blocking_in_thread(_read_html_prefix, final_path)
        url_canonical = extract_canonical_url(html_prefix, base_url=url_final)
        url_normalized_canonical = normalize_url_for_dedup(url_canonical) if url_canonical else None
        return url_canonical, url_normalized_canonical
    except (OSError, ValueError) as exc:
        logger.warning("Canonical URL metadata unavailable: %s", str(exc)[:200])
        return None, None


async def download_url_ingest_file(*, url: str, body: UrlUploadRequest, tenant_id: UUID) -> UrlIngestFile:
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4()
    temp_path = upload_dir / f"{file_id}.urltmp"
    source_lease = SourceFileLease(temp_path)
    try:
        downloaded = await download_url_to_path(
            url,
            temp_path,
            options=URLDownloadOptions(
                max_bytes=(settings.URL_INGEST_MAX_BYTES or settings.MAX_FILE_SIZE),
                timeout_sec=float(settings.URL_INGEST_TIMEOUT_SEC or 30.0),
                follow_redirects=settings.URL_INGEST_FOLLOW_REDIRECTS,
                user_agent=body.user_agent,
                extra_headers=body.fetch_headers,
            ),
        )

        content_type = downloaded.content_type
        if content_type is not None:
            content_type = content_type.split(";", 1)[0].strip().lower()
        file_ext = _resolve_url_file_ext(filename=body.filename, url=url, content_type=content_type)
        final_path = upload_dir / f"{file_id}{file_ext}"
        source_lease.path = final_path
        _finalize_url_download(temp_path, final_path)
        content_sha256 = await run_blocking_in_thread(compute_file_hash, final_path)
        source_lease.transfer()
        return UrlIngestFile(
            file_id=file_id,
            final_path=final_path,
            file_ext=file_ext,
            downloaded=downloaded,
            content_type=content_type,
            fetched_at_iso=datetime.now(UTC).isoformat(),
            content_sha256=content_sha256,
        )
    finally:
        source_lease.cleanup()
        unlink_source(temp_path)


def write_local_html_ingest_file(*, body: LocalHtmlIngestRequest, tenant_id: UUID) -> LocalHtmlIngestFile:
    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    data = body.html.encode("utf-8", "ignore")
    if settings.MAX_FILE_SIZE > 0 and len(data) > settings.MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large")

    safe_name = _sanitize_filename(body.filename or "confluence-page.html")
    file_ext = _resolve_local_html_file_ext(safe_name)
    file_id = uuid.uuid4()
    file_path = upload_dir / f"{file_id}{file_ext}"
    source_lease = SourceFileLease(file_path)
    try:
        try:
            file_path.write_bytes(data)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to write html file: {str(exc)[:120]}") from exc
        result = LocalHtmlIngestFile(
            file_id=file_id,
            file_path=file_path,
            file_ext=file_ext,
            filename=safe_name,
            file_size=len(data),
            fetched_at_iso=datetime.now(UTC).isoformat(),
            content_sha256=hashlib.sha256(data).hexdigest(),
        )
        source_lease.transfer()
        return result
    finally:
        source_lease.cleanup()


async def url_source_metadata(*, url: str, ingest_file: UrlIngestFile) -> UrlSourceMetadata:
    downloaded = ingest_file.downloaded
    last_modified_raw = downloaded.last_modified
    if last_modified_raw is not None:
        last_modified_raw = last_modified_raw.strip()
        if not last_modified_raw:
            last_modified_raw = None
    last_modified_norm = _normalize_datetime_utc_iso(last_modified_raw)
    etag_raw = downloaded.etag
    if etag_raw is not None:
        etag_raw = etag_raw.strip()
        if not etag_raw:
            etag_raw = None
    if etag_raw and len(etag_raw) > 500:
        etag_raw = etag_raw[:500]

    url_final = downloaded.final_url.strip() or url
    url_normalized_requested = normalize_url_for_dedup(url)
    url_normalized_final = normalize_url_for_dedup(url_final)
    url_canonical, url_normalized_canonical = await _extract_url_canonical_metadata(
        content_type=ingest_file.content_type,
        final_path=ingest_file.final_path,
        url_final=url_final,
    )
    url_normalized = url_normalized_canonical or url_normalized_final or url_normalized_requested
    return UrlSourceMetadata(
        final_url=url_final,
        normalized_requested=url_normalized_requested,
        normalized_final=url_normalized_final,
        canonical_url=url_canonical,
        normalized_canonical=url_normalized_canonical,
        normalized_url=url_normalized,
        last_modified_at=last_modified_norm or ingest_file.fetched_at_iso,
        last_modified_source="http:last-modified" if last_modified_norm else "fallback:fetched_at",
        last_modified_raw=last_modified_raw,
        etag=etag_raw,
    )
