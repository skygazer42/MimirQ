"""
Lightweight parsing and hierarchical chunk preview APIs:
- /pipeline/parse-preview: route parsing by file type
  (auto/Pandoc/MarkItDown/DeepDoc/MinerU/...), return Markdown + image refs
- /pipeline/chunk-preview: hierarchical Markdown chunking (paragraph/sentence) with highlight offsets
"""

import json
import re
import shutil
import uuid
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.governance_profile import (
    BuiltinProcessingScriptListResponse,
    BuiltinProcessingScriptOut,
    GovernanceProfileCreate,
    GovernanceProfileImportResponse,
    GovernanceProfileListResponse,
    GovernanceProfileOut,
    GovernanceProfileResolvedResponse,
    GovernanceProfileSummary,
    GovernanceProfileUpdate,
)
from app.api.schemas.ingestion_policy import IngestionPolicy, IngestionRule
from app.api.schemas.pipeline import (
    AutoAnnotationRequest,
    AutoAnnotationResponse,
    CleanPreviewRequest,
    CleanPreviewResponse,
    CleanRegexRuleModel,
    CleanRulesResponse,
    GovernanceAnalyzeRequest,
    GovernanceAnalyzeResponse,
    GovernanceCommonLineCandidate,
    GovernanceCommonLinesLearnRequest,
    GovernanceCommonLinesLearnResponse,
    IngestionPreviewResponse,
    KeywordExtractRequest,
    KeywordExtractResponse,
    LLMCleanPreviewRequest,
    LLMCleanPreviewResponse,
    ParsePreviewResponse,
    PipelineCapabilitiesResponse,
    PipelineChunkPreviewRequest,
    PipelineChunkPreviewResponse,
    PipelinePluginChunkReportRequest,
    PipelinePluginChunkReportResponse,
    PipelinePluginGoldenDraftImportRequest,
    PipelinePluginGoldenDraftImportResponse,
    PipelinePluginGoldenDraftRequest,
    PipelinePluginGoldenDraftResponse,
    PipelinePluginListResponse,
    ZipWithImagesResponse,
)
from app.api.utils.response_headers import download_response_headers
from app.api.utils.upload import save_upload_file
from app.api.v1.pipeline_support.auto_annotations import (
    _AutoAnnotationDraft,
    _collect_common_lines_texts,
    _collect_compliance_annotations,
    _collect_document_focus_annotations,
    _dedupe_auto_annotations,
    _dedupe_auto_document_tags,
    _derive_document_tags_from_annotations,
    _finalize_auto_annotation_keyword_provider,
    _normalize_auto_annotation_providers,
)
from app.api.v1.pipeline_support.capabilities import (
    _pipeline_chunk_strategy_info,
    _pipeline_parser_backend_info,
)
from app.api.v1.pipeline_support.clean_preview import (
    _PIPELINE_FALLBACK_LOG_MESSAGE,
    _analyze_governance_preview,
    _apply_preview_cleanup_stats,
    _apply_preview_format_transforms,
    _apply_preview_sensitive_redaction,
    _build_clean_preview_response,
    _build_clean_preview_rules,
    _clean_preview_rule_stats,
    _CleanPreviewResponseContext,
    _detect_preview_language,
    _extract_clean_preview_frontmatter,
    _extract_governance_input_text,
    _extract_preview_keywords,
    _extract_preview_title,
    _governance_analysis_options,
    _parse_llm_clean_response,
    _preview_drop_reason,
    _request_llm_clean_preview,
    _resolve_llm_clean_prompt_selection,
)
from app.api.v1.pipeline_support.governance_profiles import (
    GOVERNANCE_PROFILE_NOT_FOUND_DETAIL as GOVERNANCE_PROFILE_NOT_FOUND_DETAIL,
)
from app.api.v1.pipeline_support.governance_profiles import (
    _normalize_governance_profile_import_record,
    _profile_out_from_row,
    _profile_summary_from_row,
    _raw_governance_profile_import_items,
    _read_governance_profile_import_json,
    _resolve_custom_profile_row,
    _resolve_profile_ref,
    _upsert_governance_profile_import_record,
)
from app.api.v1.pipeline_support.ingestion_preview import (
    _build_ingestion_clean_preview_request,
    _dataset_metadata_dict,
    _ingestion_preview_defaults,
    _ingestion_preview_explain,
    _ingestion_preview_rule_output,
    _ingestion_rule_preprocess_steps,
    _IngestionPreviewConfig,
    _preprocess_ingestion_preview_file,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.pipeline_versions import build_doc_pipeline_key, get_active_pipeline_hash
from app.core.regex_runtime import RegexSubstitutionTimeoutError
from app.core.regex_safety import RegexRulesValidationError
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.models.governance_profile import GovernanceProfile as DBGovernanceProfile
from app.parsing.backends import normalize_parser_backend
from app.parsing.factory import ParserFactory
from app.parsing.subprocess_runner import SubprocessCancelled, SubprocessWorkerError, run_subprocess_worker
from app.parsing.utils.zip_processor import zip_image_processor
from app.rag.chunking import chunker_factory, hierarchical_chunk_markdown
from app.rag.core.logging import get_logger
from app.rag.pipeline_plugins.golden_drafts import build_golden_draft_bundle_from_chunks
from app.rag.pipeline_plugins.registry import (
    PipelinePluginRegistryError,
    default_plugin_directories,
    list_pipeline_plugins_with_errors,
    resolve_registered_plugin_descriptor,
)
from app.rag.pipeline_plugins.reports import (
    build_pipeline_plugin_chunk_report as build_pipeline_plugin_chunk_report_data,
)
from app.rag.preprocessing.cleaning import (
    build_repeated_line_signatures,
    clean_markdown,
    learn_common_line_candidates,
)
from app.rag.preprocessing.rules import DEFAULT_MARKDOWN_RULES
from app.services.dataset_service import DatasetService
from app.services.governance_processing_scripts import list_builtin_processing_scripts
from app.services.governance_profiles import (
    get_builtin_governance_profiles,
    validate_and_normalize_payload,
    validate_profile_key,
)
from app.services.governance_profiles_resolver import resolve_governance_profile_ref_effective
from app.services.ingestion_policy import export_policy_json, match_ingestion_rule, parse_ingestion_policy_from_metadata
from app.services.pipeline_config import resolve_pipeline_effective
from app.types.pipeline import PipelineOptions

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)

