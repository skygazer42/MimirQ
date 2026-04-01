"""
Dataset management API.
Supports dataset creation, query, update, deletion, and permission management.
"""
import contextlib
import gzip as gzip_lib
import io
import json
import re
import uuid
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.dataset import (
    DatasetChunkTargetsV2,
    DatasetCloneRequest,
    DatasetConfigBundle,
    DatasetConfigExport,
    DatasetConfigImportRequest,
    DatasetCreate,
    DatasetIngestionStats,
    DatasetListResponse,
    DatasetOut,
    DatasetPurgeResponse,
    DatasetRAGDefaults,
    DatasetRetentionPolicy,
    DatasetUpdate,
)
from app.api.schemas.dataset_category import DatasetCategoryAssignmentRequest, DatasetCategoryAssignmentResponse
from app.api.schemas.dataset_health import DatasetHealthIngestionSummary, DatasetHealthResponse
from app.api.schemas.dataset_profile import (
    DatasetProfileDocumentListResponse,
    DatasetProfileFindingListResponse,
    DatasetProfileScanRunCreateRequest,
    DatasetProfileScanRunListResponse,
    DatasetProfileScanRunOut,
    DatasetProfileSummary,
)
from app.api.schemas.document import DocumentPipelineOptions
from app.api.schemas.ingestion_policy import (
    DatasetTableRoutingPolicyAudit,
    IngestionPolicy,
    IngestionPolicyImportResponse,
    IngestionPolicyRollbackRequest,
    IngestionPolicyVersionListResponse,
    IngestionPolicyWithAudit,
    IngestionRuleTableRoutingAudit,
    TableRoutingSettingAudit,
)
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.pipeline_versions import build_doc_pipeline_key, get_active_pipeline_hash
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.dataset_category import DatasetCategory, DatasetCategoryMembership
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.models.dataset_profile_scan import DatasetProfileScanRun as DBDatasetProfileScanRun
from app.models.document import Document as DBDocument
from app.models.document import DocumentPermission
from app.models.group_permissions import DatasetGroupPermission
from app.parsing.backends import normalize_parser_backend
from app.parsing.factory import ParserFactory
from app.rag.chunking import chunker_factory
from app.rag.core.hashing import stable_hash
from app.services.audit_log_service import audit_log_event
from app.services.dataset_category_service import DatasetCategoryService, collect_descendant_ids
from app.services.dataset_profile_scan_runner import run_dataset_profile_deep_scan
from app.services.dataset_profile_service import (
    compute_dataset_profile_summary,
    list_bucket_documents,
    list_finding_documents,
)
from app.services.dataset_service import DatasetGroupPermissionService, DatasetPermissionService, DatasetService
from app.services.fls_policy import parse_fls_policy_from_metadata, validate_and_normalize_fls_policy
from app.services.ingestion_policy import (
    export_policy_json,
    parse_ingestion_policy_from_metadata,
    validate_and_normalize_ingestion_policy,
)
from app.services.pipeline_config import parse_pipeline_from_metadata, upsert_pipeline_metadata
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission
from app.services.report_html import render_dataset_profile_html
from app.services.retention_policy import parse_retention_policy_from_metadata, upsert_retention_policy_metadata
from app.services.tenant_group_service import TenantGroupService
from app.tasks.queue import enqueue_dataset_profile_scan
from app.types.pipeline import PipelineOptions

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_DATASET_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
_APPLICATION_JSON_MEDIA_TYPE = "application/json"

def _dataset_pipeline_out(ds: Dataset) -> DocumentPipelineOptions | None:
    meta = getattr(ds, "dataset_metadata", None)
    if not isinstance(meta, dict):
        return None
    opts = parse_pipeline_from_metadata(meta)
    data = {k: getattr(opts, k) for k in opts.__dataclass_fields__}  # type: ignore[attr-defined]
    # Only return if any pipeline override exists
    if not any(v is not None for v in data.values()):
        return None
    return DocumentPipelineOptions(**data)


def _dataset_retention_policy_out(ds: Dataset) -> DatasetRetentionPolicy | None:
    meta = getattr(ds, "dataset_metadata", None)
    if not isinstance(meta, dict):
        return None
    pol = parse_retention_policy_from_metadata(meta)
    return pol if isinstance(pol, DatasetRetentionPolicy) else None


def _dataset_ingestion_defaults(ds: Dataset) -> tuple[str | None, str | None]:
    meta = getattr(ds, "dataset_metadata", None)
    if not isinstance(meta, dict):
        return None, None
    pb = meta.get("default_parser_backend")
    cs = meta.get("default_chunk_strategy")
    pb_out = str(pb).strip() if isinstance(pb, str) and pb.strip() else None
    cs_out = str(cs).strip() if isinstance(cs, str) and cs.strip() else None
    return pb_out, cs_out


_TABLE_ROUTING_EXTENSIONS = {".csv", ".xls", ".xlsx"}


def _resolve_table_routing_setting(
    *,
    rule_patch_value: Any,
    dataset_default: bool | None,
    global_default: bool,
) -> TableRoutingSettingAudit:
    if rule_patch_value is not None:
        return TableRoutingSettingAudit(value=bool(rule_patch_value), source="rule_pipeline_patch")
    if dataset_default is not None:
        return TableRoutingSettingAudit(value=bool(dataset_default), source="dataset_pipeline_default")
    return TableRoutingSettingAudit(value=bool(global_default), source="global_default")


def _build_table_routing_policy_audit(*, meta: dict[str, Any], policy: IngestionPolicy) -> DatasetTableRoutingPolicyAudit:
    dataset_opts = parse_pipeline_from_metadata(meta)

    dataset_defaults = {
        "table_store_enabled": bool(dataset_opts.table_store_enabled) if dataset_opts.table_store_enabled is not None else False,
        "table_store_auto_route": bool(dataset_opts.table_store_auto_route) if dataset_opts.table_store_auto_route is not None else False,
        "table_store_sidecar_exclusive_routing": (
            bool(dataset_opts.table_store_sidecar_exclusive_routing)
            if dataset_opts.table_store_sidecar_exclusive_routing is not None
            else False
        ),
    }
    dataset_default_presence = {
        "table_store_enabled": dataset_opts.table_store_enabled is not None,
        "table_store_auto_route": dataset_opts.table_store_auto_route is not None,
        "table_store_sidecar_exclusive_routing": dataset_opts.table_store_sidecar_exclusive_routing is not None,
    }
    global_defaults = {
        "table_store_enabled": bool(getattr(settings, "TABLE_STORE_ENABLED", False)),
        "table_store_auto_route": bool(getattr(settings, "TABLE_STORE_AUTO_ROUTE", False)),
        "table_store_sidecar_exclusive_routing": bool(
            getattr(settings, "TABLE_STORE_SIDECAR_EXCLUSIVE_ROUTING", False)
        ),
    }

    rule_audits: list[IngestionRuleTableRoutingAudit] = []
    for rule in policy.rules or []:
        patch = rule.pipeline_patch if isinstance(rule.pipeline_patch, dict) else {}
        exts: list[str] = []
        for ext in (rule.match.extensions if rule.match is not None else []) or []:
            sval = str(ext or "").strip().lower()
            if not sval:
                continue
            if not sval.startswith("."):
                sval = "." + sval
            exts.append(sval)

        patch_has_table_keys = any(
            k in patch
            for k in (
                "table_store_enabled",
                "table_store_auto_route",
                "table_store_sidecar_exclusive_routing",
            )
        )
        is_table_rule = bool(set(exts) & _TABLE_ROUTING_EXTENSIONS) or patch_has_table_keys

        ds_enabled = dataset_defaults["table_store_enabled"] if dataset_default_presence["table_store_enabled"] else None
        ds_auto_route = (
            dataset_defaults["table_store_auto_route"] if dataset_default_presence["table_store_auto_route"] else None
        )
        ds_sidecar_exclusive = (
            dataset_defaults["table_store_sidecar_exclusive_routing"]
            if dataset_default_presence["table_store_sidecar_exclusive_routing"]
            else None
        )

        rule_audits.append(
            IngestionRuleTableRoutingAudit(
                rule_id=str(rule.id),
                rule_name=str(rule.name),
                enabled=bool(rule.enabled),
                match_extensions=exts,
                table_rule_match=is_table_rule,
                table_store_enabled=_resolve_table_routing_setting(
                    rule_patch_value=patch.get("table_store_enabled"),
                    dataset_default=ds_enabled,
                    global_default=global_defaults["table_store_enabled"],
                ),
                table_store_auto_route=_resolve_table_routing_setting(
                    rule_patch_value=patch.get("table_store_auto_route"),
                    dataset_default=ds_auto_route,
                    global_default=global_defaults["table_store_auto_route"],
                ),
                table_store_sidecar_exclusive_routing=_resolve_table_routing_setting(
                    rule_patch_value=patch.get("table_store_sidecar_exclusive_routing"),
                    dataset_default=ds_sidecar_exclusive,
                    global_default=global_defaults["table_store_sidecar_exclusive_routing"],
                ),
            )
        )

    return DatasetTableRoutingPolicyAudit(
        version="1",
        table_extensions=sorted(_TABLE_ROUTING_EXTENSIONS),
        global_defaults=global_defaults,
        dataset_pipeline_defaults=dataset_defaults,
        rules=rule_audits,
    )


def _dataset_rag_defaults_out(ds: Dataset) -> DatasetRAGDefaults | None:
    meta = getattr(ds, "dataset_metadata", None)
    if not isinstance(meta, dict):
        return None
    raw = meta.get("rag_defaults")
    if not isinstance(raw, dict):
        return None
    try:
        # DatasetRAGDefaults is small and extra="ignore"; safe to parse best-effort.
        parsed = DatasetRAGDefaults(**raw)
    except Exception:
        return None
    # Hide empty objects for cleaner API responses.
    if not parsed.model_dump(exclude_none=True):
        return None
    return parsed


def _dataset_rag_config_template_defaults_out(ds: Dataset) -> tuple[UUID | None, str | None, str | None]:
    meta = getattr(ds, "dataset_metadata", None)
    if not isinstance(meta, dict):
        return None, None, None

    raw_id = meta.get("default_rag_config_template_id")
    template_id: UUID | None = None
    if isinstance(raw_id, str) and raw_id.strip():
        try:
            template_id = UUID(raw_id.strip())
        except Exception:
            template_id = None

    raw_key = meta.get("default_rag_config_template_key")
    template_key = str(raw_key).strip() if isinstance(raw_key, str) and raw_key.strip() else None

    raw_ab = meta.get("default_rag_config_ab_experiment_key")
    ab_key = str(raw_ab).strip() if isinstance(raw_ab, str) and raw_ab.strip() else None

    return template_id, template_key, ab_key


