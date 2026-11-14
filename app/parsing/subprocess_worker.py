"""
Subprocess worker for heavy parsing operations.

This module is executed via:
  python -m app.parsing.subprocess_worker <payload_path> <result_path>

It exists so the caller can truly cancel parsing by terminating the process
(docling/torch-based parsers are not cooperatively cancellable in-process).
"""

import json
import time
import traceback
import uuid
from contextlib import ExitStack
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.documents import Document

from app.core.config import settings
from app.core.optional_deps import optional_import
from app.parsing.backends import normalize_parser_backend
from app.rag.core.logging import get_logger, setup_logging

logger = get_logger("parsing.subprocess_worker")


@lru_cache(maxsize=1)
def _get_pil_image():  # noqa: ANN202
    return optional_import("PIL.Image", feature="parse_ingest_image_materialize", pip_name="Pillow")


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _jsonable(obj: Any) -> Any:
    # Preserve ints/floats/bools/None; fallback to str for unknown types.
    return json.loads(json.dumps(obj, ensure_ascii=False, default=str))


def _safe_upload_child(*parts: str) -> Path:
    root = Path(settings.UPLOAD_DIR).resolve(strict=False)
    candidate = root.joinpath(*parts).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("path outside upload directory") from exc
    return candidate


def _safe_worker_io_path(path: Path) -> Path:
    resolved = Path(path).resolve(strict=False)
    upload_root = Path(settings.UPLOAD_DIR).resolve(strict=False)
    try:
        resolved.relative_to(upload_root)
    except ValueError as exc:
        raise ValueError("worker result path outside upload directory") from exc
    return resolved


def _write_result(
    path: Path, *, ok: bool, data: dict[str, Any] | None = None, error: dict[str, Any] | None = None
) -> None:
    payload: dict[str, Any] = {"ok": bool(ok)}
    if ok:
        payload["data"] = data or {}
    else:
        payload["error"] = error or {}
    # Path is constrained to settings.UPLOAD_DIR by _safe_worker_io_path().
    _safe_worker_io_path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")  # NOSONAR


def _documents_need_image_persist(documents: list[Document]) -> bool:
    for doc in documents:
        meta = doc.metadata
        if meta.get("image") is None:
            continue
        doc_type = meta.get("doc_type_kwd")
        if isinstance(doc_type, str) and doc_type.lower() == "image":
            return True
    return False


def _prepare_ingest_image_dir(
    *,
    tenant_id: UUID,
    artifact_root: Path | None,
    needs_persist: bool,
) -> tuple[Path | None, Path | None]:
    if not needs_persist:
        return artifact_root, None

    if artifact_root is None:
        artifact_root = _safe_upload_child(str(tenant_id), ".mimirq_parse", uuid.uuid4().hex)
    else:
        artifact_root = _safe_worker_io_path(artifact_root)

    images_dir = artifact_root.joinpath("images").resolve(strict=False)
    images_dir.mkdir(parents=True, exist_ok=True)
    return artifact_root, images_dir


def _assign_ingest_image_metadata(
    doc: Document,
    *,
    meta: dict[str, Any],
    tenant_id: UUID,
    artifact_root: Path | None,
    images_dir: Path | None,
) -> Path:
    if artifact_root is not None:
        meta["artifact_dir"] = str(artifact_root)
    out_id = uuid.uuid4().hex
    out_path = (images_dir or _safe_upload_child(str(tenant_id), "images")).joinpath(f"{out_id}.jpg")
    meta["image_path"] = str(out_path)
    meta.pop("image", None)
    doc.metadata = meta
    return out_path


def _persist_ingest_image(raw: Any, *, out_path: Path, pil_image: Any | None) -> None:
    if pil_image is None:
        return

    from io import BytesIO

    with ExitStack() as cleanup:
        image_obj = raw
        if isinstance(raw, (bytes, bytearray)):
            image_obj = pil_image.open(BytesIO(bytes(raw)))
            cleanup.callback(image_obj.close)
        try:
            if getattr(image_obj, "mode", None) != "RGB":
                converted = image_obj.convert("RGB")
                if converted is not image_obj:
                    cleanup.callback(converted.close)
                image_obj = converted
        except Exception as exc:
            logger.debug("Ignoring non-critical subprocess worker image conversion failure: %s", exc)
        image_obj.save(out_path, format="JPEG", quality=85, optimize=True)


