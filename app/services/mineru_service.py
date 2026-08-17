"""
MinerU document parsing service.
Supports two modes:
1. MinerU online API: https://mineru.net (returns ZIP with Markdown)
2. MinerU local service: returns ZIP (Markdown + images)
Both modes support advanced PDF parsing (tables, images, formulas, etc.)
"""

import asyncio
import io
import re
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiofiles
import httpx
from langchain_core.documents import Document

from app.core.async_bridge import run_coroutine_sync as _run_coroutine_sync
from app.core.config import settings
from app.core.http_client import get_http_client_pool
from app.core.jwt_inspect import format_unix_ts_utc, try_get_jwt_exp
from app.parsing.utils.markdown_response import extract_markdown_response_text
from app.parsing.utils.mineru_layout import (
    extract_position_tagged_markdown_from_zip_bytes,
    extract_position_tagged_markdown_from_zip_path,
)
from app.parsing.utils.zip_processor import zip_image_processor
from app.rag.core.logging import get_logger
from app.services.document_preview_utils import _write_preview_owner_binding

logger = get_logger("services.mineru")

OCTET_STREAM = "application/octet-stream"
UNKNOWN_ERROR = "Unknown error"
MINERU_FALLBACK_LOG_MESSAGE = "Ignoring non-critical MinerU fallback failure: %s"


def _normalize_local_backend(value: Any) -> str:
    backend = str(value or "pipeline").strip().lower().replace("_", "-")
    aliases = {
        "": "pipeline",
        "auto": "pipeline",
        "vlm": "vlm-http-client",
        "vlm-http": "vlm-http-client",
        "vlm-httpclient": "vlm-http-client",
    }
    backend = aliases.get(backend, backend)
    if backend not in {"pipeline", "vlm-http-client"}:
        logger.warning("Unsupported MinerU backend %r; falling back to pipeline.", value)
        return "pipeline"
    return backend


def _zip_safe_entries(zip_bytes: bytes) -> tuple[zipfile.ZipFile, list[zipfile.ZipInfo]]:
    max_files = int(getattr(settings, "ZIP_MAX_FILES", 2000))
    max_total = int(getattr(settings, "ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES", 500_000_000))
    max_single = int(getattr(settings, "ZIP_MAX_SINGLE_UNCOMPRESSED_BYTES", 100_000_000))
    zip_file = zipfile.ZipFile(io.BytesIO(zip_bytes), "r")
    infos = zip_file.infolist()
    if len(infos) > max_files:
        zip_file.close()
        raise ValueError(f"ZIP contains too many files: {len(infos)} > {max_files}")

    total_bytes = 0
    for info in infos:
        total_bytes += int(getattr(info, "file_size", 0) or 0)
        if info.file_size and info.file_size > max_single:
            zip_file.close()
            raise ValueError(f"ZIP entry too large: {info.filename} ({info.file_size} bytes)")
    if total_bytes > max_total:
        zip_file.close()
        raise ValueError(f"ZIP uncompressed size too large: {total_bytes} > {max_total}")
    return zip_file, infos


def _markdown_zip_infos(infos: list[zipfile.ZipInfo]) -> list[zipfile.ZipInfo]:
    markdown_infos: list[zipfile.ZipInfo] = []
    for info in infos:
        if info.is_dir():
            continue
        name = (info.filename or "").replace("\\", "/")
        parts = [part.lower() for part in name.split("/") if part]
        if "__macosx" in parts:
            continue
        if name.lower().endswith(".md"):
            markdown_infos.append(info)
    return markdown_infos


def _preferred_markdown_info(markdown_infos: list[zipfile.ZipInfo]) -> zipfile.ZipInfo | None:
    preferred_names = ["full.md", "output.md", "result.md", "index.md", "readme.md"]
    for preferred_name in preferred_names:
        for info in markdown_infos:
            base = (info.filename or "").replace("\\", "/").split("/")[-1].lower()
            if base == preferred_name:
                return info

    if not markdown_infos:
        return None

    def sort_key(info: zipfile.ZipInfo) -> tuple[int, int]:
        depth = len([part for part in (info.filename or "").replace("\\", "/").split("/") if part])
        return (depth, -int(getattr(info, "file_size", 0) or 0))

    return min(markdown_infos, key=sort_key)


def _preview_markdown_refs(markdown: str) -> list[str]:
    patterns = (
        re.compile(
            r"!\[[^\]]*\]\(\s*(?:<)?([^)\s>]+)(?:>)?(?:\s+['\"][^'\"]*['\"])?\s*\)",
            flags=re.IGNORECASE,
        ),
        re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", flags=re.IGNORECASE),
    )
    refs: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in pattern.finditer(markdown):
            ref = match.group(1)
            if not isinstance(ref, str):
                continue
            ref = ref.strip()
            if not ref or ref in seen:
                continue
            seen.add(ref)
            refs.append(ref)
    return refs


