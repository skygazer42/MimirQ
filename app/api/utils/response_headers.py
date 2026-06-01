"""Shared HTTP response header helpers."""

from __future__ import annotations

import re
from urllib.parse import quote

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]+")
_ASCII_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _clean_download_filename(filename: str, *, fallback: str = "download") -> str:
    raw = _CONTROL_CHARS_RE.sub("_", str(filename or "")).replace("\\", "_").replace("/", "_")
    cleaned = raw.strip().strip('"').strip("'")
    if not cleaned or cleaned in {".", ".."}:
        cleaned = fallback
    return cleaned[:180] or fallback


def _ascii_download_filename(filename: str, *, fallback: str = "download") -> str:
    cleaned = _ASCII_FILENAME_RE.sub("_", filename).strip("._ ")
    return (cleaned[:180] or fallback)


def content_disposition_header(filename: str, *, disposition: str = "attachment") -> str:
    safe_name = _clean_download_filename(filename)
    ascii_name = _ascii_download_filename(safe_name)
    quoted = quote(safe_name, safe="")
    disp = "inline" if str(disposition).lower() == "inline" else "attachment"
    return f"{disp}; filename*=UTF-8''{quoted}; filename=\"{ascii_name}\""


def download_response_headers(
    filename: str,
    *,
    cache_control: str | None = "no-store",
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    headers: dict[str, str] = {
        "Content-Disposition": content_disposition_header(filename),
        "X-Content-Type-Options": "nosniff",
    }
    if cache_control:
        headers["Cache-Control"] = cache_control
    if extra:
        headers.update(extra)
    return headers


def set_download_content_disposition(headers: dict[str, str], filename: str) -> dict[str, str]:
    headers["Content-Disposition"] = content_disposition_header(filename)
    headers.setdefault("X-Content-Type-Options", "nosniff")
    return headers
