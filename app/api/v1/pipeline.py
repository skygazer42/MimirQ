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
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Annotated, Any, TypeVar
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.pipelines import (
    AutoAnnotationRequest,
    AutoAnnotationResponse,
    BuiltinProcessingScriptListResponse,
    BuiltinProcessingScriptOut,
    CleanPreviewRequest,
    CleanPreviewResponse,
    CleanRegexRuleModel,
    CleanRulesResponse,
    GovernanceAnalyzeRequest,
    GovernanceAnalyzeResponse,
    GovernanceCommonLineCandidate,
    GovernanceCommonLinesLearnRequest,
    GovernanceCommonLinesLearnResponse,
    GovernanceProfileCreate,
    GovernanceProfileImportResponse,
    GovernanceProfileListQuery,
    GovernanceProfileListResponse,
    GovernanceProfileOut,
    GovernanceProfileResolvedResponse,
    GovernanceProfileSummary,
    GovernanceProfileUpdate,
    IngestionPreviewResponse,
    KeywordExtractRequest,
    KeywordExtractResponse,
    LLMCleanPreviewRequest,
    LLMCleanPreviewResponse,
    ParsePreviewResponse,
    PipelineCapabilitiesResponse,
    PipelineChunkPreviewRequest,
    PipelineChunkPreviewResponse,
    PipelineIngestionPreviewForm,
    PipelineParsePreviewForm,
    PipelinePluginChunkReportRequest,
    PipelinePluginChunkReportResponse,
    PipelinePluginGoldenDraftImportRequest,
    PipelinePluginGoldenDraftImportResponse,
    PipelinePluginGoldenDraftRequest,
    PipelinePluginGoldenDraftResponse,
    PipelinePluginListResponse,
    PipelineProfileImportForm,
    PipelineZipUploadForm,
    ZipWithImagesResponse,
)
from app.api.schemas.sources import IngestionPolicy, IngestionRule
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.api.utils import file_response_headers, save_upload_file
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
from app.api.v1.pipeline_support.capabilities import _pipeline_chunk_strategy_info, _pipeline_parser_backend_info
from app.api.v1.pipeline_support.clean_preview import (
    _PIPELINE_FALLBACK_LOG_MESSAGE,
    _analyze_governance_preview,
    _extract_governance_input_text,
    _governance_analysis_options,
    _LLMCleanPromptSelection,
    _parse_llm_clean_response,
    _request_llm_clean_preview,
    _resolve_llm_clean_prompt_selection,
    build_clean_preview,
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
    _ingestion_preview_defaults,
    _ingestion_preview_explain,
    _ingestion_preview_rule_output,
    _ingestion_rule_preprocess_steps,
    _IngestionPreviewConfig,
    _preprocess_ingestion_preview_file,
)
from app.core.async_bridge import run_blocking_in_thread
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.pipeline_versions import build_doc_pipeline_key, get_active_pipeline_hash
from app.core.regex_safety import RegexRulesValidationError
from app.models.document import Document, DocumentChunk
from app.models.governance_profile import GovernanceProfile
from app.parsing.backends import normalize_parser_backend
from app.parsing.factory import ParserFactory
from app.parsing.subprocess_runner import SubprocessCancelled, SubprocessWorkerError, run_subprocess_worker
from app.parsing.utils.zip_processor import process_zip_with_images
from app.rag.chunking import chunker_factory, hierarchical_chunk_markdown
from app.rag.core.logging import get_logger
from app.rag.pipeline_plugins.golden_drafts import build_golden_draft_bundle_from_chunks
from app.rag.pipeline_plugins.registry import (
    PipelinePluginDescriptor,
    PipelinePluginRegistryError,
    default_plugin_directories,
    list_pipeline_plugins_with_errors,
    resolve_registered_plugin_descriptor,
)
from app.rag.pipeline_plugins.reports import (
    build_pipeline_plugin_chunk_report as build_pipeline_plugin_chunk_report_data,
)
from app.rag.preprocessing.cleaning import learn_common_line_candidates
from app.rag.preprocessing.rules import DEFAULT_MARKDOWN_RULES
from app.services import dataset_service
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

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)
_BUILTIN_GOVERNANCE_PROFILES = get_builtin_governance_profiles()
_BUILTIN_GOVERNANCE_BY_KEY = {p.key: p for p in _BUILTIN_GOVERNANCE_PROFILES}
_BUILTIN_PROCESSING_SCRIPTS = list_builtin_processing_scripts()
_T = TypeVar("_T")


async def _run_pipeline_db_call(callback: Callable[..., _T], **kwargs: Any) -> _T:
    """Wait for the worker-owned Session to close before propagating cancellation."""

    def work() -> _T:
        with SessionLocal() as worker_db:
            return callback(worker_db, **kwargs)

    return await run_blocking_in_thread(work)