def _preview_image_members(zip_file: zipfile.ZipFile) -> dict[str, str]:
    image_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
    member_by_key: dict[str, str] = {}
    for info in zip_file.infolist():
        if info.is_dir():
            continue
        name = (info.filename or "").replace("\\", "/").lstrip("/")
        if not name:
            continue
        parts_lower = [part.lower() for part in name.split("/") if part]
        if "__macosx" in parts_lower:
            continue
        if Path(name).suffix.lower() not in image_exts:
            continue
        member_by_key[name] = name
        member_by_key[Path(name).name] = name
    return member_by_key


def _preview_zip_member_for_ref(ref: str, member_by_key: dict[str, str]) -> tuple[str, str] | None:
    parsed_ref = urlparse(ref)
    scheme = (parsed_ref.scheme or "").lower().strip()
    if scheme in {"http", "https"} or (parsed_ref.netloc or "").strip():
        return None
    if "/api/v1/documents/image/" in ref or "/api/v1/documents/image-url/" in ref:
        return None
    normalized_ref = zip_image_processor._normalize_ref_path(ref)
    if not normalized_ref:
        return None
    member = member_by_key.get(normalized_ref)
    if not member and not normalized_ref.startswith("images/"):
        member = member_by_key.get(f"images/{normalized_ref}")
    if not member:
        return None
    return normalized_ref, member


def _normalize_batch_state_counters(extract_result: list[Any]) -> tuple[int, int, int, str | None]:
    completed_files = 0
    failed_files = 0
    running_files = 0
    first_error: str | None = None
    for item in extract_result:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state") or "").lower()
        if state == "done":
            completed_files += 1
            continue
        if state == "failed":
            failed_files += 1
            if not first_error:
                err = (item.get("err_msg") or "").strip()
                if err:
                    first_error = err
            continue
        if state == "running":
            running_files += 1
    return completed_files, failed_files, running_files, first_error


def _normalized_batch_status(
    *, total_files: int, completed_files: int, failed_files: int, running_files: int
) -> tuple[str, int]:
    done_files = completed_files + failed_files
    if total_files <= 0:
        return "pending", 0
    progress = int((done_files / float(total_files)) * 100)
    if done_files >= total_files:
        return ("failed" if failed_files > 0 else "completed"), 100
    if running_files > 0:
        return "processing", progress
    return "pending", progress


def _matching_extract_item(
    extract_result: list[dict[str, Any]], *, field_name: str, value: str | None
) -> dict[str, Any] | None:
    if not value:
        return None
    expected = str(value)
    for item in extract_result:
        if not isinstance(item, dict):
            continue
        if str(item.get(field_name) or "") == expected:
            return item
    return None


def _extract_preview_image_reference(
    *,
    zip_file: zipfile.ZipFile,
    member: str,
    normalized_ref: str,
    images_dir: Path,
    tenant_id: str,
    account_id: str | None,
    max_bytes: int,
    image_exts: set[str],
    cached_id_by_norm: dict[str, str],
    extracted: list[dict[str, str]],
) -> tuple[str, dict[str, dict[str, str]]] | None:
    img_id = cached_id_by_norm.get(normalized_ref)
    if not img_id:
        try:
            binary = zip_file.read(member)
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            return None
        if not binary or len(binary) > max_bytes:
            return None

        ext = Path(member).suffix.lower()
        if ext not in image_exts:
            ext = ".png"
        img_id = uuid.uuid4().hex
        out_path = images_dir / f"{img_id}{ext}"
        try:
            out_path.write_bytes(binary)
            _write_preview_owner_binding(
                images_dir=images_dir,
                preview_id=img_id,
                binding=(
                    {"tenant_id": str(tenant_id), "account_id": str(account_id or "").strip()}
                    if str(account_id or "").strip()
                    else None
                ),
            )
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            return None

        cached_id_by_norm[normalized_ref] = img_id
        extracted.append({"id": img_id, "filename": out_path.name, "url": f"/api/v1/documents/image/{img_id}"})

    url = f"/api/v1/documents/image/{img_id}"
    keys = {normalized_ref, Path(normalized_ref).name}
    return url, {key: {"url": url} for key in keys if key}


def _bounded_preview_refs(markdown: str) -> list[str]:
    refs = _preview_markdown_refs(markdown)
    if not refs:
        return []
    max_images = max(0, int(getattr(settings, "ZIP_MAX_IMAGES", 0) or 0))
    if max_images and len(refs) > max_images:
        return refs[:max_images]
    return refs