def _close_ingest_image(raw: Any) -> None:
    try:
        if raw is not None and not isinstance(raw, (bytes, bytearray)) and hasattr(raw, "close"):
            raw.close()
    except Exception as exc:
        logger.debug("Ignoring non-critical subprocess worker image close failure: %s", exc)


def _materialize_images_for_ingest(
    documents: list[Document],
    *,
    tenant_id: UUID,
    artifact_root: Path | None = None,
) -> list[Document]:
    """
    Convert in-memory image objects to local files so the parent process can
    upload them to MinIO without pickling PIL.Image across processes.
    """
    if not documents:
        return []

    artifact_root, images_dir = _prepare_ingest_image_dir(
        tenant_id=tenant_id,
        artifact_root=artifact_root,
        needs_persist=_documents_need_image_persist(documents),
    )
    pil_image = _get_pil_image()

    for doc in documents:
        meta = dict(doc.metadata)
        raw = meta.get("image")
        if raw is None:
            doc.metadata = meta
            continue

        doc_type = meta.get("doc_type_kwd")
        if not isinstance(doc_type, str) or doc_type.lower() != "image":
            meta.pop("image", None)
            doc.metadata = meta
            continue

        out_path = _assign_ingest_image_metadata(
            doc,
            meta=meta,
            tenant_id=tenant_id,
            artifact_root=artifact_root,
            images_dir=images_dir,
        )

        try:
            _persist_ingest_image(raw, out_path=out_path, pil_image=pil_image)
        except Exception:
            # Keep metadata.image_path for downstream best-effort, but do not crash.
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
        finally:
            _close_ingest_image(raw)

    return list(documents)


