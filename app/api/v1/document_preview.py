
import contextlib
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentParsePreview, ParsedSegment
from app.api.utils.upload import save_upload_file
from app.core.config import settings
from app.core.database import get_db
from app.core.env import is_production_env
from app.parsing.factory import parser_factory
from app.parsing.subprocess_runner import (
    SubprocessCancelled,
    SubprocessWorkerError,
)
from app.rag.core.logging import get_logger
from app.rag.preprocessing.rules import build_governance_rules
from app.services.dataset_service import DatasetService
from app.services.pipeline_config import resolve_pipeline_effective
from app.types.document_analytics import compute_document_analytics

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _strip_preview_nul_chars(value: str) -> str:
    if not value:
        return ""
    return value.replace("\x00", "")


def _sanitize_preview_value(value: Any) -> Any:
    if isinstance(value, str):
        return _strip_preview_nul_chars(value)
    if isinstance(value, list):
        return [_sanitize_preview_value(item) for item in value]
    if isinstance(value, dict):
        return {
            _strip_preview_nul_chars(str(key)): _sanitize_preview_value(item)
            for key, item in value.items()
        }
    return value


def _should_inline_preview_parse(file_ext: str) -> bool:
    if not bool(getattr(settings, "PREVIEW_INLINE_TEXT_PARSE_ENABLED", True)):
        return False
    ext = str(file_ext or "").strip().lower()
    return ext == ".md" or ext in parser_factory.PLAIN_TEXT_EXTENSIONS


