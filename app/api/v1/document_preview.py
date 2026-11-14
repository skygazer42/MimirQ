import shutil
import uuid
from pathlib import Path
from typing import Annotated, Any, NoReturn
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from langchain_core.documents import Document

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import DocumentParsePreview, DocumentPreviewForm, ParsedSegment
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES, sanitize_upload_filename, save_upload_file
from app.api.utils.document_pipeline_input import parse_pipeline_json, to_pipeline_options
from app.core.async_bridge import run_blocking_in_thread
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.env import is_production_env
from app.parsing.factory import parser_factory
from app.parsing.subprocess_runner import (
    SubprocessCancelled,
    SubprocessWorkerError,
    run_subprocess_worker,
)
from app.rag.core.logging import get_logger
from app.rag.preprocessing.processor import governance_processor
from app.rag.preprocessing.rules import build_governance_rules
from app.services import dataset_service
from app.services.document_governance import build_governance_options
from app.services.pipeline_config import resolve_pipeline_effective, validate_pipeline_execution
from app.types.document_analytics import compute_document_analytics
from app.types.pipeline import PipelineEffective

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger("api.documents")
_PREVIEW_ARTIFACT_DIRECTORY_NAMES = frozenset(
    {".magicpdf", ".deepseek_ocr", ".qianfan_ocr", ".etl4llm", ".marker", ".paddlevl", ".olmocr"}
)


def _strip_preview_nul_chars(value: str) -> str:
    return value.replace("\x00", "")


def _sanitize_preview_value(value: Any) -> Any:
    if isinstance(value, str):
        return _strip_preview_nul_chars(value)
    if isinstance(value, list):
        return [_sanitize_preview_value(item) for item in value]
    if isinstance(value, dict):
        return {_strip_preview_nul_chars(str(key)): _sanitize_preview_value(item) for key, item in value.items()}
    return value


def _should_inline_preview_parse(file_ext: str) -> bool:
    return settings.PREVIEW_INLINE_TEXT_PARSE_ENABLED and (
        file_ext == ".md" or file_ext in parser_factory.PLAIN_TEXT_EXTENSIONS
    )


def _serialize_inline_preview_documents(documents: list[Document]) -> list[dict[str, Any]]:
    return [
        {
            "page_content": _strip_preview_nul_chars(doc.page_content),
            "metadata": _sanitize_preview_value(doc.metadata),
            "id": doc.id,
        }
        for doc in documents
    ]


def _parse_inline_text_preview(
    *,
    source_path: Path,
    resolved_backend: str,
    tenant_id: UUID,
    requested_backend: str,
) -> dict[str, Any]:
    documents, inline_backend, provenance = parser_factory.parse_with_provenance(
        source_path,
        parser_backend=resolved_backend,
        tenant_id=str(tenant_id),
        document_id=uuid.uuid4().hex,
    )
    provenance = dict(provenance)
    provenance.setdefault("payload_requested_backend", requested_backend)
    provenance.setdefault("effective_backend", resolved_backend)
    provenance.setdefault("execution_mode", "inline_document_preview")
    return {
        "resolved_backend": inline_backend,
        "pdf_quality": None,
        "documents": _serialize_inline_preview_documents(documents),
        "provenance": _sanitize_preview_value(provenance),
    }


def _validate_preview_extension(filename: str) -> str:
    file_ext = Path(filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}",
        )
    return file_ext


async def _parse_preview_payload(
    *,
    request: Request,
    temp_path: Path,
    tenant_id: UUID,
    account_id: str,
    file_ext: str,
    parser_backend: str,
) -> dict[str, Any]:
    if _should_inline_preview_parse(file_ext):
        resolved_text_backend = parser_factory.resolve_backend(file_ext, parser_backend)
        return await run_blocking_in_thread(
            _parse_inline_text_preview,
            source_path=temp_path,
            resolved_backend=resolved_text_backend,
            tenant_id=tenant_id,
            requested_backend=parser_backend,
        )
    return await run_subprocess_worker(
        tenant_id=tenant_id,
        payload={
            "action": "parse_documents",
            "tenant_id": str(tenant_id),
            "account_id": str(account_id),
            "file_path": str(temp_path),
            "parser_backend": parser_backend,
            "mode": "preview",
        },
        disconnect_check=request.is_disconnected,
        timeout_sec=float(settings.TASK_JOB_TIMEOUT_SEC),
    )


