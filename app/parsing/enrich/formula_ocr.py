"""
Formula OCR / LaTeX enrichment (Opt 3).

docs/plans/2026-03-19-document-parsing-optimization.md:
- "公式识别与 LaTeX 转写"

Design constraints:
- Disabled by default; requires an external HTTP backend.
- No heavyweight model deps in-process.
- Best-effort: failures must not crash ingest/preview.
- Security: only read local image files under the origin/asset base dir.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests

from app.rag.core.logging import get_logger

logger = get_logger("parsing.formula_ocr")


_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HTML_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_HTML_IMG_ATTR_RE = re.compile(r"(src|alt)\s*=\s*([\"'])(.*?)\2", re.IGNORECASE)
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")

_FORMULA_HINT_RE = re.compile(r"\b(formula|equation|latex|math|eqn)\b", re.IGNORECASE)
_MINIO_URL_HINT = "/api/v1/documents/image-url/"


def _clean_latex(raw: str, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return ""
    if text.startswith("$$") and text.endswith("$$") and len(text) >= 4:
        text = text[2:-2].strip()
    if text.startswith("$") and text.endswith("$") and len(text) >= 2:
        text = text[1:-1].strip()
    if max_chars > 0 and len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text


def _looks_like_table_row(line: str) -> bool:
    s = (line or "").strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def _extract_md_images(line: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for alt, src in _MD_IMAGE_RE.findall(line or ""):
        out.append((alt or "", src or ""))
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


def _is_formula_candidate(*, alt: str, src: str) -> bool:
    hint = f"{alt or ''} {src or ''}".strip()
    if not hint:
        return False
    if _FORMULA_HINT_RE.search(hint):
        return True
    # Common filename patterns.
    return bool(re.search(r"(formula|equation|math|eqn)", (src or ""), flags=re.IGNORECASE))


def _safe_read_local_image_bytes(*, src: str, origin_path: Path, max_bytes: int) -> tuple[bytes | None, str]:
    raw = str(src or "").strip()
    if not raw:
        return None, "empty_src"
    if raw.startswith("data:"):
        return None, "data_url_unsupported"
    if raw.lower().startswith(("http://", "https://")):
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
        # file:///C:/... -> C:/...
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


def _call_formula_backend(
    *,
    api_url: str,
    image_bytes: bytes,
    filename: str,
    timeout_sec: float,
) -> tuple[str, str]:
    """
    Best-effort formula OCR backend call.

    Contract (flexible):
    - POST multipart form with file field "file"
    - Response:
      - JSON {"latex": "..."} OR {"text": "..."} OR {"output": "..."} OR {"result": "..."}
      - text/*: latex directly
    """
    try:
        resp = requests.post(
            str(api_url).strip(),
            files={"file": (filename or "formula.png", image_bytes, "application/octet-stream")},
            timeout=float(timeout_sec),
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
                for key in ("latex", "text", "output", "result"):
                    val = data.get(key)
                    if isinstance(val, str) and val.strip():
                        return val, "ok_json"
        txt = resp.text if isinstance(resp.text, str) else ""
        if txt.strip():
            return txt, "ok_text"
    except Exception as exc:  # noqa: BLE001
        return "", f"parse_failed:{exc.__class__.__name__}"

    return "", "empty"


@dataclass(frozen=True, slots=True)
class FormulaOcrAudit:
    applied: bool
    formulas_added: int
    images_attempted: int
    images_succeeded: int
    elapsed_ms: int
    backend: str
    error: str | None = None
    formula_elements: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": bool(self.applied),
            "formulas_added": int(self.formulas_added),
            "images_attempted": int(self.images_attempted),
            "images_succeeded": int(self.images_succeeded),
            "elapsed_ms": int(self.elapsed_ms),
            "backend": str(self.backend or ""),
            "error": (str(self.error)[:200] if self.error else None),
            "formula_elements": list(self.formula_elements or []),
        }


def add_formula_latex_blocks(
    markdown: str,
    *,
    origin_path: Path,
    api_url: str,
    timeout_sec: float = 60.0,
    max_images: int = 12,
    max_image_bytes: int = 5_000_000,
    max_latex_chars: int = 2000,
) -> tuple[str, int, FormulaOcrAudit]:
    """
    Insert a `$$ ... $$` LaTeX block after candidate formula images in Markdown.

    This is intentionally conservative:
    - Only processes local image refs within origin_path (or asset_base_dir).
    - Skips code fences and markdown tables.
    - Does not remove the image; it only appends an explicit LaTeX representation.
    """
    raw = str(markdown or "")
    if not raw:
        return "", 0, FormulaOcrAudit(
            applied=False,
            formulas_added=0,
            images_attempted=0,
            images_succeeded=0,
            elapsed_ms=0,
            backend="formula_http",
            error=None,
        )

    url = str(api_url or "").strip()
    if not url:
        return raw, 0, FormulaOcrAudit(
            applied=False,
            formulas_added=0,
            images_attempted=0,
            images_succeeded=0,
            elapsed_ms=0,
            backend="formula_http",
            error="missing_api_url",
        )

    max_images_i = max(0, int(max_images or 0))
    if max_images_i <= 0:
        return raw, 0, FormulaOcrAudit(
            applied=False,
            formulas_added=0,
            images_attempted=0,
            images_succeeded=0,
            elapsed_ms=0,
            backend="formula_http",
            error="max_images<=0",
        )

    t0 = time.perf_counter()
    out_lines: list[str] = []
    in_fence = False
    formulas_added = 0
    images_attempted = 0
    images_succeeded = 0
    formula_elements: list[dict[str, Any]] = []

    lines = raw.splitlines()
    for i, line in enumerate(lines):
        if _FENCE_RE.match(line or ""):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        if in_fence:
            out_lines.append(line)
            continue
        if _looks_like_table_row(line):
            out_lines.append(line)
            continue

        out_lines.append(line)

        if formulas_added >= max_images_i:
            continue

        # Avoid doubling when the next non-empty line already looks like a LaTeX block.
        next_non_empty = ""
        for j in range(i + 1, min(len(lines), i + 4)):
            cand = (lines[j] or "").strip()
            if cand:
                next_non_empty = cand
                break
        if next_non_empty.startswith("$$") or next_non_empty.startswith("$"):
            continue

        images = _extract_md_images(line) + _extract_html_imgs(line)
        if not images:
            continue

        for alt, src in images:
            if formulas_added >= max_images_i:
                break
            if not _is_formula_candidate(alt=alt, src=src):
                continue

            img_bytes, reason = _safe_read_local_image_bytes(
                src=src,
                origin_path=origin_path,
                max_bytes=int(max_image_bytes or 0),
            )
            if img_bytes is None:
                logger.debug("[formula_ocr] skipped image (read=%s) src=%s", reason, str(src or "")[:200])
                continue

            images_attempted += 1
            latex_raw, status = _call_formula_backend(
                api_url=url,
                image_bytes=img_bytes,
                filename=Path(str(src or "formula.png")).name,
                timeout_sec=float(timeout_sec),
            )
            latex = _clean_latex(latex_raw, max_chars=int(max_latex_chars or 0))
            if not latex:
                logger.debug("[formula_ocr] backend returned empty latex (%s)", status)
                continue

            images_succeeded += 1
            formulas_added += 1
            out_lines.append(f"$$ {latex} $$")
            formula_elements.append(
                {
                    "kind": "equation",
                    "text": latex,
                    "attributes": {
                        "source_content_type": "formula_ocr",
                        "source_doc_type": "formula_ocr",
                        "formula_image_alt": str(alt or ""),
                        "formula_image_src": str(src or ""),
                        "formula_backend_status": str(status or ""),
                    },
                }
            )

    elapsed_ms = int(round((time.perf_counter() - t0) * 1000))
    return (
        "\n".join(out_lines).rstrip() + "\n",
        int(formulas_added),
        FormulaOcrAudit(
            applied=True,
            formulas_added=int(formulas_added),
            images_attempted=int(images_attempted),
            images_succeeded=int(images_succeeded),
            elapsed_ms=int(elapsed_ms),
            backend="formula_http",
            error=None,
            formula_elements=formula_elements,
        ),
    )


__all__ = ["FormulaOcrAudit", "add_formula_latex_blocks"]