def _preview_image_mapping(
    *,
    zip_file: zipfile.ZipFile,
    refs: list[str],
    images_dir: Path,
    tenant_id: str,
    account_id: str | None,
) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    member_by_key = _preview_image_members(zip_file)
    max_bytes = int(getattr(settings, "MAX_INLINE_IMAGE_BYTES", 10_000_000) or 10_000_000)
    max_bytes = max(1_000_000, max_bytes)
    image_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

    extracted: list[dict[str, str]] = []
    mapping: dict[str, dict[str, str]] = {}
    cached_id_by_norm: dict[str, str] = {}
    for ref in refs:
        resolved_member = _preview_zip_member_for_ref(ref, member_by_key)
        if resolved_member is None:
            continue
        norm, member = resolved_member
        extracted_ref = _extract_preview_image_reference(
            zip_file=zip_file,
            member=member,
            normalized_ref=norm,
            images_dir=images_dir,
            tenant_id=tenant_id,
            account_id=account_id,
            max_bytes=max_bytes,
            image_exts=image_exts,
            cached_id_by_norm=cached_id_by_norm,
            extracted=extracted,
        )
        if extracted_ref is None:
            continue
        _url, ref_mapping = extracted_ref
        mapping.update(ref_mapping)
    return extracted, mapping


