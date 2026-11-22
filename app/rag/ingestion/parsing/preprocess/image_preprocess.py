"""
Image-level preprocessing (before parsing).

This module sits *before* the parsing subprocess backends. It is meant to:
- Fix obvious orientation issues (EXIF transpose) for standalone images
- Optionally call external services for deskew/dewarp/watermark removal

Scope:
- Feature-flagged stage in ingest pipeline (disabled by default).
- Lightweight orientation normalization (EXIF for images; rotation metadata for PDFs).
- Optional external HTTP backends for deskew and watermark removal.
- Best-effort PDF watermark annotation stripping (cheap path) before model-based removal.
"""

import logging
import time
from contextlib import closing
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import fitz
from PIL import Image

from app.infrastructure.config import settings
from app.rag.ingestion.parsing.preprocess.deskew import deskew_via_http
from app.rag.ingestion.parsing.preprocess.handwriting_cleanup import cleanup_handwriting_document
from app.rag.ingestion.parsing.preprocess.orientation import fix_exif_orientation, normalize_pdf_rotation
from app.rag.ingestion.parsing.preprocess.paddle_doc_preprocess import preprocess_with_paddle_doc
from app.rag.ingestion.parsing.preprocess.watermark import cleanup_watermark_document, strip_pdf_watermark_annotations
from app.rag.ingestion.parsing.utils.artifact_normalizer import sanitize_artifact_run_id

logger = logging.getLogger("parsing.image_preprocess")


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def _handwriting_warning(note: str) -> str | None:
    normalized = note.strip().lower()
    if normalized == "missing_model_path":
        return "handwriting_cleanup_model_missing"
    if normalized.startswith("model_unavailable:"):
        return "handwriting_cleanup_model_unavailable"
    if normalized == "missing_api_url":
        return "handwriting_cleanup_api_url_missing"
    if normalized.startswith(("http_", "write_failed:", "read_failed:")) or normalized in {
        "empty_response",
        "unsupported_backend",
    }:
        return "handwriting_cleanup_backend_failed"
    if normalized.startswith("heuristic_failed:"):
        return "handwriting_cleanup_backend_failed"
    if normalized.startswith("onnx_"):
        return "handwriting_cleanup_backend_failed"
    return None


def _watermark_warning(note: str) -> str | None:
    normalized = note.strip().lower()
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
    if normalized.startswith(
        ("onnx_", "watermark_write_failed:", "watermark_empty_response", "heuristic_failed:", "strip_failed:")
    ):
        return "watermark_backend_failed"
    return None


