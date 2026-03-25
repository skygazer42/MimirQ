"""
Watermark helpers for preprocessing (Module 2).

This provides two best-effort paths:
1) PDF annotation stripping via PyMuPDF (cheap; no model).
2) External HTTP watermark removal backend (optional; may use Florence-2/LaMa/etc).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests


def strip_pdf_watermark_annotations(
    *,
    input_path: Path,
    output_path: Path,
    sample_pages: int = 3,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Remove watermark/stamp-like annotations from a PDF (best-effort).

    Returns (changed, note, meta).
    """
    meta: dict[str, Any] = {"sample_pages": int(sample_pages or 0)}
    t0 = time.perf_counter()
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # noqa: BLE001
        meta["elapsed_ms"] = int(round((time.perf_counter() - t0) * 1000))
        return False, f"pymupdf_missing:{exc.__class__.__name__}", meta

    doc = None
    removed = 0
    scanned_pages = 0
    try:
        doc = fitz.open(str(input_path))
        n = int(doc.page_count)
        k = max(1, min(int(sample_pages or 0) or 1, n))
        for i in range(k):
            page = doc.load_page(i)
            scanned_pages += 1
            annots = list(page.annots() or [])
            for annot in annots:
                try:
                    typ = getattr(annot, "type", None)
                    name = ""
                    if isinstance(typ, (tuple, list)) and len(typ) >= 2:
                        name = str(typ[1] or "")
                    info = getattr(annot, "info", None) or {}
                    subject = str((info or {}).get("subject") or (info or {}).get("title") or "")
                    hint = f"{name} {subject}".lower()
                    if "watermark" in hint or name.strip().lower() in {"watermark", "stamp"}:
                        page.delete_annot(annot)
                        removed += 1
                except Exception:
                    continue

        if removed <= 0:
            meta["removed"] = 0
            meta["scanned_pages"] = int(scanned_pages)
            meta["elapsed_ms"] = int(round((time.perf_counter() - t0) * 1000))
            return False, "no_watermark_annots", meta

        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(output_path), garbage=4, deflate=True)
        meta["removed"] = int(removed)
        meta["scanned_pages"] = int(scanned_pages)
        meta["elapsed_ms"] = int(round((time.perf_counter() - t0) * 1000))
        return True, f"removed_annots:{removed}", meta
    except Exception as exc:  # noqa: BLE001
        meta["elapsed_ms"] = int(round((time.perf_counter() - t0) * 1000))
        return False, f"strip_failed:{exc.__class__.__name__}", meta
    finally:
        try:
            if doc is not None:
                doc.close()
        except Exception:
            pass


def remove_watermark_via_http(
    *,
    input_path: Path,
    output_path: Path,
    url: str,
    timeout_sec: float,
) -> tuple[bool, str]:
    """
    Generic watermark removal via an external service.

    Contract (best-effort):
    - POST multipart form with file field "file"
    - Response body is treated as the processed file bytes (PDF or image).
    """
    try:
        file_bytes = input_path.read_bytes()
        resp = requests.post(
            str(url).strip(),
            files={"file": (input_path.name, file_bytes, "application/octet-stream")},
            timeout=float(timeout_sec),
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"watermark_http_failed:{exc.__class__.__name__}"

    if int(resp.status_code) >= 400:
        return False, f"watermark_http_{int(resp.status_code)}"
    if not resp.content:
        return False, "watermark_empty_response"

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(resp.content)
        return True, "watermark_ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"watermark_write_failed:{exc.__class__.__name__}"


__all__ = ["remove_watermark_via_http", "strip_pdf_watermark_annotations"]