def _serialize_inline_preview_documents(documents: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for doc in documents or []:
        metadata = getattr(doc, "metadata", None) or {}
        out.append(
            {
                "page_content": _strip_preview_nul_chars(str(getattr(doc, "page_content", "") or "")),
                "metadata": _sanitize_preview_value(metadata if isinstance(metadata, dict) else {}),
                "id": str(getattr(doc, "id", "") or "") or None,
            }
        )
    return out


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
    if isinstance(provenance, dict):
        provenance = dict(provenance)
        provenance.setdefault("payload_requested_backend", str(requested_backend or ""))
        provenance.setdefault("effective_backend", str(resolved_backend or ""))
        provenance.setdefault("execution_mode", "inline_document_preview")
    return {
        "resolved_backend": inline_backend,
        "pdf_quality": None,
        "documents": _serialize_inline_preview_documents(documents),
        "provenance": _sanitize_preview_value(provenance),
    }


@dataclass
class PreviewDocumentFormFields:
    parser_backend: str = Form(settings.DEFAULT_PARSER_BACKEND)
    chunk_strategy: str = Form(settings.DEFAULT_CHUNK_STRATEGY)
    dataset_id: str | None = Form(None)
    pipeline: str | None = Form(None)


@dataclass
class PreviewDocumentGovernanceOverridesFormFields:
    governance_enabled: bool | None = Form(None)
    governance_remove_toc_lines: bool | None = Form(None)
    governance_remove_noise_lines: bool | None = Form(None)
    governance_unwrap_lines: bool | None = Form(None)
    governance_remove_common_lines: bool | None = Form(None)
    governance_unwrap_max_line_length: int | None = Form(None)
    governance_noise_min_chars: int | None = Form(None)
    governance_noise_ratio_threshold: float | None = Form(None)
    governance_common_lines_min_docs: int | None = Form(None)
    governance_common_lines_min_ratio: float | None = Form(None)


@router.post("/preview", response_model=DocumentParsePreview, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def preview_document(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    form: Annotated[PreviewDocumentFormFields, Depends()],
    gov_overrides_form: Annotated[PreviewDocumentGovernanceOverridesFormFields, Depends()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Document parse preview endpoint.

    Only parses the document and returns structured segments; does not create
    a document record or persist data. Useful for frontend custom chunking.
    """
    from app.api.v1 import documents as documents_module  # Local import to avoid router circular import.

    DatasetService.ensure_member(db, tenant_id, account_id)
    file.filename = documents_module._sanitize_filename(file.filename)

    parser_backend = form.parser_backend
    dataset_id = form.dataset_id
    pipeline = form.pipeline

    pipeline_overrides = documents_module.PipelineOptionOverrides(**asdict(gov_overrides_form))
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}",
        )

    upload_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    upload_dir.mkdir(parents=True, exist_ok=True)

    run_dir = upload_dir / uuid.uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=True)
    temp_path = run_dir / f"input{file_ext}"
    artifact_dirs: set[str] = set()

    try:
        file_size = await save_upload_file(file, temp_path, max_bytes=settings.MAX_FILE_SIZE)

        if _should_inline_preview_parse(file_ext):
            resolved_text_backend = parser_factory.resolve_backend(file_ext, parser_backend)
            parsed = _parse_inline_text_preview(
                source_path=temp_path,
                resolved_backend=resolved_text_backend,
                tenant_id=tenant_id,
                requested_backend=parser_backend,
            )
        else:
            parsed = await documents_module.run_subprocess_worker(
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
                timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
            )
        documents = [
            Document(
                page_content=str(item.get("page_content") or ""),
                metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                id=item.get("id") if isinstance(item.get("id"), str) else None,
            )
            for item in (parsed.get("documents") or [])
            if isinstance(item, dict)
        ]
        resolved_backend = str(parsed.get("resolved_backend") or parser_backend)
        pdf_quality = parsed.get("pdf_quality") if isinstance(parsed.get("pdf_quality"), dict) else None
        for doc in documents:
            artifact_dir = (doc.metadata or {}).get("artifact_dir")
            if isinstance(artifact_dir, str) and artifact_dir.strip():
                artifact_dirs.add(artifact_dir.strip())

        dataset_meta: dict = {}
        if dataset_id:
            try:
                ds = DatasetService.get_dataset(db, tenant_id, UUID(str(dataset_id)))
                DatasetService.assert_dataset_readable(db, ds, account_id)
                dataset_meta = dict(getattr(ds, "dataset_metadata", None) or {})
            except HTTPException:
                raise
            except Exception:
                dataset_meta = {}

        pipeline_options = documents_module._to_pipeline_options(
            pipeline=documents_module._parse_pipeline_json(pipeline),
            overrides=pipeline_overrides,
        )
        pipeline_effective = resolve_pipeline_effective(
            dataset_metadata=dataset_meta,
            document_metadata={},
            request_overrides=pipeline_options,
        )

        raw_markdown = "\n\n".join([(d.page_content or "") for d in documents])
        raw_analytics = compute_document_analytics(
            markdown=raw_markdown,
            documents=documents,
            pdf_quality=pdf_quality,
            detect_language=bool(pipeline_effective.governance_detect_language),
            language_min_chars=int(pipeline_effective.governance_language_min_chars or 0),
        ).to_dict()

        if pipeline_effective.governance_enabled:
            extra_rules = list(getattr(pipeline_effective, "governance_regex_rules", None) or [])
            combined_rules = build_governance_rules(extra_rules) if extra_rules else None
            governance_kwargs = {
                **({"rules": combined_rules} if combined_rules else {}),
                "remove_toc_lines": pipeline_effective.governance_remove_toc_lines,
                "remove_noise_lines": pipeline_effective.governance_remove_noise_lines,
                "unwrap_lines": pipeline_effective.governance_unwrap_lines,
                "remove_common_lines": pipeline_effective.governance_remove_common_lines,
                "remove_boilerplate": pipeline_effective.governance_remove_boilerplate,
                "remove_images": pipeline_effective.governance_remove_images,
                "extract_frontmatter": pipeline_effective.governance_extract_frontmatter,
                "strip_frontmatter": pipeline_effective.governance_strip_frontmatter,
                "detect_language": pipeline_effective.governance_detect_language,
                "language_min_chars": pipeline_effective.governance_language_min_chars,
                "normalize_urls": pipeline_effective.governance_normalize_urls,
                "normalize_urls_strip_tracking": pipeline_effective.governance_normalize_urls_strip_tracking,
                "drop_duplicate_paragraphs": pipeline_effective.governance_drop_duplicate_paragraphs,
                "drop_duplicate_paragraphs_min_occurrences": pipeline_effective.governance_drop_duplicate_paragraphs_min_occurrences,
                "drop_duplicate_paragraphs_min_chars": pipeline_effective.governance_drop_duplicate_paragraphs_min_chars,
                "drop_duplicate_paragraphs_max_chars": pipeline_effective.governance_drop_duplicate_paragraphs_max_chars,
                "trim_references": pipeline_effective.governance_trim_references,
                "extract_keywords": pipeline_effective.governance_extract_keywords,
                "keywords_provider": pipeline_effective.governance_keywords_provider,
                "keywords_top_k": pipeline_effective.governance_keywords_top_k,
                "keywords_max_chars": pipeline_effective.governance_keywords_max_chars,
                "normalize_tables": pipeline_effective.governance_normalize_tables,
                "strip_code_line_numbers": pipeline_effective.governance_strip_code_line_numbers,
                "pii_anonymize": pipeline_effective.governance_pii_anonymize,
                "pii_mode": pipeline_effective.governance_pii_mode,
                "pii_mask": pipeline_effective.governance_pii_mask,
                "secrets_redact": pipeline_effective.governance_secrets_redact,
                "secrets_mode": pipeline_effective.governance_secrets_mode,
                "secrets_mask": pipeline_effective.governance_secrets_mask,
                "max_blank_lines": pipeline_effective.governance_max_blank_lines,
                "drop_outline_only": pipeline_effective.governance_drop_outline_only,
                "drop_outline_min_content_chars": pipeline_effective.governance_drop_outline_min_content_chars,
                "drop_outline_max_heading_ratio": pipeline_effective.governance_drop_outline_max_heading_ratio,
                "drop_low_density": pipeline_effective.governance_drop_low_density,
                "drop_low_density_threshold": pipeline_effective.governance_drop_low_density_threshold,
                "unwrap_max_line_length": pipeline_effective.governance_unwrap_max_line_length,
                "noise_min_chars": pipeline_effective.governance_noise_min_chars,
                "noise_ratio_threshold": pipeline_effective.governance_noise_ratio_threshold,
                "common_lines_min_docs": pipeline_effective.governance_common_lines_min_docs,
                "common_lines_min_ratio": pipeline_effective.governance_common_lines_min_ratio,
            }
            documents, _stats = documents_module.governance_processor.clean_documents(
                documents,
                **governance_kwargs,
            )

        cleaned_markdown = "\n\n".join([(d.page_content or "") for d in documents])
        cleaned_analytics = compute_document_analytics(
            markdown=cleaned_markdown,
            documents=documents,
            pdf_quality=pdf_quality,
            detect_language=bool(pipeline_effective.governance_detect_language),
            language_min_chars=int(pipeline_effective.governance_language_min_chars or 0),
        ).to_dict()

        segments: list[ParsedSegment] = []
        for idx, doc in enumerate(documents):
            segments.append(
                ParsedSegment(
                    index=idx,
                    content=doc.page_content,
                    page_number=doc.metadata.get("page"),
                    metadata=doc.metadata or {},
                )
            )

        return DocumentParsePreview(
            filename=file.filename,
            file_type=file_ext.lstrip("."),
            file_size=file_size,
            segments=segments,
            parser_backend=resolved_backend,
            analytics={"raw": raw_analytics, "cleaned": cleaned_analytics},
        )
    except SubprocessCancelled:
        raise HTTPException(status_code=499, detail="Client closed request") from None
    except SubprocessWorkerError as exc:
        err_type = (exc.details or {}).get("type")
        if err_type == "ValueError":
            raise HTTPException(status_code=400, detail=f"Invalid input: {str(exc)[:100]}") from exc
        documents_module.logger.error("Subprocess worker failed during preview: %s", str(exc)[:200])
        msg = (str(exc) or "").strip()
        if not msg:
            details = exc.details or {}
            msg = str(details.get("message") or details.get("type") or exc.__class__.__name__).strip()
        msg = msg[:200]
        detail = "Failed to parse document" if is_production_env() else f"Failed to parse document: {msg}"
        raise HTTPException(status_code=500, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid input: {str(exc)[:100]}") from exc
    except IOError as exc:
        documents_module.logger.error("File read error during preview: %s", str(exc)[:200])
        raise HTTPException(status_code=500, detail="File read error") from exc
    except HTTPException:
        raise
    except Exception as exc:
        documents_module.logger.error("Unexpected error during document preview: %s", str(exc)[:200])
        msg = (str(exc) or "").strip()
        if not msg:
            msg = exc.__class__.__name__
        msg = msg[:200]
        detail = "Failed to parse document" if is_production_env() else f"Failed to parse document: {msg}"
        raise HTTPException(status_code=500, detail=detail) from exc
    finally:
        try:
            if run_dir.exists():
                shutil.rmtree(run_dir, ignore_errors=True)
        except OSError as exc:
            documents_module.logger.warning("Failed to clean up preview directory %s: %s", run_dir, exc)

        if artifact_dirs and not bool(getattr(settings, "MAGIC_PDF_KEEP_ARTIFACTS", False)):
            upload_root = Path(settings.UPLOAD_DIR).resolve(strict=False)
            tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)
            for raw in sorted(artifact_dirs):
                try:
                    path = Path(raw).resolve(strict=False)
                    if not path.exists():
                        continue
                    if not any(
                        part in path.parts
                        for part in {".magicpdf", ".deepseek_ocr", ".qianfan_ocr", ".etl4llm", ".marker", ".paddlevl", ".olmocr"}
                    ):
                        continue
                    path.relative_to(tenant_root)
                except Exception:
                    get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                    continue
                with contextlib.suppress(Exception):
                    shutil.rmtree(path, ignore_errors=True)