def _dataset_prompt_defaults_out(ds: Dataset) -> tuple[UUID | None, str | None, str | None]:
    meta = getattr(ds, "dataset_metadata", None)
    if not isinstance(meta, dict):
        return None, None, None

    raw_id = meta.get("default_prompt_template_id")
    prompt_id: UUID | None = None
    if isinstance(raw_id, str) and raw_id.strip():
        try:
            prompt_id = UUID(raw_id.strip())
        except Exception:
            prompt_id = None

    raw_key = meta.get("default_prompt_template_key")
    prompt_key = str(raw_key).strip() if isinstance(raw_key, str) and raw_key.strip() else None

    raw_ab = meta.get("default_prompt_ab_experiment_key")
    ab_key = str(raw_ab).strip() if isinstance(raw_ab, str) and raw_ab.strip() else None

    return prompt_id, prompt_key, ab_key


def _dataset_chunk_targets_v2_out(ds: Dataset) -> DatasetChunkTargetsV2 | None:
    meta = getattr(ds, "dataset_metadata", None)
    if not isinstance(meta, dict):
        return None
    raw = meta.get("chunk_targets_v2")
    if not isinstance(raw, dict):
        return None
    try:
        parsed = DatasetChunkTargetsV2(**raw)
    except Exception:
        return None
    # Hide empty objects for cleaner API responses.
    if not parsed.model_dump(exclude_none=True):
        return None
    return parsed


@router.get("/{dataset_id}/ingestion/stats", response_model=DatasetIngestionStats, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset_ingestion_stats(
    dataset_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Lightweight dataset ingestion stats (documents/chunks/chars/status breakdown).

    Notes:
    - Enforces dataset read permission.
    - Applies document-level ACL filtering for non-owners ("security trimming").
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    query = db.query(DBDocument).filter(
        DBDocument.tenant_id == tenant_id,
        DBDocument.dataset_id == dataset_id,
    )

    # Document-level ACL filter (dataset owner bypass).
    if str(getattr(ds, "owner_id", "") or "") != str(account_id or ""):
        doc_perm_subq = (
            db.query(DocumentPermission.document_id)
            .filter(
                DocumentPermission.tenant_id == tenant_id,
                DocumentPermission.account_id == account_id,
            )
            .subquery()
        )
        query = query.filter(
            or_(
                DBDocument.access_mode.is_(None),
                DBDocument.access_mode.in_(["inherit", "all_team_members"]),
                DBDocument.owner_id == account_id,
                and_(
                    DBDocument.access_mode == "partial_members",
                    DBDocument.id.in_(doc_perm_subq),
                ),
            )
        )

    status_rows = (
        query.with_entities(DBDocument.status, func.count(DBDocument.id))
        .group_by(DBDocument.status)
        .all()
    )
    by_status = {str(status): int(count) for status, count in status_rows if status is not None}
    total_docs = int(sum(by_status.values()))

    sums = query.with_entities(
        func.coalesce(func.sum(DBDocument.chunk_count), 0),
        func.coalesce(func.sum(DBDocument.file_size), 0),
        func.coalesce(func.sum(DBDocument.total_characters), 0),
        func.max(DBDocument.processed_at),
    ).one()
    total_chunks = int(sums[0] or 0)
    total_size = int(sums[1] or 0)
    total_chars = int(sums[2] or 0)
    last_processed_at = sums[3]

    return DatasetIngestionStats(
        dataset_id=dataset_id,
        total_documents=total_docs,
        by_status=by_status,
        total_chunks=total_chunks,
        total_size=total_size,
        total_characters=total_chars,
        last_processed_at=last_processed_at,
    )


_ALLOWED_PARSER_DEFAULTS = set(ParserFactory.SUPPORTED_PDF_BACKENDS) | set(ParserFactory.SUPPORTED_NON_PDF_BACKENDS)


def _normalize_dataset_default_parser_backend(value: str) -> str:
    """
    Normalize and validate a dataset-level default parser backend.

    Note: availability is not validated here (depends on deployment config); we only validate
    that the identifier is known to the backend.
    """
    normalized = normalize_parser_backend(value) or ""
    if not normalized:
        return ""
    if normalized not in _ALLOWED_PARSER_DEFAULTS:
        allowed = sorted(_ALLOWED_PARSER_DEFAULTS)
        raise HTTPException(status_code=400, detail=f"Unsupported default_parser_backend '{value}'. Supported: {allowed}")
    return normalized


def _normalize_dataset_default_chunk_strategy(value: str) -> str:
    """Normalize/validate a dataset-level default chunk strategy."""
    try:
        return chunker_factory.resolve_strategy(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/", response_model=DatasetOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_dataset(
    payload: DatasetCreate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)]
):
    dataset = DatasetService.create_dataset(
        db=db,
        tenant_id=tenant_id,
        name=payload.name,
        description=payload.description,
        permission=payload.permission,
        owner_id=account_id,
        partial_members=payload.partial_member_list or [],
        partial_groups=payload.partial_group_list or [],
    )

    # Optional dataset-level defaults (stored in datasets.metadata).
    meta = dict(getattr(dataset, "dataset_metadata", None) or {})
    changed = False

    # 1) Pipeline defaults (governance/indexing).
    if payload.pipeline is not None:
        options = PipelineOptions(**payload.pipeline.model_dump(exclude_none=True))
        changed = upsert_pipeline_metadata(meta, options=options) or changed

    # 2) Ingestion defaults (parser/chunk strategy).
    if payload.default_parser_backend is not None:
        raw = str(payload.default_parser_backend or "").strip()
        if raw:
            meta["default_parser_backend"] = _normalize_dataset_default_parser_backend(raw)
        else:
            meta.pop("default_parser_backend", None)
        changed = True
    if payload.default_chunk_strategy is not None:
        raw = str(payload.default_chunk_strategy or "").strip()
        if raw:
            meta["default_chunk_strategy"] = _normalize_dataset_default_chunk_strategy(raw)
        else:
            meta.pop("default_chunk_strategy", None)
        changed = True

    # 3) RAG defaults (chat retrieval defaults).
    if payload.rag_defaults is not None:
        data = payload.rag_defaults.model_dump(exclude_none=True)
        if data:
            meta["rag_defaults"] = data
        else:
            meta.pop("rag_defaults", None)
        changed = True

    # 4) RAG config template defaults (optional; for safe rollout/rollback of retrieval/rerank knobs).
    if payload.default_rag_config_template_id is not None:
        meta["default_rag_config_template_id"] = str(payload.default_rag_config_template_id)
        changed = True
    if payload.default_rag_config_template_key is not None:
        val = str(payload.default_rag_config_template_key or "").strip().lower()
        if val:
            meta["default_rag_config_template_key"] = val
        else:
            meta.pop("default_rag_config_template_key", None)
        changed = True
    if payload.default_rag_config_ab_experiment_key is not None:
        val = str(payload.default_rag_config_ab_experiment_key or "").strip()
        if val:
            meta["default_rag_config_ab_experiment_key"] = val
        else:
            meta.pop("default_rag_config_ab_experiment_key", None)
        changed = True

    # 5) Prompt defaults (prompt template + optional A/B experiment key).
    if payload.default_prompt_template_id is not None:
        meta["default_prompt_template_id"] = str(payload.default_prompt_template_id)
        changed = True
    if payload.default_prompt_template_key is not None:
        val = str(payload.default_prompt_template_key or "").strip().lower()
        if val:
            meta["default_prompt_template_key"] = val
        else:
            meta.pop("default_prompt_template_key", None)
        changed = True
    if payload.default_prompt_ab_experiment_key is not None:
        val = str(payload.default_prompt_ab_experiment_key or "").strip()
        if val:
            meta["default_prompt_ab_experiment_key"] = val
        else:
            meta.pop("default_prompt_ab_experiment_key", None)
        changed = True

    # 6) Chunk target spec (best-effort; used by profiling/auto-tune).
    if payload.chunk_targets_v2 is not None:
        data = payload.chunk_targets_v2.model_dump(exclude_none=True)
        if data:
            meta["chunk_targets_v2"] = data
        else:
            meta.pop("chunk_targets_v2", None)
        changed = True

    # 7) Retention policy (lifecycle automation).
    if payload.retention_policy is not None:
        data = payload.retention_policy.model_dump(exclude_none=True)
        if data:
            meta["retention_policy"] = data
        else:
            meta.pop("retention_policy", None)
        changed = True

    if changed:
        dataset.dataset_metadata = meta
        db.commit()
        db.refresh(dataset)

    partial_list = None
    partial_groups = None
    if dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
        partial_list = DatasetPermissionService.get_dataset_partial_member_list(db, tenant_id, dataset.id)
        partial_groups = DatasetGroupPermissionService.get_dataset_partial_group_list(db, tenant_id, dataset.id)

    default_parser_backend, default_chunk_strategy = _dataset_ingestion_defaults(dataset)
    (
        rag_config_template_id,
        rag_config_template_key,
        rag_config_ab_experiment_key,
    ) = _dataset_rag_config_template_defaults_out(dataset)
    prompt_template_id, prompt_template_key, prompt_ab_experiment_key = _dataset_prompt_defaults_out(dataset)
    chunk_targets_v2 = _dataset_chunk_targets_v2_out(dataset)
    retention_policy = _dataset_retention_policy_out(dataset)

    # Best-effort audit log (commit separately; never block response).
    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="dataset.create",
        resource_type="dataset",
        resource_id=str(dataset.id),
        details={
            "name": str(dataset.name or "")[:255],
            "permission": str(dataset.permission or ""),
        },
    )
    try:
        db.commit()
    except Exception:
        pass

    return DatasetOut(
        id=dataset.id,
        tenant_id=dataset.tenant_id,
        name=dataset.name,
        description=dataset.description,
        permission=dataset.permission,
        owner_id=dataset.owner_id,
        partial_member_list=partial_list,
        partial_group_list=partial_groups,
        default_parser_backend=default_parser_backend,
        default_chunk_strategy=default_chunk_strategy,
        rag_defaults=_dataset_rag_defaults_out(dataset),
        default_rag_config_template_id=rag_config_template_id,
        default_rag_config_template_key=rag_config_template_key,
        default_rag_config_ab_experiment_key=rag_config_ab_experiment_key,
        default_prompt_template_id=prompt_template_id,
        default_prompt_template_key=prompt_template_key,
        default_prompt_ab_experiment_key=prompt_ab_experiment_key,
        chunk_targets_v2=chunk_targets_v2,
        pipeline=_dataset_pipeline_out(dataset),
        retention_policy=retention_policy,
    )


