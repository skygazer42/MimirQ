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
from app.parsing.enrich.image_caption import (
    _extract_line_images,
    _looks_like_table_row,
    _next_line_has_caption,
)
from app.parsing.enrich.image_references import normalize_local_image_ref as _normalize_local_image_ref
from app.parsing.enrich.image_references import read_local_image_bytes
from app.rag.core.logging import get_logger

logger = get_logger("parsing.vlm_image_caption")
_IMAGE_CAPTION_PREFIX = "Image caption:"


_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")

_GENERIC_ALT_RE = re.compile(r"^(image|figure|photo|picture|diagram|chart|page\s+\d+\s+image)\b", re.IGNORECASE)


def _clean_caption_text(s: str, *, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", s).strip()
    if not cleaned:
        return ""
    if max_chars > 0 and len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned


def _resolve_origin_image_path(*, src: str, origin_path: Path) -> Path | None:
    resolved_ref, reason = _normalize_local_image_ref(src)
    if reason:
        return None

    base_dir = origin_path.resolve(strict=False)
    if base_dir.is_file():
        base_dir = base_dir.parent

    base_dir_resolved = base_dir.resolve(strict=False)
    path_obj = Path(resolved_ref)
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


def _safe_read_local_image_bytes(*, src: str, origin_path: Path, max_bytes: int) -> bytes | None:
    raw = src.strip()
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
    image_bytes, _reason = read_local_image_bytes(path_obj, max_bytes=max_bytes)
    return image_bytes


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
            "applied": self.applied,
            "captions_added": self.captions_added,
            "images_attempted": self.images_attempted,
            "images_succeeded": self.images_succeeded,
            "elapsed_ms": self.elapsed_ms,
            "backend": self.backend,
            "error": (self.error[:200] if self.error else None),
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


def _filename_caption(src: str, *, max_caption_chars: int) -> str:
    return _clean_caption_text(Path(unquote(src.strip())).name, max_chars=max_caption_chars)


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
        filename=str(Path(unquote(src.strip())).name or "image"),
        timeout_sec=timeout_sec,
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
    if remaining <= 0 or _looks_like_table_row(line) or not line.strip() or _next_line_has_caption(lines, idx):
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
    raw = markdown
    if not raw:
        return _invalid_vlm_result("", error=None)

    url = api_url.strip()
    if not url:
        return _invalid_vlm_result(raw, error="missing_api_url")

    max_images_i = max(0, int(max_images or 0))
    if max_images_i <= 0:
        return _invalid_vlm_result(raw, error="max_images_zero")

    max_bytes = int(
        max_image_bytes
        if isinstance(max_image_bytes, int) and max_image_bytes > 0
        else settings.MAX_INLINE_IMAGE_BYTES or 10_000_000
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

        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
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
        lead = line[:token_start]
        caption_text = _clean_caption_text("; ".join(captions), max_chars=max_caption_chars)
        if caption_text:
            out.append(f"{lead}{prefix0} {caption_text}")

    result = "\n".join(out)
    if ends_with_newline and not result.endswith("\n"):
        result += "\n"

    elapsed_ms = int(round((time.perf_counter() - t0) * 1000))
    audit = VLMImageCaptionAudit(
        applied=added > 0 or attempted > 0,
        captions_added=added,
        images_attempted=attempted,
        images_succeeded=succeeded,
        elapsed_ms=elapsed_ms,
        backend="vlm_http",
        error=None,
    )
    return result, added, audit


__all__ = [
    "VLMImageCaptionAudit",
    "add_vlm_image_captions",
]