async def _cleanup_preview_directory(run_dir: Path) -> None:
    """Clean the request-owned directory under the existing shielded budget."""
    with anyio.fail_after(5.0, shield=True):
        await run_blocking_in_thread(shutil.rmtree, run_dir, ignore_errors=True)


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
)
def list_pipeline_plugins_endpoint() -> PipelinePluginListResponse:
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
    return PipelinePluginListResponse.model_validate(
        {
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
    )


def _plugin_marker_refs(plugin_ref: str, descriptor: PipelinePluginDescriptor) -> set[str]:
    refs = {plugin_ref.strip()}
    refs.update((value.strip() for value in descriptor.refs.values()))
    return {ref for ref in refs if ref}


def _assert_pipeline_plugin_executable(descriptor: PipelinePluginDescriptor) -> None:
    if descriptor.published is not True or descriptor.executable is not True:
        plugin_id = descriptor.id
        version = descriptor.version
        status = descriptor.test_status
        qualified = f"{plugin_id}@{version}" if version else plugin_id
        raise HTTPException(
            status_code=409, detail=f"plugin '{qualified}' is not executable; local test report status is {status}"
        )


def _resolve_plugin_relative_input_path(plugin_dir: Path, input_path: str) -> Path:
    raw = input_path.strip() or "sample.json"
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


@router.post("/plugins/chunk-report", response_model=PipelinePluginChunkReportResponse, response_model_by_alias=True)
def build_pipeline_plugin_chunk_report_endpoint(
    payload: PipelinePluginChunkReportRequest, *, account_id: Annotated[str, Depends(get_current_account_id)]
) -> PipelinePluginChunkReportResponse:
    """
    Build a review-only governance/chunk/KG report for a registered plugin sample.

    The sample path is scoped to the plugin directory. This API executes local
    plugin code, so callers select a registered plugin ref rather than arbitrary
    host paths.
    """
    try:
        descriptor = resolve_registered_plugin_descriptor(payload.plugin_ref)
    except PipelinePluginRegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_pipeline_plugin_executable(descriptor)
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
            section_metadata_keys=tuple(payload.section_metadata_keys),
            title_metadata_keys=tuple(payload.title_metadata_keys),
            metadata_highlight_keys=tuple(payload.metadata_highlight_keys),
        )
    except PipelinePluginRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"failed to build plugin chunk report: {exc}") from exc
    return PipelinePluginChunkReportResponse.model_validate(report)


def _assert_unmarked_plugin_golden_chunks_allowed(include_unmarked_chunks: bool) -> None:
    if not include_unmarked_chunks:
        return
    if settings.PYTHON_PIPELINE_PLUGIN_ALLOW_UNMARKED_GOLDEN_CHUNKS:
        return
    raise HTTPException(
        status_code=400,
        detail="include_unmarked_chunks requires PYTHON_PIPELINE_PLUGIN_ALLOW_UNMARKED_GOLDEN_CHUNKS=true; plugin Golden drafts normally use only chunks produced by the selected plugin",
    )


def _chunk_marked_by_plugin(meta: dict[str, Any], plugin_refs: set[str]) -> bool:
    if not plugin_refs:
        return False
    for key in ("chunk_python_plugin", "governance_python_plugin"):
        value = meta.get(key)
        if value is not None:
            value = value.strip()
        if value and value in plugin_refs:
            return True
    return False


def _active_doc_pipeline_key(document_id: UUID, doc_metadata: dict[str, Any]) -> str | None:
    active_hash = get_active_pipeline_hash(doc_metadata)
    return build_doc_pipeline_key(document_id, active_hash) if active_hash else None


def _chunk_matches_active_pipeline(chunk_meta: dict[str, Any], active_key: str | None) -> bool:
    if not active_key:
        return True
    chunk_key = chunk_meta.get("doc_pipeline_key")
    if chunk_key is not None:
        chunk_key = chunk_key.strip()
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
    rows = (
        db.query(DocumentChunk, Document)
        .join(Document, and_(Document.id == DocumentChunk.document_id, Document.tenant_id == DocumentChunk.tenant_id))
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            Document.tenant_id == tenant_id,
            Document.dataset_id == dataset_id,
            Document.status == "completed",
            Document.publication_status == "published",
            Document.archived_at.is_(None),
            Document.disabled_at.is_(None),
            DocumentChunk.disabled_at.is_(None),
        )
        .order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
        .limit(max_chunks)
        .all()
    )
    chunks: list[DocumentChunk] = []
    for chunk, document in rows:
        chunk_meta = dict(chunk.doc_metadata or {})
        if not include_unmarked_chunks and (not _chunk_marked_by_plugin(chunk_meta, plugin_refs)):
            continue
        doc_meta = dict(document.doc_metadata or {})
        if not _chunk_matches_active_pipeline(chunk_meta, _active_doc_pipeline_key(document.id, doc_meta)):
            continue
        chunks.append(chunk)
    return chunks


