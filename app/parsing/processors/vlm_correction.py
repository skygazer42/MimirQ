from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import httpx
from langchain_core.documents import Document

from app.rag.core.logging import get_logger
from app.rag.core.vision_reader import _describe_with_vision_llm


def should_apply_vlm_correction(
    *,
    enabled: bool,
    pdf_quality: dict[str, Any] | None,
    min_table_score: float,
) -> bool:
    if not bool(enabled):
        return False
    raw = (pdf_quality or {}).get("table_quality_score")
    try:
        score = float(raw)
    except Exception:
        return False
    return score < float(min_table_score)


def _render_pdf_page_png(file_path: Path, page_number: int) -> bytes:
    doc = fitz.open(str(file_path))
    try:
        page = doc.load_page(max(0, int(page_number) - 1))
        pix = page.get_pixmap(alpha=False, dpi=144)
        return bytes(pix.tobytes("png"))
    finally:
        doc.close()


def _build_correction_prompt(markdown: str) -> str:
    body = (markdown or "").strip()
    return (
        "You are correcting OCR/parsing markdown for a document page.\n"
        "Use the page image as the source of truth.\n"
        "- Preserve meaning.\n"
        "- Fix table structure, row/column alignment, list numbering, and obvious OCR corruption.\n"
        "- Return Markdown only.\n"
        "- Do not add explanations.\n\n"
        f"Current markdown:\n{body}\n"
    )


async def _correct_markdown_with_vision_async(*, markdown: str, image_bytes: bytes) -> str:
    async with httpx.AsyncClient() as http_client:
        return (await _describe_with_vision_llm(
            http_client=http_client,
            image_bytes=image_bytes,
            prompt=_build_correction_prompt(markdown),
        )).strip()


def _correct_markdown_with_vision(*, markdown: str, image_bytes: bytes) -> str:
    return asyncio.run(_correct_markdown_with_vision_async(markdown=markdown, image_bytes=image_bytes))


def _run_coroutine_sync(factory) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(factory())).result()


async def apply_vlm_correction_async(
    *,
    documents: list[Document] | None,
    file_path: Path,
    max_pages: int = 2,
) -> tuple[list[Document], dict[str, Any]]:
    out: list[Document] = []
    applied_pages: list[int] = []
    remaining = max(0, int(max_pages or 0))

    for doc in list(documents or []):
        meta = dict(doc.metadata or {})
        page_raw = meta.get("page")
        if page_raw is None:
            page_raw = meta.get("page_number")
        try:
            page = int(page_raw or 0)
        except Exception:
            page = 0

        next_doc = doc
        if remaining > 0 and page > 0 and (doc.page_content or "").strip():
            try:
                image_bytes = _render_pdf_page_png(file_path, page)
                corrected = await _correct_markdown_with_vision_async(
                    markdown=doc.page_content or "",
                    image_bytes=image_bytes,
                )
                if corrected:
                    next_meta = dict(meta)
                    next_meta["vlm_correction_applied"] = True
                    next_doc = Document(page_content=corrected, metadata=next_meta, id=getattr(doc, "id", None))
                    applied_pages.append(page)
                    remaining -= 1
            except Exception:
                next_doc = doc

        out.append(next_doc)

    return out, {"applied_pages": applied_pages, "applied": bool(applied_pages)}


def apply_vlm_correction(
    *,
    documents: list[Document] | None,
    file_path: Path,
    max_pages: int = 2,
) -> tuple[list[Document], dict[str, Any]]:
    out: list[Document] = []
    applied_pages: list[int] = []
    remaining = max(0, int(max_pages or 0))

    for doc in list(documents or []):
        meta = dict(doc.metadata or {})
        page_raw = meta.get("page")
        if page_raw is None:
            page_raw = meta.get("page_number")
        try:
            page = int(page_raw or 0)
        except Exception:
            page = 0

        next_doc = doc
        if remaining > 0 and page > 0 and (doc.page_content or "").strip():
            try:
                image_bytes = _render_pdf_page_png(file_path, page)
                corrected = _correct_markdown_with_vision(
                    markdown=doc.page_content or "",
                    image_bytes=image_bytes,
                ).strip()
                if corrected:
                    next_meta = dict(meta)
                    next_meta["vlm_correction_applied"] = True
                    next_doc = Document(page_content=corrected, metadata=next_meta, id=getattr(doc, "id", None))
                    applied_pages.append(page)
                    remaining -= 1
            except Exception:
                next_doc = doc

        out.append(next_doc)

    return out, {"applied_pages": applied_pages, "applied": bool(applied_pages)}


logger = get_logger("parsing.vlm_correction")


@dataclass(frozen=True, slots=True)
class VLMCorrAudit:
    applied: bool
    changed: bool
    pages_attempted: int
    pages_changed: int
    elapsed_ms: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": bool(self.applied),
            "changed": bool(self.changed),
            "pages_attempted": int(self.pages_attempted),
            "pages_changed": int(self.pages_changed),
            "elapsed_ms": int(self.elapsed_ms),
            "error": (str(self.error)[:200] if self.error else None),
        }


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or isinstance(value, bool):
            return float(default)
        f = float(value)
        if f != f:  # NaN
            return float(default)
        return float(f)
    except Exception:
        return float(default)


