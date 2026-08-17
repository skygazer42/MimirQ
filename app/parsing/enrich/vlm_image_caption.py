"""
VLM-backed inline image captioning.

Design constraints:
- Safe defaults: disabled unless explicitly enabled + API URL configured.
- No heavy model deps in-process: use external HTTP backend only.
- Best-effort: failures must not crash ingest/preview.
"""

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from app.core.async_bridge import run_coroutine_sync as _run_coroutine_sync
from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("parsing.vlm_image_caption")
_IMAGE_CAPTION_PREFIX = "Image caption:"


# Match Markdown inline image: ![alt](src "optional title")
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

# Match reference-style image: ![alt][ref]
_MD_IMAGE_REF_RE = re.compile(r"!\[([^\]]*)\]\[([^\]]+)\]")

# Match a single HTML <img ...> tag.
_HTML_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_HTML_IMG_ATTR_RE = re.compile(r"(src|alt)\s*=\s*([\"'])(.*?)\2", re.IGNORECASE)

_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")

_CAPTION_PREFIXES = ("image caption:", "caption:")

_GENERIC_ALT_RE = re.compile(r"^(image|figure|photo|picture|diagram|chart|page\\s+\\d+\\s+image)\\b", re.IGNORECASE)


def _normalize_caption_check(line: str) -> str:
    s = (line or "").strip()
    while s.startswith(">"):
        s = s[1:].lstrip()
    return s.lower()


