"""
Image-level preprocessing (before parsing).

This module sits *before* the parsing subprocess backends. It is meant to:
- Fix obvious orientation issues (EXIF transpose) for standalone images
- Optionally call external services for deskew/dewarp/watermark removal

Scope (per docs/plans/2026-03-19-model-based-deskew-watermark-removal.md):
- Feature-flagged stage in ingest pipeline (disabled by default).
- Lightweight orientation normalization (EXIF for images; rotation metadata for PDFs).
- Optional external HTTP backends for deskew and watermark removal.
- Best-effort PDF watermark annotation stripping (cheap path) before model-based removal.
"""


import re
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz
from PIL import Image

from app.core.config import settings
from app.parsing.preprocess.deskew import deskew_via_http
from app.parsing.preprocess.handwriting_cleanup import cleanup_handwriting_document
from app.parsing.preprocess.orientation import fix_exif_orientation, normalize_pdf_rotation
from app.parsing.preprocess.paddle_doc_preprocess import preprocess_with_paddle_doc
from app.parsing.preprocess.watermark import cleanup_watermark_document, strip_pdf_watermark_annotations
from app.rag.core.logging import get_logger

logger = get_logger("parsing.image_preprocess")


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def _sanitize_run_id(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", text)[:120] or "preprocess"
    return text


def _handwriting_warning(note: str) -> str | None:
    normalized = str(note or "").strip().lower()
    if normalized == "missing_model_path":
        return "handwriting_cleanup_model_missing"
    if normalized.startswith("model_unavailable:"):
        return "handwriting_cleanup_model_unavailable"
    if normalized == "missing_api_url":
        return "handwriting_cleanup_api_url_missing"
    if normalized.startswith(("http_", "write_failed:")):
        return "handwriting_cleanup_backend_failed"
    if normalized.startswith("heuristic_failed:"):
        return "handwriting_cleanup_backend_failed"
    if normalized.startswith("onnx_"):
        return "handwriting_cleanup_backend_failed"
    return None


def _watermark_warning(note: str) -> str | None:
    normalized = str(note or "").strip().lower()
    if normalized == "missing_model_path":
        return "watermark_model_missing"
    if normalized.startswith("model_unavailable:"):
        return "watermark_model_unavailable"
    if normalized == "missing_api_url":
        return "watermark_api_url_missing"
    if normalized in {"no_mask_boxes", "unsupported_input_type"}:
        return None
    if normalized.startswith(("http_", "watermark_http_")):
        return "watermark_backend_failed"
    if normalized.startswith(("onnx_", "watermark_write_failed:", "watermark_empty_response")):
        return "watermark_backend_failed"
    return None


def _paddle_warning(note: str) -> str | None:
    normalized = str(note or "").strip().lower()
    if normalized.startswith("backend_unavailable:"):
        return "paddle_ocr_backend_unavailable"
    if normalized.startswith("predict_failed:"):
        return "paddle_ocr_backend_failed"
    return None


def _run_handwriting_cleanup_stage(
    *,
    current: Path,
    artifact_root: Path,
    output_stem: str,
    warnings: list[str],
) -> "tuple[Path, bool, ImagePreprocessStepLog, dict[str, Any] | None]":
    t0 = time.perf_counter()
    if not bool(getattr(settings, "HANDWRITING_CLEANUP_ENABLED", False)):
        return (
            current,
            False,
            ImagePreprocessStepLog(
                id="handwriting_cleanup",
                applied=False,
                changed=False,
                note="disabled",
                elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
            ),
            None,
        )

    output_path = artifact_root / f"{output_stem}.handwriting{current.suffix.lower()}"
    changed, note, info = cleanup_handwriting_document(
        input_path=current,
        output_path=output_path,
        backend=str(getattr(settings, "HANDWRITING_CLEANUP_BACKEND", "auto") or "auto"),
        model_path=str(getattr(settings, "HANDWRITING_CLEANUP_MODEL_PATH", "") or ""),
        api_url=str(getattr(settings, "HANDWRITING_CLEANUP_API_URL", "") or ""),
        timeout_sec=float(getattr(settings, "HANDWRITING_CLEANUP_TIMEOUT_SEC", 60) or 60),
    )
    warning = _handwriting_warning(note)
    if warning:
        warnings.append(warning)
    return (
        output_path if changed else current,
        bool(changed),
        ImagePreprocessStepLog(
            id="handwriting_cleanup",
            applied=True,
            changed=bool(changed),
            note=note,
            elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
        ),
        info,
    )


def _run_paddle_doc_preprocess_stage(
    *,
    current: Path,
    artifact_root: Path,
    output_stem: str,
    warnings: list[str],
) -> "tuple[Path, bool, ImagePreprocessStepLog, dict[str, Any] | None]":
    t0 = time.perf_counter()
    if not bool(getattr(settings, "PADDLE_OCR_PREPROCESS_ENABLED", False)):
        return (
            current,
            False,
            ImagePreprocessStepLog(
                id="paddle_ocr_preprocess",
                applied=False,
                changed=False,
                note="disabled",
                elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
            ),
            None,
        )

    output_path = artifact_root / f"{output_stem}.paddleocr{current.suffix.lower()}"
    changed, note, info = preprocess_with_paddle_doc(
        input_path=current,
        output_path=output_path,
        backend=str(getattr(settings, "PADDLE_OCR_PREPROCESS_BACKEND", "local") or "local"),
        device=str(getattr(settings, "PADDLE_OCR_PREPROCESS_DEVICE", "cpu") or "cpu"),
        lang=str(getattr(settings, "PADDLE_OCR_PREPROCESS_LANG", "ch") or "ch"),
        use_doc_orientation_classify=bool(getattr(settings, "PADDLE_OCR_USE_DOC_ORIENTATION_CLASSIFY", True)),
        use_doc_unwarping=bool(getattr(settings, "PADDLE_OCR_USE_DOC_UNWARPING", True)),
        use_textline_orientation=bool(getattr(settings, "PADDLE_OCR_USE_TEXTLINE_ORIENTATION", False)),
    )
    warning = _paddle_warning(note)
    if warning:
        warnings.append(warning)
    return (
        output_path if changed else current,
        bool(changed),
        ImagePreprocessStepLog(
            id="paddle_ocr_preprocess",
            applied=True,
            changed=bool(changed),
            note=note,
            elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
        ),
        info,
    )


def _preprocess_pdf_pages_via_raster(
    *,
    input_path: Path,
    output_path: Path,
    document_id: str | None,
    warnings: list[str],
) -> tuple[bool, str, dict[str, Any]]:
    src = fitz.open(str(input_path))
    out = fitz.open()
    changed_any = False
    processed_pages = 0
    try:
        for page_index in range(int(src.page_count or 0)):
            page = src.load_page(page_index)
            pix = page.get_pixmap(alpha=False)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            tmp_in = output_path.parent / f"{input_path.stem}.page-{page_index + 1}.png"
            image.save(tmp_in)

            result = preprocess_image_document(
                input_path=tmp_in,
                document_id=f"{document_id or input_path.stem}-page-{page_index + 1}",
                pdf_quality={"score": 0.0, "is_scanned": True, "page_count": 1},
            )
            warnings.extend(f"pagewise:{warning}" for warning in (result.warnings or []))
            page_img_path = Path(result.output_path)
            with Image.open(page_img_path) as processed:
                buf = BytesIO()
                processed.convert("RGB").save(buf, format="PNG")
                rect = fitz.Rect(0, 0, float(processed.width), float(processed.height))
                out_page = out.new_page(width=rect.width, height=rect.height)
                out_page.insert_image(rect, stream=buf.getvalue())
            changed_any = changed_any or bool(result.changed)
            processed_pages += 1
        if not changed_any:
            return False, "pagewise_no_change", {"backend": "pagewise_raster", "processed_pages": processed_pages}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out.save(str(output_path), garbage=4, deflate=True)
        return True, "pagewise_pdf_rebuilt", {"backend": "pagewise_raster", "processed_pages": processed_pages}
    finally:
        try:
            src.close()
        except Exception as exc:
            logger.debug("Ignoring non-critical image preprocess fallback failure: %s", exc)
        try:
            out.close()
        except Exception as exc:
            logger.debug("Ignoring non-critical image preprocess fallback failure: %s", exc)


@dataclass(frozen=True, slots=True)
class ImagePreprocessStepLog:
    id: str
    applied: bool
    changed: bool
    note: str = ""
    elapsed_ms: int = 0


@dataclass(frozen=True, slots=True)
class ImagePreprocessResult:
    input_path: str
    output_path: str
    changed: bool
    steps: list[ImagePreprocessStepLog]
    warnings: list[str]
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_path": self.input_path,
            "output_path": self.output_path,
            "changed": bool(self.changed),
            "steps": [
                {
                    "id": s.id,
                    "applied": bool(s.applied),
                    "changed": bool(s.changed),
                    "note": s.note,
                    "elapsed_ms": int(s.elapsed_ms or 0),
                }
                for s in (self.steps or [])
            ],
            "warnings": list(self.warnings or []),
            "meta": dict(self.meta or {}),
        }


