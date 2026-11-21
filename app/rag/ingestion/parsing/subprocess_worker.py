"""
Subprocess worker for heavy parsing operations.

This module is executed via:
  python -m app.rag.ingestion.parsing.subprocess_worker <payload_path> <result_path>

It exists so the caller can truly cancel parsing by terminating the process
(docling/torch-based parsers are not cooperatively cancellable in-process).
"""

import json
import logging
import time
import traceback
import uuid
from contextlib import ExitStack
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.infrastructure.observability.logging import configure_worker_logging
from app.infrastructure.runtime.dependencies import optional_import
from app.rag.ingestion.parsing.backends import normalize_parser_backend

logger = logging.getLogger("parsing.subprocess_worker")


@lru_cache(maxsize=1)
def _get_pil_image():  # noqa: ANN202
    return optional_import("PIL.Image", feature="parse_ingest_image_materialize", pip_name="Pillow")


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _jsonable(obj: Any) -> Any:
    # Preserve ints/floats/bools/None; fallback to str for unknown types.
    return json.loads(json.dumps(obj, ensure_ascii=False, default=str, allow_nan=False))


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
        payload["data"] = {} if data is None else data
    else:
        payload["error"] = {} if error is None else error
    # Path is constrained to settings.UPLOAD_DIR by _safe_worker_io_path().
    _safe_worker_io_path(path).write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )  # NOSONAR


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
    *,
    meta: dict[str, Any],
    artifact_root: Path | None,
    images_dir: Path,
) -> Path:
    if artifact_root is not None:
        meta["artifact_dir"] = str(artifact_root)
    out_id = uuid.uuid4().hex
    out_path = images_dir.joinpath(f"{out_id}.jpg")
    meta["image_path"] = str(out_path)
    meta.pop("image", None)
    return out_path


def _persist_ingest_image(raw: Any, *, out_path: Path, pil_image: Any | None) -> None:
    if pil_image is None:
        raise RuntimeError("Pillow is required to materialize subprocess image output")

    from io import BytesIO

    with ExitStack() as cleanup:
        image_obj = raw
        if isinstance(raw, (bytes, bytearray)):
            source = cleanup.enter_context(BytesIO(bytes(raw)))
            image_obj = pil_image.open(source)
            cleanup.callback(image_obj.close)
        if image_obj.mode != "RGB":
            converted = image_obj.convert("RGB")
            if converted is not image_obj:
                cleanup.callback(converted.close)
            image_obj = converted
        image_obj.save(out_path, format="JPEG", quality=85, optimize=True)


def _close_ingest_image(raw: Any, *, pending_error: BaseException | None) -> None:
    try:
        if raw is not None and not isinstance(raw, (bytes, bytearray)):
            raw.close()
    except BaseException as exc:
        if pending_error is None:
            raise
        pending_error.add_note(f"Subprocess image cleanup failed: {type(exc).__name__}")
        logger.warning("Subprocess image cleanup failed while propagating an error", exc_info=True)


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

    with ExitStack() as artifact_cleanup:
        with ExitStack() as image_cleanup:
            seen_images: set[int] = set()
            for doc in documents:
                raw = doc.metadata.get("image")
                if raw is not None and not isinstance(raw, (bytes, bytearray)) and id(raw) not in seen_images:
                    seen_images.add(id(raw))
                    image_cleanup.push(
                        lambda _kind, error, _tb, image=raw: _close_ingest_image(image, pending_error=error)
                    )

            needs_persist = _documents_need_image_persist(documents)
            artifact_root, images_dir = _prepare_ingest_image_dir(
                tenant_id=tenant_id, artifact_root=artifact_root, needs_persist=needs_persist
            )
            pil_image = _get_pil_image() if needs_persist else None

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

                out_path = _assign_ingest_image_metadata(meta=meta, artifact_root=artifact_root, images_dir=images_dir)
                artifact_cleanup.callback(out_path.unlink, missing_ok=True)
                _persist_ingest_image(raw, out_path=out_path, pil_image=pil_image)
                doc.metadata = meta
        # Every image persisted and in-memory resource closed; transfer artifacts.
        artifact_cleanup.pop_all()

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


def _materialization_mode(value: Any) -> str:
    if not isinstance(value, str) or value.strip().lower() not in {"preview", "ingest"}:
        raise ValueError(f"Unsupported subprocess materialization mode: {value!r}")
    return value.strip().lower()


def _materialize_documents_for_mode(
    documents: list[Document],
    *,
    mode: str,
    tenant_id: UUID,
    account_id: str | None,
    raw_artifact_root: Any,
) -> list[Document]:
    if mode == "preview":
        from app.services.documents.preview import (
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
    file_path = Path(payload["file_path"])
    requested_backend = payload.get("parser_backend")
    mode = _materialization_mode(payload.get("mode", "preview"))

    dataset_id = payload.get("dataset_id")
    document_id = payload.get("document_id")

    file_ext = file_path.suffix.lower()
    pdf_quality = payload.get("pdf_quality") if isinstance(payload.get("pdf_quality"), dict) else None
    effective_backend = requested_backend
    if file_ext == ".pdf":
        requested = normalize_parser_backend(requested_backend)
        if pdf_quality is None and (not requested or requested == "auto"):
            from app.rag.ingestion.parsing.routing import route_pdf_backend

            effective_backend, pdf_quality = route_pdf_backend(
                file_path,
                requested,
                sample_pages=3,
                use_ocr_validation=settings.RAPIDOCR_ENABLED,
            )
        else:
            effective_backend = requested

    from app.rag.ingestion.parsing.factory import parser_factory

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
    file_path = Path(payload["file_path"])
    strategy = payload["strategy"]
    mode = _materialization_mode(payload.get("mode", "preview"))

    from app.rag.ingestion.indexing.processor import chunk_integrated_file

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
    file_path = Path(payload["file_path"])
    parser_backend = payload.get("parser_backend")
    from app.rag.ingestion.parsing.processors.parser_service import parse_for_preview

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
    configure_worker_logging()
    import sys

    if len(sys.argv) != 3:
        raise SystemExit("Usage: python -m app.rag.ingestion.parsing.subprocess_worker <payload_path> <result_path>")

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