@router.get("/", response_model=DatasetListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_datasets(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    category_id: Annotated[
        UUID | None, Query(description='Optional: filter datasets by category (tree)')
    ] = None,
    include_descendants: Annotated[
        bool, Query(description='When filtering by category_id, include subtree')
    ] = True,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)]
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    group_ids = list(
        TenantGroupService.resolve_account_group_ids(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
        )
    )

    readable_filters = [
        Dataset.owner_id == account_id,
        Dataset.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS,
        db.query(DatasetPermission.id)
        .filter(
            DatasetPermission.tenant_id == tenant_id,
            DatasetPermission.dataset_id == Dataset.id,
            DatasetPermission.account_id == account_id,
        )
        .exists(),
    ]
    if group_ids:
        readable_filters.append(
            db.query(DatasetGroupPermission.id)
            .filter(
                DatasetGroupPermission.tenant_id == tenant_id,
                DatasetGroupPermission.dataset_id == Dataset.id,
                DatasetGroupPermission.group_id.in_(group_ids),
            )
            .exists()
        )

    # List only datasets readable by the current account.
    query = db.query(Dataset).filter(Dataset.tenant_id == tenant_id)
    query = query.filter(or_(*readable_filters))
    # Optional category filter (best-effort; default includes subtree).
    if category_id is not None:
        try:
            rows = (
                db.query(DatasetCategory.id, DatasetCategory.parent_id)
                .filter(DatasetCategory.tenant_id == tenant_id)
                .all()
            )
            parent_by_id = {cid: pid for cid, pid in rows if cid is not None}
            category_ids = (
                collect_descendant_ids(root_id=category_id, parent_by_id=parent_by_id)
                if bool(include_descendants)
                else {category_id}
            )
            ds_ids_subq = (
                db.query(DatasetCategoryMembership.dataset_id)
                .filter(
                    DatasetCategoryMembership.tenant_id == tenant_id,
                    DatasetCategoryMembership.category_id.in_(list(category_ids)),
                )
                .subquery()
            )
            query = query.filter(Dataset.id.in_(ds_ids_subq))
        except Exception:
            # Keep list endpoint resilient; treat as "no category filter".
            pass
    total = query.count()
    datasets = query.order_by(Dataset.created_at.desc()).offset(skip).limit(limit).all()

    # Avoid N+1 queries for PARTIAL_MEMBERS datasets
    partial_ids = [ds.id for ds in datasets if ds.permission == DatasetPermissionEnum.PARTIAL_MEMBERS]
    partial_member_map = {}
    partial_group_map = {}
    if partial_ids:
        rows = (
            db.query(DatasetPermission)
            .filter(
                DatasetPermission.tenant_id == tenant_id,
                DatasetPermission.dataset_id.in_(partial_ids),
            )
            .all()
        )
        from collections import defaultdict

        tmp = defaultdict(list)
        for row in rows:
            tmp[row.dataset_id].append(row.account_id)
        partial_member_map = dict(tmp)

        rows = (
            db.query(DatasetGroupPermission)
            .filter(
                DatasetGroupPermission.tenant_id == tenant_id,
                DatasetGroupPermission.dataset_id.in_(partial_ids),
            )
            .all()
        )
        tmp_g = defaultdict(list)
        for row in rows:
            tmp_g[row.dataset_id].append(row.group_id)
        partial_group_map = dict(tmp_g)

    results = []
    for ds in datasets:
        partial_list = None
        partial_groups = None
        if ds.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
            partial_list = partial_member_map.get(ds.id, [])
            partial_groups = partial_group_map.get(ds.id, [])
        default_parser_backend, default_chunk_strategy = _dataset_ingestion_defaults(ds)
        (
            rag_config_template_id,
            rag_config_template_key,
            rag_config_ab_experiment_key,
        ) = _dataset_rag_config_template_defaults_out(ds)
        prompt_template_id, prompt_template_key, prompt_ab_experiment_key = _dataset_prompt_defaults_out(ds)
        chunk_targets_v2 = _dataset_chunk_targets_v2_out(ds)
        retention_policy = _dataset_retention_policy_out(ds)
        results.append(DatasetOut(
            id=ds.id,
            tenant_id=ds.tenant_id,
            name=ds.name,
            description=ds.description,
            permission=ds.permission,
            owner_id=ds.owner_id,
            partial_member_list=partial_list,
            partial_group_list=partial_groups,
            default_parser_backend=default_parser_backend,
            default_chunk_strategy=default_chunk_strategy,
            rag_defaults=_dataset_rag_defaults_out(ds),
            default_rag_config_template_id=rag_config_template_id,
            default_rag_config_template_key=rag_config_template_key,
            default_rag_config_ab_experiment_key=rag_config_ab_experiment_key,
            default_prompt_template_id=prompt_template_id,
            default_prompt_template_key=prompt_template_key,
            default_prompt_ab_experiment_key=prompt_ab_experiment_key,
            chunk_targets_v2=chunk_targets_v2,
            pipeline=_dataset_pipeline_out(ds),
            retention_policy=retention_policy,
        ))
    return {"total": total, "items": results}


@router.get("/{dataset_id}", response_model=DatasetOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset(
    dataset_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)]
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)
    partial_list = None
    partial_groups = None
    if dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
        partial_list = DatasetPermissionService.get_dataset_partial_member_list(db, tenant_id, dataset_id)
        partial_groups = DatasetGroupPermissionService.get_dataset_partial_group_list(db, tenant_id, dataset_id)
    default_parser_backend, default_chunk_strategy = _dataset_ingestion_defaults(dataset)
    (
        rag_config_template_id,
        rag_config_template_key,
        rag_config_ab_experiment_key,
    ) = _dataset_rag_config_template_defaults_out(dataset)
    prompt_template_id, prompt_template_key, prompt_ab_experiment_key = _dataset_prompt_defaults_out(dataset)
    chunk_targets_v2 = _dataset_chunk_targets_v2_out(dataset)
    retention_policy = _dataset_retention_policy_out(dataset)
    return DatasetOut(
        id=dataset.id,
        tenant_id=dataset.tenant_id,
        name=dataset.name,
        description=dataset.description,
        permission=dataset.permission,
        owner_id=dataset.owner_id,
        partial_member_list=partial_list,
        partial_group_list=partial_groups,
        default_parser_backend=default_parser_backend,
        default_chunk_strategy=default_chunk_strategy,
        rag_defaults=_dataset_rag_defaults_out(dataset),
        default_rag_config_template_id=rag_config_template_id,
        default_rag_config_template_key=rag_config_template_key,
        default_rag_config_ab_experiment_key=rag_config_ab_experiment_key,
        default_prompt_template_id=prompt_template_id,
        default_prompt_template_key=prompt_template_key,
        default_prompt_ab_experiment_key=prompt_ab_experiment_key,
        chunk_targets_v2=chunk_targets_v2,
        pipeline=_dataset_pipeline_out(dataset),
        retention_policy=retention_policy,
    )