def _serialize_documents(documents: list[Document]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for doc in documents:
        out.append(
            {
                "page_content": doc.page_content,
                "metadata": _jsonable(doc.metadata),
                "id": doc.id,
            }
        )
    return out


def _materialize_documents_for_mode(
    documents: list[Document],
    *,
    mode: str,
    tenant_id: UUID,
    account_id: str | None,
    raw_artifact_root: Any,
) -> list[Document]:
    if mode == "preview":
        from app.services.document_preview_utils import (
            _materialize_extracted_images_for_preview,
            _materialize_local_images_for_preview,
        )

        documents = _materialize_extracted_images_for_preview(documents, tenant_id=tenant_id, account_id=account_id)
        return _materialize_local_images_for_preview(documents, tenant_id=tenant_id, account_id=account_id)
    artifact_root = None
    if isinstance(raw_artifact_root, str) and raw_artifact_root.strip():
        artifact_root = Path(raw_artifact_root.strip())
    return _materialize_images_for_ingest(documents, tenant_id=tenant_id, artifact_root=artifact_root)


def _parse_documents(payload: dict[str, Any]) -> dict[str, Any]:
    tenant_id = _as_uuid(payload["tenant_id"])
    file_path = Path(str(payload["file_path"]))
    requested_backend = payload.get("parser_backend")
    mode = (payload.get("mode") or "preview").strip().lower()

    dataset_id = payload.get("dataset_id")
    document_id = payload.get("document_id")

    file_ext = file_path.suffix.lower()
    pdf_quality = payload.get("pdf_quality") if isinstance(payload.get("pdf_quality"), dict) else None
    effective_backend = requested_backend
    if file_ext == ".pdf":
        requested = normalize_parser_backend(requested_backend)
        if pdf_quality is None and (not requested or requested == "auto"):
            from app.parsing.routing import route_pdf_backend

            effective_backend, pdf_quality = route_pdf_backend(
                file_path,
                requested,
                sample_pages=3,
                use_ocr_validation=settings.RAPIDOCR_ENABLED,
            )
        else:
            effective_backend = requested

    from app.parsing.factory import parser_factory

    documents, resolved_backend, provenance = parser_factory.parse_with_provenance(
        file_path,
        parser_backend=effective_backend,
        dataset_id=str(dataset_id) if dataset_id else None,
        document_id=str(document_id) if document_id else None,
        tenant_id=str(tenant_id),
        account_id=payload.get("account_id"),
        pdf_quality=pdf_quality,
        html_xpath=(payload.get("html_xpath") if isinstance(payload.get("html_xpath"), str) else None),
    )
    # The factory returns a provenance dictionary; add this worker's routing choices.
    provenance = dict(provenance)
    provenance.setdefault("payload_requested_backend", requested_backend)
    provenance.setdefault("effective_backend", effective_backend)

    documents = _materialize_documents_for_mode(
        documents,
        mode=mode,
        tenant_id=tenant_id,
        account_id=payload.get("account_id"),
        raw_artifact_root=payload.get("artifact_root"),
    )

    return {
        "resolved_backend": resolved_backend,
        "pdf_quality": _jsonable(pdf_quality),
        "documents": _serialize_documents(documents),
        "provenance": _jsonable(provenance),
    }


def _integrated_chunk(payload: dict[str, Any]) -> dict[str, Any]:
    tenant_id = _as_uuid(payload["tenant_id"])
    file_path = Path(str(payload["file_path"]))
    strategy = str(payload["strategy"])
    mode = (payload.get("mode") or "preview").strip().lower()

    from app.parsing.processors.processor import chunk_integrated_file

    documents = chunk_integrated_file(file_path, strategy)

    documents = _materialize_documents_for_mode(
        documents,
        mode=mode,
        tenant_id=tenant_id,
        account_id=payload.get("account_id"),
        raw_artifact_root=payload.get("artifact_root"),
    )

    return {"documents": _serialize_documents(documents)}


def _pipeline_parse_preview(payload: dict[str, Any]) -> dict[str, Any]:
    tenant_id = _as_uuid(payload["tenant_id"])
    file_path = Path(str(payload["file_path"]))
    parser_backend = payload.get("parser_backend")
    from app.parsing.processors.parser_service import parse_for_preview

    result = parse_for_preview(
        file_path=file_path,
        tenant_id=tenant_id,
        account_id=payload.get("account_id"),
        parser_backend=parser_backend,
    )
    return _jsonable(result)


def _sleep(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Test-only helper action for validating subprocess cancellation.

    Sleeps for `duration_sec` and returns a small payload.
    """
    raw = payload.get("duration_sec")
    try:
        duration = float(raw or 0.0)
    except Exception:
        duration = 0.0
    duration = max(0.0, min(duration, 60.0))
    time.sleep(duration)
    return {"slept_sec": duration}


def main() -> int:
    setup_logging()
    import sys

    if len(sys.argv) != 3:
        raise SystemExit("Usage: python -m app.parsing.subprocess_worker <payload_path> <result_path>")

    payload_path = _safe_worker_io_path(Path(sys.argv[1]))
    result_path = _safe_worker_io_path(Path(sys.argv[2]))

    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")

        action = payload.get("action")
        if not isinstance(action, str) or not action.strip():
            raise ValueError("missing action")
        action = action.strip()

        if action == "parse_documents":
            data = _parse_documents(payload)
        elif action == "integrated_chunk":
            data = _integrated_chunk(payload)
        elif action == "pipeline_parse_preview":
            data = _pipeline_parse_preview(payload)
        elif action == "sleep":
            data = _sleep(payload)
        else:
            raise ValueError(f"unsupported action: {action}")

        _write_result(result_path, ok=True, data=data)
        return 0
    except Exception as exc:  # noqa: BLE001
        err = {
            "message": str(exc)[:500] or exc.__class__.__name__,
            "type": exc.__class__.__name__,
            "traceback": traceback.format_exc(limit=50),
        }
        try:
            _write_result(result_path, ok=False, error=err)
        except Exception as write_exc:
            logger.debug("Ignoring non-critical subprocess worker result write failure: %s", write_exc)
        logger.exception("Subprocess worker failed: %s", str(exc)[:200])
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
