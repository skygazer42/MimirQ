import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import httpx
from langchain_core.documents import Document
from pydantic import BaseModel, ConfigDict, ValidationError

from app.infrastructure.config import settings
from app.infrastructure.runtime.async_bridge import run_coroutine_sync as _run_coroutine_sync
from app.rag.ingestion.parsing.utils.scalars import coerce_float, coerce_int
from app.rag.llm.vision_reader import _describe_with_vision_llm

logger = logging.getLogger("parsing.vlm_correction")


class _CorrectionResponse(BaseModel):
    markdown: str
    model_config = ConfigDict(strict=True, extra="ignore")


def should_apply_vlm_correction(
    *,
    enabled: bool,
    pdf_quality: dict[str, Any] | None,
    min_table_score: float,
) -> bool:
    if not enabled:
        return False
    if pdf_quality is None:
        return False
    score = coerce_float(pdf_quality.get("table_quality_score"))
    return score is not None and score < min_table_score


def _render_pdf_page_png(file_path: Path, page_number: int) -> bytes:
    doc = fitz.open(str(file_path))
    try:
        page = doc.load_page(page_number - 1)
        pix = page.get_pixmap(alpha=False, dpi=144)
        return bytes(pix.tobytes("png"))
    finally:
        doc.close()


def _build_correction_prompt(markdown: str) -> str:
    body = markdown.strip()
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
    timeout = float(settings.VISION_LLM_TIMEOUT_SEC)
    async with httpx.AsyncClient(timeout=timeout) as http_client:
        return (
            await _describe_with_vision_llm(
                http_client=http_client,
                image_bytes=image_bytes,
                prompt=_build_correction_prompt(markdown),
            )
        ).strip()


async def apply_vlm_correction_async(
    *,
    documents: list[Document] | None,
    file_path: Path,
    max_pages: int = 2,
) -> tuple[list[Document], dict[str, Any]]:
    out: list[Document] = []
    applied_pages: list[int] = []
    remaining = max(0, max_pages)
    errors: list[str] = []

    for doc in documents if documents is not None else []:
        meta = dict(doc.metadata)
        page_raw = meta.get("page")
        if page_raw is None:
            page_raw = meta.get("page_number")
        page = coerce_int(page_raw)

        next_doc = doc
        if remaining > 0 and page is not None and page > 0 and doc.page_content.strip():
            remaining -= 1
            try:
                image_bytes = await asyncio.to_thread(_render_pdf_page_png, file_path, page)
                corrected = await _correct_markdown_with_vision_async(
                    markdown=doc.page_content,
                    image_bytes=image_bytes,
                )
                if corrected:
                    next_meta = dict(meta)
                    next_meta["vlm_correction_applied"] = True
                    next_doc = Document(page_content=corrected, metadata=next_meta, id=doc.id)
                    applied_pages.append(page)
                else:
                    errors.append(f"page_{page}:empty_response")
            except Exception as exc:
                errors.append(f"page_{page}:{type(exc).__name__}")
                logger.warning("VLM correction failed for page %d", page, exc_info=True)

        out.append(next_doc)

    return out, {"applied_pages": applied_pages, "applied": bool(applied_pages), "errors": errors}


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
            "applied": self.applied,
            "changed": self.changed,
            "pages_attempted": self.pages_attempted,
            "pages_changed": self.pages_changed,
            "elapsed_ms": self.elapsed_ms,
            "error": (self.error[:200] if self.error else None),
        }


def _should_correct_pdf(*, pdf_quality: dict[str, Any] | None, min_table_quality: float) -> bool:
    if pdf_quality is None:
        return True  # No signal -> allow (backend can decide).
    return should_apply_vlm_correction(enabled=True, pdf_quality=pdf_quality, min_table_score=min_table_quality)


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
    payload = {"markdown": markdown, "meta": dict((meta if meta is not None else {}))}
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        try:
            resp = await client.post(
                api_url,
                json=payload,
            )
        except httpx.HTTPError as exc:
            return markdown, False, f"http_failed:{exc.__class__.__name__}"

        if not resp.is_success:
            return markdown, False, f"http_{resp.status_code}"

        content_type = resp.headers.get("content-type", "").lower()
        try:
            if "application/json" in content_type:
                out = _CorrectionResponse.model_validate_json(resp.content).markdown
                note = "ok_json"
            else:
                out = resp.text
                note = "ok_text"
        except ValidationError as exc:
            return markdown, False, f"parse_failed:{exc.__class__.__name__}"
        if not out.strip():
            return markdown, False, "empty_response"
        return out, out.strip() != markdown.strip(), note


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
    out = list(pages)
    if not enabled:
        return out, VLMCorrAudit(
            applied=False,
            changed=False,
            pages_attempted=0,
            pages_changed=0,
            elapsed_ms=0,
            error=None,
        )

    url = api_url.strip()
    if not url:
        return out, VLMCorrAudit(
            applied=False,
            changed=False,
            pages_attempted=0,
            pages_changed=0,
            elapsed_ms=0,
            error="missing_api_url",
        )

    if not _should_correct_pdf(pdf_quality=pdf_quality, min_table_quality=float(min_table_quality)):
        return out, VLMCorrAudit(
            applied=False,
            changed=False,
            pages_attempted=0,
            pages_changed=0,
            elapsed_ms=0,
            error="skip_high_table_quality",
        )

    max_pages_i = max(0, max_pages)
    max_chars_i = max(0, max_chars)

    attempted = 0
    changed = 0
    errors: list[str] = []
    t0 = time.perf_counter()

    for i, raw in enumerate(out):
        if max_pages_i and attempted >= max_pages_i:
            break
        if not raw.strip():
            continue
        if max_chars_i and len(raw) > max_chars_i:
            continue

        attempted += 1
        corrected, is_changed, note = _call_vlm_backend(
            api_url=url,
            markdown=raw,
            meta={**(meta if meta is not None else {}), "page_index": i + 1},
            timeout_sec=timeout_sec,
        )
        if note not in {"ok_json", "ok_text"}:
            errors.append(f"page_{i + 1}:{note}")
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
        pages_attempted=attempted,
        pages_changed=changed,
        elapsed_ms=elapsed_ms,
        error="; ".join(errors)[:200] if errors else None,
    )


__all__ = [
    "apply_vlm_correction_async",
    "maybe_correct_markdown_pages",
    "should_apply_vlm_correction",
    "VLMCorrAudit",
]