@router.get("/{dataset_id}/categories", response_model=DatasetCategoryAssignmentResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset_categories(
    dataset_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    category_ids = DatasetCategoryService.list_dataset_category_ids(db, tenant_id=tenant_id, account_id=account_id, dataset_id=dataset_id)
    return DatasetCategoryAssignmentResponse(dataset_id=dataset_id, category_ids=category_ids)


@router.put("/{dataset_id}/categories", response_model=DatasetCategoryAssignmentResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def set_dataset_categories(
    dataset_id: UUID,
    payload: DatasetCategoryAssignmentRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    category_ids = DatasetCategoryService.set_dataset_categories(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        category_ids=payload.category_ids or [],
    )
    return DatasetCategoryAssignmentResponse(dataset_id=dataset_id, category_ids=category_ids)


@router.patch("/{dataset_id}", response_model=DatasetOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def update_dataset(
    dataset_id: UUID,
    payload: DatasetUpdate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)]
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)

    updated = DatasetService.update_dataset(
        db=db,
        dataset=dataset,
        updater_id=account_id,
        name=payload.name,
        description=payload.description,
        permission=payload.permission,
        partial_members=payload.partial_member_list,
        partial_groups=payload.partial_group_list,
    )

    # Update dataset-level defaults (stored in datasets.metadata).
    meta = dict(getattr(updated, "dataset_metadata", None) or {})
    changed = False

    if payload.pipeline is not None:
        options = PipelineOptions(**payload.pipeline.model_dump(exclude_none=True))
        changed = upsert_pipeline_metadata(meta, options=options) or changed

    if payload.default_parser_backend is not None:
        raw = str(payload.default_parser_backend or "").strip()
        if raw:
            meta["default_parser_backend"] = _normalize_dataset_default_parser_backend(raw)
        else:
            meta.pop("default_parser_backend", None)
        changed = True

    if payload.default_chunk_strategy is not None:
        raw = str(payload.default_chunk_strategy or "").strip()
        if raw:
            meta["default_chunk_strategy"] = _normalize_dataset_default_chunk_strategy(raw)
        else:
            meta.pop("default_chunk_strategy", None)
        changed = True

    if payload.rag_defaults is not None:
        data = payload.rag_defaults.model_dump(exclude_none=True)
        if data:
            meta["rag_defaults"] = data
        else:
            meta.pop("rag_defaults", None)
        changed = True

    # RAG config template defaults allow explicit clearing via `null` (need fields_set checks).
    if "default_rag_config_template_id" in payload.model_fields_set:
        if payload.default_rag_config_template_id is not None:
            meta["default_rag_config_template_id"] = str(payload.default_rag_config_template_id)
        else:
            meta.pop("default_rag_config_template_id", None)
        changed = True

    if "default_rag_config_template_key" in payload.model_fields_set:
        val = str(payload.default_rag_config_template_key or "").strip().lower()
        if val:
            meta["default_rag_config_template_key"] = val
        else:
            meta.pop("default_rag_config_template_key", None)
        changed = True

    if "default_rag_config_ab_experiment_key" in payload.model_fields_set:
        val = str(payload.default_rag_config_ab_experiment_key or "").strip()
        if val:
            meta["default_rag_config_ab_experiment_key"] = val
        else:
            meta.pop("default_rag_config_ab_experiment_key", None)
        changed = True

    # Prompt defaults allow explicit clearing via `null` (need fields_set checks).
    if "default_prompt_template_id" in payload.model_fields_set:
        if payload.default_prompt_template_id is not None:
            meta["default_prompt_template_id"] = str(payload.default_prompt_template_id)
        else:
            meta.pop("default_prompt_template_id", None)
        changed = True

    if "default_prompt_template_key" in payload.model_fields_set:
        val = str(payload.default_prompt_template_key or "").strip().lower()
        if val:
            meta["default_prompt_template_key"] = val
        else:
            meta.pop("default_prompt_template_key", None)
        changed = True

    if "default_prompt_ab_experiment_key" in payload.model_fields_set:
        val = str(payload.default_prompt_ab_experiment_key or "").strip()
        if val:
            meta["default_prompt_ab_experiment_key"] = val
        else:
            meta.pop("default_prompt_ab_experiment_key", None)
        changed = True

    if payload.chunk_targets_v2 is not None:
        data = payload.chunk_targets_v2.model_dump(exclude_none=True)
        if data:
            meta["chunk_targets_v2"] = data
        else:
            meta.pop("chunk_targets_v2", None)
        changed = True

    if "retention_policy" in payload.model_fields_set:
        changed = upsert_retention_policy_metadata(meta, policy=payload.retention_policy, replace=True) or changed

    if changed:
        updated.dataset_metadata = meta
        db.commit()
        db.refresh(updated)

    partial_list = None
    partial_groups = None
    if updated.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
        partial_list = DatasetPermissionService.get_dataset_partial_member_list(db, tenant_id, updated.id)
        partial_groups = DatasetGroupPermissionService.get_dataset_partial_group_list(db, tenant_id, updated.id)

    default_parser_backend, default_chunk_strategy = _dataset_ingestion_defaults(updated)
    (
        rag_config_template_id,
        rag_config_template_key,
        rag_config_ab_experiment_key,
    ) = _dataset_rag_config_template_defaults_out(updated)
    prompt_template_id, prompt_template_key, prompt_ab_experiment_key = _dataset_prompt_defaults_out(updated)
    chunk_targets_v2 = _dataset_chunk_targets_v2_out(updated)
    retention_policy = _dataset_retention_policy_out(updated)

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="dataset.update",
        resource_type="dataset",
        resource_id=str(updated.id),
        details={
            "changed": bool(changed),
            "name": str(updated.name or "")[:255],
            "permission": str(updated.permission or ""),
        },
    )
    try:
        db.commit()
    except Exception:
        pass

    return DatasetOut(
        id=updated.id,
        tenant_id=updated.tenant_id,
        name=updated.name,
        description=updated.description,
        permission=updated.permission,
        owner_id=updated.owner_id,
        partial_member_list=partial_list,
        partial_group_list=partial_groups,
        default_parser_backend=default_parser_backend,
        default_chunk_strategy=default_chunk_strategy,
        rag_defaults=_dataset_rag_defaults_out(updated),
        default_rag_config_template_id=rag_config_template_id,
        default_rag_config_template_key=rag_config_template_key,
        default_rag_config_ab_experiment_key=rag_config_ab_experiment_key,
        default_prompt_template_id=prompt_template_id,
        default_prompt_template_key=prompt_template_key,
        default_prompt_ab_experiment_key=prompt_ab_experiment_key,
        chunk_targets_v2=chunk_targets_v2,
        pipeline=_dataset_pipeline_out(updated),
        retention_policy=retention_policy,
    )


def _build_dataset_config_bundle(ds: Dataset) -> DatasetConfigBundle:
    meta = getattr(ds, "dataset_metadata", None)
    meta_dict = meta if isinstance(meta, dict) else {}

    default_parser_backend, default_chunk_strategy = _dataset_ingestion_defaults(ds)
    (
        rag_config_template_id,
        rag_config_template_key,
        rag_config_ab_experiment_key,
    ) = _dataset_rag_config_template_defaults_out(ds)
    prompt_template_id, prompt_template_key, prompt_ab_experiment_key = _dataset_prompt_defaults_out(ds)

    ingestion_policy = None
    if "ingestion_policy" in meta_dict:
        ingestion_policy = parse_ingestion_policy_from_metadata(meta_dict)

    fls_policy = None
    if "fls_policy" in meta_dict:
        fls_policy = parse_fls_policy_from_metadata(meta_dict)

    workflow_layout = meta_dict.get("workflow_layout") if isinstance(meta_dict.get("workflow_layout"), dict) else None

    return DatasetConfigBundle(
        default_parser_backend=default_parser_backend,
        default_chunk_strategy=default_chunk_strategy,
        rag_defaults=_dataset_rag_defaults_out(ds),
        default_rag_config_template_id=rag_config_template_id,
        default_rag_config_template_key=rag_config_template_key,
        default_rag_config_ab_experiment_key=rag_config_ab_experiment_key,
        default_prompt_template_id=prompt_template_id,
        default_prompt_template_key=prompt_template_key,
        default_prompt_ab_experiment_key=prompt_ab_experiment_key,
        chunk_targets_v2=_dataset_chunk_targets_v2_out(ds),
        pipeline=_dataset_pipeline_out(ds),
        retention_policy=_dataset_retention_policy_out(ds),
        ingestion_policy=ingestion_policy,
        fls_policy=fls_policy,
        workflow_layout=dict(workflow_layout) if isinstance(workflow_layout, dict) else None,
    )


@router.get("/{dataset_id}/config/export", response_model=DatasetConfigExport, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_config(
    dataset_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Export a portable dataset config bundle (JSON)."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    return DatasetConfigExport(
        version="1",
        dataset_id=ds.id,
        name=str(ds.name or ""),
        exported_at=datetime.now(UTC),
        config=_build_dataset_config_bundle(ds),
    )


@router.post("/{dataset_id}/config/import", response_model=DatasetOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def import_dataset_config(
    dataset_id: UUID,
    payload: DatasetConfigImportRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Import a dataset config bundle.

    Semantics:
    - replace=false (default): apply only non-null fields in the bundle (no clearing).
    - replace=true: overwrite/clear supported config keys based on bundle content.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    replace = bool(payload.replace)
    cfg = payload.config
    meta = dict(getattr(ds, "dataset_metadata", None) or {})
    changed = False

    # Pipeline defaults
    if replace or cfg.pipeline is not None:
        if cfg.pipeline is not None:
            options = PipelineOptions(**cfg.pipeline.model_dump(exclude_none=True))
            changed = upsert_pipeline_metadata(meta, options=options) or changed
        else:
            meta.pop("pipeline", None)
            changed = True

    # Ingestion defaults
    if replace or cfg.default_parser_backend is not None:
        raw = str(cfg.default_parser_backend or "").strip()
        if raw:
            meta["default_parser_backend"] = _normalize_dataset_default_parser_backend(raw)
        else:
            meta.pop("default_parser_backend", None)
        changed = True

    if replace or cfg.default_chunk_strategy is not None:
        raw = str(cfg.default_chunk_strategy or "").strip()
        if raw:
            meta["default_chunk_strategy"] = _normalize_dataset_default_chunk_strategy(raw)
        else:
            meta.pop("default_chunk_strategy", None)
        changed = True

    # RAG defaults
    if replace or cfg.rag_defaults is not None:
        data = cfg.rag_defaults.model_dump(exclude_none=True) if cfg.rag_defaults is not None else {}
        if data:
            meta["rag_defaults"] = data
        else:
            meta.pop("rag_defaults", None)
        changed = True

    # RAG config template defaults
    if replace or cfg.default_rag_config_template_id is not None:
        if cfg.default_rag_config_template_id is not None:
            meta["default_rag_config_template_id"] = str(cfg.default_rag_config_template_id)
        else:
            meta.pop("default_rag_config_template_id", None)
        changed = True

    if replace or cfg.default_rag_config_template_key is not None:
        val = str(cfg.default_rag_config_template_key or "").strip().lower()
        if val:
            meta["default_rag_config_template_key"] = val
        else:
            meta.pop("default_rag_config_template_key", None)
        changed = True

    if replace or cfg.default_rag_config_ab_experiment_key is not None:
        val = str(cfg.default_rag_config_ab_experiment_key or "").strip()
        if val:
            meta["default_rag_config_ab_experiment_key"] = val
        else:
            meta.pop("default_rag_config_ab_experiment_key", None)
        changed = True

    # Prompt defaults
    if replace or cfg.default_prompt_template_id is not None:
        if cfg.default_prompt_template_id is not None:
            meta["default_prompt_template_id"] = str(cfg.default_prompt_template_id)
        else:
            meta.pop("default_prompt_template_id", None)
        changed = True

    if replace or cfg.default_prompt_template_key is not None:
        val = str(cfg.default_prompt_template_key or "").strip().lower()
        if val:
            meta["default_prompt_template_key"] = val
        else:
            meta.pop("default_prompt_template_key", None)
        changed = True

    if replace or cfg.default_prompt_ab_experiment_key is not None:
        val = str(cfg.default_prompt_ab_experiment_key or "").strip()
        if val:
            meta["default_prompt_ab_experiment_key"] = val
        else:
            meta.pop("default_prompt_ab_experiment_key", None)
        changed = True

    if replace or cfg.chunk_targets_v2 is not None:
        if cfg.chunk_targets_v2 is not None:
            data = cfg.chunk_targets_v2.model_dump(exclude_none=True)
            if data:
                meta["chunk_targets_v2"] = data
            else:
                meta.pop("chunk_targets_v2", None)
        else:
            meta.pop("chunk_targets_v2", None)
        changed = True

    if replace or cfg.retention_policy is not None:
        changed = upsert_retention_policy_metadata(meta, policy=cfg.retention_policy, replace=True) or changed

    # Ingestion policy
    if replace or cfg.ingestion_policy is not None:
        if cfg.ingestion_policy is not None:
            normalized = validate_and_normalize_ingestion_policy(cfg.ingestion_policy)
            meta["ingestion_policy"] = normalized.model_dump()
        else:
            meta.pop("ingestion_policy", None)
        changed = True

    # FLS policy
    if replace or cfg.fls_policy is not None:
        if cfg.fls_policy is not None:
            normalized = validate_and_normalize_fls_policy(cfg.fls_policy)
            meta["fls_policy"] = normalized.model_dump()
        else:
            meta.pop("fls_policy", None)
        changed = True

    if replace or cfg.workflow_layout is not None:
        if cfg.workflow_layout is not None:
            meta["workflow_layout"] = dict(cfg.workflow_layout)
        else:
            meta.pop("workflow_layout", None)
        changed = True

    if changed:
        ds.dataset_metadata = meta
        db.commit()
        db.refresh(ds)

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="dataset.config.import",
        resource_type="dataset",
        resource_id=str(ds.id),
        details={"replace": bool(replace)},
    )
    with contextlib.suppress(Exception):
        db.commit()

    partial_list = None
    partial_groups = None
    if ds.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
        partial_list = DatasetPermissionService.get_dataset_partial_member_list(db, tenant_id, ds.id)
        partial_groups = DatasetGroupPermissionService.get_dataset_partial_group_list(db, tenant_id, ds.id)

    default_parser_backend, default_chunk_strategy = _dataset_ingestion_defaults(ds)
    (
        rag_config_template_id,
        rag_config_template_key,
        rag_config_ab_experiment_key,
    ) = _dataset_rag_config_template_defaults_out(ds)
    prompt_template_id, prompt_template_key, prompt_ab_experiment_key = _dataset_prompt_defaults_out(ds)
    chunk_targets_v2 = _dataset_chunk_targets_v2_out(ds)
    retention_policy = _dataset_retention_policy_out(ds)

    return DatasetOut(
        id=ds.id,
        tenant_id=ds.tenant_id,
        name=ds.name,
        description=ds.description,
        permission=ds.permission,
        owner_id=ds.owner_id,
        partial_member_list=partial_list,
        partial_group_list=partial_groups,
        default_parser_backend=default_parser_backend,
        default_chunk_strategy=default_chunk_strategy,
        rag_defaults=_dataset_rag_defaults_out(ds),
        default_rag_config_template_id=rag_config_template_id,
        default_rag_config_template_key=rag_config_template_key,
        default_rag_config_ab_experiment_key=rag_config_ab_experiment_key,
        default_prompt_template_id=prompt_template_id,
        default_prompt_template_key=prompt_template_key,
        default_prompt_ab_experiment_key=prompt_ab_experiment_key,
        chunk_targets_v2=chunk_targets_v2,
        pipeline=_dataset_pipeline_out(ds),
        retention_policy=retention_policy,
    )


@router.post("/{dataset_id}/clone", response_model=DatasetOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def clone_dataset(
    dataset_id: UUID,
    payload: DatasetCloneRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Clone an existing dataset (config + optional permission/members)."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    src = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_writable(db, src, account_id)

    permission = src.permission if payload.copy_permission else DatasetPermissionEnum.ALL_TEAM_MEMBERS
    partial_members: list[str] = []
    partial_groups: list[UUID] = []
    if permission == DatasetPermissionEnum.PARTIAL_MEMBERS and payload.copy_partial_members:
        partial_members = DatasetPermissionService.get_dataset_partial_member_list(db, tenant_id, src.id) or []
        partial_groups = DatasetGroupPermissionService.get_dataset_partial_group_list(db, tenant_id, src.id) or []

    created = DatasetService.create_dataset(
        db=db,
        tenant_id=tenant_id,
        name=str(payload.name or "").strip(),
        description=str(payload.description or "").strip() or None,
        permission=permission,
        owner_id=account_id,
        partial_members=partial_members,
        partial_groups=partial_groups,
    )

    # Copy portable config keys from the source dataset.
    created.dataset_metadata = dict(getattr(src, "dataset_metadata", None) or {})
    db.commit()
    db.refresh(created)

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="dataset.clone",
        resource_type="dataset",
        resource_id=str(created.id),
        details={"source_dataset_id": str(src.id)},
    )
    with contextlib.suppress(Exception):
        db.commit()

    partial_list = None
    partial_groups_out = None
    if created.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
        partial_list = DatasetPermissionService.get_dataset_partial_member_list(db, tenant_id, created.id)
        partial_groups_out = DatasetGroupPermissionService.get_dataset_partial_group_list(db, tenant_id, created.id)

    default_parser_backend, default_chunk_strategy = _dataset_ingestion_defaults(created)
    (
        rag_config_template_id,
        rag_config_template_key,
        rag_config_ab_experiment_key,
    ) = _dataset_rag_config_template_defaults_out(created)
    prompt_template_id, prompt_template_key, prompt_ab_experiment_key = _dataset_prompt_defaults_out(created)
    chunk_targets_v2 = _dataset_chunk_targets_v2_out(created)
    retention_policy = _dataset_retention_policy_out(created)

    return DatasetOut(
        id=created.id,
        tenant_id=created.tenant_id,
        name=created.name,
        description=created.description,
        permission=created.permission,
        owner_id=created.owner_id,
        partial_member_list=partial_list,
        partial_group_list=partial_groups_out,
        default_parser_backend=default_parser_backend,
        default_chunk_strategy=default_chunk_strategy,
        rag_defaults=_dataset_rag_defaults_out(created),
        default_rag_config_template_id=rag_config_template_id,
        default_rag_config_template_key=rag_config_template_key,
        default_rag_config_ab_experiment_key=rag_config_ab_experiment_key,
        default_prompt_template_id=prompt_template_id,
        default_prompt_template_key=prompt_template_key,
        default_prompt_ab_experiment_key=prompt_ab_experiment_key,
        chunk_targets_v2=chunk_targets_v2,
        pipeline=_dataset_pipeline_out(created),
        retention_policy=retention_policy,
    )


@router.delete("/{dataset_id}", status_code=204, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def delete_dataset(
    dataset_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)]
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)

    # Prevent deleting non-empty datasets. The DB also enforces tenant-safe dataset references; keep the API check for a friendly 409.
    doc_count = (
        db.query(DBDocument)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id)
        .count()
    )
    if doc_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Dataset is not empty: {doc_count} documents still reference this dataset. Delete documents first.",
        )

    # Prevent deleting while long-running dataset scans are still active.
    active_profile_scans = (
        db.query(DBDatasetProfileScanRun)
        .filter(
            DBDatasetProfileScanRun.tenant_id == tenant_id,
            DBDatasetProfileScanRun.dataset_id == dataset_id,
            DBDatasetProfileScanRun.status.in_(["pending", "running"]),
        )
        .count()
    )
    active_precheck_scans = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
            DBDatasetPrecheckScanRun.status.in_(["pending", "running"]),
        )
        .count()
    )
    if active_profile_scans > 0 or active_precheck_scans > 0:
        raise HTTPException(
            status_code=409,
            detail="Dataset has active scan runs (pending/running). Cancel them and retry.",
        )

    # Capture precheck run ids for best-effort artifact cleanup after deletion.
    precheck_run_ids = [
        r[0]
        for r in (
            db.query(DBDatasetPrecheckScanRun.id)
            .filter(DBDatasetPrecheckScanRun.tenant_id == tenant_id, DBDatasetPrecheckScanRun.dataset_id == dataset_id)
            .all()
        )
        if r and r[0] is not None
    ]

    db.delete(dataset)
    db.commit()

    # Best-effort: cleanup structured table store directory for this dataset.
    try:
        import shutil
        from pathlib import Path

        root = Path(str(getattr(settings, "TABLE_STORE_DIR", "./uploads/table_store") or "./uploads/table_store"))
        ds_dir = (root / str(tenant_id) / str(dataset_id)).resolve(strict=False)
        # Defense-in-depth: only delete under TABLE_STORE_DIR.
        from app.services.path_safety import resolve_under_base

        safe_dir = resolve_under_base(ds_dir, base=root)
        if safe_dir is not None and safe_dir.exists():
            shutil.rmtree(safe_dir, ignore_errors=True)
    except Exception:
        pass

    # Best-effort: cleanup precheck artifacts under uploads/{tenant}/precheck/{run_id}/
    try:
        import shutil
        from pathlib import Path

        upload_root = Path(getattr(settings, "UPLOAD_DIR", "./uploads") or "./uploads")
        tenant_root = upload_root / str(tenant_id)
        for rid in precheck_run_ids:
            try:
                run_dir = tenant_root / "precheck" / str(rid)
                from app.services.path_safety import resolve_under_base

                safe = resolve_under_base(run_dir, base=tenant_root)
                if safe is not None and safe.exists():
                    shutil.rmtree(safe, ignore_errors=True)
            except Exception:
                continue
    except Exception:
        pass
    return None