_BUILTIN_GOVERNANCE_PROFILES = get_builtin_governance_profiles()
_BUILTIN_GOVERNANCE_BY_KEY = {p.key: p for p in _BUILTIN_GOVERNANCE_PROFILES}
_BUILTIN_PROCESSING_SCRIPTS = list_builtin_processing_scripts()


def _safe_pipeline_plugin_error_path(path: Path | None, roots: Iterable[Path]) -> str:
    if path is None:
        return ""
    try:
        resolved = path.expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return path.name or str(path)

    for root in sorted((Path(item).expanduser() for item in roots), key=lambda item: len(str(item)), reverse=True):
        try:
            rel = resolved.relative_to(root.resolve())
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        rel_text = rel.as_posix()
        return rel_text if rel_text and rel_text != "." else resolved.name
    return resolved.name


@router.get(
    "/plugins",
    dependencies=[Depends(get_current_account_id)],
    response_model=PipelinePluginListResponse,
    response_model_exclude_none=True,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def list_pipeline_plugins_endpoint():
    """
    List registered local pipeline plugins.

    Plugins become executable only after their package manifest is published and
    the local runner report matches the current package hash.
    """
    plugins, errors = list_pipeline_plugins_with_errors()
    plugin_roots = default_plugin_directories()
    items = []
    for plugin in plugins:
        items.append(
            {
                "id": plugin.id,
                "version": plugin.version,
                "name": plugin.name,
                "description": plugin.description,
                "published": plugin.published,
                "executable": plugin.executable,
                "test_status": plugin.test_status,
                "package_hash": plugin.package_hash,
                "test_report": plugin.test_report,
                "stages": sorted(plugin.entries.keys()),
                "refs": plugin.refs,
                "contract": plugin.contract_summary,
                "processing_templates": plugin.processing_templates,
                "suggested_pipeline_patch": plugin.suggested_pipeline_patch,
            }
        )
    return {
        "items": items,
        "errors": [
            {
                "plugin_dir": _safe_pipeline_plugin_error_path(error.plugin_dir, plugin_roots),
                "manifest_path": _safe_pipeline_plugin_error_path(error.manifest_path, plugin_roots),
                "error": error.error,
            }
            for error in errors
        ],
    }


def _plugin_marker_refs(plugin_ref: str, descriptor: Any) -> set[str]:
    refs = {str(plugin_ref or "").strip()}
    raw_refs = getattr(descriptor, "refs", {}) or {}
    if isinstance(raw_refs, dict):
        refs.update(str(value or "").strip() for value in raw_refs.values())
    return {ref for ref in refs if ref}


def _assert_pipeline_plugin_executable(plugin_ref: str, descriptor: Any) -> None:
    if getattr(descriptor, "published", True) is not True or getattr(descriptor, "executable", True) is not True:
        plugin_id = str(getattr(descriptor, "id", "") or plugin_ref)
        version = str(getattr(descriptor, "version", "") or "")
        status = str(getattr(descriptor, "test_status", "") or "unknown")
        qualified = f"{plugin_id}@{version}" if version else plugin_id
        raise HTTPException(
            status_code=409,
            detail=f"plugin '{qualified}' is not executable; local test report status is {status}",
        )


def _assert_pipeline_plugin_ready_for_golden(plugin_ref: str, descriptor: Any) -> None:
    _assert_pipeline_plugin_executable(plugin_ref, descriptor)


def _resolve_plugin_relative_input_path(plugin_dir: Path, input_path: str) -> Path:
    raw = str(input_path or "").strip() or "sample.json"
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise HTTPException(status_code=400, detail="input_path must stay inside the plugin directory")
    try:
        plugin_root = plugin_dir.expanduser().resolve()
        resolved = (plugin_root / candidate).resolve()
        resolved.relative_to(plugin_root)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="input_path must stay inside the plugin directory") from exc
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="plugin chunk report input_path not found")
    return resolved


