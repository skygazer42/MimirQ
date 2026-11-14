"""
Formula OCR / LaTeX enrichment.

Design constraints:
- Disabled by default; requires an external HTTP backend.
- No heavyweight model deps in-process.
- Best-effort: failures must not crash ingest/preview.
- Security: only read local image files under the origin/asset base dir.
"""

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.async_bridge import run_coroutine_sync as _run_coroutine_sync
from app.parsing.enrich.image_references import extract_html_images as _extract_html_imgs
from app.parsing.enrich.image_references import next_non_empty_line as _next_non_empty_line
from app.parsing.enrich.image_references import normalize_local_image_ref as _normalize_local_image_ref
from app.parsing.enrich.image_references import read_local_image_bytes as _read_local_image_bytes
from app.rag.core.logging import get_logger

logger = get_logger("parsing.formula_ocr")


_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")

_FORMULA_HINT_RE = re.compile(r"\b(formula|equation|latex|math|eqn)\b", re.IGNORECASE)
_MINIO_URL_HINT = "/api/v1/documents/image-url/"


def _clean_latex(raw: str, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", raw).strip()
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
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def _is_formula_candidate(*, alt: str, src: str) -> bool:
    hint = f"{alt} {src}".strip()
    if not hint:
        return False
    if _FORMULA_HINT_RE.search(hint):
        return True
    # Common filename patterns.
    return bool(re.search(r"(formula|equation|math|eqn)", src, flags=re.IGNORECASE))


def _resolve_origin_image_path(*, src: str, origin_path: Path) -> tuple[Path | None, str | None]:
    resolved_ref, reason = _normalize_local_image_ref(src)
    if reason:
        return None, reason

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
    except ValueError:
        return None, "path_outside_origin"
    if not path_obj.exists() or not path_obj.is_file():
        return None, "missing_file"
    return path_obj, None


def _safe_read_local_image_bytes(*, src: str, origin_path: Path, max_bytes: int) -> tuple[bytes | None, str]:
    raw = src.strip()
    if not raw:
        return None, "empty_src"
    if raw.startswith("data:"):
        return None, "data_url_unsupported"
    if urlparse(raw).scheme in {"http", "https"}:
        return None, "remote_url_unsupported"
    if _MINIO_URL_HINT in raw:
        return None, "already_minio_url"
    path_obj, reason = _resolve_origin_image_path(src=raw, origin_path=origin_path)
    if path_obj is None:
        return None, str(reason or "missing_file")
    return _read_local_image_bytes(path_obj, max_bytes=max_bytes)


async def _call_formula_backend_async(
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
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        try:
            resp = await client.post(
                api_url,
                files={"file": (filename or "formula.png", image_bytes, "application/octet-stream")},
            )
        except httpx.RequestError as exc:
            return "", f"http_failed:{exc.__class__.__name__}"

        if resp.status_code >= 400:
            return "", f"http_{resp.status_code}"

        content_type = str(resp.headers.get("content-type") or "").lower()
        try:
            if "application/json" in content_type:
                data = resp.json()
                if isinstance(data, dict):
                    for key in ("latex", "text", "output", "result"):
                        val = data.get(key)
                        if isinstance(val, str) and val.strip():
                            return val, "ok_json"
            txt = resp.text
            if txt.strip():
                return txt, "ok_text"
        except ValueError as exc:
            return "", f"parse_failed:{exc.__class__.__name__}"

        return "", "empty"


def _call_formula_backend(
    *,
    api_url: str,
    image_bytes: bytes,
    filename: str,
    timeout_sec: float,
) -> tuple[str, str]:
    return _run_coroutine_sync(
        lambda: _call_formula_backend_async(
            api_url=api_url,
            image_bytes=image_bytes,
            filename=filename,
            timeout_sec=timeout_sec,
        )
    )


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
            "applied": self.applied,
            "formulas_added": self.formulas_added,
            "images_attempted": self.images_attempted,
            "images_succeeded": self.images_succeeded,
            "elapsed_ms": self.elapsed_ms,
            "backend": self.backend,
            "error": (self.error[:200] if self.error else None),
            "formula_elements": list(self.formula_elements or []),
        }


def _extract_formula_element(
    *,
    alt: str,
    src: str,
    origin_path: Path,
    max_image_bytes: int,
    api_url: str,
    timeout_sec: float,
    max_latex_chars: int,
) -> tuple[dict[str, Any] | None, int, int]:
    if not _is_formula_candidate(alt=alt, src=src):
        return None, 0, 0

    img_bytes, reason = _safe_read_local_image_bytes(
        src=src,
        origin_path=origin_path,
        max_bytes=max_image_bytes,
    )
    if img_bytes is None:
        logger.debug("[formula_ocr] skipped image (read=%s) src=%s", reason, src[:200])
        return None, 0, 0

    latex_raw, status = _call_formula_backend(
        api_url=api_url,
        image_bytes=img_bytes,
        filename=Path(src).name,
        timeout_sec=timeout_sec,
    )
    latex = _clean_latex(latex_raw, max_chars=max_latex_chars)
    if not latex:
        logger.debug("[formula_ocr] backend returned empty latex (%s)", status)
        return None, 1, 0

    return (
        {
            "latex": latex,
            "element": {
                "kind": "equation",
                "text": latex,
                "attributes": {
                    "source_content_type": "formula_ocr",
                    "source_doc_type": "formula_ocr",
                    "formula_image_alt": alt,
                    "formula_image_src": src,
                    "formula_backend_status": status,
                },
            },
        },
        1,
        1,
    )


def _extract_formula_elements_for_line(
    line: str,
    *,
    lines: list[str],
    index: int,
    remaining: int,
    origin_path: Path,
    max_image_bytes: int,
    api_url: str,
    timeout_sec: float,
    max_latex_chars: int,
) -> tuple[list[dict[str, Any]], int, int]:
    if remaining <= 0 or _next_non_empty_line(lines, index).startswith("$"):
        return [], 0, 0

    extracted: list[dict[str, Any]] = []
    attempted = 0
    succeeded = 0
    for alt, src in _MD_IMAGE_RE.findall(line) + _extract_html_imgs(line):
        if len(extracted) >= remaining:
            break
        element, attempted_inc, succeeded_inc = _extract_formula_element(
            alt=alt,
            src=src,
            origin_path=origin_path,
            max_image_bytes=max_image_bytes,
            api_url=api_url,
            timeout_sec=timeout_sec,
            max_latex_chars=max_latex_chars,
        )
        attempted += attempted_inc
        succeeded += succeeded_inc
        if element is not None:
            extracted.append(element)
    return extracted, attempted, succeeded


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
    raw = markdown
    if not raw:
        return (
            "",
            0,
            FormulaOcrAudit(
                applied=False,
                formulas_added=0,
                images_attempted=0,
                images_succeeded=0,
                elapsed_ms=0,
                backend="formula_http",
                error=None,
            ),
        )

    url = api_url.strip()
    if not url:
        return (
            raw,
            0,
            FormulaOcrAudit(
                applied=False,
                formulas_added=0,
                images_attempted=0,
                images_succeeded=0,
                elapsed_ms=0,
                backend="formula_http",
                error="missing_api_url",
            ),
        )

    max_images_i = max(0, int(max_images or 0))
    if max_images_i <= 0:
        return (
            raw,
            0,
            FormulaOcrAudit(
                applied=False,
                formulas_added=0,
                images_attempted=0,
                images_succeeded=0,
                elapsed_ms=0,
                backend="formula_http",
                error="max_images<=0",
            ),
        )

    t0 = time.perf_counter()
    image_byte_limit = int(max_image_bytes or 0)
    request_timeout = float(timeout_sec)
    latex_limit = int(max_latex_chars or 0)
    out_lines: list[str] = []
    in_fence = False
    formulas_added = 0
    images_attempted = 0
    images_succeeded = 0
    formula_elements: list[dict[str, Any]] = []

    lines = raw.splitlines()
    for i, line in enumerate(lines):
        if _FENCE_RE.match(line):
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

        extracted, attempted, succeeded = _extract_formula_elements_for_line(
            line,
            lines=lines,
            index=i,
            remaining=max_images_i - formulas_added,
            origin_path=origin_path,
            max_image_bytes=image_byte_limit,
            api_url=url,
            timeout_sec=request_timeout,
            max_latex_chars=latex_limit,
        )
        images_attempted += attempted
        images_succeeded += succeeded
        for element in extracted:
            formulas_added += 1
            out_lines.append(f"$$ {element['latex']} $$")
            formula_elements.append(element["element"])

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
