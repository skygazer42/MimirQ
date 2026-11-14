"""Save incoming files, normalize source paths, and clean partial transfers."""

import hashlib
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

import anyio
from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)

FILENAME_INVALID_CHARS_DETAIL = "Filename contains invalid characters"
_WINDOWS_DRIVE_LETTER_RE = re.compile(r"^[a-zA-Z]:$")
_UPLOAD_SOURCE_PATH_MAX_LEN = 500
FILE_CLOSE_TIMEOUT_SEC = 5.0


async def cleanup_partial_file(path: Path, *, operation: str) -> None:
    """Remove an incomplete transfer without replacing its original failure."""
    try:
        with anyio.fail_after(FILE_CLOSE_TIMEOUT_SEC, shield=True):
            await anyio.Path(path).unlink(missing_ok=True)
    except OSError as exc:
        # Cleanup must not replace the transfer failure or cancellation.
        logger.warning("Partial %s cleanup failed: error_type=%s", operation, type(exc).__name__)


async def _close_transfer_resources(
    close_callbacks: Sequence[tuple[str, Callable[[], Awaitable[None]]]],
    *,
    primary_error: BaseException | None,
) -> BaseException | None:
    """Close resources in reverse order; cancellation takes priority over ordinary errors."""
    cancelled_error_class = anyio.get_cancelled_exc_class()
    for resource_name, close in reversed(close_callbacks):
        try:
            with anyio.fail_after(FILE_CLOSE_TIMEOUT_SEC, shield=True):
                await close()
        except cancelled_error_class as exc:
            if not isinstance(primary_error, cancelled_error_class):
                primary_error = exc
        except BaseException as exc:  # noqa: BLE001 - Keep the first failure and attempt every remaining close.
            if primary_error is None:
                primary_error = exc
            else:
                logger.warning("Transfer %s close failed: error_type=%s", resource_name, type(exc).__name__)
    return primary_error


async def save_upload_file(
    upload_file: UploadFile,
    destination: Path,
    *,
    max_bytes: int,
    chunk_size: int = 1024 * 1024,
) -> int:
    """Save an upload, close its input and return the written byte count."""
    return await _write_upload_file(upload_file, destination, max_bytes=max_bytes, chunk_size=chunk_size)


async def save_upload_file_with_hash(
    upload_file: UploadFile,
    destination: Path,
    *,
    max_bytes: int,
    chunk_size: int = 1024 * 1024,
    hash_name: str = "sha256",
) -> tuple[int, str]:
    """Save and close an upload, returning its byte count and content hash."""
    hasher = hashlib.new(hash_name)
    size_bytes = await _write_upload_file(
        upload_file, destination, max_bytes=max_bytes, chunk_size=chunk_size, hasher=hasher
    )
    return size_bytes, hasher.hexdigest()


async def _write_upload_file(
    upload_file: UploadFile,
    destination: Path,
    *,
    max_bytes: int,
    chunk_size: int,
    hasher=None,
) -> int:
    total_size = 0
    close_callbacks = [("input", upload_file.close)]
    primary_error: BaseException | None = None
    try:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")
        await anyio.Path(destination.parent).mkdir(parents=True, exist_ok=True)
        output = await anyio.open_file(destination, "wb")
        close_callbacks.append(("output", output.aclose))
        while chunk := await upload_file.read(chunk_size):
            total_size += len(chunk)
            if total_size > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Max size: {max_bytes / 1024 / 1024}MB",
                )
            if hasher is not None:
                hasher.update(chunk)
            await output.write(chunk)
    except BaseException as exc:  # noqa: BLE001 - Cancellation must also close owned resources.
        primary_error = exc

    primary_error = await _close_transfer_resources(close_callbacks, primary_error=primary_error)
    if primary_error is not None:
        await cleanup_partial_file(destination, operation="upload")
        if isinstance(primary_error, OSError):
            raise HTTPException(status_code=500, detail="Failed to save file") from primary_error
        raise primary_error
    return total_size


def compute_file_hash(path: Path, *, hash_name: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    hasher = hashlib.new(hash_name)
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def _assert_upload_filename_has_no_control_chars(raw: str) -> None:
    if "\x7f" in raw or any(ord(ch) < 32 for ch in raw):
        raise HTTPException(status_code=400, detail=FILENAME_INVALID_CHARS_DETAIL)


def normalize_upload_path_parts(filename: str | None) -> list[str]:
    if filename is None:
        return []
    _assert_upload_filename_has_no_control_chars(filename)
    parts = [part.strip() for part in filename.replace("\\", "/").split("/")]
    parts = [part for part in parts if part and part != "."]
    if parts and _WINDOWS_DRIVE_LETTER_RE.fullmatch(parts[0]):
        parts = parts[1:]
    normalized: list[str] = []
    for part in parts:
        if part == "..":
            if normalized:
                normalized.pop()
        else:
            normalized.append(part)
    if len(normalized) == 2 and normalized[0].lower() == "fakepath":
        return normalized[1:]
    return normalized


def normalize_upload_key(filename: str | None) -> str:
    parts = normalize_upload_path_parts(filename)
    if not parts:
        return sanitize_upload_filename(filename)
    return "/".join(parts)[:_UPLOAD_SOURCE_PATH_MAX_LEN]


def sanitize_upload_filename(filename: str | None) -> str:
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    cleaned = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Filename is required")
    if len(cleaned) > 255:
        raise HTTPException(status_code=400, detail="Filename too long (max 255 characters)")
    _assert_upload_filename_has_no_control_chars(cleaned)
    if cleaned in {".", ".."}:
        raise HTTPException(status_code=400, detail=FILENAME_INVALID_CHARS_DETAIL)
    return cleaned