@router.post("/{dataset_id}/purge", response_model=DatasetPurgeResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def purge_dataset_documents(
    dataset_id: UUID,
    max_delete: Annotated[
        int, Query(ge=1, le=10000, description='Max documents to delete in this call')
    ] = 1000,
    dry_run: Annotated[bool, Query(description='Plan only; do not delete')] = True,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Purge documents within a dataset (bounded, best-effort).

    Notes:
    - This endpoint intentionally does NOT delete the dataset record itself.
      Once the dataset is empty, callers can use DELETE /datasets/{id}.
    - Default is dry-run for safety.
    - Uses the existing document delete lifecycle to ensure artifacts (vectors/KG/object storage) are removed.
    """
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.LIFECYCLE_MANAGE,
        detail="No permission to purge dataset documents",
    )

    DatasetService.get_dataset(db, tenant_id, dataset_id)

    # Avoid purging while long-running dataset scans are still active.
    active_profile_scans = (
        db.query(DBDatasetProfileScanRun)
        .filter(
            DBDatasetProfileScanRun.tenant_id == tenant_id,
            DBDatasetProfileScanRun.dataset_id == dataset_id,
            DBDatasetProfileScanRun.status.in_(["pending", "running"]),
        )
        .count()
    )
    active_precheck_scans = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
            DBDatasetPrecheckScanRun.status.in_(["pending", "running"]),
        )
        .count()
    )
    if active_profile_scans > 0 or active_precheck_scans > 0:
        raise HTTPException(
            status_code=409,
            detail="Dataset has active scan runs (pending/running). Cancel them and retry.",
        )

    # Plan eligible documents for this call (bounded).
    rows = (
        db.query(DBDocument.id)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id)
        .order_by(DBDocument.created_at.asc(), DBDocument.id.asc())
        .limit(int(max_delete or 0))
        .all()
    )
    document_ids = [row[0] for row in rows if row and row[0] is not None]
    eligible = len(document_ids)

    deleted = 0
    not_found = 0
    denied = 0
    conflicts = 0
    errors = 0

    if not bool(dry_run):
        from app.api.v1.documents import _delete_document_lifecycle

        for document_id in document_ids:
            try:
                await _delete_document_lifecycle(
                    document_id=document_id,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    db=db,
                    enforce_permissions=False,
                )
                deleted += 1
            except HTTPException as exc:
                if exc.status_code == 404:
                    not_found += 1
                    continue
                if exc.status_code in (401, 403):
                    denied += 1
                    continue
                if exc.status_code in (409, 413, 429, 503):
                    conflicts += 1
                    continue
                errors += 1
                continue
            except Exception:
                errors += 1
                continue

    # Best-effort audit log (commit separately; never block response).
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="dataset.purge",
            resource_type="dataset",
            resource_id=str(dataset_id),
            details={
                "dry_run": bool(dry_run),
                "max_delete": int(max_delete or 0),
                "eligible": int(eligible or 0),
                "deleted": int(deleted or 0),
                "not_found": int(not_found or 0),
                "denied": int(denied or 0),
                "conflicts": int(conflicts or 0),
                "errors": int(errors or 0),
            },
        )
        db.commit()
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()

    return DatasetPurgeResponse(
        dataset_id=dataset_id,
        dry_run=bool(dry_run),
        max_delete=int(max_delete or 0),
        eligible=int(eligible or 0),
        deleted=int(deleted or 0),
        not_found=int(not_found or 0),
        denied=int(denied or 0),
        conflicts=int(conflicts or 0),
        errors=int(errors or 0),
    )


_INGESTION_POLICY_VERSIONS_KEY = "ingestion_policy_versions"
_INGESTION_POLICY_CURRENT_VERSION_ID_KEY = "ingestion_policy_current_version_id"
_MAX_INGESTION_POLICY_VERSIONS = 50


def _append_ingestion_policy_version(
    meta: dict,
    *,
    policy: IngestionPolicy,
    account_id: str,
    source: str,
    note: str | None = None,
    rollback_from_version_id: str | None = None,
    rollback_to_version_id: str | None = None,
) -> tuple[dict, str]:
    versions_raw = meta.get(_INGESTION_POLICY_VERSIONS_KEY)
    versions: list[dict] = [v for v in versions_raw if isinstance(v, dict)] if isinstance(versions_raw, list) else []

    version_id = uuid.uuid4().hex
    item: dict[str, object] = {
        "id": version_id,
        "created_at": datetime.now(UTC).isoformat(),
        "created_by": str(account_id or "").strip() or None,
        "source": str(source or "put"),
        "policy": policy.model_dump(),
    }
    if isinstance(note, str) and note.strip():
        item["note"] = note.strip()[:200]
    if rollback_from_version_id:
        item["rollback_from_version_id"] = str(rollback_from_version_id)
    if rollback_to_version_id:
        item["rollback_to_version_id"] = str(rollback_to_version_id)

    versions = [item] + versions
    if len(versions) > _MAX_INGESTION_POLICY_VERSIONS:
        versions = versions[:_MAX_INGESTION_POLICY_VERSIONS]

    meta[_INGESTION_POLICY_VERSIONS_KEY] = versions
    meta[_INGESTION_POLICY_CURRENT_VERSION_ID_KEY] = version_id
    return meta, version_id


@router.get("/{dataset_id}/ingestion-policy", response_model=IngestionPolicyWithAudit, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset_ingestion_policy(
    dataset_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)
    meta = getattr(dataset, "dataset_metadata", None)
    meta_obj = meta if isinstance(meta, dict) else {}
    policy = parse_ingestion_policy_from_metadata(meta_obj) or IngestionPolicy(version="1", rules=[])
    audit = _build_table_routing_policy_audit(meta=meta_obj, policy=policy)
    return IngestionPolicyWithAudit(
        version=policy.version,
        rules=policy.rules,
        table_routing_policy_audit=audit,
    )


@router.get("/{dataset_id}/ingestion-policy/versions", response_model=IngestionPolicyVersionListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_dataset_ingestion_policy_versions(
    dataset_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    meta = dict(getattr(dataset, "dataset_metadata", None) or {})
    current_id = meta.get(_INGESTION_POLICY_CURRENT_VERSION_ID_KEY)
    current_id = str(current_id) if isinstance(current_id, str) and current_id.strip() else None

    items_raw = meta.get(_INGESTION_POLICY_VERSIONS_KEY)
    items = items_raw if isinstance(items_raw, list) else []
    # Keep stable order: newest first (we always prepend).
    return IngestionPolicyVersionListResponse(current_version_id=current_id, items=[it for it in items if isinstance(it, dict)])


@router.post("/{dataset_id}/ingestion-policy/rollback", response_model=IngestionPolicy, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def rollback_dataset_ingestion_policy(
    dataset_id: UUID,
    body: IngestionPolicyRollbackRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)

    meta = dict(getattr(dataset, "dataset_metadata", None) or {})
    items_raw = meta.get(_INGESTION_POLICY_VERSIONS_KEY)
    items = items_raw if isinstance(items_raw, list) else []
    target_id = str(body.version_id or "").strip()
    if not target_id:
        raise HTTPException(status_code=400, detail="version_id is required")

    target: dict | None = None
    for it in items:
        if not isinstance(it, dict):
            continue
        if str(it.get("id") or "").strip() == target_id:
            target = it
            break
    if target is None:
        raise HTTPException(status_code=404, detail="policy version not found")

    raw_policy = target.get("policy")
    if not isinstance(raw_policy, dict):
        raise HTTPException(status_code=400, detail="invalid stored policy version")

    try:
        model = IngestionPolicy(**raw_policy)
        normalized = validate_and_normalize_ingestion_policy(model)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid stored ingestion policy: {str(exc)[:200]}") from exc

    # Apply as current policy.
    if normalized.rules:
        meta["ingestion_policy"] = normalized.model_dump()
    else:
        meta.pop("ingestion_policy", None)

    prev_current = meta.get(_INGESTION_POLICY_CURRENT_VERSION_ID_KEY)
    prev_current_id = str(prev_current) if isinstance(prev_current, str) and prev_current.strip() else None
    meta, _new_id = _append_ingestion_policy_version(
        meta,
        policy=normalized,
        account_id=account_id,
        source="rollback",
        rollback_from_version_id=prev_current_id,
        rollback_to_version_id=target_id,
    )

    dataset.dataset_metadata = meta
    db.commit()
    db.refresh(dataset)
    return normalized


@router.put("/{dataset_id}/ingestion-policy", response_model=IngestionPolicy, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def put_dataset_ingestion_policy(
    dataset_id: UUID,
    payload: IngestionPolicy,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)

    normalized = validate_and_normalize_ingestion_policy(payload)
    meta = dict(getattr(dataset, "dataset_metadata", None) or {})
    if normalized.rules:
        meta["ingestion_policy"] = normalized.model_dump()
    else:
        meta.pop("ingestion_policy", None)
    meta, _vid = _append_ingestion_policy_version(meta, policy=normalized, account_id=account_id, source="put")
    dataset.dataset_metadata = meta
    db.commit()
    db.refresh(dataset)
    return normalized


@router.post("/{dataset_id}/ingestion-policy/import", response_model=IngestionPolicyImportResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def import_dataset_ingestion_policy(
    dataset_id: UUID,
    file: Annotated[UploadFile, File(...)],
    replace: Annotated[bool, Form()] = True,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)

    max_bytes = 256 * 1024
    raw = await file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(status_code=400, detail="policy file too large (max 256KB)")
    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="invalid JSON (expect UTF-8)") from exc

    try:
        model = IngestionPolicy(**obj)
        normalized = validate_and_normalize_ingestion_policy(model)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid ingestion policy: {str(exc)[:200]}") from exc

    meta = dict(getattr(dataset, "dataset_metadata", None) or {})
    if not replace and "ingestion_policy" in meta:
        # Best-effort: do not merge in v1 (explicit by design).
        raise HTTPException(status_code=409, detail="ingestion_policy already exists; set replace=true to overwrite")
    if normalized.rules:
        meta["ingestion_policy"] = normalized.model_dump()
    else:
        meta.pop("ingestion_policy", None)
    meta, _vid = _append_ingestion_policy_version(meta, policy=normalized, account_id=account_id, source="import")
    dataset.dataset_metadata = meta
    db.commit()
    db.refresh(dataset)
    return IngestionPolicyImportResponse(replaced=True, rule_count=len(normalized.rules))


@router.get("/{dataset_id}/ingestion-policy/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_ingestion_policy(
    dataset_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)
    meta = getattr(dataset, "dataset_metadata", None)
    policy = parse_ingestion_policy_from_metadata(meta if isinstance(meta, dict) else {}) or IngestionPolicy(version="1", rules=[])

    content = export_policy_json(policy)
    safe = _DATASET_SAFE_NAME_RE.sub("_", str(getattr(dataset, "name", "") or "dataset"))[:64]
    filename = f"{safe}.ingestion-policy.json"
    return Response(
        content=content,
        media_type=_APPLICATION_JSON_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _scan_run_out_from_row(row: DBDatasetProfileScanRun) -> DatasetProfileScanRunOut:
    cfg = getattr(row, "config", None)
    if not isinstance(cfg, dict):
        cfg = {}
    summary = getattr(row, "summary", None)
    if not isinstance(summary, dict):
        summary = {}
    return DatasetProfileScanRunOut(
        id=row.id,
        tenant_id=row.tenant_id,
        dataset_id=row.dataset_id,
        requested_by=getattr(row, "requested_by", None),
        kind=str(getattr(row, "kind", "") or "deep"),
        status=str(getattr(row, "status", "") or "pending"),
        progress=int(getattr(row, "progress", 0) or 0),
        config=cfg,
        summary=summary,
        error_message=getattr(row, "error_message", None),
        started_at=getattr(row, "started_at", None),
        finished_at=getattr(row, "finished_at", None),
        created_at=getattr(row, "created_at", None),
        updated_at=getattr(row, "updated_at", None),
    )


def _run_deep_scan_background(
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    scan_run_id: UUID,
) -> None:
    """
    BackgroundTasks wrapper for deep scan when the queue is disabled.

    Uses a dedicated DB session and marks the run as failed on exception.
    """
    db = SessionLocal()
    try:
        run_dataset_profile_deep_scan(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            scan_run_id=scan_run_id,
        )
    except Exception as exc:  # noqa: BLE001
        try:
            row = (
                db.query(DBDatasetProfileScanRun)
                .filter(
                    DBDatasetProfileScanRun.id == scan_run_id,
                    DBDatasetProfileScanRun.tenant_id == tenant_id,
                    DBDatasetProfileScanRun.dataset_id == dataset_id,
                )
                .first()
            )
            if row is not None:
                row.status = "failed"
                row.error_message = str(exc)[:200]
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.get("/{dataset_id}/profile/summary", response_model=DatasetProfileSummary, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset_profile_summary(
    dataset_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    summary = compute_dataset_profile_summary(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
    )
    return summary


@router.get("/{dataset_id}/health", response_model=DatasetHealthResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset_health(
    dataset_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Dataset health dashboard v1.

    Keep it light: reuse existing profile summary and derive ingestion signals from it.
    """
    profile = compute_dataset_profile_summary(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
    )

    by_status = {str(k): int(v or 0) for k, v in (getattr(profile, "by_status", None) or {}).items()}

    ingestion = DatasetHealthIngestionSummary(
        total_documents=int(getattr(profile, "total_documents", 0) or 0),
        by_status=by_status,
        pending=int(by_status.get("pending", 0) or 0),
        processing=int(by_status.get("processing", 0) or 0),
        completed=int(by_status.get("completed", 0) or 0),
        failed=int(by_status.get("failed", 0) or 0),
        quarantined=int(by_status.get("quarantined", 0) or 0),
        cancelled=int(by_status.get("cancelled", 0) or 0),
    )

    return DatasetHealthResponse(
        dataset_id=dataset_id,
        generated_at=datetime.now(UTC),
        profile=profile,
        ingestion=ingestion,
    )


@router.get("/{dataset_id}/profile/findings/{finding_key}", response_model=DatasetProfileFindingListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_dataset_profile_finding_documents(
    dataset_id: UUID,
    finding_key: str,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        return list_finding_documents(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            finding_key=finding_key,
            skip=int(skip or 0),
            limit=int(limit or 50),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:200]) from exc


@router.get("/{dataset_id}/profile/buckets/documents", response_model=DatasetProfileDocumentListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_dataset_profile_bucket_documents(
    dataset_id: UUID,
    dimension: Annotated[str, Query(..., max_length=40)],
    bucket: Annotated[str, Query(..., max_length=200)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    include_preview: Annotated[bool, Query()] = True,
    preview_max_chars: Annotated[int, Query(ge=80, le=2000)] = 360,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    try:
        return list_bucket_documents(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            dimension=dimension,
            bucket=bucket,
            skip=int(skip or 0),
            limit=int(limit or 50),
            include_preview=bool(include_preview),
            preview_max_chars=int(preview_max_chars or 0),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:200]) from exc


@router.post("/{dataset_id}/profile/scan-runs", response_model=DatasetProfileScanRunOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def create_dataset_profile_scan_run(
    dataset_id: UUID,
    body: DatasetProfileScanRunCreateRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)

    # Prevent accidental duplicate long-running scans.
    existing = (
        db.query(DBDatasetProfileScanRun)
        .filter(
            DBDatasetProfileScanRun.tenant_id == tenant_id,
            DBDatasetProfileScanRun.dataset_id == dataset_id,
            DBDatasetProfileScanRun.status.in_(["pending", "running"]),
        )
        .order_by(DBDatasetProfileScanRun.created_at.desc())
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="A scan run is already pending/running for this dataset")

    cfg = body.model_dump(exclude_none=True)
    row = DBDatasetProfileScanRun(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        requested_by=account_id,
        kind="deep",
        status="pending",
        progress=0,
        config=cfg,
        summary={},
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    job_id = f"dataset_profile_scan:{tenant_id}:{dataset_id}:{row.id}"
    task_id = await enqueue_dataset_profile_scan(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        scan_run_id=row.id,
        requested_by=account_id,
        job_id=job_id,
    )
    if not task_id:
        # Queue disabled; run in-process after response.
        background_tasks.add_task(
            _run_deep_scan_background,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            scan_run_id=row.id,
        )

    return _scan_run_out_from_row(row)


@router.get("/{dataset_id}/profile/scan-runs", response_model=DatasetProfileScanRunListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_dataset_profile_scan_runs(
    dataset_id: UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    q = (
        db.query(DBDatasetProfileScanRun)
        .filter(DBDatasetProfileScanRun.tenant_id == tenant_id, DBDatasetProfileScanRun.dataset_id == dataset_id)
    )
    total = int(q.count())
    rows = (
        q.order_by(DBDatasetProfileScanRun.created_at.desc())
        .offset(int(skip or 0))
        .limit(int(limit or 20))
        .all()
    )
    return DatasetProfileScanRunListResponse(total=total, items=[_scan_run_out_from_row(r) for r in rows])


@router.get("/{dataset_id}/profile/scan-runs/{scan_run_id}", response_model=DatasetProfileScanRunOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset_profile_scan_run(
    dataset_id: UUID,
    scan_run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    row = (
        db.query(DBDatasetProfileScanRun)
        .filter(
            DBDatasetProfileScanRun.id == scan_run_id,
            DBDatasetProfileScanRun.tenant_id == tenant_id,
            DBDatasetProfileScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Scan run not found")
    return _scan_run_out_from_row(row)


@router.get("/{dataset_id}/profile/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_profile_summary(
    dataset_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    summary = compute_dataset_profile_summary(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
    )
    # Use JSON mode so UUID/datetime serialize correctly.
    content = json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    safe = _DATASET_SAFE_NAME_RE.sub("_", str(getattr(dataset, "name", "") or "dataset"))[:64]
    filename = f"{safe}.profile.json"
    return Response(
        content=content,
        media_type=_APPLICATION_JSON_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'},
    )


@router.get("/{dataset_id}/profile/export-html", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_profile_html_report(
    dataset_id: UUID,
    redact: Annotated[bool, Query(description='Whether to redact dataset name/id for sharing')] = True,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    summary = compute_dataset_profile_summary(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
    )

    html = render_dataset_profile_html(
        title="MimirQ · 数据画像报告",
        dataset_name=str(getattr(dataset, "name", "") or ""),
        dataset_id=str(dataset_id),
        generated_at=summary.generated_at,
        summary=summary.model_dump(),
        redact=bool(redact),
    )

    safe = _DATASET_SAFE_NAME_RE.sub("_", str(getattr(dataset, "name", "") or "dataset"))[:64]
    filename = f"{safe}.profile.html"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'},
    )


def _iter_gzip_chunks(chunks: Iterator[bytes], *, flush_bytes: int = 64 * 1024) -> Iterator[bytes]:
    """
    Streaming gzip wrapper for byte iterators.

    Keeps memory bounded for large NDJSON exports.
    """
    buffer = io.BytesIO()
    gz = gzip_lib.GzipFile(fileobj=buffer, mode="wb")
    try:
        for chunk in chunks:
            if not chunk:
                continue
            gz.write(chunk)
            if buffer.tell() >= int(flush_bytes or 0):
                gz.flush()
                data = buffer.getvalue()
                if data:
                    yield data
                buffer.seek(0)
                buffer.truncate(0)
        gz.close()
        data = buffer.getvalue()
        if data:
            yield data
    finally:
        try:
            gz.close()
        except Exception:
            pass


def _summarize_document_metadata(meta: Any, *, max_keys_sample: int = 20) -> dict[str, Any] | None:
    """
    Return a small, PII-safe summary of a document metadata dict.

    Intentionally does not include metadata values.
    """
    if not isinstance(meta, dict) or not meta:
        return None
    keys: list[str] = []
    for k in meta.keys():
        if isinstance(k, str) and k.strip():
            keys.append(k.strip())
    keys_sorted = sorted(set(keys))
    max_keys_sample = max(0, int(max_keys_sample or 0))
    return {
        "keys_count": int(len(keys_sorted)),
        "keys_sample": keys_sorted[:max_keys_sample],
    }


def _dt_to_json(v: Any) -> str | None:
    """
    Serialize datetime-like objects for JSON outputs.

    We prefer the "Z" suffix for UTC to avoid "+" being interpreted as a space in
    query strings when callers reuse exported cursors.
    """
    if v is None:
        return None
    if not isinstance(v, datetime):
        return None
    try:
        s = v.isoformat()
    except Exception:
        return None
    # Align with Pydantic's common JSON encoding for UTC.
    if s.endswith("+00:00"):
        s = s[:-6] + "Z"
    return s


def _export_document_row(doc: DBDocument, *, include_sensitive: bool) -> dict[str, Any]:
    meta = doc.doc_metadata if isinstance(getattr(doc, "doc_metadata", None), dict) else {}

    active_hash = get_active_pipeline_hash(meta)
    pipeline_hash = str(meta.get("pipeline_hash") or "").strip() or None
    active_pipeline_hash = str(meta.get("active_pipeline_hash") or "").strip() or None
    doc_pipeline_key = build_doc_pipeline_key(doc.id, active_hash) if active_hash else None
    file_sha256 = str(meta.get("file_sha256") or "").strip().lower() or None

    source_url = str(meta.get("source_url") or "").strip() or None
    source_path = str(meta.get("source_path") or "").strip() or None
    source_last_modified_at = str(meta.get("source_last_modified_at") or "").strip() or None
    source_last_modified_source = str(meta.get("source_last_modified_source") or "").strip() or None
    source_fetched_at = str(meta.get("source_fetched_at") or "").strip() or None
    source_etag = str(meta.get("source_etag") or "").strip() or None
    if source_etag and len(source_etag) > 500:
        source_etag = source_etag[:500]

    out: dict[str, Any] = {
        "schema": "mimirq.dataset_document_export.v1",
        "id": str(doc.id),
        "tenant_id": str(doc.tenant_id),
        "dataset_id": (str(doc.dataset_id) if getattr(doc, "dataset_id", None) is not None else None),
        "status": str(getattr(doc, "status", "") or ""),
        "file_type": str(getattr(doc, "file_type", "") or ""),
        "file_size": int(getattr(doc, "file_size", 0) or 0),
        "chunk_count": int(getattr(doc, "chunk_count", 0) or 0),
        "total_characters": int(getattr(doc, "total_characters", 0) or 0),
        "created_at": _dt_to_json(getattr(doc, "created_at", None)),
        "updated_at": _dt_to_json(getattr(doc, "updated_at", None)),
        "processed_at": _dt_to_json(getattr(doc, "processed_at", None)),
        "archived_at": _dt_to_json(getattr(doc, "archived_at", None)),
        "disabled_at": _dt_to_json(getattr(doc, "disabled_at", None)),
        # Lifecycle / governance workflow signals (PII-safe by default).
        "lifecycle_owner_hash": None,
        "review_due_at": _dt_to_json(getattr(doc, "review_due_at", None)),
        "authority_level": (int(getattr(doc, "authority_level", 0) or 0) if getattr(doc, "authority_level", None) is not None else None),
        "supersedes_document_id": (str(getattr(doc, "supersedes_document_id", "") or "") or None),
        # Stable fingerprints.
        "file_sha256": file_sha256,
        "doc_pipeline_key": doc_pipeline_key,
        "pipeline_hash": pipeline_hash,
        "active_pipeline_hash": active_pipeline_hash,
        # Source / connector staleness signals (no raw content).
        "source_url_hash": (stable_hash(source_url, length=16) if source_url and not include_sensitive else None),
        "source_path_hash": (stable_hash(source_path, length=16) if source_path and not include_sensitive else None),
        "source_last_modified_at": source_last_modified_at,
        "source_last_modified_source": source_last_modified_source,
        "source_fetched_at": source_fetched_at,
        "source_etag": source_etag,
    }

    if include_sensitive:
        out.update(
            {
                "filename": str(getattr(doc, "filename", "") or ""),
                "file_path": str(getattr(doc, "file_path", "") or ""),
                "owner_id": (str(getattr(doc, "owner_id", "") or "") or None),
                "access_mode": (str(getattr(doc, "access_mode", "") or "") or None),
                "lifecycle_owner": (str(getattr(doc, "lifecycle_owner", "") or "") or None),
                "error_message": (str(getattr(doc, "error_message", "") or "") or None),
                "doc_metadata": meta,
            }
        )
    else:
        filename = str(getattr(doc, "filename", "") or "").strip()
        file_path = str(getattr(doc, "file_path", "") or "").strip()
        owner_id = str(getattr(doc, "owner_id", "") or "").strip()
        lifecycle_owner = str(getattr(doc, "lifecycle_owner", "") or "").strip()
        error_message = str(getattr(doc, "error_message", "") or "").strip()
        out.update(
            {
                "filename_hash": (stable_hash(filename, length=16) if filename else None),
                "file_path_hash": (stable_hash(file_path, length=16) if file_path else None),
                "owner_id_hash": (stable_hash(owner_id, length=16) if owner_id else None),
                "lifecycle_owner_hash": (stable_hash(lifecycle_owner, length=16) if lifecycle_owner else None),
                "has_error": bool(error_message),
                "doc_metadata_summary": _summarize_document_metadata(meta),
            }
        )

    return out


@router.get("/{dataset_id}/documents/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_documents_ndjson(
    dataset_id: UUID,
    limit: Annotated[int, Query(ge=1, le=10000)] = 1000,
    after_created_at: Annotated[
        datetime | None, Query(description='Cursor: last seen created_at')
    ] = None,
    after_id: Annotated[UUID | None, Query(description='Cursor: last seen id (tie-breaker)')] = None,
    include_sensitive: Annotated[bool, Query(description='Include sensitive fields (admin-only)')] = False,
    export_format: Annotated[str, Query(description='ndjson|json')] = "ndjson",
    gzip: Annotated[
        bool, Query(description='Return gzip-compressed NDJSON (Content-Encoding: gzip)')
    ] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Export dataset documents as NDJSON (JSON Lines) for compliance / lifecycle workflows.

    Security posture:
    - Requires tenant lifecycle.manage permission (owner/admin).
    - PII-safe by default (include_sensitive=false): raw filenames/paths/metadata values are not exported.
    """
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.LIFECYCLE_MANAGE,
        detail="No permission to export dataset documents",
    )

    ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
    fmt = str(export_format or "ndjson").strip().lower() or "ndjson"
    if fmt not in {"ndjson", "json"}:
        raise HTTPException(status_code=400, detail="export_format must be one of: ndjson, json")

    q = (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
        )
    )
    if after_created_at is not None:
        if after_id is not None:
            q = q.filter(
                or_(
                    DBDocument.created_at > after_created_at,
                    and_(DBDocument.created_at == after_created_at, DBDocument.id > after_id),
                )
            )
        else:
            q = q.filter(DBDocument.created_at > after_created_at)

    rows = q.order_by(DBDocument.created_at.asc(), DBDocument.id.asc()).limit(limit).all()

    # Best-effort audit log (PII-safe).
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="dataset.documents.export",
            resource_type="dataset",
            resource_id=str(dataset_id),
            details={
                "limit": int(limit or 0),
                "returned": int(len(rows)),
                "cursor_after_created_at": (after_created_at.isoformat() if after_created_at else None),
                "cursor_after_id": (str(after_id) if after_id else None),
                "include_sensitive": bool(include_sensitive),
                "export_format": fmt,
                "gzip": bool(gzip),
            },
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    safe = _DATASET_SAFE_NAME_RE.sub("_", str(getattr(ds, "name", "") or "dataset"))[:64]
    headers = {"Cache-Control": "no-store"}

    if fmt == "json":
        items = [_export_document_row(row, include_sensitive=bool(include_sensitive)) for row in rows]
        next_cursor = None
        if rows:
            last = rows[-1]
            next_cursor = {
                "after_created_at": _dt_to_json(last.created_at),
                "after_id": str(last.id),
            }

        payload = {
            "schema": "mimirq.dataset_document_export_page.v1",
            "dataset_id": str(dataset_id),
            "limit": int(limit or 0),
            "returned": int(len(items)),
            "next_cursor": next_cursor,
            "items": items,
        }
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")

        filename = f"{safe}.documents.json"
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        if gzip:
            headers["Content-Encoding"] = "gzip"
            headers["Content-Disposition"] = f'attachment; filename="{filename}.gz"'
            content = gzip_lib.compress(content)

        return Response(
            content=content,
            media_type=_APPLICATION_JSON_MEDIA_TYPE,
            headers=headers,
        )

    def _iter_lines() -> Iterator[bytes]:
        for row in rows:
            payload = _export_document_row(row, include_sensitive=bool(include_sensitive))
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"
            yield line.encode("utf-8")

    body_iter: Iterator[bytes] = _iter_lines()
    filename = f"{safe}.documents.ndjson"

    headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    if gzip:
        headers["Content-Encoding"] = "gzip"
        headers["Content-Disposition"] = f'attachment; filename="{filename}.gz"'
        body_iter = _iter_gzip_chunks(body_iter)

    return StreamingResponse(body_iter, media_type="application/x-ndjson", headers=headers)


@router.get("/{dataset_id}/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_bundle_zip(
    dataset_id: UUID,
    limit: Annotated[
        int, Query(ge=1, le=10000, description='Max documents to include in the bundle')
    ] = 2000,
    include_sensitive: Annotated[
        bool, Query(description='Include sensitive fields in documents metadata')
    ] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Export a dataset "bundle" as a single ZIP archive.

    This is intended for enterprise lifecycle/compliance workflows:
    - Portable snapshot of dataset config
    - Bounded document inventory (NDJSON), PII-safe by default
    """
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.LIFECYCLE_MANAGE,
        detail="No permission to export dataset bundle",
    )

    ds = DatasetService.get_dataset(db, tenant_id, dataset_id)

    docs = (
        db.query(DBDocument)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id)
        .order_by(DBDocument.created_at.asc(), DBDocument.id.asc())
        .limit(int(limit or 0))
        .all()
    )

    exported_at = datetime.now(UTC)

    # Best-effort audit log (PII-safe).
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="dataset.export_bundle",
            resource_type="dataset",
            resource_id=str(dataset_id),
            details={
                "limit": int(limit or 0),
                "returned": int(len(docs)),
                "include_sensitive": bool(include_sensitive),
                "exported_at": exported_at.isoformat(),
            },
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    dataset_payload: dict[str, Any] = {
        "schema": "mimirq.dataset_export.v1",
        "exported_at": _dt_to_json(exported_at),
        "tenant_id": str(tenant_id),
        "dataset": {
            "id": str(getattr(ds, "id", "")),
            "name": str(getattr(ds, "name", "") or ""),
            "description": str(getattr(ds, "description", "") or ""),
            "permission": str(getattr(ds, "permission", "") or ""),
            "owner_id": (str(getattr(ds, "owner_id", "") or "") or None),
            "created_at": _dt_to_json(getattr(ds, "created_at", None)),
            "updated_at": _dt_to_json(getattr(ds, "updated_at", None)),
        },
    }

    config_payload = {
        "schema": "mimirq.dataset_config_export.v1",
        "version": "1",
        "dataset_id": getattr(ds, "id", None),
        "name": str(getattr(ds, "name", "") or ""),
        "exported_at": exported_at,
        "config": _build_dataset_config_bundle(ds),
    }

    # Write bundle ZIP in memory (bounded by `limit`).
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "dataset.json",
            json.dumps(dataset_payload, ensure_ascii=False, separators=(",", ":"), default=str),
        )
        zf.writestr(
            "config.json",
            json.dumps(config_payload, ensure_ascii=False, separators=(",", ":"), default=str),
        )

        doc_lines: list[str] = []
        artifacts_docs: list[dict[str, Any]] = []
        for d in docs:
            row = _export_document_row(d, include_sensitive=bool(include_sensitive))
            doc_lines.append(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str))

            raw_path = str(getattr(d, "file_path", "") or "").strip()
            storage_kind = "unknown"
            if raw_path.startswith("minio://"):
                storage_kind = "minio"
            elif raw_path.startswith("s3://"):
                storage_kind = "s3"
            elif raw_path.startswith("manual://") or not raw_path:
                storage_kind = "manual"
            else:
                storage_kind = "local"

            storage: dict[str, Any] = {
                "kind": storage_kind,
                "uri_hash": (stable_hash(raw_path, length=16) if raw_path else None),
            }
            if include_sensitive and raw_path:
                storage["uri"] = raw_path

            artifacts_docs.append(
                {
                    "document_id": str(getattr(d, "id", "")),
                    "doc_pipeline_key": row.get("doc_pipeline_key"),
                    "pipeline_hash": row.get("pipeline_hash"),
                    "active_pipeline_hash": row.get("active_pipeline_hash"),
                    "file_type": row.get("file_type"),
                    "file_size": row.get("file_size"),
                    "chunk_count": row.get("chunk_count"),
                    "storage": storage,
                }
            )
        zf.writestr("documents.ndjson", ("\n".join(doc_lines) + ("\n" if doc_lines else "")).encode("utf-8"))

        artifacts_payload: dict[str, Any] = {
            "schema": "mimirq.dataset_export_artifacts.v1",
            "exported_at": _dt_to_json(exported_at),
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "vector_backend": str(getattr(settings, "VECTOR_BACKEND", "") or ""),
            "kg_enabled": bool(getattr(settings, "KG_ENABLED", False)),
            "documents": artifacts_docs,
        }

        if bool(getattr(settings, "KG_ENABLED", False)):
            try:
                from app.rag.kg.models import KgSourceEvent  # noqa: WPS433

                doc_ids = [getattr(d, "id", None) for d in docs]
                doc_ids = [did for did in doc_ids if did is not None]
                if doc_ids:
                    events = (
                        db.query(KgSourceEvent)
                        .filter(KgSourceEvent.tenant_id == tenant_id, KgSourceEvent.document_id.in_(doc_ids))
                        .count()
                    )
                else:
                    events = 0
                artifacts_payload["kg_stats"] = {"events": int(events or 0)}
            except Exception:
                artifacts_payload["kg_stats"] = {"events": None, "error": "kg_stats_unavailable"}

        zf.writestr(
            "artifacts.json",
            json.dumps(artifacts_payload, ensure_ascii=False, separators=(",", ":"), default=str),
        )

        zf.writestr(
            "README.txt",
            (
                "MimirQ Dataset Export Bundle\n\n"
                "- dataset.json: dataset summary (safe)\n"
                "- config.json: portable dataset config bundle\n"
                "- documents.ndjson: document inventory (PII-safe by default)\n"
                "- artifacts.json: compliance-oriented artifact manifest (indexes/storage refs; redacted by default)\n"
                "\n"
                "Security:\n"
                "- include_sensitive=false (default) omits raw filenames/paths and doc_metadata values.\n"
            ),
        )

    raw = buf.getvalue()
    safe = _DATASET_SAFE_NAME_RE.sub("_", str(getattr(ds, "name", "") or "dataset"))[:64]
    filename = f"{safe}.export.zip"
    return Response(
        content=raw,
        media_type="application/zip",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
