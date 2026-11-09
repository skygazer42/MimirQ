"""Shared parsing rules for local image references used by enrichment stages."""

import re
from pathlib import Path
from urllib.parse import unquote, urlparse

HTML_IMAGE_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_HTML_IMAGE_ATTR_RE = re.compile(r"(src|alt)\s*=\s*([\"'])(.*?)\2", re.IGNORECASE)


def extract_html_images(line: str) -> list[tuple[str, str]]:
    images: list[tuple[str, str]] = []
    for tag in HTML_IMAGE_TAG_RE.findall(line):
        alt = ""
        src = ""
        for key, _quote, value in _HTML_IMAGE_ATTR_RE.findall(tag):
            normalized_key = key.strip().lower()
            if normalized_key == "alt":
                alt = value
            elif normalized_key == "src":
                src = value
        images.append((alt, src))
    return images


def normalize_local_image_ref(raw: str) -> tuple[str | None, str | None]:
    resolved_ref = raw
    if raw.lower().startswith("file://"):
        parsed = urlparse(raw)
        if str(parsed.scheme).lower() != "file":
            return None, "unsupported_scheme"
        netloc = str(parsed.netloc).strip().lower()
        if netloc and netloc not in {"localhost", "127.0.0.1"}:
            return None, "remote_file_url"
        resolved_ref = unquote(str(parsed.path))
        if not resolved_ref:
            return None, "empty_file_path"
        if re.match(r"^/[a-zA-Z]:/", resolved_ref):
            resolved_ref = resolved_ref[1:]
        return resolved_ref, None
    return unquote(resolved_ref), None


def read_local_image_bytes(path: Path, *, max_bytes: int) -> tuple[bytes | None, str]:
    try:
        if int(path.stat().st_size) > int(max_bytes):
            return None, "too_large"
    except Exception:
        return None, "stat_failed"
    try:
        data = path.read_bytes()
    except Exception:
        return None, "read_failed"
    if len(data) > int(max_bytes):
        return None, "too_large"
    return data, "ok"


def next_non_empty_line(lines: list[str], start: int, *, limit: int = 4) -> str:
    for index in range(start + 1, min(len(lines), start + limit)):
        candidate = lines[index].strip()
        if candidate:
            return candidate
    return ""


__all__ = [
    "HTML_IMAGE_TAG_RE",
    "extract_html_images",
    "next_non_empty_line",
    "normalize_local_image_ref",
    "read_local_image_bytes",
]