def _paddle_warning(note: str) -> str | None:
    normalized = note.strip().lower()
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
    if not settings.HANDWRITING_CLEANUP_ENABLED:
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
        backend=settings.HANDWRITING_CLEANUP_BACKEND,
        model_path=settings.HANDWRITING_CLEANUP_MODEL_PATH,
        api_url=settings.HANDWRITING_CLEANUP_API_URL,
        timeout_sec=settings.HANDWRITING_CLEANUP_TIMEOUT_SEC,
    )
    warning = _handwriting_warning(note)
    if warning:
        warnings.append(warning)
    return (
        output_path if changed else current,
        changed,
        ImagePreprocessStepLog(
            id="handwriting_cleanup",
            applied=True,
            changed=changed,
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
    if not settings.PADDLE_OCR_PREPROCESS_ENABLED:
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
        backend=settings.PADDLE_OCR_PREPROCESS_BACKEND,
        device=settings.PADDLE_OCR_PREPROCESS_DEVICE,
        lang=settings.PADDLE_OCR_PREPROCESS_LANG,
        use_doc_orientation_classify=settings.PADDLE_OCR_USE_DOC_ORIENTATION_CLASSIFY,
        use_doc_unwarping=settings.PADDLE_OCR_USE_DOC_UNWARPING,
        use_textline_orientation=settings.PADDLE_OCR_USE_TEXTLINE_ORIENTATION,
    )
    warning = _paddle_warning(note)
    if warning:
        warnings.append(warning)
    return (
        output_path if changed else current,
        changed,
        ImagePreprocessStepLog(
            id="paddle_ocr_preprocess",
            applied=True,
            changed=changed,
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
    changed_any = False
    processed_pages = 0
    with (
        TemporaryDirectory(prefix="mimirq_pages_", dir=output_path.parent) as scratch,
        fitz.open(str(input_path)) as source,
        fitz.open() as output,
    ):
        for page_index in range(source.page_count):
            page = source.load_page(page_index)
            pixmap = page.get_pixmap(alpha=False)
            temporary_input = Path(scratch) / f"{input_path.stem}.page-{page_index + 1}.png"
            with closing(Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)) as image:
                image.save(temporary_input)
            result = preprocess_image_document(
                input_path=temporary_input,
                document_id=f"{document_id or input_path.stem}-page-{page_index + 1}",
                pdf_quality={"score": 0.0, "is_scanned": True, "page_count": 1},
            )
            warnings.extend(f"pagewise:{warning}" for warning in result.warnings)
            processed_pages += 1
            if not result.changed:
                output.insert_pdf(source, from_page=page_index, to_page=page_index)
                continue
            with (
                closing(Image.open(result.output_path)) as processed,
                closing(processed.convert("RGB")) as rgb,
                BytesIO() as buffer,
            ):
                rgb.save(buffer, format="PNG")
                rectangle = fitz.Rect(0, 0, float(processed.width), float(processed.height))
                output_page = output.new_page(width=rectangle.width, height=rectangle.height)
                output_page.insert_image(rectangle, stream=buffer.getvalue())
            changed_any = True
        if changed_any:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output.save(str(output_path), garbage=4, deflate=True)
    note = "pagewise_pdf_rebuilt" if changed_any else "pagewise_no_change"
    return changed_any, note, {"backend": "pagewise_raster", "processed_pages": processed_pages}


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
            "changed": self.changed,
            "steps": [
                {
                    "id": step.id,
                    "applied": step.applied,
                    "changed": step.changed,
                    "note": step.note,
                    "elapsed_ms": step.elapsed_ms,
                }
                for step in self.steps
            ],
            "warnings": list(self.warnings),
            "meta": dict(self.meta),
        }


def _disabled_preprocess_result(input_path: Path) -> ImagePreprocessResult:
    return ImagePreprocessResult(
        input_path=str(input_path),
        output_path=str(input_path),
        changed=False,
        steps=[ImagePreprocessStepLog(id="image_preprocess", applied=False, changed=False, note="disabled")],
        warnings=[],
        meta={"enabled": False},
    )


def _unsupported_preprocess_result(input_path: Path, *, meta: dict[str, Any]) -> ImagePreprocessResult:
    return ImagePreprocessResult(
        input_path=str(input_path),
        output_path=str(input_path),
        changed=False,
        steps=[ImagePreprocessStepLog(id="image_preprocess", applied=False, changed=False, note="unsupported_ext")],
        warnings=[],
        meta=meta,
    )


def _high_quality_pdf_skip_result(input_path: Path, *, meta: dict[str, Any]) -> ImagePreprocessResult:
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


def _artifact_root(input_path: Path, *, document_id: str | None) -> Path:
    run_id = sanitize_artifact_run_id(document_id or input_path.stem, fallback="preprocess")
    parent = input_path.parent.resolve(strict=False) / ".mimirq_preprocess"
    root = (parent / run_id).resolve(strict=False)
    if root.parent != parent:
        raise ValueError("Image preprocessing artifacts require a direct child directory")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _append_orientation_step(
    *,
    current: Path,
    artifact_root: Path,
    input_path: Path,
    sample_pages: int,
    meta: dict[str, Any],
    steps: list[ImagePreprocessStepLog],
    is_pdf: bool,
) -> tuple[Path, bool]:
    t0 = time.perf_counter()
    if not settings.ORIENTATION_ENABLED:
        steps.append(
            ImagePreprocessStepLog(
                id="orientation",
                applied=False,
                changed=False,
                note="disabled",
                elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
            )
        )
        return current, False

    if is_pdf:
        out_path = artifact_root / f"{input_path.stem}.oriented.pdf"
        changed, note, info = normalize_pdf_rotation(
            input_path=current, output_path=out_path, sample_pages=sample_pages
        )
        meta["pdf_rotation"] = info
    else:
        out_path = artifact_root / f"{input_path.stem}.oriented{input_path.suffix.lower()}"
        changed, note, info = fix_exif_orientation(input_path=current, output_path=out_path)
        meta["image_orientation"] = info
    steps.append(
        ImagePreprocessStepLog(
            id="orientation",
            applied=True,
            changed=bool(changed),
            note=note,
            elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
        )
    )
    return (out_path if changed else current), bool(changed)


def _append_deskew_step(
    *,
    current: Path,
    artifact_root: Path,
    input_path: Path,
    steps: list[ImagePreprocessStepLog],
    is_pdf: bool,
) -> tuple[Path, bool]:
    t0 = time.perf_counter()
    if not settings.DESKEW_ENABLED:
        steps.append(
            ImagePreprocessStepLog(
                id="deskew",
                applied=False,
                changed=False,
                note="disabled",
                elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
            )
        )
        return current, False

    backend = settings.DESKEW_BACKEND.strip().lower()
    url = settings.DESKEW_PADDLE_URL.strip()
    timeout_sec = settings.DESKEW_TIMEOUT_SEC
    note = "missing_backend_or_url"
    changed = False
    if backend in {"auto", "paddle"} and url:
        suffix = ".pdf" if is_pdf else input_path.suffix.lower()
        out_path = artifact_root / f"{input_path.stem}.deskew{suffix}"
        changed, note = deskew_via_http(
            input_path=current,
            output_path=out_path,
            url=url,
            timeout_sec=timeout_sec,
        )
        current = out_path if changed else current
    steps.append(
        ImagePreprocessStepLog(
            id="deskew",
            applied=True,
            changed=bool(changed),
            note=note if changed or note else "skipped",
            elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
        )
    )
    return current, bool(changed)


def _append_pdf_watermark_steps(
    *,
    current: Path,
    artifact_root: Path,
    input_path: Path,
    document_id: str | None,
    sample_pages: int,
    warnings: list[str],
    steps: list[ImagePreprocessStepLog],
    meta: dict[str, Any],
) -> tuple[Path, bool]:
    if not settings.WATERMARK_REMOVAL_ENABLED:
        t0 = time.perf_counter()
        steps.append(
            ImagePreprocessStepLog(
                id="watermark_removal",
                applied=False,
                changed=False,
                note="disabled",
                elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
            )
        )
        return current, False

    changed_any = False
    t0 = time.perf_counter()
    if settings.WATERMARK_PDF_ANNOT_STRIP_ENABLED:
        annots_out = artifact_root / f"{input_path.stem}.dewatermark_annots.pdf"
        changed, note, info = strip_pdf_watermark_annotations(
            input_path=current,
            output_path=annots_out,
            sample_pages=sample_pages,
        )
        meta["pdf_watermark_annots"] = info
        if changed:
            current = annots_out
            changed_any = True
        steps.append(
            ImagePreprocessStepLog(
                id="watermark_annots",
                applied=True,
                changed=bool(changed),
                note=note,
                elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
            )
        )
    else:
        steps.append(
            ImagePreprocessStepLog(
                id="watermark_annots",
                applied=False,
                changed=False,
                note="disabled",
                elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
            )
        )

    t1 = time.perf_counter()
    api_url = settings.WATERMARK_REMOVAL_API_URL.strip()
    timeout_sec = settings.WATERMARK_TIMEOUT_SEC
    backend = settings.WATERMARK_REMOVAL_BACKEND.strip().lower()
    model_path = settings.WATERMARK_REMOVAL_MODEL_PATH
    out_path = artifact_root / f"{input_path.stem}.dewatermark.pdf"
    if backend in {"local", "auto"} and model_path.strip():
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
            elapsed_ms=int(round((time.perf_counter() - t1) * 1000)),
        )
    )
    return current, changed_any


