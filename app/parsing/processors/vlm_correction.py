from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import httpx
from langchain_core.documents import Document

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


__all__ = [
    "apply_vlm_correction",
    "apply_vlm_correction_async",
    "should_apply_vlm_correction",
]