def _looks_like_table_row(line: str) -> bool:
    s = (line or "").strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def _clean_caption_text(s: str, *, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", str(s or "")).strip()
    if not cleaned:
        return ""
    if max_chars > 0 and len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned


def _extract_md_images(line: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for alt, src in _MD_IMAGE_RE.findall(line or ""):
        out.append((alt or "", src or ""))
    # Reference-style image doesn't include src; keep alt only.
    for alt, _ref in _MD_IMAGE_REF_RE.findall(line or ""):
        if alt:
            out.append((alt or "", ""))
    return out


def _extract_html_imgs(line: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for tag in _HTML_IMG_TAG_RE.findall(line or ""):
        alt = ""
        src = ""
        for key, _q, val in _HTML_IMG_ATTR_RE.findall(tag):
            k = (key or "").strip().lower()
            if k == "alt":
                alt = val
            elif k == "src":
                src = val
        out.append((alt or "", src or ""))
    return out


def _normalize_local_image_ref(raw: str) -> tuple[str | None, str | None]:
    resolved_ref = raw
    if raw.lower().startswith("file://"):
        parsed = urlparse(raw)
        if str(parsed.scheme or "").lower() != "file":
            return None, "unsupported_scheme"
        netloc = str(parsed.netloc or "").strip().lower()
        if netloc and netloc not in {"localhost", "127.0.0.1"}:
            return None, "remote_file_url"
        resolved_ref = unquote(str(parsed.path or ""))
        if not resolved_ref:
            return None, "empty_file_path"
        if re.match(r"^/[a-zA-Z]:/", resolved_ref):
            resolved_ref = resolved_ref[1:]
        return resolved_ref, None
    return unquote(resolved_ref), None


def _resolve_origin_image_path(*, src: str, origin_path: Path) -> Path | None:
    resolved_ref, reason = _normalize_local_image_ref(src)
    if reason:
        return None

    base_dir = origin_path.resolve(strict=False)
    if base_dir.is_file():
        base_dir = base_dir.parent

    base_dir_resolved = base_dir.resolve(strict=False)
    path_obj = Path(resolved_ref or "")
    if not path_obj.is_absolute():
        path_obj = (base_dir_resolved / path_obj).resolve(strict=False)
    else:
        path_obj = path_obj.resolve(strict=False)

    try:
        path_obj.relative_to(base_dir_resolved)
    except Exception:
        return None
    if not path_obj.exists() or not path_obj.is_file():
        return None
    return path_obj


def _read_local_image_bytes(path_obj: Path, *, max_bytes: int) -> bytes | None:
    try:
        if int(path_obj.stat().st_size) > int(max_bytes):
            return None
    except Exception:
        return None
    try:
        data = path_obj.read_bytes()
    except Exception:
        return None
    if len(data) > int(max_bytes):
        return None
    return data


def _safe_read_local_image_bytes(*, src: str, origin_path: Path, max_bytes: int) -> bytes | None:
    raw = str(src or "").strip()
    if not raw:
        return None
    if raw.startswith("data:"):
        return None
    if urlparse(raw).scheme in {"http", "https"}:
        return None
    if "/api/v1/documents/image-url/" in raw:
        # Already rewritten to MinIO URL (no local file mapping here).
        return None
    path_obj = _resolve_origin_image_path(src=raw, origin_path=origin_path)
    if path_obj is None:
        return None
    return _read_local_image_bytes(path_obj, max_bytes=max_bytes)


async def _call_caption_backend_async(
    *,
    api_url: str,
    image_bytes: bytes,
    filename: str,
    timeout_sec: float,
) -> tuple[str, str]:
    """
    Best-effort caption backend call.

    Contract (flexible):
    - POST multipart form with file field "file"
    - Response:
      - JSON {"caption": "..."} OR {"text": "..."} OR
      - raw text body (treated as caption)
    """
    timeout = float(timeout_sec)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(
                str(api_url).strip(),
                files={"file": (filename or "image", image_bytes, "application/octet-stream")},
            )
        except Exception as exc:  # noqa: BLE001
            return "", f"http_failed:{exc.__class__.__name__}"

        if int(resp.status_code) >= 400:
            return "", f"http_{int(resp.status_code)}"

        content_type = str(resp.headers.get("content-type") or "").lower()
        try:
            if "application/json" in content_type:
                data = resp.json()
                if isinstance(data, dict):
                    for key in ("caption", "text", "output"):
                        val = data.get(key)
                        if isinstance(val, str) and val.strip():
                            return val, "ok_json"
            txt = resp.text if isinstance(resp.text, str) else ""
            if txt.strip():
                return txt, "ok_text"
        except Exception as exc:  # noqa: BLE001
            return "", f"parse_failed:{exc.__class__.__name__}"

        return "", "empty"


def _call_caption_backend(*, api_url: str, image_bytes: bytes, filename: str, timeout_sec: float) -> tuple[str, str]:
    return _run_coroutine_sync(
        lambda: _call_caption_backend_async(
            api_url=api_url,
            image_bytes=image_bytes,
            filename=filename,
            timeout_sec=timeout_sec,
        )
    )


@dataclass(frozen=True, slots=True)
class VLMImageCaptionAudit:
    applied: bool
    captions_added: int
    images_attempted: int
    images_succeeded: int
    elapsed_ms: int
    backend: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": bool(self.applied),
            "captions_added": int(self.captions_added),
            "images_attempted": int(self.images_attempted),
            "images_succeeded": int(self.images_succeeded),
            "elapsed_ms": int(self.elapsed_ms),
            "backend": str(self.backend or ""),
            "error": (str(self.error)[:200] if self.error else None),
        }


def _invalid_vlm_result(
    raw: str,
    *,
    error: str | None,
) -> tuple[str, int, VLMImageCaptionAudit]:
    return (
        raw,
        0,
        VLMImageCaptionAudit(
            applied=False,
            captions_added=0,
            images_attempted=0,
            images_succeeded=0,
            elapsed_ms=0,
            backend="vlm_http",
            error=error,
        ),
    )


def _extract_line_images(line: str) -> tuple[int, list[tuple[str, str]]]:
    token_start = (line or "").find("![")
    if token_start >= 0:
        tail = (line or "")[token_start:]
        tail_wo_images = _MD_IMAGE_RE.sub("", tail)
        tail_wo_images = _MD_IMAGE_REF_RE.sub("", tail_wo_images)
        if (_MD_IMAGE_RE.search(tail) or _MD_IMAGE_REF_RE.search(tail)) and not tail_wo_images.strip():
            return token_start, _extract_md_images(tail)
        return token_start, []

    token_start = (line or "").lower().find("<img")
    if token_start >= 0:
        tail = (line or "")[token_start:]
        if _HTML_IMG_TAG_RE.search(tail) and not _HTML_IMG_TAG_RE.sub("", tail).strip():
            return token_start, _extract_html_imgs(tail)
    return -1, []


def _next_line_has_caption(lines: list[str], idx: int) -> bool:
    next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
    return _normalize_caption_check(next_line).startswith(_CAPTION_PREFIXES)


def _filename_caption(src: str, *, max_caption_chars: int) -> str:
    return _clean_caption_text(Path(unquote(str(src or "").strip())).name, max_chars=max_caption_chars)


def _resolve_vlm_caption(
    *,
    alt: str,
    src: str,
    origin_path: Path,
    api_url: str,
    timeout_sec: float,
    max_bytes: int,
    max_caption_chars: int,
) -> tuple[str, int, int]:
    alt0 = _clean_caption_text(alt, max_chars=max_caption_chars)
    if alt0 and not _GENERIC_ALT_RE.match(alt0):
        return alt0, 0, 0

    image_bytes = _safe_read_local_image_bytes(src=src, origin_path=origin_path, max_bytes=max_bytes)
    if not image_bytes:
        return _filename_caption(src, max_caption_chars=max_caption_chars), 0, 0

    cap_raw, note = _call_caption_backend(
        api_url=api_url,
        image_bytes=image_bytes,
        filename=str(Path(unquote(str(src or "").strip())).name or "image"),
        timeout_sec=float(timeout_sec or 60.0),
    )
    cap = _clean_caption_text(cap_raw, max_chars=max_caption_chars)
    if cap:
        return cap, 1, 1
    logger.debug("VLM caption empty (%s)", note)
    return "", 1, 0


def _resolve_line_captions(
    line: str,
    *,
    lines: list[str],
    idx: int,
    remaining: int,
    origin_path: Path,
    api_url: str,
    timeout_sec: float,
    max_bytes: int,
    max_caption_chars: int,
) -> tuple[int, list[str], int, int]:
    if remaining <= 0 or _looks_like_table_row(line) or not (line or "").strip() or _next_line_has_caption(lines, idx):
        return -1, [], 0, 0

    token_start, images = _extract_line_images(line)
    if not images:
        return token_start, [], 0, 0

    captions: list[str] = []
    attempted = 0
    succeeded = 0
    for alt, src in images:
        if len(captions) >= remaining:
            break
        caption, attempted_inc, succeeded_inc = _resolve_vlm_caption(
            alt=alt,
            src=src,
            origin_path=origin_path,
            api_url=api_url,
            timeout_sec=timeout_sec,
            max_bytes=max_bytes,
            max_caption_chars=max_caption_chars,
        )
        attempted += attempted_inc
        succeeded += succeeded_inc
        if caption:
            captions.append(caption)
    return token_start, captions, attempted, succeeded


def _advance_fence_state(line: str, *, in_fence: bool) -> tuple[bool, bool]:
    if _FENCE_RE.match(line or ""):
        return not in_fence, True
    return in_fence, bool(in_fence)


def add_vlm_image_captions(
    markdown: str,
    *,
    origin_path: Path,
    api_url: str,
    timeout_sec: float = 60.0,
    max_images: int = 20,
    max_image_bytes: int | None = None,
    prefix: str = _IMAGE_CAPTION_PREFIX,
    max_caption_chars: int = 200,
) -> tuple[str, int, VLMImageCaptionAudit]:
    """
    Insert VLM captions after inline images in markdown (best-effort).
    """
    raw = str(markdown or "")
    if not raw:
        return _invalid_vlm_result("", error=None)

    url = str(api_url or "").strip()
    if not url:
        return _invalid_vlm_result(raw, error="missing_api_url")

    max_images_i = max(0, int(max_images or 0))
    if max_images_i <= 0:
        return _invalid_vlm_result(raw, error="max_images_zero")

    max_bytes = int(
        max_image_bytes
        if isinstance(max_image_bytes, int) and max_image_bytes > 0
        else int(getattr(settings, "MAX_INLINE_IMAGE_BYTES", 10_000_000) or 10_000_000)
    )
    max_bytes = max(100_000, max_bytes)

    lines = raw.splitlines()
    ends_with_newline = raw.endswith("\n")

    out: list[str] = []
    added = 0
    attempted = 0
    succeeded = 0
    in_fence = False
    t0 = time.perf_counter()

    for idx, line in enumerate(lines):
        out.append(line)

        in_fence, skip_line = _advance_fence_state(line, in_fence=in_fence)
        if skip_line:
            continue
        if added >= max_images_i:
            continue
        token_start, captions, attempted_inc, succeeded_inc = _resolve_line_captions(
            line,
            lines=lines,
            idx=idx,
            remaining=max_images_i - added,
            origin_path=origin_path,
            api_url=url,
            timeout_sec=float(timeout_sec or 60.0),
            max_bytes=max_bytes,
            max_caption_chars=int(max_caption_chars or 0),
        )
        attempted += attempted_inc
        succeeded += succeeded_inc

        if not captions:
            continue

        added += len(captions)
        prefix0 = str(prefix or _IMAGE_CAPTION_PREFIX).strip() or _IMAGE_CAPTION_PREFIX
        lead = line[:token_start] if token_start is not None and token_start >= 0 else ""
        caption_text = _clean_caption_text("; ".join(captions), max_chars=max_caption_chars)
        if caption_text:
            out.append(f"{lead}{prefix0} {caption_text}")

    result = "\n".join(out)
    if ends_with_newline and not result.endswith("\n"):
        result += "\n"

    elapsed_ms = int(round((time.perf_counter() - t0) * 1000))
    audit = VLMImageCaptionAudit(
        applied=bool(added > 0 or attempted > 0),
        captions_added=int(added),
        images_attempted=int(attempted),
        images_succeeded=int(succeeded),
        elapsed_ms=int(elapsed_ms),
        backend="vlm_http",
        error=None,
    )
    return result, int(added), audit


__all__ = [
    "VLMImageCaptionAudit",
    "add_vlm_image_captions",
]