@router.post(
    "/plugins/chunk-report",
    response_model=PipelinePluginChunkReportResponse,
    response_model_by_alias=True,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def build_pipeline_plugin_chunk_report_endpoint(
    payload: PipelinePluginChunkReportRequest,
    *,
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> PipelinePluginChunkReportResponse:
    """
    Build a review-only governance/chunk/KG report for a registered plugin sample.

    The sample path is scoped to the plugin directory. This API executes local
    plugin code, so callers select a registered plugin ref rather than arbitrary
    host paths.
    """
    _ = account_id
    try:
        descriptor = resolve_registered_plugin_descriptor(payload.plugin_ref)
    except PipelinePluginRegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_pipeline_plugin_executable(payload.plugin_ref, descriptor)
    input_path = _resolve_plugin_relative_input_path(descriptor.plugin_dir, payload.input_path)
    try:
        report = build_pipeline_plugin_chunk_report_data(
            descriptor.plugin_dir,
            input_path=input_path,
            max_examples_per_section=payload.max_examples_per_section,
            preview_chars=payload.preview_chars,
            governance_params=payload.governance_params,
            chunk_params=payload.chunk_params,
            kg_params=payload.kg_params,
            section_metadata_keys=tuple(payload.section_metadata_keys or ()),
            title_metadata_keys=tuple(payload.title_metadata_keys or ()),
            metadata_highlight_keys=tuple(payload.metadata_highlight_keys or ()),
        )
    except PipelinePluginRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"failed to build plugin chunk report: {exc}") from exc
    return PipelinePluginChunkReportResponse.model_validate(report)


def _assert_unmarked_plugin_golden_chunks_allowed(include_unmarked_chunks: bool) -> None:
    if not include_unmarked_chunks:
        return
    if bool(getattr(settings, "PYTHON_PIPELINE_PLUGIN_ALLOW_UNMARKED_GOLDEN_CHUNKS", False)):
        return
    raise HTTPException(
        status_code=400,
        detail=(
            "include_unmarked_chunks requires "
            "PYTHON_PIPELINE_PLUGIN_ALLOW_UNMARKED_GOLDEN_CHUNKS=true; "
            "plugin Golden drafts normally use only chunks produced by the selected plugin"
        ),
    )


def _chunk_marked_by_plugin(meta: dict[str, Any], plugin_refs: set[str]) -> bool:
    if not plugin_refs:
        return False
    for key in ("chunk_python_plugin", "governance_python_plugin"):
        value = str(meta.get(key) or "").strip()
        if value and value in plugin_refs:
            return True
    return False


def _active_doc_pipeline_key(document_id: UUID, doc_metadata: dict[str, Any]) -> str | None:
    active_hash = get_active_pipeline_hash(doc_metadata)
    return build_doc_pipeline_key(document_id, active_hash) if active_hash else None


def _chunk_matches_active_pipeline(chunk_meta: dict[str, Any], active_key: str | None) -> bool:
    if not active_key:
        return True
    chunk_key = str(chunk_meta.get("doc_pipeline_key") or "").strip()
    return not chunk_key or chunk_key == active_key


def _load_plugin_golden_draft_chunks(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    plugin_refs: set[str],
    max_chunks: int,
    include_unmarked_chunks: bool = False,
) -> list[DocumentChunk]:
    cap = max(1, min(50_000, int(max_chunks or 5000)))
    rows = (
        db.query(DocumentChunk, DBDocument)
        .join(
            DBDocument,
            and_(DBDocument.id == DocumentChunk.document_id, DBDocument.tenant_id == DocumentChunk.tenant_id),
        )
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.status == "completed",
            DBDocument.publication_status == "published",
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
            DocumentChunk.disabled_at.is_(None),
        )
        .order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
        .limit(cap)
        .all()
    )
    chunks: list[DocumentChunk] = []
    for chunk, document in rows:
        chunk_meta = dict(getattr(chunk, "doc_metadata", None) or {})
        if not include_unmarked_chunks and not _chunk_marked_by_plugin(chunk_meta, plugin_refs):
            continue
        doc_meta = dict(getattr(document, "doc_metadata", None) or {})
        if not _chunk_matches_active_pipeline(chunk_meta, _active_doc_pipeline_key(document.id, doc_meta)):
            continue
        chunks.append(chunk)
    return chunks


def _build_plugin_golden_draft_response(
    *,
    dataset_id: UUID,
    plugin_ref: str,
    descriptor: Any,
    chunks: Iterable[DocumentChunk],
    max_items: int,
) -> PipelinePluginGoldenDraftResponse:
    plugin_id = str(getattr(descriptor, "id", ""))
    bundle = build_golden_draft_bundle_from_chunks(
        dataset_id=dataset_id,
        chunks=chunks,
        golden_rules=getattr(descriptor, "golden_rules", {}) or {},
        plugin_id=plugin_id,
        plugin_version=str(getattr(descriptor, "version", "")),
        plugin_ref=plugin_ref,
        plugin_package_hash=str(getattr(descriptor, "package_hash", "")),
        max_items=max_items,
    )
    return PipelinePluginGoldenDraftResponse(
        dataset_id=dataset_id,
        plugin_id=plugin_id,
        plugin_version=str(getattr(descriptor, "version", "")),
        plugin_ref=plugin_ref,
        items_total=len(bundle.get("items") or []),
        bundle=bundle,
    )