def _append_image_watermark_step(
    *,
    current: Path,
    artifact_root: Path,
    input_path: Path,
    warnings: list[str],
    steps: list[ImagePreprocessStepLog],
    meta: dict[str, Any],
) -> tuple[Path, bool]:
    t0 = time.perf_counter()
    if not settings.WATERMARK_REMOVAL_ENABLED:
        steps.append(
            ImagePreprocessStepLog(
                id="watermark_removal",
                applied=False,
                changed=False,
                note="disabled",
                elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
            )
        )
        return current, False

    api_url = settings.WATERMARK_REMOVAL_API_URL.strip()
    timeout_sec = settings.WATERMARK_TIMEOUT_SEC
    backend = settings.WATERMARK_REMOVAL_BACKEND.strip().lower()
    model_path = settings.WATERMARK_REMOVAL_MODEL_PATH
    out_path = artifact_root / f"{input_path.stem}.dewatermark{input_path.suffix.lower()}"
    changed, note, info = cleanup_watermark_document(
        input_path=current,
        output_path=out_path,
        backend=backend,
        model_path=model_path,
        api_url=api_url,
        timeout_sec=timeout_sec,
    )
    meta["watermark_removal"] = info
    warning = _watermark_warning(note)
    if warning:
        warnings.append(warning)
    if changed:
        current = out_path
    steps.append(
        ImagePreprocessStepLog(
            id="watermark_removal",
            applied=True,
            changed=bool(changed),
            note=note,
            elapsed_ms=int(round((time.perf_counter() - t0) * 1000)),
        )
    )
    return current, bool(changed)


def _finalize_preprocess_result(
    *,
    input_path: Path,
    current: Path,
    changed_any: bool,
    artifact_root: Path,
    steps: list[ImagePreprocessStepLog],
    warnings: list[str],
    meta: dict[str, Any],
) -> ImagePreprocessResult:
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


