from __future__ import annotations

from pathlib import Path
from typing import Any

from app.parsing.factory import ParserFactory
from app.rag.core.logging import get_logger

logger = get_logger(__name__)


def _empty_pdf_text_sample() -> dict[str, Any]:
    return {"page_count": 0, "samples": [], "is_scanned": False}


def sample_pdf_text_pages(
    pdf_path: Path,
    *,
    max_pages: int = 3,
    max_excerpt_chars: int = 240,
) -> dict[str, Any]:
    """
    Best-effort PDF page text sampling for diagnostics.

    Returns:
      {
        "page_count": int,
        "samples": [{"page": int, "text_chars": int, "excerpt": str}],
        "is_scanned": bool
      }
    """
    try:
        import fitz  # PyMuPDF
    except Exception:
        return _empty_pdf_text_sample()

    path = Path(pdf_path)
    if not path.exists() or not path.is_file():
        return _empty_pdf_text_sample()

    try:
        doc = fitz.open(str(path))
    except Exception:
        return _empty_pdf_text_sample()

    try:
        page_count = int(getattr(doc, "page_count", 0) or 0)
        if page_count <= 0:
            return {"page_count": page_count, "samples": [], "is_scanned": False}

        # Sample first/middle/last pages (1-based) with de-dup.
        idxs: list[int] = [1]
        if page_count >= 3:
            idxs.append(page_count // 2 + 1)
        if page_count >= 2:
            idxs.append(page_count)
        idxs = sorted({i for i in idxs if 1 <= i <= page_count})
        idxs = idxs[: max(0, int(max_pages or 0))] if int(max_pages or 0) > 0 else idxs

        samples: list[dict[str, Any]] = []
        for page_no in idxs:
            try:
                page = doc.load_page(page_no - 1)
                txt = (page.get_text("text") or "").strip()
            except Exception:
                txt = ""

            excerpt = txt[: max(0, int(max_excerpt_chars or 0))] if txt else ""
            samples.append({"page": page_no, "text_chars": len(txt), "excerpt": excerpt})

        # Heuristic: if none of sampled pages has meaningful selectable text, treat as scanned.
        is_scanned = bool(samples) and all(int(s.get("text_chars") or 0) < 20 for s in samples)
        return {"page_count": page_count, "samples": samples, "is_scanned": is_scanned}
    finally:
        try:
            doc.close()
        except Exception as exc:
            logger.debug("Ignoring PDF diagnostics document close failure: %s", exc)


def _filter_available_backends(file_ext: str, *, parser_factory: ParserFactory) -> list[str]:
    if file_ext == ".pdf":
        candidates = [
            "auto",
            "docling",
            "deepseek_ocr",
            "qianfan_ocr",
            "etl4llm",
            "mineru",
            "deepdoc",
            "magicpdf",
            "markitdown",
            "marker",
            "paddle_vl",
            "olmocr",
            "basic",
        ]
    else:
        candidates = [
            "auto",
            "pandoc",
            "markitdown",
            "docling",
            "deepdoc",
            "excel",
            "docx",
            "pptx",
            "html",
            "csv",
            "json",
        ]

    out: list[str] = []
    for backend in candidates:
        try:
            parser_factory.resolve_backend(file_ext, backend)
        except Exception:
            continue
        if backend not in out:
            out.append(backend)
    return out


def suggest_parser_backends(
    file_ext: str,
    *,
    parser_factory: ParserFactory,
    pdf_is_scanned: bool | None = None,
) -> list[str]:
    """
    Suggest a small ordered list of parser backends for user retry actions.
    """
    file_ext0 = str(file_ext or "").strip().lower()
    available = _filter_available_backends(file_ext0, parser_factory=parser_factory)

    if file_ext0 == ".pdf" and pdf_is_scanned is True:
        priority = [
            "auto",
            "deepseek_ocr",
            "qianfan_ocr",
            "etl4llm",
            "mineru",
            "deepdoc",
            "docling",
            "basic",
        ]
    elif file_ext0 == ".pdf":
        priority = ["auto", "docling", "etl4llm", "deepdoc", "markitdown", "basic"]
    else:
        priority = ["auto", "pandoc", "markitdown", "docling", "deepdoc"]

    suggested = [b for b in priority if b in available]
    if not suggested and available:
        suggested = available[:5]
    return suggested[:8]


def build_parse_failure_diagnostics(
    *,
    file_path: Path,
    file_ext: str,
    parser_backend_requested: str,
    parser_backend_resolved: str,
    error_type: str,
    error_message: str,
) -> dict[str, Any]:
    """
    Build a structured diagnostics payload for parse failures (best-effort).
    """
    ext = str(file_ext or "").strip().lower()
    requested = str(parser_backend_requested or "").strip().lower() or "auto"
    resolved = str(parser_backend_resolved or "").strip().lower() or requested

    diag: dict[str, Any] = {
        "file_type": ext,
        "parser_backend_requested": requested,
        "parser_backend": resolved,
        "error_type": str(error_type or ""),
        "error_message": str(error_message or "")[:400],
    }

    parser_factory = ParserFactory()

    pdf_sample: dict[str, Any] | None = None
    pdf_is_scanned: bool | None = None
    if ext == ".pdf":
        pdf_sample = sample_pdf_text_pages(Path(file_path), max_pages=3, max_excerpt_chars=240)
        pdf_is_scanned = bool(pdf_sample.get("is_scanned")) if isinstance(pdf_sample, dict) else None
        diag["pdf_sample"] = pdf_sample

    diag["suggested_backends"] = suggest_parser_backends(ext, parser_factory=parser_factory, pdf_is_scanned=pdf_is_scanned)
    return diag


__all__ = [
    "build_parse_failure_diagnostics",
    "sample_pdf_text_pages",
    "suggest_parser_backends",
]