async def _import_plugin_golden_draft_bundle(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    bundle: dict[str, Any],
    overwrite: bool,
    max_items: int,
) -> dict[str, Any]:
    items = bundle.get("items") if isinstance(bundle, dict) else []
    if not isinstance(items, list) or not items:
        return {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [],
            "created_case_ids": [],
            "updated_case_ids": [],
            "case_ids": [],
        }

    from app.api.schemas.regression import RagasRegressionCaseImportRequest
    from app.api.v1.evaluations import import_ragas_regression_cases

    payload = RagasRegressionCaseImportRequest(
        dataset_id=dataset_id,
        overwrite=bool(overwrite),
        max_items=max(1, min(2000, int(max_items or 500))),
        items=items,
    )
    result = await import_ragas_regression_cases(
        payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    return result if isinstance(result, dict) else dict(result)


@router.post(
    "/plugins/golden-draft",
    response_model=PipelinePluginGoldenDraftResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def build_pipeline_plugin_golden_draft(
    payload: PipelinePluginGoldenDraftRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> PipelinePluginGoldenDraftResponse:
    """
    Build a review-only regression case bundle from chunks produced by a plugin.

    This endpoint does not import or persist golden cases. Review the returned
    bundle, then import it through the regression case import API or the
    pipeline-side golden-draft/import helper.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = DatasetService.get_dataset(db, tenant_id, payload.dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    try:
        descriptor = resolve_registered_plugin_descriptor(payload.plugin_ref)
    except PipelinePluginRegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_pipeline_plugin_ready_for_golden(payload.plugin_ref, descriptor)
    _assert_unmarked_plugin_golden_chunks_allowed(payload.include_unmarked_chunks)

    chunks = _load_plugin_golden_draft_chunks(
        db=db,
        tenant_id=tenant_id,
        dataset_id=payload.dataset_id,
        plugin_refs=_plugin_marker_refs(payload.plugin_ref, descriptor),
        max_chunks=payload.max_chunks,
        include_unmarked_chunks=payload.include_unmarked_chunks,
    )
    return _build_plugin_golden_draft_response(
        dataset_id=payload.dataset_id,
        plugin_ref=payload.plugin_ref,
        descriptor=descriptor,
        chunks=chunks,
        max_items=payload.max_items,
    )


@router.post(
    "/plugins/golden-draft/import",
    response_model=PipelinePluginGoldenDraftImportResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def import_pipeline_plugin_golden_draft(
    payload: PipelinePluginGoldenDraftImportRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> PipelinePluginGoldenDraftImportResponse:
    """Build a plugin golden draft bundle and import it into regression cases."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = DatasetService.get_dataset(db, tenant_id, payload.dataset_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)

    try:
        descriptor = resolve_registered_plugin_descriptor(payload.plugin_ref)
    except PipelinePluginRegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_pipeline_plugin_ready_for_golden(payload.plugin_ref, descriptor)
    _assert_unmarked_plugin_golden_chunks_allowed(payload.include_unmarked_chunks)

    chunks = _load_plugin_golden_draft_chunks(
        db=db,
        tenant_id=tenant_id,
        dataset_id=payload.dataset_id,
        plugin_refs=_plugin_marker_refs(payload.plugin_ref, descriptor),
        max_chunks=payload.max_chunks,
        include_unmarked_chunks=payload.include_unmarked_chunks,
    )
    draft = _build_plugin_golden_draft_response(
        dataset_id=payload.dataset_id,
        plugin_ref=payload.plugin_ref,
        descriptor=descriptor,
        chunks=chunks,
        max_items=payload.max_items,
    )
    import_result = await _import_plugin_golden_draft_bundle(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=payload.dataset_id,
        bundle=draft.bundle,
        overwrite=payload.overwrite,
        max_items=payload.max_items,
    )
    return PipelinePluginGoldenDraftImportResponse(draft=draft, import_result=import_result)


@router.get(
    "/capabilities",
    response_model=PipelineCapabilitiesResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_pipeline_capabilities(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Return available parsers and chunking strategies for the frontend.

    Note: only availability info is returned (no sensitive config like API keys).
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    default_parser_backend = (
        normalize_parser_backend(getattr(settings, "DEFAULT_PARSER_BACKEND", "auto") or "auto") or "auto"
    )
    default_chunk_strategy = (
        (getattr(settings, "DEFAULT_CHUNK_STRATEGY", "langchain_recursive") or "langchain_recursive").strip().lower()
    )

    pdf_backends = [_pipeline_parser_backend_info(name) for name in sorted(ParserFactory.SUPPORTED_PDF_BACKENDS)]

    # Expose all strategies known to the backend (frontends may choose a subset).
    all_strats = set(chunker_factory.SUPPORTED_STRATEGIES.keys()) | set(chunker_factory.INTEGRATED_PIPELINE_STRATEGIES)
    chunk_strategies = [_pipeline_chunk_strategy_info(name) for name in sorted(all_strats)]

    return PipelineCapabilitiesResponse(
        default_parser_backend=default_parser_backend,
        default_chunk_strategy=default_chunk_strategy,
        pdf_backends=pdf_backends,
        chunk_strategies=chunk_strategies,
    )


@router.get(
    "/governance-profiles",
    response_model=GovernanceProfileListResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def list_governance_profiles(
    q: str | None = None,
    include_builtin: bool = True,
    limit: int = 200,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    List governance profiles (built-in + tenant custom profiles).

    Notes:
    - Built-in profiles are shipped in code (read-only).
    - Custom profiles are stored in DB (tenant-scoped).
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = (q or "").strip().lower()
    items: list[GovernanceProfileSummary] = []
    builtin_count = 0

    if include_builtin:
        for p in _BUILTIN_GOVERNANCE_PROFILES:
            if query and query not in (p.name.lower() + " " + p.description.lower()):
                continue
            items.append(
                GovernanceProfileSummary(
                    id=None,
                    key=p.key,
                    name=p.name,
                    description=p.description,
                    is_system=True,
                )
            )
        builtin_count = len(items)

    q_db = db.query(DBGovernanceProfile).filter(DBGovernanceProfile.tenant_id == tenant_id)
    if query:
        like = f"%{query}%"
        # Avoid depending on database-specific full-text features.
        q_db = q_db.filter(
            (DBGovernanceProfile.name.ilike(like))
            | (DBGovernanceProfile.description.ilike(like))
            | (DBGovernanceProfile.key.ilike(like))
        )

    total_custom = int(q_db.count() or 0)
    rows = q_db.order_by(DBGovernanceProfile.updated_at.desc()).limit(min(int(limit or 200), 200)).all()
    items.extend([_profile_summary_from_row(r) for r in rows])

    return GovernanceProfileListResponse(total=(builtin_count + total_custom), items=items)


@router.get(
    "/governance-processing-scripts/builtins",
    response_model=BuiltinProcessingScriptListResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def list_builtin_processing_scripts_endpoint(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
):
    """
    List built-in processing script templates exposed on the 重复行学习 page.

    Notes:
    - Templates are read-only and shipped in code.
    - Per ``GovernanceProcessingScript`` schema, scripts are persisted with a
      governance profile only for review/versioning; the ingestion pipeline does
      not execute them. Templates are reference code customers can copy as a
      starting point.
    """
    items = [
        BuiltinProcessingScriptOut(
            key=s.key,
            name=s.name,
            description=s.description,
            language=s.language,
            stage=s.stage,
            content=s.content,
            tags=list(s.tags),
        )
        for s in _BUILTIN_PROCESSING_SCRIPTS
    ]
    return BuiltinProcessingScriptListResponse(total=len(items), items=items)


@router.post(
    "/governance-profiles",
    response_model=GovernanceProfileOut,
    status_code=201,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def create_governance_profile(
    body: GovernanceProfileCreate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    name = str(body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    try:
        key = validate_profile_key(body.key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if key:
        exists = (
            db.query(DBGovernanceProfile.id)
            .filter(DBGovernanceProfile.tenant_id == tenant_id, DBGovernanceProfile.key == key)
            .first()
        )
        if exists:
            raise HTTPException(status_code=409, detail="profile key already exists")

    try:
        payload = validate_and_normalize_payload(body.payload)
    except RegexRulesValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.to_detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row = DBGovernanceProfile(
        tenant_id=tenant_id,
        key=key,
        name=name[:200],
        description=(str(body.description).strip()[:2000] if body.description is not None else None),
        is_system=False,
        payload=payload.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _profile_out_from_row(row)


@router.get(
    "/governance-profiles/{profile_ref}",
    response_model=GovernanceProfileOut,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_governance_profile(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    return _resolve_profile_ref(
        db=db,
        tenant_id=tenant_id,
        profile_ref=profile_ref,
        builtin_by_key=_BUILTIN_GOVERNANCE_BY_KEY,
    )


@router.get(
    "/governance-profiles/{profile_ref}/resolved",
    response_model=GovernanceProfileResolvedResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_governance_profile_resolved(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    try:
        resolved = resolve_governance_profile_ref_effective(
            db=db,
            tenant_id=tenant_id,
            profile_ref=profile_ref,
        )
    except ValueError as exc:
        msg = str(exc) or "invalid profile_ref"
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=400, detail=msg) from exc

    return GovernanceProfileResolvedResponse(
        profile=resolved.profile,
        chain=resolved.chain,
        effective=resolved.effective,
    )


@router.patch(
    "/governance-profiles/{profile_ref}",
    response_model=GovernanceProfileOut,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def update_governance_profile(
    profile_ref: str,
    body: GovernanceProfileUpdate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = _resolve_custom_profile_row(
        db=db,
        tenant_id=tenant_id,
        profile_ref=profile_ref,
        builtin_by_key=_BUILTIN_GOVERNANCE_BY_KEY,
    )

    if body.name is not None:
        name = str(body.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name must not be empty")
        row.name = name[:200]

    if body.description is not None:
        desc = str(body.description or "").strip()
        row.description = desc[:2000] if desc else None

    if body.payload is not None:
        try:
            payload = validate_and_normalize_payload(body.payload)
        except RegexRulesValidationError as exc:
            raise HTTPException(status_code=400, detail=exc.to_detail()) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row.payload = payload.model_dump()

    db.commit()
    db.refresh(row)
    return _profile_out_from_row(row)


@router.delete("/governance-profiles/{profile_ref}", status_code=204, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def delete_governance_profile(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = _resolve_custom_profile_row(
        db=db,
        tenant_id=tenant_id,
        profile_ref=profile_ref,
        builtin_by_key=_BUILTIN_GOVERNANCE_BY_KEY,
    )

    db.delete(row)
    db.commit()
    return None


@router.post(
    "/governance-profiles/import",
    response_model=GovernanceProfileImportResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def import_governance_profiles(
    file: Annotated[UploadFile, File(...)],
    overwrite: Annotated[bool, Form()] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Import governance profile scripts (JSON).

    Security:
    - Only declarative JSON is accepted (no executable code).
    - Strong validation on regex rules and option keys is applied server-side.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    raw_profiles = _raw_governance_profile_import_items(await _read_governance_profile_import_json(file))
    created = 0
    updated = 0
    out_items: list[GovernanceProfileSummary] = []
    for item in raw_profiles:
        record = _normalize_governance_profile_import_record(item)
        created_delta, updated_delta, summary = _upsert_governance_profile_import_record(
            db=db,
            tenant_id=tenant_id,
            record=record,
            overwrite=bool(overwrite),
        )
        created += created_delta
        updated += updated_delta
        out_items.append(summary)

    db.commit()
    return GovernanceProfileImportResponse(created=created, updated=updated, items=out_items)


@router.get("/governance-profiles/{profile_ref}/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_governance_profile(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    profile = _resolve_profile_ref(
        db=db,
        tenant_id=tenant_id,
        profile_ref=profile_ref,
        builtin_by_key=_BUILTIN_GOVERNANCE_BY_KEY,
    )

    payload = profile.payload.model_dump()
    export_obj = {
        "name": profile.name,
        "description": profile.description,
        "key": profile.key,
        "payload": payload,
    }

    # Best-effort safe filename.
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(profile.key or "profile"))[:64]
    filename = f"{safe_key}.governance-profile.json"
    content = json.dumps(export_obj, ensure_ascii=False, indent=2).encode("utf-8")
    return Response(
        content=content,
        media_type="application/json",
        headers=download_response_headers(filename),
    )


@router.get(
    "/governance-profiles/{profile_ref}/export-ingestion-policy",
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def export_governance_profile_ingestion_policy(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Export a minimal, importable dataset ingestion policy that references the given governance profile.

    This "closes the loop" for operators: build custom governance profiles in the UI, then export
    an ingestion_policy JSON snippet to be imported into a dataset.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    profile = _resolve_profile_ref(
        db=db,
        tenant_id=tenant_id,
        profile_ref=profile_ref,
        builtin_by_key=_BUILTIN_GOVERNANCE_BY_KEY,
    )

    # Best-effort safe filename + rule id.
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(profile.key or "profile"))[:64] or "profile"
    filename = f"{safe_key}.ingestion_policy.json"

    # Match all files by default; operators can refine extensions/filename_regex after import.
    rule = IngestionRule(
        id=f"gov:{safe_key}"[:100],
        name=f"Governance: {str(profile.name or '').strip() or safe_key}"[:200],
        enabled=True,
        match={"extensions": []},
        preprocess={"enabled": False, "steps": []},
        governance_profile_ref=str(profile.key or "").strip() or None,
        pipeline_patch={},
    )

    policy = IngestionPolicy(version="1", rules=[rule])
    content = export_policy_json(policy)
    return Response(
        content=content,
        media_type="application/json",
        headers=download_response_headers(filename),
    )


@router.post("/parse-preview", response_model=ParsePreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def parse_preview(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    parser_backend: Annotated[str | None, Form()] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Parse a file into a Markdown preview without persisting it; extract inline images to uploads/{tenant}/images.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}",
        )

    # Save to a temporary path.
    preview_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    run_dir = preview_dir / uuid.uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=True)
    temp_path = run_dir / f"input{file_ext}"
    try:
        await save_upload_file(file, temp_path, max_bytes=settings.MAX_FILE_SIZE)

        result = await run_subprocess_worker(
            tenant_id=tenant_id,
            payload={
                "action": "pipeline_parse_preview",
                "tenant_id": str(tenant_id),
                "account_id": str(account_id),
                "file_path": str(temp_path),
                "parser_backend": parser_backend,
            },
            disconnect_check=request.is_disconnected,
            timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
        )
        return result
    except SubprocessCancelled:
        raise HTTPException(status_code=499, detail="Client closed request") from None
    except SubprocessWorkerError as e:
        err_type = (e.details or {}).get("type")
        if err_type == "ValueError":
            raise HTTPException(status_code=400, detail=str(e)) from e
        raise HTTPException(status_code=500, detail="Failed to parse preview") from e
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def _profile_pipeline_patch_for_ingestion(
    *,
    db: Session,
    tenant_id: UUID,
    profile_ref: str,
) -> dict[str, object]:
    prof = _resolve_profile_ref(
        db=db,
        tenant_id=tenant_id,
        profile_ref=profile_ref,
        builtin_by_key=_BUILTIN_GOVERNANCE_BY_KEY,
    )
    patch_dict = dict(prof.payload.pipeline_patch or {})
    rules = [rule.model_dump() for rule in (prof.payload.regex_rules or [])]
    if rules:
        patch_dict["governance_regex_rules"] = rules
    return patch_dict


def _resolve_ingestion_preview_config(
    *,
    matched_rule: object | None,
    parser_backend: str | None,
    chunk_strategy: str | None,
    db: Session,
    tenant_id: UUID,
) -> _IngestionPreviewConfig:
    default_pb, default_cs, base_pb, base_cs = _ingestion_preview_defaults(parser_backend, chunk_strategy)
    config = _IngestionPreviewConfig(
        base_parser_backend=base_pb,
        base_chunk_strategy=base_cs,
        parser_backend_choice=base_pb,
        chunk_strategy_choice=base_cs,
    )
    if matched_rule is None:
        return config

    if base_pb in {"", "auto", default_pb} and matched_rule.parser_backend:
        config.parser_backend_choice = str(matched_rule.parser_backend)
    if base_cs in {"", default_cs} and matched_rule.chunk_strategy:
        config.chunk_strategy_choice = str(matched_rule.chunk_strategy)

    config.preprocess_steps = _ingestion_rule_preprocess_steps(matched_rule)
    governance_profile_ref = getattr(matched_rule, "governance_profile_ref", None)
    if isinstance(governance_profile_ref, str) and governance_profile_ref.strip():
        config.governance_profile_ref = governance_profile_ref.strip()
        config.patch_dict.update(
            _profile_pipeline_patch_for_ingestion(
                db=db,
                tenant_id=tenant_id,
                profile_ref=config.governance_profile_ref,
            )
        )
    config.patch_dict.update(dict(getattr(matched_rule, "pipeline_patch", None) or {}))
    return config


@router.post("/ingestion-preview", response_model=IngestionPreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def ingestion_preview(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    dataset_id: Annotated[UUID, Form(...)],
    parser_backend: Annotated[str | None, Form()] = None,
    chunk_strategy: Annotated[str | None, Form()] = None,
    diff_max_lines: Annotated[int, Form()] = 2000,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    One-shot ingestion preview for a dataset:
    - match dataset ingestion policy
    - preprocess file (before parsing)
    - parse to Markdown (preview)
    - run governance clean preview (issues + unified diff)
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}",
        )

    preview_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    run_dir = preview_dir / uuid.uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=True)
    temp_path = run_dir / f"input{file_ext}"

    try:
        await save_upload_file(file, temp_path, max_bytes=settings.MAX_FILE_SIZE)

        dataset_meta = _dataset_metadata_dict(dataset)
        policy = parse_ingestion_policy_from_metadata(dataset_meta) or None
        matched_rule = match_ingestion_rule(policy, filename=file.filename, file_ext=file_ext)
        config = _resolve_ingestion_preview_config(
            matched_rule=matched_rule,
            parser_backend=parser_backend,
            chunk_strategy=chunk_strategy,
            db=db,
            tenant_id=tenant_id,
        )

        # Preprocess file (before parsing).
        parse_path, pre_summary = _preprocess_ingestion_preview_file(temp_path, config.preprocess_steps)

        # Compute effective governance options (dataset defaults + rule/profile patches).
        patch_opts = PipelineOptions(**config.patch_dict) if config.patch_dict else PipelineOptions()
        effective = resolve_pipeline_effective(
            dataset_metadata=dataset_meta,
            document_metadata={},
            request_overrides=patch_opts,
        )

        # Parse preview via subprocess worker.
        parsed = await run_subprocess_worker(
            tenant_id=tenant_id,
            payload={
                "action": "pipeline_parse_preview",
                "tenant_id": str(tenant_id),
                "account_id": str(account_id),
                "file_path": str(parse_path),
                "parser_backend": config.parser_backend_choice,
            },
            disconnect_check=request.is_disconnected,
            timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
        )

        # Governance clean preview (issues + diff).
        clean_body = _build_ingestion_clean_preview_request(
            parsed=parsed,
            effective=effective,
            diff_max_lines=diff_max_lines,
        )
        cleaned = clean_preview(body=clean_body, tenant_id=tenant_id, account_id=account_id, db=db)
        rule_out = _ingestion_preview_rule_output(matched_rule, config)
        explain = _ingestion_preview_explain(
            dataset_id=dataset_id,
            file=file,
            file_ext=file_ext,
            config=config,
            rule_out=rule_out,
            pre_summary=pre_summary,
            parsed=parsed,
        )

        return {
            "rule": rule_out,
            "preprocess": pre_summary,
            "parse": parsed,
            "clean": cleaned,
            "explain": explain,
        }
    except SubprocessCancelled:
        raise HTTPException(status_code=499, detail="Client closed request") from None
    except SubprocessWorkerError as e:
        err_type = (e.details or {}).get("type")
        if err_type == "ValueError":
            raise HTTPException(status_code=400, detail=str(e)) from e
        raise HTTPException(status_code=500, detail="Failed to parse preview") from e
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


@router.post("/chunk-preview", response_model=PipelineChunkPreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def chunk_preview(
    body: PipelineChunkPreviewRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Perform hierarchical chunking for Markdown text and return highlight offsets.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    chunks = hierarchical_chunk_markdown(body.markdown)
    return PipelineChunkPreviewResponse(**chunks)


@router.post(
    "/clean-preview",
    response_model=CleanPreviewResponse,
    response_model_exclude_none=True,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def clean_preview(
    body: CleanPreviewRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Preview governance-style cleaning for Markdown (no persistence) to compare before/after.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    input_text = _extract_governance_input_text(body)
    input_text, frontmatter, title, tags = _extract_clean_preview_frontmatter(input_text, body)
    baseline_text = input_text or ""

    analysis_opts = _governance_analysis_options(body)
    rules, rule_meta = _build_clean_preview_rules(body)
    common_lines = (
        build_repeated_line_signatures(
            baseline_text,
            min_occurrences=body.common_lines_min_occurrences,
            max_line_length=body.unwrap_max_line_length,
        )
        if body.remove_common_lines
        else None
    )
    try:
        result = clean_markdown(
            baseline_text,
            rules=rules,
            regex_timeout_ms=int(getattr(settings, "GOVERNANCE_REGEX_TIMEOUT_MS", 100) or 100),
            normalize_line_endings=body.normalize_line_endings,
            trim_trailing_spaces=body.trim_trailing_spaces,
            collapse_blank_lines=body.collapse_blank_lines,
            max_blank_lines=body.max_blank_lines,
            remove_control_chars=body.remove_control_chars,
            remove_toc_lines=body.remove_toc_lines,
            remove_noise_lines=body.remove_noise_lines,
            unwrap_lines=body.unwrap_lines,
            remove_common_lines=body.remove_common_lines,
            common_lines=common_lines,
            unwrap_max_line_length=body.unwrap_max_line_length,
            noise_min_chars=body.noise_min_chars,
            noise_ratio_threshold=body.noise_ratio_threshold,
        )
    except RegexSubstitutionTimeoutError as exc:
        raise HTTPException(status_code=400, detail=exc.to_detail()) from exc

    rule_hits = list(getattr(result, "rule_hits", None) or [])
    rule_stats = _clean_preview_rule_stats(rules, rule_meta, rule_hits)

    text = _apply_preview_format_transforms(result.markdown, body)
    text, pii_hits, secrets_hits = _apply_preview_sensitive_redaction(text, body)
    text, paragraphs_dropped, references_removed_lines, urls_changed = _apply_preview_cleanup_stats(text, body)
    response_context = _CleanPreviewResponseContext(
        baseline_text=baseline_text,
        body=body,
        clean_result=result,
        rule_stats=rule_stats,
        pii_hits=pii_hits,
        secrets_hits=secrets_hits,
        frontmatter=frontmatter,
        title=title,
        tags=tags,
        urls_changed=urls_changed,
        paragraphs_dropped=paragraphs_dropped,
        references_removed_lines=references_removed_lines,
        analysis_opts=analysis_opts,
    )

    drop_reason = _preview_drop_reason(text, body)
    if drop_reason is not None:
        return _build_clean_preview_response(
            response_context,
            markdown="",
            dropped=True,
            drop_reason=drop_reason,
        )

    response_context.title = _extract_preview_title(text, title)
    response_context.language, response_context.language_confidence = _detect_preview_language(text, body)
    response_context.keywords = _extract_preview_keywords(text, body)
    return _build_clean_preview_response(
        response_context,
        markdown=text,
        dropped=False,
        drop_reason=None,
    )


@router.post(
    "/learn-common-lines",
    response_model=GovernanceCommonLinesLearnResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def learn_common_lines(
    body: GovernanceCommonLinesLearnRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Learn common/repeated header/footer lines across multiple documents in a dataset.

    This endpoint is intended to support "learning mode" in the governance UI:
    discover candidate lines, then turn them into regex rules and write into a custom profile.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = DatasetService.get_dataset(db, tenant_id, body.dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    total, texts = _collect_common_lines_texts(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=body.dataset_id,
        limit_docs=int(body.limit_docs),
        use_original=bool(body.use_original),
    )

    if len(texts) < 2:
        raise HTTPException(
            status_code=400,
            detail=(
                "Not enough documents with persisted parsed content. "
                "Enable persist_parsed_content and ingest some documents first."
            ),
        )

    candidates_raw = learn_common_line_candidates(
        texts,
        min_docs=int(body.min_docs),
        min_ratio=float(body.min_ratio),
        max_line_length=int(body.max_line_length),
        max_candidates=int(body.max_candidates),
    )
    candidates = [
        GovernanceCommonLineCandidate(
            signature=str(it.get("signature") or ""),
            sample=str(it.get("sample") or "")[:400],
            docs=int(it.get("docs") or 0),
            ratio=float(it.get("ratio") or 0.0),
        )
        for it in candidates_raw
        if isinstance(it, dict) and str(it.get("signature") or "").strip()
    ]

    return GovernanceCommonLinesLearnResponse(
        dataset_id=body.dataset_id,
        total_documents=int(total),
        used_documents=int(len(texts)),
        candidates=candidates,
    )


@router.post(
    "/governance-analyze",
    response_model=GovernanceAnalyzeResponse,
    response_model_exclude_none=True,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def governance_analyze(
    body: GovernanceAnalyzeRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Analyze a text for governance issues without performing cleaning/persistence.

    This is intended for "quality check" UI flows to recommend治理配置/预设。
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    input_text = _extract_governance_input_text(body)
    analysis_opts = _governance_analysis_options(body)
    base = input_text or ""
    out_issues, patch = _analyze_governance_preview(base, "", body, analysis_opts)
    return GovernanceAnalyzeResponse(
        input_chars=len(base),
        input_lines=len(base.splitlines()),
        issues=out_issues,
        suggested_pipeline_patch=dict(patch or {}),
    )


@router.get("/clean-rules", response_model=CleanRulesResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_clean_rules(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Return default governance rules for UI selection/editing.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    return CleanRulesResponse(
        rules=[CleanRegexRuleModel(pattern=r.pattern, repl=r.repl, flags=r.flags) for r in DEFAULT_MARKDOWN_RULES]
    )


@router.post("/extract-keywords", response_model=KeywordExtractResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def extract_keywords(
    body: KeywordExtractRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Extract keywords (for governance/annotation/classification).

    Supported providers:
    - provider=auto (prefer HanLP, fallback to jieba)
    - provider=jieba / jieba_tfidf (default)
    - provider=jieba_textrank
    - provider=hanlp (optional dependency; requires `hanlp` and `HANLP_TOKENIZER_MODEL`)
    - provider=simple (lightweight regex tokenization + term frequency)
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    from app.rag.preprocessing.keyword import (
        KeywordProviderUnavailable,
        UnsupportedKeywordProvider,
    )
    from app.rag.preprocessing.keyword import (
        extract_keywords as extract_keywords_fn,
    )

    provider = (body.provider or "jieba").lower()
    try:
        keywords = extract_keywords_fn(body.text or "", provider=provider, top_k=int(body.top_k))
        return KeywordExtractResponse(provider=provider, keywords=keywords)
    except KeywordProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except UnsupportedKeywordProvider as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Keyword extraction failed: {str(exc)}") from exc


@router.post("/auto-annotations", response_model=AutoAnnotationResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def auto_annotations(
    body: AutoAnnotationRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Generate reviewable annotation candidates for the data-governance UI.

    Default mode extracts document-focus spans for human review:
    - LLM first when configured
    - local keyword/rule extraction as fallback
    - sensitive/compliance detectors only when explicitly requested

    Results are suggestions for human confirmation, not authoritative labels.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    source = str(body.text or "")
    total_chars = len(source)
    max_chars = max(1, min(int(body.max_chars or 20_000), 200_000))
    scan_text = source[:max_chars]
    max_items = max(1, min(int(body.max_annotations or 80), 500))

    mode = str(body.mode or "document_focus").strip().lower()
    providers = _normalize_auto_annotation_providers(body)
    draft = _AutoAnnotationDraft()

    try:
        if mode == "document_focus":
            await _collect_document_focus_annotations(draft, scan_text, body, providers, max_items)
        else:
            await _collect_compliance_annotations(draft, scan_text, body, providers, max_items)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Auto annotation failed: {str(exc)}") from exc

    keyword_provider = _finalize_auto_annotation_keyword_provider(draft.keyword_provider, body, providers)

    annotations = _dedupe_auto_annotations(draft.candidates, max_items=max_items)
    if not draft.document_tags:
        draft.document_tags.extend(_derive_document_tags_from_annotations(annotations, max_items=max_items))
    document_tags = _dedupe_auto_document_tags(draft.document_tags, max_items=max_items)
    return AutoAnnotationResponse(
        annotations=annotations,
        document_tags=document_tags,
        summary=draft.summary,
        text_chars=total_chars,
        scanned_chars=len(scan_text),
        truncated=total_chars > len(scan_text),
        keyword_provider=keyword_provider,
        strategy=draft.strategy,  # type: ignore[arg-type]
        providers_used=draft.providers_used,
        warnings=draft.warnings,
    )


@router.post("/llm-clean-preview", response_model=LLMCleanPreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def llm_clean_preview(
    body: LLMCleanPreviewRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Use an LLM to preview governance-style cleaning for Markdown (no persistence).

    Notes:
    - This endpoint calls an LLM (requires `LLM_API_KEY/LLM_API_BASE/LLM_MODEL`).
    - PromptTemplate can override the cleaning strategy via `prompt_template_id` / `template_key` / `ab_experiment_key`.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    markdown = body.markdown or ""
    if len(markdown) > int(body.max_chars):
        raise HTTPException(
            status_code=413,
            detail=f"Markdown too large for LLM preview (len={len(markdown)} > max_chars={body.max_chars}).",
        )

    prompt_selection = _resolve_llm_clean_prompt_selection(body=body, db=db, tenant_id=tenant_id, account_id=account_id)
    resp = await _request_llm_clean_preview(markdown=markdown, body=body, system_prompt=prompt_selection.system_prompt)
    cleaned, warnings = _parse_llm_clean_response(resp, markdown)

    return LLMCleanPreviewResponse(
        markdown=cleaned,
        changed=(cleaned != markdown),
        model_used=body.model or settings.LLM_MODEL,
        prompt_template_id=prompt_selection.prompt_template_id,
        template_key=prompt_selection.template_key,
        ab_experiment_key=prompt_selection.ab_experiment_key,
        ab_variant=prompt_selection.ab_variant,
        warnings=warnings,
    )


@router.post(
    "/upload-zip-with-images",
    response_model=ZipWithImagesResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def upload_zip_with_images(
    file: Annotated[UploadFile, File(...)],
    dataset_id: Annotated[str, Form(...)],
    document_id: Annotated[str | None, Form()] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Upload a ZIP that contains Markdown + images.

    Auto processing:
    1. Unzip the archive
    2. Upload all images to MinIO
    3. Replace Markdown image refs with MinIO URLs
    4. Return the rewritten Markdown and image list

    Args:
        file: ZIP file (Markdown + images)
        dataset_id: Dataset ID (used for MinIO paths)
        document_id: Optional document ID (defaults to file name)

    Returns:
        {
            "markdown": "rewritten Markdown",
            "images": [{"img_id": "...", "url": "...", "original_path": "..."}],
            "image_count": count
        }
    """
    if not settings.MINIO_ENABLED:
        raise HTTPException(
            status_code=503, detail="MinIO is disabled; cannot process image uploads. Set MINIO_ENABLED=true"
        )

    # Validate file type.
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP format files are supported")

    try:
        dataset_uuid = UUID(str(dataset_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid dataset_id") from exc
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_uuid)
    DatasetService.assert_dataset_writable(db, dataset, account_id)

    # Save to a temporary file.
    temp_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "temp_zip"
    temp_dir.mkdir(parents=True, exist_ok=True)

    temp_zip_path = temp_dir / f"{uuid.uuid4()}.zip"

    try:
        # Write to a temporary file (streamed, size-limited).
        await save_upload_file(file, temp_zip_path, max_bytes=settings.MAX_FILE_SIZE)

        # Process ZIP: extract images and upload to MinIO.
        doc_id = document_id or file.filename.rsplit(".", 1)[0]
        result = zip_image_processor.process_zip_with_images(
            zip_path=temp_zip_path, tenant_id=str(tenant_id), dataset_id=dataset_id, document_id=doc_id
        )

        return {
            "markdown": result["markdown"],
            "images": result["images"],
            "image_count": result["image_count"],
            "dataset_id": dataset_id,
            "document_id": doc_id,
        }

    except HTTPException:
        raise
    except (ValueError, zipfile.BadZipFile) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid ZIP format/content: {str(e)}",
        ) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ZIP processing failed: {str(e)}") from e
    finally:
        # Clean up temporary files.
        try:
            if temp_zip_path.exists():
                temp_zip_path.unlink()
        except Exception as exc:
            logger.debug(_PIPELINE_FALLBACK_LOG_MESSAGE, exc)
