"""
Upload helpers shared across API routes.

Centralizes:
- streaming upload-to-disk
- hard size limits
- best-effort cleanup on failure
"""

import contextlib
import hashlib
import re
from pathlib import Path

import aiofiles
from fastapi import HTTPException, UploadFile

FILENAME_INVALID_CHARS_DETAIL = "Filename contains invalid characters"
_WINDOWS_DRIVE_LETTER_RE = re.compile(r"^[a-zA-Z]:$")
_UPLOAD_SOURCE_PATH_MAX_LEN = 500


def _safe_unlink(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


async def save_upload_file(
    upload_file: UploadFile,
    destination: Path,
    *,
    max_bytes: int,
    chunk_size: int = 1024 * 1024,
) -> int:
    """
    Stream-upload to disk with a hard size limit to avoid large in-memory reads.

    Returns the written size (bytes).
    """
    total_size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with aiofiles.open(destination, "wb") as f:
            while True:
                chunk = await upload_file.read(chunk_size)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Max size: {max_bytes / 1024 / 1024}MB",
                    )
                await f.write(chunk)
        return total_size
    except HTTPException:
        _safe_unlink(destination)
        raise
    except Exception as exc:  # noqa: BLE001
        _safe_unlink(destination)
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(exc)[:200]}") from exc
    finally:
        # Avoid leaking file descriptors for multi-file uploads.
        with contextlib.suppress(Exception):
            await upload_file.close()


async def save_upload_file_with_hash(
    upload_file: UploadFile,
    destination: Path,
    *,
    max_bytes: int,
    chunk_size: int = 1024 * 1024,
    hash_name: str = "sha256",
) -> tuple[int, str]:
    """
    Stream-upload to disk with a hard size limit + compute a content hash (default: sha256).

    Returns (written_size_bytes, hex_digest).
    """
    total_size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        hasher = hashlib.new(hash_name)
        async with aiofiles.open(destination, "wb") as f:
            while True:
                chunk = await upload_file.read(chunk_size)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Max size: {max_bytes / 1024 / 1024}MB",
                    )
                hasher.update(chunk)
                await f.write(chunk)
        return total_size, hasher.hexdigest()
    except HTTPException:
        _safe_unlink(destination)
        raise
    except Exception as exc:  # noqa: BLE001
        _safe_unlink(destination)
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(exc)[:200]}") from exc
    finally:
        # Avoid leaking file descriptors for multi-file uploads.
        with contextlib.suppress(Exception):
            await upload_file.close()


def compute_file_hash(path: Path, *, hash_name: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
    hasher = hashlib.new(hash_name)
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _assert_upload_filename_has_no_control_chars(raw: str) -> None:
    if "\x7f" in raw or any(ord(ch) < 32 for ch in raw):
        raise HTTPException(status_code=400, detail=FILENAME_INVALID_CHARS_DETAIL)


def _split_upload_path_parts(cleaned: str) -> list[str]:
    parts = [p.strip() for p in cleaned.split("/") if p.strip() and p.strip() != "."]
    if parts and _WINDOWS_DRIVE_LETTER_RE.fullmatch(parts[0]):
        return parts[1:]
    return parts


def _collapse_upload_path_parts(parts: list[str]) -> list[str]:
    stack: list[str] = []
    for p in parts:
        if p == "..":
            if stack:
                stack.pop()
            continue
        stack.append(p)
    return stack


def _drop_fakepath_prefix(parts: list[str]) -> list[str]:
    if len(parts) == 2 and parts[0].lower() == "fakepath":
        return [parts[1]]
    return parts


def _normalize_upload_path_parts(filename: str) -> list[str]:
    raw = str(filename or "")
    if not raw:
        return []
    _assert_upload_filename_has_no_control_chars(raw)

    cleaned = raw.replace("\\", "/").strip()
    if not cleaned:
        return []

    parts = _split_upload_path_parts(cleaned)
    if not parts:
        return []

    return _drop_fakepath_prefix(_collapse_upload_path_parts(parts))


def _normalize_upload_key(filename: str) -> str:
    parts = _normalize_upload_path_parts(filename)
    if not parts:
        return _sanitize_filename(filename)
    key = "/".join(parts)
    if len(key) > _UPLOAD_SOURCE_PATH_MAX_LEN:
        key = key[:_UPLOAD_SOURCE_PATH_MAX_LEN]
    return key


def _sanitize_filename(filename: str) -> str:
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    cleaned = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Filename is required")
    if len(cleaned) > 255:
        raise HTTPException(status_code=400, detail="Filename too long (max 255 characters)")
    if "\x7f" in cleaned or any(ord(ch) < 32 for ch in cleaned):
        raise HTTPException(status_code=400, detail=FILENAME_INVALID_CHARS_DETAIL)
    if cleaned in {".", ".."}:
        raise HTTPException(status_code=400, detail=FILENAME_INVALID_CHARS_DETAIL)
    return cleaned


__all__ = ["save_upload_file", "save_upload_file_with_hash", "compute_file_hash", "FILENAME_INVALID_CHARS_DETAIL"]