class MinerUService:
    """MinerU parsing service."""

    def __init__(self):
        self.api_base = ""
        self.api_token = ""
        self.model_version = "vlm"
        self.local_server_url: str | None = None
        self.local_backend = "pipeline"
        self.enabled = False

        # Best-effort JWT expiry diagnostics (MinerU online API token may expire).
        self._token_exp: int | None = None
        self._warned_token_expired = False

        self._refresh_config(log_disabled_warning=True)

    def _refresh_config(self, *, log_disabled_warning: bool = False) -> None:
        """
        Sync runtime config from `settings`.

        - Local MinerU does not require API token; online API does.
        - If the token looks like a JWT and is expired, treat online mode as disabled
          (best-effort) to avoid repeated 401 failures.
        """
        self.api_base = (getattr(settings, "MINERU_API_BASE", "") or "").strip().rstrip(
            "/"
        ) or "https://mineru.net/api/v4"
        self.api_token = (getattr(settings, "MINERU_API_TOKEN", "") or "").strip()
        self.model_version = (getattr(settings, "MINERU_MODEL_VERSION", "") or "").strip() or "vlm"
        self.local_backend = _normalize_local_backend(getattr(settings, "MINERU_BACKEND", "pipeline"))

        local_url = (getattr(settings, "MINERU_LOCAL_SERVER_URL", "") or "").strip()
        self.local_server_url = local_url.rstrip("/") if local_url else None

        self._token_exp = try_get_jwt_exp(self.api_token) if self.api_token else None
        now = int(time.time())
        token_valid = bool(self.api_token) and (self._token_exp is None or int(self._token_exp) > now)

        self.enabled = bool(getattr(settings, "MINERU_ENABLED", False)) and (token_valid or bool(self.local_server_url))

        if (
            bool(getattr(settings, "MINERU_ENABLED", False))
            and self.api_token
            and self._token_exp is not None
            and int(self._token_exp) <= now
            and not self._warned_token_expired
        ):
            logger.warning(
                "MINERU_API_TOKEN appears expired (exp=%s). Refresh token to use MinerU online API.",
                format_unix_ts_utc(int(self._token_exp)),
            )
            self._warned_token_expired = True

        if log_disabled_warning and not self.enabled:
            logger.warning(
                "MinerU is disabled. Set MINERU_ENABLED=True and configure "
                "MINERU_API_TOKEN (online) or MINERU_LOCAL_SERVER_URL (local) to enable."
            )

    def _format_auth_error(self, status_code: int) -> str:
        exp = self._token_exp
        if exp is not None:
            now = int(time.time())
            if int(exp) <= now:
                return (
                    f"MinerU API unauthorized (HTTP {status_code}): MINERU_API_TOKEN expired at "
                    f"{format_unix_ts_utc(int(exp))}"
                )
            return (
                f"MinerU API unauthorized (HTTP {status_code}): invalid MINERU_API_TOKEN "
                f"(exp={format_unix_ts_utc(int(exp))})"
            )
        return f"MinerU API unauthorized (HTTP {status_code}): invalid MINERU_API_TOKEN"

    def _ensure_online_enabled(self) -> None:
        self._refresh_config()
        if not bool(getattr(settings, "MINERU_ENABLED", False)):
            raise RuntimeError("MinerU is disabled. Set MINERU_ENABLED=true to enable.")
        if not self.api_token:
            raise RuntimeError("MinerU online API requires MINERU_API_TOKEN.")
        if self._token_exp is not None and int(self._token_exp) <= int(time.time()):
            raise RuntimeError(
                f"MINERU_API_TOKEN expired at {format_unix_ts_utc(int(self._token_exp))}. Please refresh token."
            )

    @staticmethod
    def _raise_batch_results_error(message: Any) -> None:
        detail = str(message or UNKNOWN_ERROR).strip() or UNKNOWN_ERROR
        normalized = detail.lower()
        if (
            "task not found" in normalized
            or "not found or expire" in normalized
            or "not found or expired" in normalized
        ):
            raise LookupError(detail)
        raise RuntimeError(f"Get batch results failed: {detail}")

    def _get_headers(self) -> dict[str, str]:
        """Get request headers."""
        self._ensure_online_enabled()
        return {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_token}", "Accept": "*/*"}

    async def _arequest_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Send an HTTP request and parse JSON (async with retries).

        NOTE: Reuse the global HTTPClientPool to avoid blocking the event loop.
        """
        pool = get_http_client_pool()
        try:
            resp = await pool.request_with_retry(method, url, headers=headers, timeout=30.0, **kwargs)
        except httpx.HTTPStatusError as exc:
            status = int(getattr(exc.response, "status_code", 0) or 0)
            if status in {401, 403}:
                raise RuntimeError(self._format_auth_error(status)) from exc
            raise RuntimeError(f"MinerU API request failed (HTTP {status}): {str(exc)[:200]}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"MinerU API request failed: {str(exc)[:200]}") from exc
        try:
            return resp.json()
        finally:
            # Ensure response is closed to release connection back to pool.
            try:
                await resp.aclose()
            except Exception as exc:
                logger.debug(MINERU_FALLBACK_LOG_MESSAGE, exc)

    async def aapply_upload_url(self, filename: str, data_id: str) -> dict[str, Any]:
        """Request a single file upload URL (async)."""
        self._ensure_online_enabled()

        url = f"{self.api_base}/file-urls/batch"
        data = {"files": [{"name": filename, "data_id": data_id}], "model_version": self.model_version}

        result = await self._arequest_json("POST", url, headers=self._get_headers(), json=data)
        if result.get("code") == 0:
            batch_id = result["data"]["batch_id"]
            upload_url = result["data"]["file_urls"][0]
            return {"batch_id": batch_id, "upload_url": upload_url, "data_id": data_id}
        raise RuntimeError(f"Apply upload URL failed: {result.get('msg', UNKNOWN_ERROR)}")

    def apply_upload_url(self, filename: str, data_id: str) -> dict[str, Any]:
        """
        Request a single file upload URL.

        Args:
            filename: File name.
            data_id: Custom data ID (identifier).

        Returns:
            {
                "batch_id": "xxx",
                "upload_url": "https://...",
                "data_id": "xxx"
            }
        """
        return _run_coroutine_sync(lambda: self.aapply_upload_url(filename, data_id))

    async def aapply_batch_upload_urls(self, files: list[dict[str, str]]) -> dict[str, Any]:
        """Request batch upload URLs (async)."""
        self._ensure_online_enabled()
        if len(files) > 200:
            raise ValueError("Maximum 200 files per batch")

        url = f"{self.api_base}/file-urls/batch"
        data = {"files": files, "model_version": self.model_version}

        result = await self._arequest_json("POST", url, headers=self._get_headers(), json=data)
        if result.get("code") == 0:
            return {"batch_id": result["data"]["batch_id"], "file_urls": result["data"]["file_urls"], "files": files}
        raise RuntimeError(f"Apply batch upload URLs failed: {result.get('msg', 'Unknown error')}")

    def apply_batch_upload_urls(self, files: list[dict[str, str]]) -> dict[str, Any]:
        """
        Request batch upload URLs.

        Args:
            files: File list, format: [{"name": "file1.pdf", "data_id": "id1"}, ...]
                   Up to 200 files.

        Returns:
            {
                "batch_id": "xxx",
                "file_urls": ["https://...", "https://..."],
                "files": [{"name": "...", "data_id": "..."}, ...]
            }
        """
        return _run_coroutine_sync(lambda: self.aapply_batch_upload_urls(files))

    async def aupload_file(self, file_path: Path, upload_url: str) -> bool:
        """
        Upload file to MinerU.

        Args:
            file_path: Local file path.
            upload_url: Issued upload URL.

        Returns:
            Whether upload succeeded.
        """
        pool = get_http_client_pool()
        try:
            # MinerU upload does not require Content-Type.
            class _FileChunks:
                def __init__(self, path: Path, *, chunk_size: int = 1024 * 1024):
                    self._path = path
                    self._chunk_size = chunk_size

                def __aiter__(self):
                    async def gen():
                        async with aiofiles.open(self._path, "rb") as f:
                            while True:
                                chunk = await f.read(self._chunk_size)
                                if not chunk:
                                    break
                                yield chunk

                    return gen()

            resp = await pool.put(upload_url, content=_FileChunks(file_path), timeout=300.0)
            ok = int(getattr(resp, "status_code", 0) or 0) == 200
            try:
                await resp.aclose()
            except Exception as exc:
                logger.debug(MINERU_FALLBACK_LOG_MESSAGE, exc)
            return ok
        except Exception as exc:  # noqa: BLE001
            logger.exception("Upload file failed: %s", str(exc)[:200])
            return False

    def upload_file(self, file_path: Path, upload_url: str) -> bool:
        return bool(_run_coroutine_sync(lambda: self.aupload_file(file_path, upload_url)))

    async def aget_task_status(self, batch_id: str) -> dict[str, Any]:
        """
        Query batch parsing task status (async).

        MinerU online API returns per-file states via:
        `GET /extract-results/batch/{batch_id}`
        """
        self._ensure_online_enabled()

        url = f"{self.api_base}/extract-results/batch/{batch_id}"
        result = await self._arequest_json("GET", url, headers=self._get_headers())
        if result.get("code") == 0:
            data = result.get("data") or {}
            return self._normalize_batch_status(data)
        self._raise_batch_results_error(result.get("msg", UNKNOWN_ERROR))

    def get_task_status(self, batch_id: str) -> dict[str, Any]:
        """
        Query batch parsing task status.

        Args:
            batch_id: Batch ID.

        Returns:
            Task status info.
        """
        return _run_coroutine_sync(lambda: self.aget_task_status(batch_id))

    @staticmethod
    def _normalize_batch_status(batch_data: dict[str, Any]) -> dict[str, Any]:
        """
        Normalize MinerU batch results response into our API-friendly schema.

        MinerU response example:
        {
          "batch_id": "...",
          "extract_result": [
            {"data_id":"...", "file_name":"...", "state":"waiting-file|running|done|failed", "err_msg":"", ...}
          ]
        }
        """
        extract_result = batch_data.get("extract_result") or []
        if not isinstance(extract_result, list):
            extract_result = []

        total_files = len(extract_result)
        completed_files, failed_files, running_files, first_error = _normalize_batch_state_counters(extract_result)
        status, progress = _normalized_batch_status(
            total_files=total_files,
            completed_files=completed_files,
            failed_files=failed_files,
            running_files=running_files,
        )

        return {
            "status": status,
            "total_files": total_files,
            "completed_files": completed_files,
            "failed_files": failed_files,
            "progress": max(0, min(100, int(progress))),
            "result_url": None,
            "error": first_error,
        }

    @staticmethod
    def _pick_extract_item(
        extract_result: list[dict[str, Any]],
        *,
        data_id: str | None = None,
        filename: str | None = None,
    ) -> dict[str, Any] | None:
        if not extract_result:
            return None

        return (
            _matching_extract_item(extract_result, field_name="data_id", value=data_id)
            or _matching_extract_item(extract_result, field_name="file_name", value=filename)
            or (extract_result[0] if len(extract_result) == 1 and isinstance(extract_result[0], dict) else None)
        )

    async def aget_batch_results(self, batch_id: str) -> dict[str, Any]:
        """Fetch raw MinerU batch results (async)."""
        self._ensure_online_enabled()
        url = f"{self.api_base}/extract-results/batch/{batch_id}"
        result = await self._arequest_json("GET", url, headers=self._get_headers())
        if result.get("code") == 0:
            return result.get("data") or {}
        self._raise_batch_results_error(result.get("msg", UNKNOWN_ERROR))

    def get_batch_results(self, batch_id: str) -> dict[str, Any]:
        """Fetch raw MinerU batch results (sync)."""
        return _run_coroutine_sync(lambda: self.aget_batch_results(batch_id))

    async def await_for_completion(
        self,
        batch_id: str,
        *,
        data_id: str | None = None,
        filename: str | None = None,
        poll_interval: int = 5,
        max_interval: int = 30,
        backoff_factor: float = 1.5,
        jitter: float = 0.2,
    ) -> dict[str, Any]:
        """
        Wait for parsing completion for a single file in a batch.

        Args:
            batch_id: Batch ID.
            data_id: The file's `data_id` used when applying upload URL (recommended).
            filename: Fallback selector when `data_id` is unavailable.
            poll_interval: Poll interval (seconds).

        Returns:
            The matched extract_result item.
        """
        current_interval = max(1, int(poll_interval))

        while True:
            batch = await self.aget_batch_results(batch_id)
            extract_result = batch.get("extract_result") or []
            if not isinstance(extract_result, list):
                extract_result = []

            item = self._pick_extract_item(extract_result, data_id=data_id, filename=filename)
            state = str((item or {}).get("state") or "").lower()

            logger.info("Task %s state=%s (data_id=%s)", batch_id, state or "unknown", data_id or "")

            if state == "done":
                return item or {}
            if state == "failed":
                err = (item or {}).get("err_msg") or UNKNOWN_ERROR
                raise RuntimeError(f"Task {batch_id} failed: {err}")

            # Exponential backoff with jitter (best-effort)
            sleep_for = float(current_interval)
            if jitter and jitter > 0:
                # add +/- jitter
                delta = sleep_for * float(jitter)
                sleep_for = max(0.5, sleep_for - delta)  # lower bound
            await asyncio.sleep(sleep_for)
            current_interval = min(int(max_interval), int(current_interval * float(backoff_factor)))

    def wait_for_completion(
        self,
        batch_id: str,
        *,
        data_id: str | None = None,
        filename: str | None = None,
        timeout: int = 600,
        poll_interval: int = 5,
    ) -> dict[str, Any]:
        async def _run_with_timeout() -> dict[str, Any]:
            try:
                return await asyncio.wait_for(
                    self.await_for_completion(
                        batch_id,
                        data_id=data_id,
                        filename=filename,
                        poll_interval=poll_interval,
                    ),
                    timeout=timeout,
                )
            except TimeoutError as exc:
                raise TimeoutError(f"Task {batch_id} timeout after {timeout} seconds") from exc

        return _run_coroutine_sync(_run_with_timeout)

    async def adownload_result(self, result_url: str) -> str:
        """Download parse result (Markdown, async)."""
        pool = get_http_client_pool()
        resp = await pool.get(result_url, timeout=60.0)
        try:
            return resp.text
        finally:
            try:
                await resp.aclose()
            except Exception as exc:
                logger.debug(MINERU_FALLBACK_LOG_MESSAGE, exc)

    def download_result(self, result_url: str) -> str:
        """
        Download parse result (Markdown).

        Args:
            result_url: Result download URL.

        Returns:
            Markdown content.
        """
        return str(_run_coroutine_sync(lambda: self.adownload_result(result_url)))

    async def adownload_result_zip(self, zip_url: str) -> bytes:
        """Download parse result ZIP bytes (async)."""
        pool = get_http_client_pool()
        resp = await pool.get(zip_url, timeout=300.0)
        try:
            return bytes(resp.content)
        finally:
            try:
                await resp.aclose()
            except Exception as exc:
                logger.debug(MINERU_FALLBACK_LOG_MESSAGE, exc)

    def download_result_zip(self, zip_url: str) -> bytes:
        """Download parse result ZIP bytes (sync)."""
        return bytes(_run_coroutine_sync(lambda: self.adownload_result_zip(zip_url)))

    @staticmethod
    def _extract_markdown_from_zip_bytes(zip_bytes: bytes) -> str:
        """
        Extract markdown text from a MinerU result ZIP (prefers `full.md`).
        """
        zip_file, infos = _zip_safe_entries(zip_bytes)
        with zip_file as zf:
            markdown_infos = _markdown_zip_infos(infos)
            chosen = _preferred_markdown_info(markdown_infos)
            if chosen is None:
                return ""
            with zf.open(chosen, "r") as f:
                raw = f.read()
            return raw.decode("utf-8", errors="ignore").strip()

    def _extract_preview_images_from_zip_bytes(
        self,
        *,
        zip_bytes: bytes,
        markdown: str,
        tenant_id: str,
        account_id: str | None = None,
    ) -> tuple[str, list[dict[str, str]]]:
        """
        MinerU online API returns images inside the result ZIP (e.g. "images/xxx.jpg")
        while Markdown references them with relative paths. For preview endpoints (no
        persisted document id), extract referenced images to:
          uploads/{tenant_id}/images/{uuid}.{ext}
        and rewrite Markdown refs to:
          /api/v1/documents/image/{uuid}
        """
        if not tenant_id or not isinstance(markdown, str) or not markdown:
            return markdown, []

        lowered = markdown.lower()
        if "![" not in lowered and "<img" not in lowered:
            return markdown, []

        images_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        refs = _bounded_preview_refs(markdown)
        if not refs:
            return markdown, []
        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes), "r")
        except Exception:
            return markdown, []

        try:
            extracted, mapping = _preview_image_mapping(
                zip_file=zf,
                refs=refs,
                images_dir=images_dir,
                tenant_id=tenant_id,
                account_id=account_id,
            )
            if mapping:
                markdown = zip_image_processor._replace_image_refs(markdown, mapping)
            return markdown, extracted
        finally:
            try:
                zf.close()
            except Exception as exc:
                logger.debug(MINERU_FALLBACK_LOG_MESSAGE, exc)

    def _documents_from_zip_bytes(
        self,
        *,
        zip_bytes: bytes,
        file_path: Path,
        tenant_id: str | None = None,
        account_id: str | None = None,
        dataset_id: str | None = None,
        document_id: str | None = None,
        parser_name: str = "mineru_local",
        extra_metadata: dict[str, Any] | None = None,
    ) -> list[Document]:
        images_meta: list[dict] = []
        if dataset_id and document_id and settings.MINIO_ENABLED:
            with tempfile.TemporaryDirectory(prefix="mineru_zip_") as tmp_dir:
                tmp_zip_path = Path(tmp_dir) / "result.zip"
                tmp_zip_path.write_bytes(zip_bytes)

                result = zip_image_processor.process_zip_with_images(
                    zip_path=tmp_zip_path,
                    tenant_id=str(tenant_id) if tenant_id else None,
                    dataset_id=str(dataset_id),
                    document_id=str(document_id),
                )
                markdown_content = extract_markdown_response_text(result)
                images_meta = result.get("images") or []
                position_tagged_markdown = extract_position_tagged_markdown_from_zip_path(tmp_zip_path)
        else:
            markdown_content = self._extract_markdown_from_zip_bytes(zip_bytes)
            if tenant_id:
                markdown_content, _preview_images = self._extract_preview_images_from_zip_bytes(
                    zip_bytes=zip_bytes,
                    markdown=markdown_content,
                    tenant_id=str(tenant_id),
                    account_id=str(account_id) if account_id else None,
                )
            position_tagged_markdown = extract_position_tagged_markdown_from_zip_bytes(zip_bytes)

        metadata: dict[str, Any] = {
            "source": file_path.name,
            "file_type": file_path.suffix.lstrip("."),
            "parser": parser_name,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        if position_tagged_markdown:
            metadata["position_tagged_markdown"] = position_tagged_markdown
        if images_meta:
            metadata["images"] = images_meta
            metadata["image_count"] = len(images_meta)

        logger.info("Parse complete. Content length: %s chars", len(markdown_content))
        return [Document(page_content=markdown_content, metadata=metadata)]

    async def aparse_file(
        self,
        file_path: Path,
        data_id: str | None = None,
        *,
        tenant_id: str | None = None,
        account_id: str | None = None,
        dataset_id: str | None = None,
        document_id: str | None = None,
    ) -> list[Document]:
        """
        End-to-end parsing flow (upload → wait → download result), async version.
        """
        self._ensure_online_enabled()

        file_path = Path(file_path)
        data_id = data_id or str(file_path.stem)
        logger.info("Applying upload URL for %s...", file_path.name)
        upload_info = await self.aapply_upload_url(file_path.name, data_id)

        batch_id = upload_info["batch_id"]
        upload_url = upload_info["upload_url"]

        logger.info("Uploading %s...", file_path.name)
        success = await self.aupload_file(file_path, upload_url)
        if not success:
            raise RuntimeError(f"Failed to upload {file_path.name}")

        logger.info("Upload complete. Batch ID: %s", batch_id)
        logger.info("Waiting for parsing completion...")
        item = await self.await_for_completion(
            batch_id,
            data_id=data_id,
            filename=file_path.name,
            poll_interval=5,
        )

        zip_url = (item or {}).get("full_zip_url") or (item or {}).get("zip_url")
        if not zip_url:
            raise RuntimeError("No result ZIP URL in response")

        logger.info("Downloading result ZIP...")
        zip_bytes = await self.adownload_result_zip(str(zip_url))

        images_meta: list[dict] = []
        if dataset_id and document_id and settings.MINIO_ENABLED:
            with tempfile.TemporaryDirectory(prefix="mineru_zip_") as tmp_dir:
                tmp_zip_path = Path(tmp_dir) / "result.zip"
                await asyncio.to_thread(tmp_zip_path.write_bytes, zip_bytes)

                result = await asyncio.to_thread(
                    zip_image_processor.process_zip_with_images,
                    zip_path=tmp_zip_path,
                    tenant_id=str(tenant_id) if tenant_id else None,
                    dataset_id=str(dataset_id),
                    document_id=str(document_id),
                )
                markdown_content = extract_markdown_response_text(result)
                images_meta = result.get("images") or []
        else:
            markdown_content = self._extract_markdown_from_zip_bytes(zip_bytes)
            if tenant_id:
                markdown_content, _preview_images = self._extract_preview_images_from_zip_bytes(
                    zip_bytes=zip_bytes,
                    markdown=markdown_content,
                    tenant_id=str(tenant_id),
                    account_id=str(account_id) if account_id else None,
                )
        position_tagged_markdown = extract_position_tagged_markdown_from_zip_bytes(zip_bytes)

        metadata = {
            "source": file_path.name,
            "file_type": "pdf",
            "parser": "mineru",
            "batch_id": batch_id,
            "data_id": data_id,
            "model_version": self.model_version,
        }
        if position_tagged_markdown:
            metadata["position_tagged_markdown"] = position_tagged_markdown
        if images_meta:
            metadata["images"] = images_meta
            metadata["image_count"] = len(images_meta)
        logger.info("Parse complete. Content length: %s chars", len(markdown_content))
        return [Document(page_content=markdown_content, metadata=metadata)]

    async def aparse_file_local(
        self,
        *,
        file_path: Path,
        dataset_id: str | None = None,
        document_id: str | None = None,
        tenant_id: str | None = None,
        account_id: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[Document]:
        """
        Parse with local MinerU (returns ZIP with Markdown + images), async version.

        - Upload multipart file to local MinerU
        - Download ZIP bytes
        - Write ZIP to temp file, then in to_thread:
          ZIP -> Markdown + image extraction + MinIO upload
        """
        self._refresh_config()
        if not self.local_server_url:
            raise RuntimeError(
                "MinerU local service not configured. Please set MINERU_LOCAL_SERVER_URL, e.g., http://localhost:30001"
            )

        parse_endpoint = f"{self.local_server_url}/file_parse"
        params = params or {}
        backend = _normalize_local_backend(params.get("backend") or self.local_backend)

        data: dict[str, Any] = {
            "lang_list": params.get("lang_list", ["ch"]),
            "backend": backend,
            "parse_method": params.get("parse_method", "auto"),
            "return_md": True,
            "response_format_zip": True,
            "return_images": True,
        }

        if data["backend"] == "vlm-http-client":
            mineru_vl_server = getattr(settings, "MINERU_VL_SERVER", None)
            if mineru_vl_server:
                data["server_url"] = mineru_vl_server

        logger.info("MinerU local parsing started (async): %s", file_path.name)

        pool = get_http_client_pool()
        try:
            # multipart upload (keep file open until request finishes)
            async with aiofiles.open(file_path, "rb") as f:
                file_bytes = await f.read()
            files = {"files": (file_path.name, file_bytes, OCTET_STREAM)}
            resp = await pool.request_with_retry(
                "POST",
                parse_endpoint,
                files=files,
                data=data,
                timeout=300.0,
            )

            try:
                content_type = str(resp.headers.get("Content-Type", "") or "")
                body = resp.content
            finally:
                try:
                    await resp.aclose()
                except Exception as exc:
                    logger.debug(MINERU_FALLBACK_LOG_MESSAGE, exc)

            if ("zip" not in content_type.lower()) and (OCTET_STREAM not in content_type.lower()):
                raise RuntimeError(f"MinerU returned unexpected content type: {content_type}")

            return await asyncio.to_thread(
                self._documents_from_zip_bytes,
                zip_bytes=body,
                file_path=file_path,
                tenant_id=str(tenant_id) if tenant_id else None,
                account_id=str(account_id) if account_id else None,
                dataset_id=str(dataset_id) if dataset_id else None,
                document_id=str(document_id) if document_id else None,
                parser_name="mineru_local",
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("MinerU local parsing failed (async): %s", str(e)[:200])
            raise RuntimeError(f"MinerU local parsing failed: {str(e)}") from e

    def parse_file(
        self,
        file_path: Path,
        data_id: str | None = None,
        *,
        tenant_id: str | None = None,
        account_id: str | None = None,
        dataset_id: str | None = None,
        document_id: str | None = None,
    ) -> list[Document]:
        """
        End-to-end parsing flow (upload → wait → download result).

        Args:
            file_path: Local file path.
            data_id: Custom data ID (optional).

        Returns:
            Parsed LangChain Document list.
        """
        return _run_coroutine_sync(
            lambda: self.aparse_file(
                file_path=file_path,
                data_id=data_id,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=dataset_id,
                document_id=document_id,
            )
        )

    def parse_file_local(
        self,
        file_path: Path,
        dataset_id: str | None = None,
        document_id: str | None = None,
        tenant_id: str | None = None,
        account_id: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[Document]:
        """
        Parse with local MinerU (returns ZIP with Markdown + images).

        Args:
            file_path: Local file path.
            dataset_id: Dataset ID.
            document_id: Document ID.
            params: Parse params.

        Returns:
            Parsed LangChain Documents (images uploaded to MinIO).
        """
        return _run_coroutine_sync(
            lambda: self.aparse_file_local(
                file_path=file_path,
                dataset_id=dataset_id,
                document_id=document_id,
                tenant_id=tenant_id,
                account_id=account_id,
                params=params,
            )
        )


# Global instance
mineru_service = MinerUService()
