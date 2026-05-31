"""
Local QR/barcode enrichment for inline markdown images.

Design constraints:
- local only; no network calls
- best-effort and deterministic
- only reads files under the provided origin path
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from PIL import Image as PILImage

from app.parsing.enrich.image_understanding import decode_image_codes, infer_visual_kind_from_pixels

_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HTML_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_HTML_IMG_ATTR_RE = re.compile(r"(src|alt)\s*=\s*([\"'])(.*?)\2", re.IGNORECASE)
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
_MINIO_URL_HINT = "/api/v1/documents/image-url/"


def _extract_md_images(line: str) -> list[tuple[str, str]]:
    return [(alt or "", src or "") for alt, src in _MD_IMAGE_RE.findall(line or "")]


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


def _safe_read_local_image_bytes(*, src: str, origin_path: Path, max_bytes: int) -> tuple[bytes | None, str]:
    raw = str(src or "").strip()
    if not raw:
        return None, "empty_src"
    if raw.startswith("data:"):
        return None, "data_url_unsupported"
    if urlparse(raw).scheme in {"http", "https"}:
        return None, "remote_url_unsupported"
    if _MINIO_URL_HINT in raw:
        return None, "already_minio_url"

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
    else:
        resolved_ref = unquote(resolved_ref)

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
        return None, "path_outside_origin"
    if not path_obj.exists() or not path_obj.is_file():
        return None, "missing_file"
    try:
        if int(path_obj.stat().st_size) > int(max_bytes):
            return None, "too_large"
    except Exception:
        return None, "stat_failed"
    try:
        data = path_obj.read_bytes()
    except Exception:
        return None, "read_failed"
    if len(data) > int(max_bytes):
        return None, "too_large"
    return data, "ok"


@dataclass(frozen=True, slots=True)
class ImageCodeAudit:
    applied: bool
    codes_added: int
    images_attempted: int
    images_succeeded: int
    elapsed_ms: int
    backend: str
    code_elements: list[dict[str, Any]] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": bool(self.applied),
            "codes_added": int(self.codes_added),
            "images_attempted": int(self.images_attempted),
            "images_succeeded": int(self.images_succeeded),
            "elapsed_ms": int(self.elapsed_ms),
            "backend": str(self.backend or ""),
            "code_elements": list(self.code_elements or []),
            "error": (str(self.error)[:200] if self.error else None),
        }


def add_image_code_blocks(
    markdown: str,
    *,
    origin_path: Path,
    max_images: int = 12,
    max_image_bytes: int = 5_000_000,
    max_code_chars: int = 500,
) -> tuple[str, int, ImageCodeAudit]:
    raw = str(markdown or "")
    if not raw:
        return "", 0, ImageCodeAudit(
            applied=False,
            codes_added=0,
            images_attempted=0,
            images_succeeded=0,
            elapsed_ms=0,
            backend="local_decode",
            code_elements=[],
            error=None,
        )

    max_images_i = max(0, int(max_images or 0))
    if max_images_i <= 0:
        return raw, 0, ImageCodeAudit(
            applied=False,
            codes_added=0,
            images_attempted=0,
            images_succeeded=0,
            elapsed_ms=0,
            backend="local_decode",
            code_elements=[],
            error="max_images<=0",
        )

    t0 = time.perf_counter()
    out_lines: list[str] = []
    in_fence = False
    codes_added = 0
    images_attempted = 0
    images_succeeded = 0
    code_elements: list[dict[str, Any]] = []

    lines = raw.splitlines()
    for index, line in enumerate(lines):
        if _FENCE_RE.match(line or ""):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        if in_fence:
            out_lines.append(line)
            continue

        out_lines.append(line)

        if codes_added >= max_images_i:
            continue

        next_non_empty = ""
        for cursor in range(index + 1, min(len(lines), index + 4)):
            candidate = (lines[cursor] or "").strip()
            if candidate:
                next_non_empty = candidate
                break
        if next_non_empty.lower().startswith("image code:"):
            continue

        images = _extract_md_images(line) + _extract_html_imgs(line)
        if not images:
            continue

        for alt, src in images:
            if codes_added >= max_images_i:
                break
            image_bytes, _ = _safe_read_local_image_bytes(
                src=src,
                origin_path=origin_path,
                max_bytes=int(max_image_bytes or 0),
            )
            if image_bytes is None:
                continue
            images_attempted += 1
            try:
                image = PILImage.open(BytesIO(image_bytes))
            except Exception:
                continue
            try:
                code_info = decode_image_codes(image)
                visual_kind = str(code_info.get("visual_kind") or "").strip().lower() if isinstance(code_info, dict) else ""
                if not visual_kind:
                    visual_kind = str(infer_visual_kind_from_pixels(image) or "").strip().lower()
            finally:
                try:
                    image.close()
                except Exception:
                    pass
            if not isinstance(code_info, dict):
                code_info = {}
            code_text = str(code_info.get("text") or "").strip()
            if not code_text and not visual_kind:
                continue
            if max_code_chars > 0 and len(code_text) > max_code_chars:
                code_text = code_text[: max_code_chars - 3].rstrip() + "..."

            images_succeeded += 1
            if code_text:
                codes_added += 1
                out_lines.append(f"Image code: {code_text}")
            element_text = code_text or str(alt or "").strip() or f"{visual_kind or 'image'} image"
            code_elements.append(
                {
                    "kind": "image",
                    "visual_kind": visual_kind or None,
                    "text": element_text,
                    "attributes": {
                        "source_content_type": "image_code" if code_text else "image_understanding",
                        "source_doc_type": "image_code" if code_text else "image",
                        "image_code_text": code_text or None,
                        "image_code_values": list(code_info.get("values") or []),
                        "image_code_src": str(src or ""),
                        "image_code_alt": str(alt or ""),
                        "image_visual_kind_source": "pixel",
                    },
                }
            )

    elapsed_ms = int(round((time.perf_counter() - t0) * 1000))
    return (
        "\n".join(out_lines).rstrip() + "\n",
        int(codes_added),
        ImageCodeAudit(
            applied=True,
            codes_added=int(codes_added),
            images_attempted=int(images_attempted),
            images_succeeded=int(images_succeeded),
            elapsed_ms=int(elapsed_ms),
            backend="local_decode",
            code_elements=code_elements,
            error=None,
        ),
    )


__all__ = ["ImageCodeAudit", "add_image_code_blocks"]