def _preprocess_document(
    *,
    input_path: Path,
    document_id: str | None,
    sample_pages: int,
    meta: dict[str, Any],
    warnings: list[str],
    steps: list[ImagePreprocessStepLog],
    is_pdf: bool,
) -> ImagePreprocessResult:
    artifact_root = _artifact_root(input_path, document_id=document_id)
    current = input_path
    changed_any = False

    current, changed = _append_orientation_step(
        current=current,
        artifact_root=artifact_root,
        input_path=input_path,
        sample_pages=sample_pages,
        meta=meta,
        steps=steps,
        is_pdf=is_pdf,
    )
    changed_any = changed_any or changed

    current, changed, step, info = _run_paddle_doc_preprocess_stage(
        current=current,
        artifact_root=artifact_root,
        output_stem=input_path.stem,
        warnings=warnings,
    )
    if info is not None:
        meta["paddle_ocr_preprocess"] = info
    changed_any = changed_any or changed
    steps.append(step)

    current, changed = _append_deskew_step(
        current=current,
        artifact_root=artifact_root,
        input_path=input_path,
        steps=steps,
        is_pdf=is_pdf,
    )
    changed_any = changed_any or changed

    current, changed, step, info = _run_handwriting_cleanup_stage(
        current=current,
        artifact_root=artifact_root,
        output_stem=input_path.stem,
        warnings=warnings,
    )
    if info is not None:
        meta["handwriting_cleanup"] = info
    changed_any = changed_any or changed
    steps.append(step)

    if is_pdf:
        current, changed = _append_pdf_watermark_steps(
            current=current,
            artifact_root=artifact_root,
            input_path=input_path,
            document_id=document_id,
            sample_pages=sample_pages,
            warnings=warnings,
            steps=steps,
            meta=meta,
        )
    else:
        current, changed = _append_image_watermark_step(
            current=current,
            artifact_root=artifact_root,
            input_path=input_path,
            warnings=warnings,
            steps=steps,
            meta=meta,
        )
    changed_any = changed_any or changed

    return _finalize_preprocess_result(
        input_path=input_path,
        current=current,
        changed_any=changed_any,
        artifact_root=artifact_root,
        steps=steps,
        warnings=warnings,
        meta=meta,
    )


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
    enabled = settings.IMAGE_PREPROCESS_ENABLED

    if not enabled:
        return _disabled_preprocess_result(input_path)

    warnings: list[str] = []
    steps: list[ImagePreprocessStepLog] = []
    meta: dict[str, Any] = {"enabled": True}

    sample_pages = settings.PREPROCESS_SAMPLE_PAGES
    skip_high_quality = settings.PREPROCESS_SKIP_HIGH_QUALITY

    # Best-effort: allow caller to pass pdf_quality for skip logic / meta.
    if isinstance(pdf_quality, dict):
        meta["pdf_quality_score"] = pdf_quality.get("score")
        meta["pdf_is_scanned"] = bool(pdf_quality.get("is_scanned", False))

    if ext == ".pdf":
        pdf_q = dict(pdf_quality) if isinstance(pdf_quality, dict) else None
        if skip_high_quality and pdf_q is None:
            try:
                from app.rag.ingestion.parsing.quality.scorer import score_pdf_quality

                pdf_q = score_pdf_quality(input_path, sample_pages=sample_pages, use_ocr_validation=False)
                if isinstance(pdf_q, dict):
                    meta["pdf_quality_score"] = pdf_q.get("score")
                    meta["pdf_is_scanned"] = bool(pdf_q.get("is_scanned", False))
            except Exception as exc:
                warnings.append(f"pdf_quality_unavailable:{type(exc).__name__}")
                pdf_q = None

        if skip_high_quality and isinstance(pdf_q, dict):
            score = pdf_q.get("score")
            is_scanned = bool(pdf_q.get("is_scanned", False))
            if score is not None and score >= 0.8 and not is_scanned:
                return _high_quality_pdf_skip_result(input_path, meta=meta)

        return _preprocess_document(
            input_path=input_path,
            document_id=document_id,
            sample_pages=sample_pages,
            meta=meta,
            warnings=warnings,
            steps=steps,
            is_pdf=True,
        )

    if ext not in _IMAGE_EXTS:
        return _unsupported_preprocess_result(input_path, meta=meta)

    return _preprocess_document(
        input_path=input_path,
        document_id=document_id,
        sample_pages=0,
        meta=meta,
        warnings=warnings,
        steps=steps,
        is_pdf=False,
    )
