"""Shared HTTP response header helpers."""

import re
from urllib.parse import quote

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]+")
_ASCII_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _clean_download_filename(filename: str) -> str:
    raw = _CONTROL_CHARS_RE.sub("_", filename).replace("\\", "_").replace("/", "_")
    cleaned = raw.strip().strip('"').strip("'")
    if not cleaned or cleaned in {".", ".."}:
        return "download"
    return cleaned[:180]


def content_disposition_header(filename: str, *, disposition: str = "attachment") -> str:
    """Encode a safe Unicode filename and its ASCII fallback for HTTP clients."""
    safe_name = _clean_download_filename(filename)
    ascii_name = _ASCII_FILENAME_RE.sub("_", safe_name).strip("._ ")[:180]
    if not ascii_name:
        # A non-ASCII name may have no usable characters for legacy clients.
        ascii_name = "download"
    quoted = quote(safe_name, safe="")
    disposition_type = "inline" if disposition.lower() == "inline" else "attachment"
    return f"{disposition_type}; filename*=UTF-8''{quoted}; filename=\"{ascii_name}\""


def file_response_headers(
    filename: str,
    *,
    disposition: str = "attachment",
    cache_control: str | None = "no-store",
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    headers: dict[str, str] = {
        "Content-Disposition": content_disposition_header(filename, disposition=disposition),
        "X-Content-Type-Options": "nosniff",
    }
    if cache_control:
        headers["Cache-Control"] = cache_control
    if extra:
        headers.update(extra)
    return headers


def set_content_disposition(
    headers: dict[str, str],
    filename: str,
    *,
    disposition: str = "attachment",
) -> dict[str, str]:
    headers["Content-Disposition"] = content_disposition_header(filename, disposition=disposition)
    headers.setdefault("X-Content-Type-Options", "nosniff")
    return headers