def preprocess_image_document(
    *,
    input_path: Path,
    document_id: str | None = None,
    pdf_quality: dict[str, Any] | None = None,
) -> ImagePreprocessResult:
    """
    Preprocess a document file before parsing.

    This stage runs before parsing backends and is guarded by feature flags.

    Supported (best-effort):
    - Standalone images: EXIF orientation fix + optional external deskew/watermark removal.
    - PDFs: rotation normalization + optional external deskew/watermark removal + optional annotation stripping.
    """
    input_path = Path(input_path)
    ext = input_path.suffix.lower()
    enabled = bool(getattr(settings, "IMAGE_PREPROCESS_ENABLED", False))

    if not enabled:
        return ImagePreprocessResult(
            input_path=str(input_path),
            output_path=str(input_path),
            changed=False,
            steps=[ImagePreprocessStepLog(id="image_preprocess", applied=False, changed=False, note="disabled")],
            warnings=[],
            meta={"enabled": False},
        )

    warnings: list[str] = []
    steps: list[ImagePreprocessStepLog] = []
    meta: dict[str, Any] = {"enabled": True}

    sample_pages = int(getattr(settings, "PREPROCESS_SAMPLE_PAGES", 3) or 3)
    skip_high_quality = bool(getattr(settings, "PREPROCESS_SKIP_HIGH_QUALITY", True))

    # Best-effort: allow caller to pass pdf_quality for skip logic / meta.
    if isinstance(pdf_quality, dict):
        meta["pdf_quality_score"] = pdf_quality.get("score")
        meta["pdf_is_scanned"] = bool(pdf_quality.get("is_scanned", False))

    if ext == ".pdf":
        pdf_q = dict(pdf_quality) if isinstance(pdf_quality, dict) else None
        if skip_high_quality and pdf_q is None:
            try:
                from app.parsing.quality.scorer import score_pdf_quality

                pdf_q = score_pdf_quality(input_path, sample_pages=sample_pages, use_ocr_validation=False)
                if isinstance(pdf_q, dict):
                    meta["pdf_quality_score"] = pdf_q.get("score")
                    meta["pdf_is_scanned"] = bool(pdf_q.get("is_scanned", False))
            except Exception:
                pdf_q = None

        if skip_high_quality and isinstance(pdf_q, dict):
            score = float(pdf_q.get("score", 0.0) or 0.0)
            is_scanned = bool(pdf_q.get("is_scanned", False))
            if score >= 0.8 and not is_scanned:
                return ImagePreprocessResult(
                    input_path=str(input_path),
                    output_path=str(input_path),
                    changed=False,
                    steps=[
                        ImagePreprocessStepLog(
                            id="pdf_preprocess",
                            applied=False,
                            changed=False,
                            note="skip_high_quality",
                            elapsed_ms=0,
                        )
                    ],
                    warnings=[],
                    meta=meta,
                )

        run_id = _sanitize_run_id(document_id or input_path.stem or "preprocess")
        artifact_root = (input_path.parent / ".mimirq_preprocess" / run_id).absolute()
        artifact_root.mkdir(parents=True, exist_ok=True)

        current = input_path
        changed_any = False

        # Step: PDF rotation normalization (cheap metadata-only fix).
        t0 = time.perf_counter()
        if bool(getattr(settings, "ORIENTATION_ENABLED", False)):
            out_path = artifact_root / f"{input_path.stem}.oriented.pdf"
            changed, note, info = normalize_pdf_rotation(input_path=current, output_path=out_path, sample_pages=sample_pages)
            meta["pdf_rotation"] = info
            if changed:
                current = out_path
                changed_any = True
            steps.append(
                ImagePreprocessStepLog(
                    id="orientation",
                    applied=True,
                    changed=bool(changed),
                    note=note,
                    elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
                )
            )
        else:
            steps.append(
                ImagePreprocessStepLog(
                    id="orientation",
                    applied=False,
                    changed=False,
                    note="disabled",
                    elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
                )
            )

        current, changed, step, info = _run_paddle_doc_preprocess_stage(
            current=current,
            artifact_root=artifact_root,
            output_stem=input_path.stem,
            warnings=warnings,
        )
        if isinstance(info, dict):
            meta["paddle_ocr_preprocess"] = info
        if changed:
            changed_any = True
        steps.append(step)

        # Step: deskew via external backend (optional).
        t1 = time.perf_counter()
        if bool(getattr(settings, "DESKEW_ENABLED", False)):
            backend = str(getattr(settings, "DESKEW_BACKEND", "auto") or "auto").strip().lower()
            url = str(getattr(settings, "DESKEW_PADDLE_URL", "") or "").strip()
            timeout_sec = float(getattr(settings, "DESKEW_TIMEOUT_SEC", 60) or 60)
            deskew_changed = False
            note = "skipped"
            if backend in {"auto", "paddle"} and url:
                out_path = artifact_root / f"{input_path.stem}.deskew.pdf"
                deskew_changed, note = deskew_via_http(
                    input_path=current,
                    output_path=out_path,
                    url=url,
                    timeout_sec=timeout_sec,
                )
                if deskew_changed:
                    current = out_path
                    changed_any = True
            else:
                note = "missing_backend_or_url"
            steps.append(
                ImagePreprocessStepLog(
                    id="deskew",
                    applied=True,
                    changed=bool(deskew_changed),
                    note=note,
                    elapsed_ms=int(round((time.perf_counter() - t1) * 1000)),
                )
            )
        else:
            steps.append(
                ImagePreprocessStepLog(
                    id="deskew",
                    applied=False,
                    changed=False,
                    note="disabled",
                    elapsed_ms=int(round((time.perf_counter() - t1) * 1000)),
                )
            )

        current, changed, step, info = _run_handwriting_cleanup_stage(
            current=current,
            artifact_root=artifact_root,
            output_stem=input_path.stem,
            warnings=warnings,
        )
        if isinstance(info, dict):
            meta["handwriting_cleanup"] = info
        if changed:
            changed_any = True
        steps.append(step)

        # Step: watermark removal (annotation strip + optional external backend).
        if bool(getattr(settings, "WATERMARK_REMOVAL_ENABLED", False)):
            t2 = time.perf_counter()
            if bool(getattr(settings, "WATERMARK_PDF_ANNOT_STRIP_ENABLED", True)):
                out_path = artifact_root / f"{input_path.stem}.dewatermark_annots.pdf"
                changed, note, info = strip_pdf_watermark_annotations(
                    input_path=current,
                    output_path=out_path,
                    sample_pages=sample_pages,
                )
                meta["pdf_watermark_annots"] = info
                if changed:
                    current = out_path
                    changed_any = True
                steps.append(
                    ImagePreprocessStepLog(
                        id="watermark_annots",
                        applied=True,
                        changed=bool(changed),
                        note=note,
                        elapsed_ms=int(round((time.perf_counter() - t2) * 1000)),
                    )
                )
            else:
                steps.append(
                    ImagePreprocessStepLog(
                        id="watermark_annots",
                        applied=False,
                        changed=False,
                        note="disabled",
                        elapsed_ms=int(round((time.perf_counter() - t2) * 1000)),
                    )
                )

            t3 = time.perf_counter()
            api_url = str(getattr(settings, "WATERMARK_REMOVAL_API_URL", "") or "").strip()
            timeout_sec = float(getattr(settings, "WATERMARK_TIMEOUT_SEC", 120) or 120)
            backend = str(getattr(settings, "WATERMARK_REMOVAL_BACKEND", "auto") or "auto").strip().lower() or "auto"
            model_path = str(getattr(settings, "WATERMARK_REMOVAL_MODEL_PATH", "") or "")
            out_path = artifact_root / f"{input_path.stem}.dewatermark.pdf"
            if backend in {"local", "auto"} and str(model_path or "").strip():
                changed, note, info = _preprocess_pdf_pages_via_raster(
                    input_path=current,
                    output_path=out_path,
                    document_id=document_id,
                    warnings=warnings,
                )
            else:
                changed, note, info = cleanup_watermark_document(
                    input_path=current,
                    output_path=out_path,
                    backend=backend,
                    model_path=model_path,
                    api_url=api_url,
                    timeout_sec=timeout_sec,
                )
            if isinstance(info, dict):
                meta["watermark_removal"] = info
            warning = _watermark_warning(note)
            if warning:
                warnings.append(warning)
            if changed:
                current = out_path
                changed_any = True
            steps.append(
                ImagePreprocessStepLog(
                    id="watermark_removal",
                    applied=True,
                    changed=bool(changed),
                    note=note,
                    elapsed_ms=int(round((time.perf_counter() - t3) * 1000)),
                )
            )
        else:
            t2 = time.perf_counter()
            steps.append(
                ImagePreprocessStepLog(
                    id="watermark_removal",
                    applied=False,
                    changed=False,
                    note="disabled",
                    elapsed_ms=int(round((time.perf_counter() - t2) * 1000)),
                )
            )

        if changed_any and current != input_path:
            meta["artifact_dir"] = str(artifact_root.resolve(strict=False))

        return ImagePreprocessResult(
            input_path=str(input_path),
            output_path=str(current),
            changed=bool(changed_any and current != input_path),
            steps=steps,
            warnings=warnings[:50],
            meta=meta,
        )

    if ext not in _IMAGE_EXTS:
        return ImagePreprocessResult(
            input_path=str(input_path),
            output_path=str(input_path),
            changed=False,
            steps=[ImagePreprocessStepLog(id="image_preprocess", applied=False, changed=False, note="unsupported_ext")],
            warnings=[],
            meta=meta,
        )

    run_id = _sanitize_run_id(document_id or input_path.stem or "preprocess")
    artifact_root = (input_path.parent / ".mimirq_preprocess" / run_id).absolute()
    artifact_root.mkdir(parents=True, exist_ok=True)

    current = input_path
    changed_any = False

    # Step: EXIF orientation fix
    t0 = time.perf_counter()
    if bool(getattr(settings, "ORIENTATION_ENABLED", False)):
        out_path = artifact_root / f"{input_path.stem}.oriented{input_path.suffix.lower()}"
        changed, note, info = fix_exif_orientation(input_path=current, output_path=out_path)
        meta["image_orientation"] = info
        if changed:
            current = out_path
            changed_any = True
        steps.append(
            ImagePreprocessStepLog(
                id="orientation",
                applied=True,
                changed=bool(changed),
                note=note,
                elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
            )
        )
    else:
        steps.append(
            ImagePreprocessStepLog(
                id="orientation",
                applied=False,
                changed=False,
                note="disabled",
                elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
            )
        )

    current, changed, step, info = _run_paddle_doc_preprocess_stage(
        current=current,
        artifact_root=artifact_root,
        output_stem=input_path.stem,
        warnings=warnings,
    )
    if isinstance(info, dict):
        meta["paddle_ocr_preprocess"] = info
    if changed:
        changed_any = True
    steps.append(step)

    # Step: deskew
    t1 = time.perf_counter()
    if bool(getattr(settings, "DESKEW_ENABLED", False)):
        backend = str(getattr(settings, "DESKEW_BACKEND", "auto") or "auto").strip().lower()
        url = str(getattr(settings, "DESKEW_PADDLE_URL", "") or "").strip()
        timeout_sec = float(getattr(settings, "DESKEW_TIMEOUT_SEC", 60) or 60)
        deskew_changed = False
        note = "skipped"
        if backend in {"auto", "paddle"} and url:
            out_path = artifact_root / f"{input_path.stem}.deskew{input_path.suffix.lower()}"
            deskew_changed, note = deskew_via_http(
                input_path=current,
                output_path=out_path,
                url=url,
                timeout_sec=timeout_sec,
            )
            if deskew_changed:
                current = out_path
                changed_any = True
        else:
            note = "missing_backend_or_url"
        steps.append(
            ImagePreprocessStepLog(
                id="deskew",
                applied=True,
                changed=bool(deskew_changed),
                note=note,
                elapsed_ms=int(round((time.perf_counter() - t1) * 1000)),
            )
        )
    else:
        steps.append(
            ImagePreprocessStepLog(
                id="deskew",
                applied=False,
                changed=False,
                note="disabled",
                elapsed_ms=int(round((time.perf_counter() - t1) * 1000)),
            )
        )

    current, changed, step, info = _run_handwriting_cleanup_stage(
        current=current,
        artifact_root=artifact_root,
        output_stem=input_path.stem,
        warnings=warnings,
    )
    if isinstance(info, dict):
        meta["handwriting_cleanup"] = info
    if changed:
        changed_any = True
    steps.append(step)

    # Step: watermark removal (optional external backend).
    t2 = time.perf_counter()
    if bool(getattr(settings, "WATERMARK_REMOVAL_ENABLED", False)):
        api_url = str(getattr(settings, "WATERMARK_REMOVAL_API_URL", "") or "").strip()
        timeout_sec = float(getattr(settings, "WATERMARK_TIMEOUT_SEC", 120) or 120)
        backend = str(getattr(settings, "WATERMARK_REMOVAL_BACKEND", "auto") or "auto").strip().lower() or "auto"
        model_path = str(getattr(settings, "WATERMARK_REMOVAL_MODEL_PATH", "") or "")
        out_path = artifact_root / f"{input_path.stem}.dewatermark{input_path.suffix.lower()}"
        changed, note, info = cleanup_watermark_document(
            input_path=current,
            output_path=out_path,
            backend=backend,
            model_path=model_path,
            api_url=api_url,
            timeout_sec=timeout_sec,
        )
        if isinstance(info, dict):
            meta["watermark_removal"] = info
        warning = _watermark_warning(note)
        if warning:
            warnings.append(warning)
        if changed:
            current = out_path
            changed_any = True
        steps.append(
            ImagePreprocessStepLog(
                id="watermark_removal",
                applied=True,
                changed=bool(changed),
                note=note,
                elapsed_ms=int(round((time.perf_counter() - t2) * 1000)),
            )
        )
    else:
        steps.append(
            ImagePreprocessStepLog(
                id="watermark_removal",
                applied=False,
                changed=False,
                note="disabled",
                elapsed_ms=int(round((time.perf_counter() - t2) * 1000)),
            )
        )

    if changed_any and current != input_path:
        meta["artifact_dir"] = str(artifact_root.resolve(strict=False))

    return ImagePreprocessResult(
        input_path=str(input_path),
        output_path=str(current),
        changed=bool(changed_any and current != input_path),
        steps=steps,
        warnings=warnings[:50],
        meta=meta,
    )