def _should_correct_pdf(*, pdf_quality: dict[str, Any] | None, min_table_quality: float) -> bool:
    if not isinstance(pdf_quality, dict):
        return True  # No signal -> allow (backend can decide).
    tq = _coerce_float(pdf_quality.get("table_quality_score"), default=1.0)
    return tq < float(min_table_quality)


async def _call_vlm_backend_async(
    *,
    api_url: str,
    markdown: str,
    meta: dict[str, Any] | None,
    timeout_sec: float,
) -> tuple[str, bool, str]:
    """
    Best-effort call to an external correction backend.

    Contract (flexible):
    - POST JSON: {"markdown": "...", "meta": {...}}
    - Response:
      - JSON {"markdown": "..."} OR
      - raw text body (treated as markdown)
    """
    payload = {"markdown": str(markdown or ""), "meta": dict(meta or {})}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                str(api_url).strip(),
                json=payload,
                timeout=float(timeout_sec),
            )
        except Exception as exc:  # noqa: BLE001
            return markdown, False, f"http_failed:{exc.__class__.__name__}"

        if int(resp.status_code) >= 400:
            return markdown, False, f"http_{resp.status_code}"

        content_type = str(resp.headers.get("content-type") or "").lower()
        try:
            if "application/json" in content_type:
                data = resp.json()
                if isinstance(data, dict) and isinstance(data.get("markdown"), str):
                    out = str(data.get("markdown") or "")
                    return out, bool(out.strip() and out.strip() != str(markdown or "").strip()), "ok_json"
            # Fallback: treat response body as markdown text.
            out = resp.text if isinstance(resp.text, str) else str(resp.content or b"", "utf-8", errors="ignore")
            return out, bool(out.strip() and out.strip() != str(markdown or "").strip()), "ok_text"
        except Exception as exc:  # noqa: BLE001
            return markdown, False, f"parse_failed:{exc.__class__.__name__}"


def _call_vlm_backend(
    *,
    api_url: str,
    markdown: str,
    meta: dict[str, Any] | None,
    timeout_sec: float,
) -> tuple[str, bool, str]:
    return _run_coroutine_sync(
        lambda: _call_vlm_backend_async(
            api_url=api_url,
            markdown=markdown,
            meta=meta,
            timeout_sec=timeout_sec,
        )
    )


def maybe_correct_markdown_pages(
    pages: list[str],
    *,
    enabled: bool,
    api_url: str,
    timeout_sec: float = 60.0,
    max_pages: int = 3,
    max_chars: int = 40_000,
    pdf_quality: dict[str, Any] | None = None,
    min_table_quality: float = 0.6,
    meta: dict[str, Any] | None = None,
) -> tuple[list[str], VLMCorrAudit]:
    """
    Correct a list of per-page markdown strings.

    Returns:
      (updated_pages, audit)
    """
    if not enabled:
        return list(pages or []), VLMCorrAudit(
            applied=False,
            changed=False,
            pages_attempted=0,
            pages_changed=0,
            elapsed_ms=0,
            error=None,
        )

    url = str(api_url or "").strip()
    if not url:
        return list(pages or []), VLMCorrAudit(
            applied=False,
            changed=False,
            pages_attempted=0,
            pages_changed=0,
            elapsed_ms=0,
            error="missing_api_url",
        )

    if not _should_correct_pdf(pdf_quality=pdf_quality, min_table_quality=float(min_table_quality)):
        return list(pages or []), VLMCorrAudit(
            applied=False,
            changed=False,
            pages_attempted=0,
            pages_changed=0,
            elapsed_ms=0,
            error="skip_high_table_quality",
        )

    max_pages_i = max(0, int(max_pages or 0))
    max_chars_i = max(0, int(max_chars or 0))
    timeout_f = float(timeout_sec or 60.0)

    out = list(pages or [])
    attempted = 0
    changed = 0
    t0 = time.perf_counter()

    for i, text in enumerate(out):
        if max_pages_i and attempted >= max_pages_i:
            break
        raw = str(text or "")
        if not raw.strip():
            continue
        if max_chars_i and len(raw) > max_chars_i:
            continue

        attempted += 1
        corrected, is_changed, _note = _call_vlm_backend(
            api_url=url,
            markdown=raw,
            meta={**(meta or {}), "page_index": int(i + 1)} if meta is not None else {"page_index": int(i + 1)},
            timeout_sec=timeout_f,
        )
        if is_changed:
            out[i] = corrected
            changed += 1

    elapsed_ms = int(round((time.perf_counter() - t0) * 1000))
    if attempted <= 0:
        return out, VLMCorrAudit(
            applied=False,
            changed=False,
            pages_attempted=0,
            pages_changed=0,
            elapsed_ms=elapsed_ms,
            error="no_pages_eligible",
        )

    return out, VLMCorrAudit(
        applied=True,
        changed=bool(changed > 0),
        pages_attempted=int(attempted),
        pages_changed=int(changed),
        elapsed_ms=int(elapsed_ms),
        error=None,
    )

__all__ = [
    "apply_vlm_correction",
    "apply_vlm_correction_async",
    "maybe_correct_markdown_pages",
    "should_apply_vlm_correction",
    "VLMCorrAudit",
]