def _materialize_preview_documents(
    parsed: dict[str, Any],
    *,
    artifact_dirs: set[str],
) -> tuple[list[Document], str, dict[str, Any] | None]:
    payload_documents = parsed["documents"]
    # Retain resource locations even when constructing a later document fails.
    for item in payload_documents:
        artifact_dir = item["metadata"].get("artifact_dir")
        if isinstance(artifact_dir, str) and artifact_dir.strip():
            artifact_dirs.add(artifact_dir.strip())
    documents = [
        Document(
            page_content=item["page_content"],
            metadata=item["metadata"],
            id=item["id"],
        )
        for item in payload_documents
    ]
    return documents, parsed["resolved_backend"], parsed["pdf_quality"]


def _load_preview_metadata(*, tenant_id: UUID, account_id: str, dataset_id: str | None) -> dict[str, Any]:
    with SessionLocal() as db:
        dataset_service.ensure_member(db, tenant_id, account_id)
        if dataset_id is None:
            return {}
        try:
            dataset_uuid = UUID(dataset_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid dataset_id") from exc
        dataset = dataset_service.get_dataset(db, tenant_id, dataset_uuid)
        dataset_service.assert_dataset_readable(db, dataset, account_id)
        metadata = dataset.dataset_metadata
        return {} if metadata is None else dict(metadata)


def _apply_preview_governance(
    *,
    documents: list[Document],
    pipeline_effective: PipelineEffective,
) -> list[Document]:
    if not pipeline_effective.governance_enabled:
        return documents
    extra_rules = pipeline_effective.governance_regex_rules
    combined_rules = build_governance_rules(extra_rules) if extra_rules else None
    cleaned_documents, _stats = governance_processor.clean_documents(
        documents,
        rules=combined_rules,
        options=build_governance_options(pipeline_effective),
    )
    return cleaned_documents


def _compute_preview_analytics(
    *,
    documents: list[Document],
    pdf_quality: dict[str, Any] | None,
    pipeline_effective: PipelineEffective,
) -> dict[str, Any]:
    markdown = "\n\n".join(d.page_content for d in documents)
    return compute_document_analytics(
        markdown=markdown,
        documents=documents,
        pdf_quality=pdf_quality,
        detect_language=pipeline_effective.governance_detect_language,
        language_min_chars=pipeline_effective.governance_language_min_chars,
    ).to_dict()


def _build_preview_segments(documents: list[Document]) -> list[ParsedSegment]:
    return [
        ParsedSegment(
            index=idx,
            content=doc.page_content,
            page_number=doc.metadata.get("page"),
            metadata=doc.metadata,
        )
        for idx, doc in enumerate(documents)
    ]


def _cleanup_preview_artifacts(*, tenant_id: UUID, artifact_dirs: set[str]) -> None:
    if not artifact_dirs or settings.MAGIC_PDF_KEEP_ARTIFACTS:
        return
    tenant_root = (Path(settings.UPLOAD_DIR) / str(tenant_id)).resolve(strict=False)
    for raw in sorted(artifact_dirs):
        try:
            path = Path(raw).resolve(strict=False)
            relative_path = path.relative_to(tenant_root)
        except (OSError, ValueError, RuntimeError) as exc:
            logger.debug("Skipping preview artifact path error_type=%s", type(exc).__name__)
            continue
        if _PREVIEW_ARTIFACT_DIRECTORY_NAMES.intersection(relative_path.parts):
            shutil.rmtree(path, ignore_errors=True)


def _raise_preview_http_exception(exc: Exception) -> NoReturn:
    if isinstance(exc, SubprocessCancelled):
        raise HTTPException(status_code=499, detail="Client closed request") from None
    if isinstance(exc, SubprocessWorkerError):
        err_type = exc.details.get("type")
        if err_type in {"ValueError", "RetiredModelProviderError"}:
            raise HTTPException(status_code=400, detail=f"Invalid input: {str(exc)[:100]}") from exc
        logger.error("Subprocess worker failed during preview: %s", str(exc)[:200])
        msg = str(exc).strip()
        if not msg:
            details = exc.details
            msg = str(details.get("message") or details.get("type") or exc.__class__.__name__).strip()
        msg = msg[:200]
        detail = "Failed to parse document" if is_production_env() else f"Failed to parse document: {msg}"
        raise HTTPException(status_code=500, detail=detail) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid input: {str(exc)[:100]}") from exc
    if isinstance(exc, IOError):
        logger.error("File read error during preview: %s", str(exc)[:200])
        raise HTTPException(status_code=500, detail="File read error") from exc
    if isinstance(exc, HTTPException):
        raise exc
    logger.error("Unexpected error during document preview: %s", str(exc)[:200])
    msg = str(exc).strip() or exc.__class__.__name__
    msg = msg[:200]
    detail = "Failed to parse document" if is_production_env() else f"Failed to parse document: {msg}"
    raise HTTPException(status_code=500, detail=detail) from exc


@router.post("/preview", response_model=DocumentParsePreview)
async def preview_document(
    request: Request,
    form: Annotated[DocumentPreviewForm, Form(media_type="multipart/form-data")],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> DocumentParsePreview:
    """
    Document parse preview endpoint.

    Only parses the document and returns structured segments; does not create
    a document record or persist data. Useful for frontend custom chunking.
    """
    dataset_meta = await run_blocking_in_thread(
        _load_preview_metadata,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=form.dataset_id,
    )
    file = form.file
    file.filename = sanitize_upload_filename(file.filename)

    parser_backend = form.parser_backend
    file_ext = _validate_preview_extension(file.filename)

    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"

    run_dir = upload_dir / uuid.uuid4().hex
    temp_path = run_dir / f"input{file_ext}"
    artifact_dirs: set[str] = set()

    try:
        file_size = await save_upload_file(file, temp_path, max_bytes=settings.MAX_FILE_SIZE)
        parsed = await _parse_preview_payload(
            request=request,
            temp_path=temp_path,
            tenant_id=tenant_id,
            account_id=account_id,
            file_ext=file_ext,
            parser_backend=parser_backend,
        )
        documents, resolved_backend, pdf_quality = await run_blocking_in_thread(
            _materialize_preview_documents,
            parsed,
            artifact_dirs=artifact_dirs,
        )
        pipeline_options = to_pipeline_options(
            pipeline=parse_pipeline_json(form.pipeline),
            overrides=form.to_pipeline_overrides(),
        )
        pipeline_effective = resolve_pipeline_effective(
            dataset_metadata=dataset_meta,
            document_metadata={},
            request_overrides=pipeline_options,
        )
        validate_pipeline_execution(pipeline_effective)
        raw_analytics = await run_blocking_in_thread(
            _compute_preview_analytics,
            documents=documents,
            pdf_quality=pdf_quality,
            pipeline_effective=pipeline_effective,
        )
        documents = await run_blocking_in_thread(
            _apply_preview_governance,
            documents=documents,
            pipeline_effective=pipeline_effective,
        )
        cleaned_analytics = await run_blocking_in_thread(
            _compute_preview_analytics,
            documents=documents,
            pdf_quality=pdf_quality,
            pipeline_effective=pipeline_effective,
        )
        return DocumentParsePreview(
            filename=file.filename,
            file_type=file_ext.lstrip("."),
            file_size=file_size,
            segments=_build_preview_segments(documents),
            parser_backend=resolved_backend,
            analytics={"raw": raw_analytics, "cleaned": cleaned_analytics},
        )
    except Exception as exc:
        _raise_preview_http_exception(exc)
    finally:
        try:
            with anyio.fail_after(5.0, shield=True):
                await run_blocking_in_thread(shutil.rmtree, run_dir, ignore_errors=True)
        except OSError as exc:
            logger.warning("Failed to clean up preview directory %s: %s", run_dir, exc, exc_info=True)
        finally:
            with anyio.fail_after(5.0, shield=True):
                await run_blocking_in_thread(
                    _cleanup_preview_artifacts, tenant_id=tenant_id, artifact_dirs=artifact_dirs
                )
