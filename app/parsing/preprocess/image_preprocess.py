"""
Image-level preprocessing (before parsing).

This module sits *before* the parsing subprocess backends. It is meant to:
- Fix obvious orientation issues (EXIF transpose) for standalone images
- Optionally call external services for deskew/dewarp/watermark removal

Phase 1 scope (per docs/plans/2026-03-19-model-based-deskew-watermark-removal.md):
- Wire the preprocessing stage into the ingest pipeline behind feature flags
- Provide a safe no-op default (disabled)
- Provide a minimal implementation for image EXIF orientation fix
- Provide scaffolding for external deskew backends (no heavy model deps in-process)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageOps

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("parsing.image_preprocess")


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def _sanitize_run_id(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", text)[:120] or "preprocess"
    return text


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


def _maybe_fix_exif_orientation(*, input_path: Path, output_path: Path) -> tuple[bool, str]:
    """
    Returns (changed, note).

    Uses EXIF orientation flag when present. This is lightweight and does not
    require OCR/model deps.
    """
    try:
        with Image.open(input_path) as img:
            try:
                orientation = int(img.getexif().get(274) or 1)
            except Exception:
                orientation = 1
            if orientation == 1:
                return False, "no_exif_rotation"

            fixed = ImageOps.exif_transpose(img)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fixed.save(output_path)
            return True, f"exif_orientation={orientation}"
    except Exception as exc:  # noqa: BLE001
        return False, f"exif_failed:{exc.__class__.__name__}"


def _maybe_deskew_via_paddle(*, input_path: Path, output_path: Path, url: str, timeout_sec: float) -> tuple[bool, str]:
    """
    Deskew via an external service.

    Contract (best-effort):
    - POST multipart form with file field "file"
    - Response: image bytes (content-type image/*) or octet-stream
    """
    try:
        file_bytes = input_path.read_bytes()
        resp = requests.post(
            url,
            files={"file": (input_path.name, file_bytes, "application/octet-stream")},
            timeout=timeout_sec,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"deskew_http_failed:{exc.__class__.__name__}"

    if resp.status_code >= 400:
        return False, f"deskew_http_{resp.status_code}"
    if not resp.content:
        return False, "deskew_empty_response"

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(resp.content)
        return True, "deskew_ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"deskew_write_failed:{exc.__class__.__name__}"


def preprocess_image_document(
    *,
    input_path: Path,
    document_id: str | None = None,
    pdf_quality: dict[str, Any] | None = None,
) -> ImagePreprocessResult:
    """
    Preprocess a document file before parsing.

    Phase 1:
    - Standalone images: optional EXIF orientation fix + optional external deskew.
    - PDFs: scaffolding only (no in-process rasterization/rewriting yet).
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

    # Best-effort: allow caller to pass pdf_quality for future skip logic.
    if isinstance(pdf_quality, dict):
        meta["pdf_quality_score"] = pdf_quality.get("score")

    # PDF scaffolding (Phase 1 keeps this a no-op).
    if ext == ".pdf":
        return ImagePreprocessResult(
            input_path=str(input_path),
            output_path=str(input_path),
            changed=False,
            steps=[ImagePreprocessStepLog(id="pdf_preprocess", applied=False, changed=False, note="not_implemented_phase1")],
            warnings=[],
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
        changed, note = _maybe_fix_exif_orientation(input_path=current, output_path=out_path)
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
            deskew_changed, note = _maybe_deskew_via_paddle(
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

    # Step: watermark removal (scaffolding only in Phase 1)
    t2 = time.perf_counter()
    if bool(getattr(settings, "WATERMARK_REMOVAL_ENABLED", False)):
        steps.append(
            ImagePreprocessStepLog(
                id="watermark_removal",
                applied=False,
                changed=False,
                note="not_implemented_phase1",
                elapsed_ms=int(round((time.perf_counter() - t2) * 1000)),
            )
        )
        warnings.append("watermark_removal_not_implemented_phase1")
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