def _build_plugin_golden_draft_response(
    *,
    dataset_id: UUID,
    plugin_ref: str,
    descriptor: PipelinePluginDescriptor,
    chunks: Iterable[DocumentChunk],
    max_items: int,
) -> PipelinePluginGoldenDraftResponse:
    plugin_id = descriptor.id
    bundle = build_golden_draft_bundle_from_chunks(
        dataset_id=dataset_id,
        chunks=chunks,
        golden_rules=descriptor.golden_rules,
        plugin_id=plugin_id,
        plugin_version=descriptor.version,
        plugin_ref=plugin_ref,
        plugin_package_hash=descriptor.package_hash,
        max_items=max_items,
    )
    return PipelinePluginGoldenDraftResponse(
        dataset_id=dataset_id,
        plugin_id=plugin_id,
        plugin_version=descriptor.version,
        plugin_ref=plugin_ref,
        items_total=len(bundle["items"]),
        bundle=bundle,
    )


def _import_plugin_golden_draft_bundle(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    bundle: dict[str, Any],
    overwrite: bool,
    max_items: int,
) -> dict[str, Any]:
    items = bundle["items"]
    if not items:
        return {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [],
            "created_case_ids": [],
            "updated_case_ids": [],
            "case_ids": [],
        }
    from app.api.schemas.evaluation import RagasRegressionCaseImportRequest
    from app.services.evaluation_case_import import import_regression_cases

    payload = RagasRegressionCaseImportRequest(
        dataset_id=dataset_id, overwrite=overwrite, max_items=max_items, items=items
    )
    return import_regression_cases(payload, tenant_id=tenant_id, account_id=account_id, db=db)


@router.post("/plugins/golden-draft", response_model=PipelinePluginGoldenDraftResponse)
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
    dataset_service.ensure_member(db, tenant_id, account_id)
    dataset = dataset_service.get_dataset(db, tenant_id, payload.dataset_id)
    dataset_service.assert_dataset_readable(db, dataset, account_id)
    try:
        descriptor = resolve_registered_plugin_descriptor(payload.plugin_ref)
    except PipelinePluginRegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_pipeline_plugin_executable(descriptor)
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


