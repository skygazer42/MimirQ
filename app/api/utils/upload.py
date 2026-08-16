"""
Upload helpers shared across API routes.

Centralizes:
- streaming upload-to-disk
- hard size limits
- best-effort cleanup on failure
"""


import contextlib
import hashlib
from pathlib import Path

import aiofiles
from fastapi import HTTPException, UploadFile


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


__all__ = ["save_upload_file", "save_upload_file_with_hash"]


def compute_file_hash(path: Path, *, hash_name: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
    hasher = hashlib.new(hash_name)
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


__all__.append("compute_file_hash")