@router.post("/plugins/golden-draft/import", response_model=PipelinePluginGoldenDraftImportResponse)
def import_pipeline_plugin_golden_draft(
    payload: PipelinePluginGoldenDraftImportRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> PipelinePluginGoldenDraftImportResponse:
    """Build a plugin golden draft bundle and import it into regression cases."""
    dataset_service.ensure_member(db, tenant_id, account_id)
    dataset = dataset_service.get_dataset(db, tenant_id, payload.dataset_id)
    dataset_service.assert_dataset_writable(db, dataset, account_id)
    try:
        descriptor = resolve_registered_plugin_descriptor(payload.plugin_ref)
    except PipelinePluginRegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_pipeline_plugin_executable(descriptor)
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
    import_result = _import_plugin_golden_draft_bundle(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=payload.dataset_id,
        bundle=draft.bundle,
        overwrite=payload.overwrite,
        max_items=payload.max_items,
    )
    return PipelinePluginGoldenDraftImportResponse(draft=draft, import_result=import_result)


@router.get("/capabilities", response_model=PipelineCapabilitiesResponse)
def get_pipeline_capabilities(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> PipelineCapabilitiesResponse:
    """
    Return available parsers and chunking strategies for the frontend.

    Note: only availability info is returned (no sensitive config like API keys).
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    default_parser_backend = normalize_parser_backend(settings.DEFAULT_PARSER_BACKEND) or "auto"
    default_chunk_strategy = settings.DEFAULT_CHUNK_STRATEGY.strip().lower()
    pdf_backends = [_pipeline_parser_backend_info(name) for name in sorted(ParserFactory.SUPPORTED_PDF_BACKENDS)]
    all_strats = set(chunker_factory.SUPPORTED_STRATEGIES.keys()) | set(chunker_factory.INTEGRATED_PIPELINE_STRATEGIES)
    chunk_strategies = [_pipeline_chunk_strategy_info(name) for name in sorted(all_strats)]
    return PipelineCapabilitiesResponse(
        default_parser_backend=default_parser_backend,
        default_chunk_strategy=default_chunk_strategy,
        pdf_backends=pdf_backends,
        chunk_strategies=chunk_strategies,
    )


@router.get("/governance-profiles", response_model=GovernanceProfileListResponse)
def list_governance_profiles(
    params: Annotated[GovernanceProfileListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> GovernanceProfileListResponse:
    """
    List governance profiles (built-in + tenant custom profiles).

    Notes:
    - Built-in profiles are shipped in code (read-only).
    - Custom profiles are stored in DB (tenant-scoped).
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    query = params.q.strip().lower() if params.q is not None else None
    items: list[GovernanceProfileSummary] = []
    builtin_count = 0
    if params.include_builtin:
        for p in _BUILTIN_GOVERNANCE_PROFILES:
            if query and query not in p.name.lower() + " " + p.description.lower():
                continue
            items.append(
                GovernanceProfileSummary(id=None, key=p.key, name=p.name, description=p.description, is_system=True)
            )
        builtin_count = len(items)
    q_db = db.query(GovernanceProfile).filter(GovernanceProfile.tenant_id == tenant_id)
    if query:
        like = f"%{query}%"
        q_db = q_db.filter(
            GovernanceProfile.name.ilike(like)
            | GovernanceProfile.description.ilike(like)
            | GovernanceProfile.key.ilike(like)
        )
    total_custom = q_db.count()
    rows = q_db.order_by(GovernanceProfile.updated_at.desc()).limit(min(params.limit or 200, 200)).all()
    items.extend([_profile_summary_from_row(r) for r in rows])
    return GovernanceProfileListResponse(total=builtin_count + total_custom, items=items)


@router.get("/governance-processing-scripts/builtins", response_model=BuiltinProcessingScriptListResponse)
async def list_builtin_processing_scripts_endpoint(
    *, tenant_id: Annotated[UUID, Depends(get_tenant_id)], account_id: Annotated[str, Depends(get_current_account_id)]
) -> BuiltinProcessingScriptListResponse:
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


@router.post("/governance-profiles", response_model=GovernanceProfileOut, status_code=201)
def create_governance_profile(
    body: GovernanceProfileCreate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> GovernanceProfileOut:
    dataset_service.ensure_member(db, tenant_id, account_id)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    try:
        key = validate_profile_key(body.key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if key:
        exists = (
            db.query(GovernanceProfile.id)
            .filter(GovernanceProfile.tenant_id == tenant_id, GovernanceProfile.key == key)
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
    row = GovernanceProfile(
        tenant_id=tenant_id,
        key=key,
        name=name,
        description=body.description.strip() if body.description is not None else None,
        is_system=False,
        payload=payload.model_dump(mode="json"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _profile_out_from_row(row)


@router.get("/governance-profiles/{profile_ref}", response_model=GovernanceProfileOut)
def get_governance_profile(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> GovernanceProfileOut:
    dataset_service.ensure_member(db, tenant_id, account_id)
    return _resolve_profile_ref(
        db=db, tenant_id=tenant_id, profile_ref=profile_ref, builtin_by_key=_BUILTIN_GOVERNANCE_BY_KEY
    )


@router.get("/governance-profiles/{profile_ref}/resolved", response_model=GovernanceProfileResolvedResponse)
def get_governance_profile_resolved(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> GovernanceProfileResolvedResponse:
    dataset_service.ensure_member(db, tenant_id, account_id)
    try:
        resolved = resolve_governance_profile_ref_effective(db=db, tenant_id=tenant_id, profile_ref=profile_ref)
    except ValueError as exc:
        msg = str(exc) or "invalid profile_ref"
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=400, detail=msg) from exc
    return GovernanceProfileResolvedResponse(
        profile=resolved.profile, chain=resolved.chain, effective=resolved.effective
    )


@router.patch("/governance-profiles/{profile_ref}", response_model=GovernanceProfileOut)
def update_governance_profile(
    profile_ref: str,
    body: GovernanceProfileUpdate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> GovernanceProfileOut:
    dataset_service.ensure_member(db, tenant_id, account_id)
    row = _resolve_custom_profile_row(
        db=db, tenant_id=tenant_id, profile_ref=profile_ref, builtin_by_key=_BUILTIN_GOVERNANCE_BY_KEY
    )
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name must not be empty")
        row.name = name
    if body.description is not None:
        desc = body.description.strip()
        row.description = desc if desc else None
    if body.payload is not None:
        try:
            payload = validate_and_normalize_payload(body.payload)
        except RegexRulesValidationError as exc:
            raise HTTPException(status_code=400, detail=exc.to_detail()) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row.payload = payload.model_dump(mode="json")
    db.commit()
    db.refresh(row)
    return _profile_out_from_row(row)


@router.delete("/governance-profiles/{profile_ref}", status_code=204)
def delete_governance_profile(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    dataset_service.ensure_member(db, tenant_id, account_id)
    row = _resolve_custom_profile_row(
        db=db, tenant_id=tenant_id, profile_ref=profile_ref, builtin_by_key=_BUILTIN_GOVERNANCE_BY_KEY
    )
    db.delete(row)
    db.commit()


def _import_governance_profile_records(
    db: Session, *, tenant_id: UUID, raw_profiles: list[object], overwrite: bool
) -> GovernanceProfileImportResponse:
    created = 0
    updated = 0
    out_items: list[GovernanceProfileSummary] = []
    for item in raw_profiles:
        record = _normalize_governance_profile_import_record(item)
        created_delta, updated_delta, summary = _upsert_governance_profile_import_record(
            db=db, tenant_id=tenant_id, record=record, overwrite=overwrite
        )
        created += created_delta
        updated += updated_delta
        out_items.append(summary)
    db.commit()
    return GovernanceProfileImportResponse(created=created, updated=updated, items=out_items)


@router.post("/governance-profiles/import", response_model=GovernanceProfileImportResponse)
async def import_governance_profiles(
    form: Annotated[PipelineProfileImportForm, Form(media_type="multipart/form-data")],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> GovernanceProfileImportResponse:
    """
    Import governance profile scripts (JSON).

    Security:
    - Only declarative JSON is accepted (no executable code).
    - Strong validation on regex rules and option keys is applied server-side.
    """
    await _run_pipeline_db_call(dataset_service.ensure_member, tenant_id=tenant_id, account_id=account_id)
    raw_profiles = _raw_governance_profile_import_items(await _read_governance_profile_import_json(form.file))
    return await _run_pipeline_db_call(
        _import_governance_profile_records, tenant_id=tenant_id, raw_profiles=raw_profiles, overwrite=form.overwrite
    )


@router.get("/governance-profiles/{profile_ref}/export")
def export_governance_profile(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    dataset_service.ensure_member(db, tenant_id, account_id)
    profile = _resolve_profile_ref(
        db=db, tenant_id=tenant_id, profile_ref=profile_ref, builtin_by_key=_BUILTIN_GOVERNANCE_BY_KEY
    )
    payload = profile.payload.model_dump()
    export_obj = {"name": profile.name, "description": profile.description, "key": profile.key, "payload": payload}
    safe_key = re.sub("[^a-zA-Z0-9_.-]+", "_", profile.key)[:64]
    filename = f"{safe_key}.governance-profile.json"
    content = json.dumps(export_obj, ensure_ascii=False, indent=2).encode("utf-8")
    return Response(content=content, media_type="application/json", headers=file_response_headers(filename))


@router.get("/governance-profiles/{profile_ref}/export-ingestion-policy")
def export_governance_profile_ingestion_policy(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """
    Export a minimal, importable dataset ingestion policy that references the given governance profile.

    This "closes the loop" for operators: build custom governance profiles in the UI, then export
    an ingestion_policy JSON snippet to be imported into a dataset.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    profile = _resolve_profile_ref(
        db=db, tenant_id=tenant_id, profile_ref=profile_ref, builtin_by_key=_BUILTIN_GOVERNANCE_BY_KEY
    )
    safe_key = re.sub("[^a-zA-Z0-9_.-]+", "_", profile.key)[:64] or "profile"
    filename = f"{safe_key}.ingestion_policy.json"
    rule = IngestionRule(
        id=f"gov:{safe_key}"[:100],
        name=f"Governance: {profile.name.strip() or safe_key}"[:200],
        enabled=True,
        match={"extensions": []},
        preprocess={"enabled": False, "steps": []},
        governance_profile_ref=profile.key,
        pipeline_patch={},
    )
    policy = IngestionPolicy(version="1", rules=[rule])
    content = export_policy_json(policy)
    return Response(content=content, media_type="application/json", headers=file_response_headers(filename))


def _assert_pipeline_dataset_writable(db: Session, *, tenant_id: UUID, account_id: str, dataset_id: UUID) -> None:
    dataset = dataset_service.get_dataset(db, tenant_id, dataset_id)
    dataset_service.assert_dataset_writable(db, dataset, account_id)


@router.post("/parse-preview", response_model=ParsePreviewResponse)
async def parse_preview(
    request: Request,
    form: Annotated[PipelineParsePreviewForm, Form(media_type="multipart/form-data")],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> ParsePreviewResponse:
    """
    Parse a file into a Markdown preview without persisting it; extract inline images to uploads/{tenant}/images.
    """
    await _run_pipeline_db_call(dataset_service.ensure_member, tenant_id=tenant_id, account_id=account_id)
    file_ext = Path(form.file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400, detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )
    preview_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    run_dir = preview_dir / uuid.uuid4().hex
    temp_path = run_dir / f"input{file_ext}"
    try:
        await save_upload_file(form.file, temp_path, max_bytes=settings.MAX_FILE_SIZE)
        result = await run_subprocess_worker(
            tenant_id=tenant_id,
            payload={
                "action": "pipeline_parse_preview",
                "tenant_id": str(tenant_id),
                "account_id": account_id,
                "file_path": str(temp_path),
                "parser_backend": form.parser_backend,
            },
            disconnect_check=request.is_disconnected,
            timeout_sec=settings.TASK_JOB_TIMEOUT_SEC,
        )
        return ParsePreviewResponse.model_validate(result)
    except SubprocessCancelled:
        raise HTTPException(status_code=499, detail="Client closed request") from None
    except SubprocessWorkerError as e:
        err_type = e.details.get("type")
        if err_type in {"ValueError", "RetiredModelProviderError"}:
            raise HTTPException(status_code=400, detail=str(e)) from e
        raise HTTPException(status_code=500, detail="Failed to parse preview") from e
    finally:
        await _cleanup_preview_directory(run_dir)


def _profile_pipeline_patch_for_ingestion(*, db: Session, tenant_id: UUID, profile_ref: str) -> dict[str, object]:
    prof = _resolve_profile_ref(
        db=db, tenant_id=tenant_id, profile_ref=profile_ref, builtin_by_key=_BUILTIN_GOVERNANCE_BY_KEY
    )
    patch_dict = prof.payload.pipeline_patch.copy()
    rules = [rule.model_dump() for rule in prof.payload.regex_rules]
    if rules:
        patch_dict["governance_regex_rules"] = rules
    return patch_dict


def _resolve_ingestion_preview_config(
    *,
    matched_rule: IngestionRule | None,
    parser_backend: str | None,
    chunk_strategy: str | None,
    db: Session,
    tenant_id: UUID,
) -> _IngestionPreviewConfig:
    default_parser_backend, default_chunk_strategy, base_parser_backend, base_chunk_strategy = (
        _ingestion_preview_defaults(parser_backend, chunk_strategy)
    )
    config = _IngestionPreviewConfig(
        base_parser_backend=base_parser_backend,
        base_chunk_strategy=base_chunk_strategy,
        parser_backend_choice=base_parser_backend,
        chunk_strategy_choice=base_chunk_strategy,
    )
    if matched_rule is None:
        return config
    if base_parser_backend in {"", "auto", default_parser_backend} and matched_rule.parser_backend:
        config.parser_backend_choice = matched_rule.parser_backend
    if base_chunk_strategy in {"", default_chunk_strategy} and matched_rule.chunk_strategy:
        config.chunk_strategy_choice = matched_rule.chunk_strategy
    config.preprocess_steps = _ingestion_rule_preprocess_steps(matched_rule)
    governance_profile_ref = matched_rule.governance_profile_ref
    if governance_profile_ref is not None and governance_profile_ref.strip():
        config.governance_profile_ref = governance_profile_ref.strip()
        config.patch_dict.update(
            _profile_pipeline_patch_for_ingestion(db=db, tenant_id=tenant_id, profile_ref=config.governance_profile_ref)
        )
    config.patch_dict.update(matched_rule.pipeline_patch)
    return config


def _prepare_ingestion_preview(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    filename: str,
    file_ext: str,
    parser_backend: str | None,
    chunk_strategy: str | None,
) -> tuple[dict[str, Any], IngestionRule | None, _IngestionPreviewConfig]:
    dataset_service.ensure_member(db, tenant_id, account_id)
    dataset = dataset_service.get_dataset(db, tenant_id, dataset_id)
    dataset_service.assert_dataset_readable(db, dataset, account_id)
    dataset_meta = dict(dataset.dataset_metadata or {})
    policy = parse_ingestion_policy_from_metadata(dataset_meta)
    matched_rule = match_ingestion_rule(policy, filename=filename, file_ext=file_ext)
    config = _resolve_ingestion_preview_config(
        matched_rule=matched_rule,
        parser_backend=parser_backend,
        chunk_strategy=chunk_strategy,
        db=db,
        tenant_id=tenant_id,
    )
    return (dataset_meta, matched_rule, config)


@router.post("/ingestion-preview", response_model=IngestionPreviewResponse)
async def ingestion_preview(
    request: Request,
    form: Annotated[PipelineIngestionPreviewForm, Form(media_type="multipart/form-data")],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> IngestionPreviewResponse:
    """
    One-shot ingestion preview for a dataset:
    - match dataset ingestion policy
    - preprocess file (before parsing)
    - parse to Markdown (preview)
    - run governance clean preview (issues + unified diff)
    """
    file_ext = Path(form.file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400, detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}"
        )
    preview_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    run_dir = preview_dir / uuid.uuid4().hex
    temp_path = run_dir / f"input{file_ext}"
    try:
        await save_upload_file(form.file, temp_path, max_bytes=settings.MAX_FILE_SIZE)
        dataset_meta, matched_rule, config = await _run_pipeline_db_call(
            _prepare_ingestion_preview,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=form.dataset_id,
            filename=form.file.filename,
            file_ext=file_ext,
            parser_backend=form.parser_backend,
            chunk_strategy=form.chunk_strategy,
        )
        parse_path, pre_summary = await run_blocking_in_thread(
            _preprocess_ingestion_preview_file, temp_path, config.preprocess_steps
        )
        patch_opts = PipelineOptions(**config.patch_dict)
        effective = resolve_pipeline_effective(
            dataset_metadata=dataset_meta, document_metadata={}, request_overrides=patch_opts
        )
        from app.services.pipeline_config import validate_pipeline_execution

        validate_pipeline_execution(effective)
        parsed = await run_subprocess_worker(
            tenant_id=tenant_id,
            payload={
                "action": "pipeline_parse_preview",
                "tenant_id": str(tenant_id),
                "account_id": account_id,
                "file_path": str(parse_path),
                "parser_backend": config.parser_backend_choice,
            },
            disconnect_check=request.is_disconnected,
            timeout_sec=settings.TASK_JOB_TIMEOUT_SEC,
        )
        clean_body = _build_ingestion_clean_preview_request(
            markdown=parsed["markdown"], effective=effective, diff_max_lines=form.diff_max_lines
        )
        cleaned = await run_blocking_in_thread(build_clean_preview, clean_body)
        rule_out = _ingestion_preview_rule_output(matched_rule, config)
        explain = _ingestion_preview_explain(
            dataset_id=form.dataset_id,
            filename=form.file.filename,
            file_ext=file_ext,
            config=config,
            rule_out=rule_out,
            pre_summary=pre_summary,
            parsed=parsed,
        )
        return IngestionPreviewResponse.model_validate(
            {"rule": rule_out, "preprocess": pre_summary, "parse": parsed, "clean": cleaned, "explain": explain}
        )
    except SubprocessCancelled:
        raise HTTPException(status_code=499, detail="Client closed request") from None
    except SubprocessWorkerError as e:
        err_type = e.details.get("type")
        if err_type in {"ValueError", "RetiredModelProviderError"}:
            raise HTTPException(status_code=400, detail=str(e)) from e
        raise HTTPException(status_code=500, detail="Failed to parse preview") from e
    finally:
        await _cleanup_preview_directory(run_dir)


@router.post("/chunk-preview", response_model=PipelineChunkPreviewResponse)
def chunk_preview(
    body: PipelineChunkPreviewRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> PipelineChunkPreviewResponse:
    """
    Perform hierarchical chunking for Markdown text and return highlight offsets.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    chunks = hierarchical_chunk_markdown(body.markdown)
    return PipelineChunkPreviewResponse(**chunks)


@router.post("/clean-preview", response_model=CleanPreviewResponse, response_model_exclude_none=True)
def clean_preview(
    body: CleanPreviewRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> CleanPreviewResponse:
    """
    Preview governance-style cleaning for Markdown (no persistence) to compare before/after.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    return build_clean_preview(body)


@router.post("/learn-common-lines", response_model=GovernanceCommonLinesLearnResponse)
def learn_common_lines(
    body: GovernanceCommonLinesLearnRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> GovernanceCommonLinesLearnResponse:
    """
    Learn common/repeated header/footer lines across multiple documents in a dataset.

    This endpoint is intended to support "learning mode" in the governance UI:
    discover candidate lines, then turn them into regex rules and write into a custom profile.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    dataset = dataset_service.get_dataset(db, tenant_id, body.dataset_id)
    dataset_service.assert_dataset_readable(db, dataset, account_id)
    total, texts = _collect_common_lines_texts(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=body.dataset_id,
        limit_docs=body.limit_docs,
        use_original=body.use_original,
    )
    if len(texts) < 2:
        raise HTTPException(
            status_code=400,
            detail="Not enough documents with persisted parsed content. Enable persist_parsed_content and ingest some documents first.",
        )
    candidates_raw = learn_common_line_candidates(
        texts,
        min_docs=body.min_docs,
        min_ratio=body.min_ratio,
        max_line_length=body.max_line_length,
        max_candidates=body.max_candidates,
    )
    candidates = [
        GovernanceCommonLineCandidate(
            signature=it["signature"], sample=it["sample"][:400], docs=it["docs"], ratio=it["ratio"]
        )
        for it in candidates_raw
    ]
    return GovernanceCommonLinesLearnResponse(
        dataset_id=body.dataset_id, total_documents=total, used_documents=len(texts), candidates=candidates
    )


@router.post("/governance-analyze", response_model=GovernanceAnalyzeResponse, response_model_exclude_none=True)
def governance_analyze(
    body: GovernanceAnalyzeRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> GovernanceAnalyzeResponse:
    """
    Analyze a text for governance issues without performing cleaning/persistence.

    This is intended for "quality check" UI flows to recommend治理配置/预设。
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    input_text = _extract_governance_input_text(body)
    analysis_opts = _governance_analysis_options(body)
    base = input_text
    out_issues, patch = _analyze_governance_preview(base, "", body, analysis_opts)
    return GovernanceAnalyzeResponse(
        input_chars=len(base), input_lines=len(base.splitlines()), issues=out_issues, suggested_pipeline_patch=patch
    )


@router.get("/clean-rules", response_model=CleanRulesResponse)
def list_clean_rules(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> CleanRulesResponse:
    """
    Return default governance rules for UI selection/editing.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    return CleanRulesResponse(
        rules=[CleanRegexRuleModel(pattern=r.pattern, repl=r.repl, flags=r.flags) for r in DEFAULT_MARKDOWN_RULES]
    )


@router.post("/extract-keywords", response_model=KeywordExtractResponse)
def extract_keywords(
    body: KeywordExtractRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> KeywordExtractResponse:
    """
    Extract keywords (for governance/annotation/classification).

    Supported providers:
    - provider=auto (jieba)
    - provider=jieba / jieba_tfidf (default)
    - provider=jieba_textrank
    - provider=simple (lightweight regex tokenization + term frequency)
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    from app.rag.preprocessing.keyword import KeywordProviderUnavailable, UnsupportedKeywordProvider
    from app.rag.preprocessing.keyword import extract_keywords as extract_keywords_fn

    provider = (body.provider or "jieba").lower()
    try:
        keywords = extract_keywords_fn(body.text, provider=provider, top_k=body.top_k)
        return KeywordExtractResponse(provider=provider, keywords=keywords)
    except KeywordProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except UnsupportedKeywordProvider as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Keyword extraction failed: {str(exc)}") from exc


@router.post("/auto-annotations", response_model=AutoAnnotationResponse)
async def auto_annotations(
    body: AutoAnnotationRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> AutoAnnotationResponse:
    """
    Generate reviewable annotation candidates for the data-governance UI.

    Default mode extracts document-focus spans for human review:
    - LLM first when configured
    - local keyword/rule extraction as fallback
    - sensitive/compliance detectors only when explicitly requested

    Results are suggestions for human confirmation, not authoritative labels.
    """
    await _run_pipeline_db_call(dataset_service.ensure_member, tenant_id=tenant_id, account_id=account_id)
    source = body.text
    total_chars = len(source)
    max_chars = body.max_chars
    scan_text = source[:max_chars]
    max_items = body.max_annotations
    mode = body.mode
    providers = _normalize_auto_annotation_providers(body)
    draft = _AutoAnnotationDraft()
    try:
        if mode == "document_focus":
            await _collect_document_focus_annotations(draft, scan_text, body, providers, max_items)
        else:
            await _collect_compliance_annotations(draft, scan_text, body, providers, max_items)
    except Exception as exc:
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
        strategy=draft.strategy,
        providers_used=draft.providers_used,
        warnings=draft.warnings,
    )


def _prepare_llm_clean_preview(
    db: Session, *, body: LLMCleanPreviewRequest, tenant_id: UUID, account_id: str
) -> _LLMCleanPromptSelection:
    dataset_service.ensure_member(db, tenant_id, account_id)
    markdown = body.markdown
    if len(markdown) > body.max_chars:
        raise HTTPException(
            status_code=413,
            detail=f"Markdown too large for LLM preview (len={len(markdown)} > max_chars={body.max_chars}).",
        )
    prompt_selection = _resolve_llm_clean_prompt_selection(body=body, db=db, tenant_id=tenant_id, account_id=account_id)
    return prompt_selection


@router.post("/llm-clean-preview", response_model=LLMCleanPreviewResponse)
async def llm_clean_preview(
    body: LLMCleanPreviewRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> LLMCleanPreviewResponse:
    """
    Use an LLM to preview governance-style cleaning for Markdown (no persistence).

    Notes:
    - This endpoint calls an LLM (requires `LLM_API_KEY/LLM_API_BASE/LLM_MODEL`).
    - PromptTemplate can override the cleaning strategy via `prompt_template_id` / `template_key` / `ab_experiment_key`.
    """
    markdown = body.markdown
    prompt_selection = await _run_pipeline_db_call(
        _prepare_llm_clean_preview, body=body, tenant_id=tenant_id, account_id=account_id
    )
    resp = await _request_llm_clean_preview(markdown=markdown, body=body, system_prompt=prompt_selection.system_prompt)
    cleaned, warnings = _parse_llm_clean_response(resp, markdown)
    return LLMCleanPreviewResponse(
        markdown=cleaned,
        changed=cleaned != markdown,
        model_used=body.model or settings.LLM_MODEL,
        prompt_template_id=prompt_selection.prompt_template_id,
        template_key=prompt_selection.template_key,
        ab_experiment_key=prompt_selection.ab_experiment_key,
        ab_variant=prompt_selection.ab_variant,
        warnings=warnings,
    )


@router.post("/upload-zip-with-images", response_model=ZipWithImagesResponse)
async def upload_zip_with_images(
    form: Annotated[PipelineZipUploadForm, Form(media_type="multipart/form-data")],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> ZipWithImagesResponse:
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
    if not form.file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP format files are supported")
    try:
        dataset_uuid = UUID(form.dataset_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid dataset_id") from exc
    await _run_pipeline_db_call(
        _assert_pipeline_dataset_writable, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_uuid
    )
    temp_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "temp_zip"
    temp_zip_path = temp_dir / f"{uuid.uuid4()}.zip"
    try:
        await save_upload_file(form.file, temp_zip_path, max_bytes=settings.MAX_FILE_SIZE)
        doc_id = form.document_id if form.document_id else form.file.filename.rsplit(".", 1)[0]
        result = await run_blocking_in_thread(
            process_zip_with_images,
            zip_path=temp_zip_path,
            tenant_id=str(tenant_id),
            dataset_id=form.dataset_id,
            document_id=doc_id,
        )
        payload = {
            "markdown": result["markdown"],
            "images": result["images"],
            "image_count": result["image_count"],
            "dataset_id": form.dataset_id,
            "document_id": doc_id,
        }
    except HTTPException:
        raise
    except (ValueError, zipfile.BadZipFile) as e:
        raise HTTPException(status_code=400, detail=f"Invalid ZIP format/content: {str(e)}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ZIP processing failed: {str(e)}") from e
    finally:
        try:
            with anyio.fail_after(5.0, shield=True):
                await run_blocking_in_thread(temp_zip_path.unlink, missing_ok=True)
        except Exception as exc:
            logger.debug(_PIPELINE_FALLBACK_LOG_MESSAGE, exc, exc_info=True)
    return ZipWithImagesResponse.model_validate(payload)
