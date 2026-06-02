"""
RAGAS evaluation API.

Provides evaluation endpoints for the RAG system, including task creation,
querying, and results.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.evaluation import (
    GeneratedQuestion,
    RagasItemSchema,
    RagasRunCreateRequest,
    RagasRunDetail,
    RagasRunList,
    RagasRunSchema,
    TestGenFromConversationsRequest,
    TestGenFromDocsRequest,
    TestGenResponse,
)
from app.api.schemas.kg_diagnostics import (
    KGSearchDiagnosticsRequest,
    KGSearchDiagnosticsResponse,
    KGSearchDiagnosticsRunDetail,
    KGSearchDiagnosticsRunList,
)
from app.api.schemas.regression import (
    RagasRegressionAblationBatchRequest,
    RagasRegressionAblationBatchResponse,
    RagasRegressionCaseCreateRequest,
    RagasRegressionCaseImportRequest,
    RagasRegressionCaseList,
    RagasRegressionCaseOut,
    RagasRegressionCasePatchRequest,
    RagasRegressionItemSchema,
    RagasRegressionRunCreateRequest,
    RagasRegressionRunDetail,
    RagasRegressionRunDiffResponse,
    RagasRegressionRunLeaderboardResponse,
    RagasRegressionRunList,
    RagasRegressionRunSchema,
    SyntheticHardcaseGenerateRequest,
    SyntheticHardcaseGenerateResponse,
)
from app.api.utils.response_headers import download_response_headers, set_download_content_disposition
from app.core.config import settings
from app.core.constants import NON_CRITICAL_EXCEPTION_LOG_MESSAGE
from app.core.database import get_db
from app.models.chat import Conversation
from app.models.evaluation import (
    KGSearchDiagnosticsRun,
    RagasEvaluationItem,
    RagasEvaluationRun,
    RagasRegressionCase,
    RagasRegressionItem,
    RagasRegressionRun,
)
from app.rag.core.logging import get_logger
from app.rag.evaluation.ragas import run_conversation_ragas_evaluation, run_regression_ragas_evaluation
from app.rag.evaluation.test_generator import (
    generate_questions_from_conversations,
    generate_questions_from_documents,
)
from app.services.audit_log_service import audit_log_event
from app.services.dataset_service import DatasetService
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission
from app.services.regression_case_bundle import export_case_bundle, plan_case_import
from app.services.regression_leaderboard import build_regression_run_leaderboard
from app.services.regression_run_ablation_batch import expand_ablation_grid
from app.services.regression_run_bundle import export_regression_run_bundle
from app.services.regression_run_diff import diff_regression_run_summaries
from app.services.regression_run_diff_html import render_regression_run_diff_html
from app.services.regression_run_retention import plan_regression_run_purge, purge_regression_run_rows
from app.services.regression_run_scope import (
    DatasetMismatchError,
    MissingCasesError,
    validate_case_ids_belong_to_dataset,
)
from app.services.regression_run_significance import compare_regression_items

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

_DETAIL_RUN_NOT_FOUND = "Run not found"
_DETAIL_KG_DISABLED = "KG is disabled (KG_ENABLED=false)"

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger("api.evaluations")
_EVALUATIONS_ROUTER_FALLBACK_LOG_MESSAGE = "Ignoring non-critical evaluations router fallback failure: %s"

_REGRESSION_RUN_CONTROL_FIELDS = {
    "case_ids",
    "dataset_id",
    "metrics",
    "use_llm_judge",
    "skip_empty_contexts",
    "max_cases",
}


def _regression_rag_params_from_request(request: RagasRegressionRunCreateRequest) -> dict[str, Any]:
    return {
        key: getattr(request, key)
        for key in RagasRegressionRunCreateRequest.model_fields
        if key not in _REGRESSION_RUN_CONTROL_FIELDS
    }


def _jsonable_regression_rag_params(rag_params: dict[str, Any]) -> dict[str, Any]:
    out = dict(rag_params)
    prompt_template_id = out.get("prompt_template_id")
    if prompt_template_id is not None:
        out["prompt_template_id"] = str(prompt_template_id)
    return out


def _regression_run_params_from_request(request: RagasRegressionRunCreateRequest) -> dict[str, Any]:
    return {
        "case_ids": [str(x) for x in (request.case_ids or [])],
        "dataset_id": str(request.dataset_id),
        "skip_empty_contexts": request.skip_empty_contexts,
        "max_cases": request.max_cases,
        "use_llm_judge": bool(getattr(request, "use_llm_judge", False)),
        "rag_params": _jsonable_regression_rag_params(_regression_rag_params_from_request(request)),
    }


def _create_regression_run_and_enqueue(
    *,
    request: RagasRegressionRunCreateRequest,
    background_tasks: BackgroundTasks,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> RagasRegressionRun:
    rag_params = _regression_rag_params_from_request(request)
    run = RagasRegressionRun(
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=request.dataset_id,
        status="pending",
        metrics=request.metrics,
        params=_regression_run_params_from_request(request),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    background_tasks.add_task(
        run_regression_ragas_evaluation,
        run_id=run.id,
        tenant_id=tenant_id,
        account_id=account_id,
        case_ids=list(request.case_ids or []),
        dataset_id=request.dataset_id,
        metric_names=request.metrics,
        use_llm_judge=bool(getattr(request, "use_llm_judge", False)),
        skip_empty_contexts=request.skip_empty_contexts,
        max_cases=request.max_cases,
        rag_params=rag_params,
    )
    return run


def _finalize_scope_document_ids(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    document_ids: list[UUID],
) -> list[str]:
    """Validate and normalize case-scoped document_ids (must be readable and within dataset)."""
    if not document_ids:
        return []

    from app.models.document import Document as DBDocument
    from app.services.document_access import filter_allowed_document_ids

    allowed = set(filter_allowed_document_ids(db, tenant_id, account_id, document_ids))
    want = {UUID(str(x)) for x in document_ids if x is not None}
    if want - allowed:
        raise HTTPException(status_code=403, detail="Some scope documents are not accessible")

    rows = (
        db.query(DBDocument.id, DBDocument.dataset_id)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(sorted(allowed)))
        .all()
    )
    bad = [str(doc_id) for doc_id, ds_id in rows if ds_id is None or UUID(str(ds_id)) != dataset_id]
    if bad:
        raise HTTPException(status_code=400, detail="Some scope documents do not belong to dataset_id")

    return [str(x) for x in sorted(allowed)]


def _enrich_reference_source_payload(
    src: dict,
    *,
    chunk_index: int | None,
    chunk_meta: dict | None,
    chunk_content: str | None,
) -> dict:
    """
    Best-effort enrichment for reference_sources payloads.

    Motivation:
    - Regression suites should survive re-ingestion/re-chunking as much as possible.
    - We store `reference_sources` as JSON, so we can enrich without migrations.

    Rules:
    - Never override explicitly provided fields.
    - Fill missing `quote` from chunk content (bounded).
    - Fill missing versioning fields (`doc_pipeline_key`, `pipeline_hash`) from chunk metadata.
    - Fill missing `chunk_index` from DB column.
    """
    payload = dict(src or {})

    if chunk_index is not None and payload.get("chunk_index") is None:
        try:
            payload["chunk_index"] = int(chunk_index)
        except Exception as exc:
            logger.debug(_EVALUATIONS_ROUTER_FALLBACK_LOG_MESSAGE, exc)

    meta = chunk_meta if isinstance(chunk_meta, dict) else {}
    if not str(payload.get("doc_pipeline_key") or "").strip():
        v = meta.get("doc_pipeline_key")
        if isinstance(v, str) and v.strip():
            payload["doc_pipeline_key"] = v.strip()
    if not str(payload.get("pipeline_hash") or "").strip():
        v = meta.get("pipeline_hash")
        if isinstance(v, str) and v.strip():
            payload["pipeline_hash"] = v.strip()

    if not str(payload.get("quote") or "").strip():
        text = (chunk_content or "").strip() if isinstance(chunk_content, str) else ""
        if text:
            payload["quote"] = text[:2000] + ("..." if len(text) > 2000 else "")

    return payload


def _finalize_reference_sources(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    reference_sources: list[dict] | list[Any],
) -> list[dict]:
    """
    Validate and normalize reference_sources payload for DB storage.

    Security:
    - Enforces tenant isolation and document ACL checks.
    Consistency:
    - Ensures (chunk_id -> document_id -> dataset_id) matches.
    UX:
    - Best-effort fill `quote` from chunk content when missing.
    """
    # Import lazily to keep module import side-effects minimal.
    from app.models.document import Document as DBDocument
    from app.models.document import DocumentChunk
    from app.services.document_access import filter_allowed_document_ids

    # Coerce to dict payloads (Pydantic models provide model_dump).
    coerced: list[dict] = []
    for src in reference_sources or []:
        if src is None:
            continue
        if hasattr(src, "model_dump"):
            coerced.append(src.model_dump(mode="json"))
        elif isinstance(src, dict):
            coerced.append(dict(src))

    doc_ids: list[UUID] = []
    chunk_ids: list[UUID] = []
    for src in coerced:
        try:
            doc_ids.append(UUID(str(src.get("document_id"))))
        except Exception:
            logging.getLogger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            continue
        try:
            chunk_ids.append(UUID(str(src.get("chunk_id"))))
        except Exception:
            logging.getLogger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            continue

    # ACL: all evidence documents must be readable.
    allowed_docs = set(filter_allowed_document_ids(db, tenant_id, account_id, doc_ids))
    if set(doc_ids) - allowed_docs:
        raise HTTPException(status_code=403, detail="Evidence documents not accessible")

    # Validate chunk ownership + dataset match; pull content for quote fallback.
    rows = (
        db.query(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DBDocument.dataset_id,
            DocumentChunk.content,
            DocumentChunk.disabled_at,
            DocumentChunk.chunk_index,
            DocumentChunk.doc_metadata,
        )
        .join(DBDocument, DBDocument.id == DocumentChunk.document_id)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.id.in_(chunk_ids),
            DBDocument.tenant_id == tenant_id,
        )
        .all()
    )
    row_by_chunk_id = {r[0]: r for r in rows if r and r[0]}
    if len(row_by_chunk_id) < len(set(chunk_ids)):
        raise HTTPException(status_code=400, detail="Some evidence chunks were not found")

    out: list[dict] = []
    for src in coerced:
        chunk_id_raw = src.get("chunk_id")
        doc_id_raw = src.get("document_id")
        if not chunk_id_raw or not doc_id_raw:
            continue
        try:
            chunk_id = UUID(str(chunk_id_raw))
            doc_id = UUID(str(doc_id_raw))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid evidence chunk_id/document_id") from None

        row = row_by_chunk_id.get(chunk_id)
        if not row:
            raise HTTPException(status_code=400, detail="Evidence chunk not found")
        _chunk_id, chunk_doc_id, chunk_dataset_id, content, disabled_at, chunk_index, chunk_meta = row
        if disabled_at is not None:
            raise HTTPException(status_code=400, detail="Evidence chunk is disabled")
        if UUID(str(chunk_doc_id)) != doc_id:
            raise HTTPException(status_code=400, detail="Evidence chunk does not belong to document_id")
        if chunk_dataset_id is None or UUID(str(chunk_dataset_id)) != dataset_id:
            raise HTTPException(status_code=400, detail="Evidence chunk does not belong to dataset_id")

        payload = _enrich_reference_source_payload(
            dict(src),
            chunk_index=chunk_index if isinstance(chunk_index, int) else None,
            chunk_meta=(chunk_meta if isinstance(chunk_meta, dict) else None),
            chunk_content=(content if isinstance(content, str) else None),
        )
        out.append(payload)

    if not out:
        raise HTTPException(status_code=400, detail="reference_sources is empty or invalid")

    return out


def _normalize_reasoning_hops(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        out.append(text[:300])
        if len(out) >= 20:
            break
    return out


def _normalize_evidence_chain(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if item is None:
            continue
        if hasattr(item, "model_dump"):
            item = item.model_dump(mode="json")
        if not isinstance(item, dict):
            continue
        doc_id = str(item.get("document_id") or "").strip()
        chunk_id = str(item.get("chunk_id") or "").strip()
        if not doc_id or not chunk_id:
            continue
        payload: dict[str, Any] = {"document_id": doc_id, "chunk_id": chunk_id}
        if item.get("chunk_index") is not None:
            try:
                payload["chunk_index"] = int(item.get("chunk_index"))
            except Exception as exc:
                logger.debug(_EVALUATIONS_ROUTER_FALLBACK_LOG_MESSAGE, exc)
        if item.get("label") is not None:
            payload["label"] = str(item.get("label"))[:100]
        out.append(payload)
        if len(out) >= 20:
            break
    return out


def _merge_regression_case_extra(
    *,
    base_extra: Any,
    reasoning_hops: Any,
    evidence_chain: Any,
) -> dict[str, Any]:
    extra = dict(base_extra) if isinstance(base_extra, dict) else {}
    hops = _normalize_reasoning_hops(reasoning_hops)
    chain = _normalize_evidence_chain(evidence_chain)
    if hops:
        extra["reasoning_hops"] = hops
    else:
        extra.pop("reasoning_hops", None)
    if chain:
        extra["evidence_chain"] = chain
    else:
        extra.pop("evidence_chain", None)
    return extra


def _attach_reasoning_fields(case_row: Any) -> Any:
    extra = getattr(case_row, "extra", None)
    extra = extra if isinstance(extra, dict) else {}
    case_row.reasoning_hops = _normalize_reasoning_hops(extra.get("reasoning_hops"))
    case_row.evidence_chain = _normalize_evidence_chain(extra.get("evidence_chain"))
    return case_row


@router.post("/ragas/runs", response_model=RagasRunSchema, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def create_ragas_run(
    request: RagasRunCreateRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a RAGAS evaluation run and execute it in background."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == request.conversation_id, Conversation.tenant_id == tenant_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    run = RagasEvaluationRun(
        tenant_id=tenant_id,
        account_id=account_id,
        conversation_id=request.conversation_id,
        status="pending",
        metrics=request.metrics,
        params={
            "requested_metrics": request.metrics,
            "max_turns": request.max_turns,
            "skip_empty_contexts": request.skip_empty_contexts,
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    background_tasks.add_task(
        run_conversation_ragas_evaluation,
        run_id=run.id,
        tenant_id=tenant_id,
        account_id=account_id,
        conversation_id=request.conversation_id,
        metric_names=request.metrics,
        max_turns=request.max_turns,
        skip_empty_contexts=request.skip_empty_contexts,
    )

    return run


@router.get("/ragas/runs", response_model=RagasRunList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def list_ragas_runs(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    conversation_id: UUID | None = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """List RAGAS evaluation runs for current tenant."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(RagasEvaluationRun).filter(RagasEvaluationRun.tenant_id == tenant_id)
    if conversation_id:
        query = query.filter(RagasEvaluationRun.conversation_id == conversation_id)

    total = query.count()
    runs = (
        query.order_by(RagasEvaluationRun.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {"total": total, "items": runs}


@router.get("/ragas/runs/{run_id}", response_model=RagasRunDetail, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_ragas_run(
    run_id: UUID,
    include_items: bool = True,
    include_contexts: bool = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get a single run and (optionally) its items."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    run = (
        db.query(RagasEvaluationRun)
        .filter(RagasEvaluationRun.id == run_id, RagasEvaluationRun.tenant_id == tenant_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail=_DETAIL_RUN_NOT_FOUND)

    items_out = []
    if include_items:
        items = (
            db.query(RagasEvaluationItem)
            .filter(RagasEvaluationItem.run_id == run_id, RagasEvaluationItem.tenant_id == tenant_id)
            .order_by(RagasEvaluationItem.turn_index.asc())
            .all()
        )
        for item in items:
            payload = RagasItemSchema.model_validate(item).model_dump()
            if not include_contexts:
                payload["retrieved_contexts"] = None
            items_out.append(payload)

    return {"run": run, "items": items_out}


@router.post("/ragas/regression/cases", response_model=RagasRegressionCaseOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def create_ragas_regression_case(
    request: RagasRegressionCaseCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a regression case (per-dataset; requires evidence sources)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    ds = DatasetService.get_dataset(db, tenant_id, request.dataset_id)
    # Governance: regression cases back CI gates ("golden questions") and are a write operation.
    DatasetService.assert_dataset_writable(db, ds, account_id)

    reference_sources = _finalize_reference_sources(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=request.dataset_id,
        reference_sources=request.reference_sources,
    )
    merged_extra = _merge_regression_case_extra(
        base_extra=request.extra,
        reasoning_hops=request.reasoning_hops,
        evidence_chain=request.evidence_chain,
    )

    row = RagasRegressionCase(
        tenant_id=tenant_id,
        dataset_id=request.dataset_id,
        document_ids=_finalize_scope_document_ids(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=request.dataset_id,
            document_ids=list(request.document_ids or []),
        ),
        question=request.question,
        expected_answer=request.expected_answer,
        reference_sources=reference_sources,
        tags=request.tags,
        extra=merged_extra,
        created_by=account_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _attach_reasoning_fields(row)


@router.patch("/ragas/regression/cases/{case_id}", response_model=RagasRegressionCaseOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def patch_ragas_regression_case(
    case_id: UUID,
    request: RagasRegressionCasePatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Patch a regression case (dataset_id is immutable)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = (
        db.query(RagasRegressionCase)
        .filter(RagasRegressionCase.id == case_id, RagasRegressionCase.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")

    ds_id = getattr(row, "dataset_id", None)
    if ds_id is not None:
        ds = DatasetService.get_dataset(db, tenant_id, ds_id)
        # Governance: patching cases can alter golden suites and should be gated as a write action.
        DatasetService.assert_dataset_writable(db, ds, account_id)

    fields = set(getattr(request, "model_fields_set", set()) or set())
    if "question" in fields and request.question is not None:
        row.question = request.question
    if "expected_answer" in fields:
        row.expected_answer = request.expected_answer
    if "tags" in fields and request.tags is not None:
        row.tags = request.tags
    if (
        "extra" in fields
        or "reasoning_hops" in fields
        or "evidence_chain" in fields
    ):
        base_extra = request.extra if ("extra" in fields and request.extra is not None) else row.extra
        row.extra = _merge_regression_case_extra(
            base_extra=base_extra,
            reasoning_hops=(request.reasoning_hops if "reasoning_hops" in fields else None),
            evidence_chain=(request.evidence_chain if "evidence_chain" in fields else None),
        )
    if "document_ids" in fields and request.document_ids is not None:
        if ds_id is None:
            raise HTTPException(status_code=400, detail="Cannot patch document_ids without dataset_id")
        row.document_ids = _finalize_scope_document_ids(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=UUID(str(ds_id)),
            document_ids=list(request.document_ids or []),
        )
    if "reference_sources" in fields and request.reference_sources is not None:
        if ds_id is None:
            raise HTTPException(status_code=400, detail="Cannot patch reference_sources without dataset_id")
        row.reference_sources = _finalize_reference_sources(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=UUID(str(ds_id)),
            reference_sources=request.reference_sources,
        )

    db.add(row)
    db.commit()
    db.refresh(row)
    return _attach_reasoning_fields(row)


@router.get("/ragas/regression/cases", response_model=RagasRegressionCaseList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def list_ragas_regression_cases(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    dataset_id: UUID | None = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """List regression cases (tenant isolated, filterable by dataset_id)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(RagasRegressionCase).filter(RagasRegressionCase.tenant_id == tenant_id)
    if dataset_id:
        query = query.filter(RagasRegressionCase.dataset_id == dataset_id)

    total = query.count()
    items = (
        query.order_by(RagasRegressionCase.updated_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    items = [_attach_reasoning_fields(x) for x in items]
    return {"total": total, "items": items}


@router.get("/ragas/regression/cases/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def export_ragas_regression_cases(
    dataset_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Export regression cases as a dataset-scoped bundle (no internal ids)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    items = (
        db.query(RagasRegressionCase)
        .filter(
            RagasRegressionCase.tenant_id == tenant_id,
            RagasRegressionCase.dataset_id == dataset_id,
        )
        .order_by(RagasRegressionCase.updated_at.desc())
        .all()
    )

    return export_case_bundle(items, dataset_id)


@router.post("/ragas/regression/cases/import", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def import_ragas_regression_cases(
    payload: RagasRegressionCaseImportRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Import (upsert) regression cases by (dataset_id + question.strip())."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    ds = DatasetService.get_dataset(db, tenant_id, payload.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    existing = (
        db.query(RagasRegressionCase)
        .filter(
            RagasRegressionCase.tenant_id == tenant_id,
            RagasRegressionCase.dataset_id == payload.dataset_id,
        )
        .all()
    )
    by_question = {str(getattr(r, "question", "") or "").strip(): r for r in existing if getattr(r, "question", None)}

    plan = plan_case_import(
        dataset_id=payload.dataset_id,
        existing_questions=set(by_question.keys()),
        items=list(payload.items or []),
        overwrite=bool(payload.overwrite),
        max_items=int(payload.max_items or 0),
    )

    created = 0
    updated = 0
    skipped = int(plan.get("skipped") or 0)
    errors: list[dict[str, Any]] = list(plan.get("errors") or [])

    for item in plan.get("create_items") or []:
        try:
            reference_sources = _finalize_reference_sources(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=payload.dataset_id,
                reference_sources=item.get("reference_sources") or [],
            )
            row = RagasRegressionCase(
                tenant_id=tenant_id,
                dataset_id=payload.dataset_id,
                question=str(item.get("question") or "").strip(),
                expected_answer=item.get("expected_answer"),
                reference_sources=reference_sources,
                tags=list(item.get("tags") or []),
                extra=_merge_regression_case_extra(
                    base_extra=None,
                    reasoning_hops=item.get("reasoning_hops"),
                    evidence_chain=item.get("evidence_chain"),
                ),
                created_by=account_id,
            )
            db.add(row)
            created += 1
        except HTTPException as exc:
            skipped += 1
            errors.append({"question": item.get("question"), "error": exc.detail})
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            errors.append({"question": item.get("question"), "error": str(exc)[:200]})

    for item in plan.get("update_items") or []:
        question = str(item.get("question") or "").strip()
        row = by_question.get(question)
        if row is None:
            skipped += 1
            errors.append({"question": question, "error": "Case not found for update"})
            continue
        try:
            reference_sources = _finalize_reference_sources(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=payload.dataset_id,
                reference_sources=item.get("reference_sources") or [],
            )
            row.expected_answer = item.get("expected_answer")
            row.tags = list(item.get("tags") or [])
            row.reference_sources = reference_sources
            row.extra = _merge_regression_case_extra(
                base_extra=row.extra,
                reasoning_hops=item.get("reasoning_hops"),
                evidence_chain=item.get("evidence_chain"),
            )
            db.add(row)
            updated += 1
        except HTTPException as exc:
            skipped += 1
            errors.append({"question": question, "error": exc.detail})
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            errors.append({"question": question, "error": str(exc)[:200]})

    db.commit()

    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}


@router.post("/ragas/regression/cases/synthetic-hardcases", response_model=SyntheticHardcaseGenerateResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def generate_synthetic_hardcases(
    payload: SyntheticHardcaseGenerateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Generate synthetic "hardcase" regression cases (PII-safe, deterministic).

    This is a quality-program helper:
    - Takes existing regression cases as seeds
    - Generates harder query variants (alias/skill pressure) using KG-derived candidates
    - Reuses the same reference_sources so evaluation remains grounded
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    if not bool(getattr(settings, "KG_ENABLED", False)):
        raise HTTPException(status_code=503, detail=_DETAIL_KG_DISABLED)

    ds = DatasetService.get_dataset(db, tenant_id, payload.dataset_id)
    if bool(payload.dry_run):
        DatasetService.assert_dataset_readable(db, ds, account_id)
    else:
        # Creating many cases is a write action (governance).
        DatasetService.assert_dataset_writable(db, ds, account_id)

    # Validate explicit case_ids when provided.
    if payload.case_ids:
        rows = (
            db.query(RagasRegressionCase.id, RagasRegressionCase.dataset_id)
            .filter(
                RagasRegressionCase.tenant_id == tenant_id,
                RagasRegressionCase.id.in_(list(payload.case_ids or [])),
            )
            .all()
        )
        try:
            validate_case_ids_belong_to_dataset(
                dataset_id=payload.dataset_id,
                case_ids=list(payload.case_ids or []),
                rows=rows,
            )
        except MissingCasesError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DatasetMismatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    max_cases = max(1, min(int(payload.max_cases or 0), 200))
    per_case = max(0, min(int(payload.hardcases_per_case or 0), 20))
    max_created = max(0, min(int(payload.max_created or 0), 5000))
    tag = str(payload.tag or "").strip() or "synthetic_hardcase"

    # Load base cases (dataset-scoped).
    base_q = db.query(RagasRegressionCase).filter(
        RagasRegressionCase.tenant_id == tenant_id,
        RagasRegressionCase.dataset_id == payload.dataset_id,
    )
    if payload.case_ids:
        base_q = base_q.filter(RagasRegressionCase.id.in_(list(payload.case_ids or [])))
    base_total = int(base_q.count())
    base_cases = (
        base_q.order_by(RagasRegressionCase.updated_at.desc(), RagasRegressionCase.id.asc())
        .limit(max_cases)
        .all()
    )

    # Dedupe against existing suite questions (casefold + collapsed whitespace).
    def _qkey(text: str) -> str:
        s = " ".join(str(text or "").strip().split())
        return s.casefold()

    existing_q_rows = (
        db.query(RagasRegressionCase.question)
        .filter(RagasRegressionCase.tenant_id == tenant_id, RagasRegressionCase.dataset_id == payload.dataset_id)
        .all()
    )
    existing_keys = {_qkey(str(q or "")) for (q,) in existing_q_rows if q}

    # Lazy imports: keep eval module import-light in non-KG environments.
    from app.rag.evaluation.kg_hardcase_deterministic import generate_hardcases_deterministic
    from app.rag.evaluation.kg_search_diagnostics import (
        _deterministic_hardcase_candidates,
        _resolve_ground_truth_event_ids,
    )

    created_ids: list[UUID] = []
    skipped_dup = 0
    errors: list[dict[str, Any]] = []
    hardcases_generated = 0
    base_used = 0

    for case in base_cases:
        if per_case <= 0:
            break
        if max_created > 0 and len(created_ids) >= max_created:
            break

        question = str(getattr(case, "question", "") or "").strip()
        if not question:
            continue

        ref_sources = getattr(case, "reference_sources", None) or []
        evidence_chunk_ids: list[str] = []
        for src in ref_sources if isinstance(ref_sources, list) else []:
            if not isinstance(src, dict):
                continue
            raw = src.get("chunk_id")
            if raw is None:
                continue
            s = str(raw).strip()
            if s:
                evidence_chunk_ids.append(s)

        gt_event_ids = _resolve_ground_truth_event_ids(db, tenant_id=tenant_id, evidence_chunk_ids=evidence_chunk_ids)
        alias_pairs, skills, tags0 = _deterministic_hardcase_candidates(db, tenant_id=tenant_id, ground_truth_event_ids=gt_event_ids)

        hardcases = generate_hardcases_deterministic(
            question=question,
            alias_pairs=alias_pairs,
            skills=skills,
            tags=tags0,
            max_items=per_case,
        )
        if not hardcases:
            continue

        base_used += 1
        for hc in hardcases:
            q2 = str(getattr(hc, "question", "") or "").strip()
            if not q2:
                continue
            hardcases_generated += 1

            key = _qkey(q2)
            if key in existing_keys:
                skipped_dup += 1
                continue

            if bool(payload.dry_run):
                existing_keys.add(key)
                continue

            # Create a new case reusing the same evidence pointers.
            base_tags = list(getattr(case, "tags", None) or [])
            tags_new = [*base_tags, tag, f"hardcase:{getattr(hc, 'kind', 'unknown')}"]
            # Keep tags small and stable.
            tags_clean: list[str] = []
            seen: set[str] = set()
            for t in tags_new:
                s = str(t or "").strip()
                if not s:
                    continue
                if s in seen:
                    continue
                seen.add(s)
                tags_clean.append(s[:80])

            extra_base = getattr(case, "extra", None)
            extra_d = dict(extra_base or {}) if isinstance(extra_base, dict) else {}
            extra_d.setdefault("synthetic_from_case_id", str(getattr(case, "id", "") or ""))
            extra_d["hardcase_kind"] = str(getattr(hc, "kind", "") or "")
            rationale = getattr(hc, "rationale", None)
            if rationale:
                extra_d["hardcase_rationale"] = str(rationale)[:400]

            row = RagasRegressionCase(
                tenant_id=tenant_id,
                dataset_id=payload.dataset_id,
                document_ids=list(getattr(case, "document_ids", None) or []),
                question=q2,
                expected_answer=getattr(case, "expected_answer", None),
                reference_sources=list(ref_sources) if isinstance(ref_sources, list) else [],
                tags=tags_clean,
                extra=extra_d,
                created_by=account_id,
            )
            db.add(row)
            db.flush()
            created_ids.append(row.id)
            existing_keys.add(key)

            if max_created > 0 and len(created_ids) >= max_created:
                break

    if not bool(payload.dry_run):
        try:
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            errors.append({"error": str(exc)[:200]})

    return SyntheticHardcaseGenerateResponse(
        dataset_id=payload.dataset_id,
        base_cases_total=int(base_total),
        base_cases_evaluated=int(base_used),
        hardcases_generated=int(hardcases_generated),
        created=int(0 if payload.dry_run else len(created_ids)),
        skipped_duplicates=int(skipped_dup),
        created_case_ids=created_ids,
        errors=errors,
    )


@router.delete("/ragas/regression/cases/{case_id}", status_code=204, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def delete_ragas_regression_case(
    case_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Delete a regression case."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = (
        db.query(RagasRegressionCase)
        .filter(RagasRegressionCase.id == case_id, RagasRegressionCase.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")

    ds_id = getattr(row, "dataset_id", None)
    if ds_id is None:
        raise HTTPException(status_code=400, detail="Cannot delete case without dataset_id")
    ds = DatasetService.get_dataset(db, tenant_id, UUID(str(ds_id)))
    # Governance: deletion is a write action; protect golden suites.
    DatasetService.assert_dataset_writable(db, ds, account_id)

    db.delete(row)
    db.commit()
    return None


@router.post("/ragas/regression/runs", response_model=RagasRegressionRunSchema, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def create_ragas_regression_run(
    request: RagasRegressionRunCreateRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a regression evaluation run and execute it in background."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    ds = DatasetService.get_dataset(db, tenant_id, request.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    if request.case_ids:
        rows = (
            db.query(RagasRegressionCase.id, RagasRegressionCase.dataset_id)
            .filter(
                RagasRegressionCase.tenant_id == tenant_id,
                RagasRegressionCase.id.in_(list(request.case_ids or [])),
            )
            .all()
        )
        try:
            validate_case_ids_belong_to_dataset(dataset_id=request.dataset_id, case_ids=list(request.case_ids), rows=rows)
        except MissingCasesError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DatasetMismatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    run = _create_regression_run_and_enqueue(
        request=request,
        background_tasks=background_tasks,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )

    return run


@router.post(
    "/ragas/regression/ablation/batch",
    response_model=RagasRegressionAblationBatchResponse,
    status_code=201,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def create_ragas_regression_ablation_batch(
    request: RagasRegressionAblationBatchRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a bounded cartesian batch of regression runs for ablation analysis."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    ds = DatasetService.get_dataset(db, tenant_id, request.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    if request.case_ids:
        rows = (
            db.query(RagasRegressionCase.id, RagasRegressionCase.dataset_id)
            .filter(
                RagasRegressionCase.tenant_id == tenant_id,
                RagasRegressionCase.id.in_(list(request.case_ids or [])),
            )
            .all()
        )
        try:
            validate_case_ids_belong_to_dataset(dataset_id=request.dataset_id, case_ids=list(request.case_ids), rows=rows)
        except MissingCasesError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DatasetMismatchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    allowed_grid_keys = set(RagasRegressionRunCreateRequest.model_fields) - _REGRESSION_RUN_CONTROL_FIELDS
    try:
        variants = expand_ablation_grid(
            request.grid,
            max_combinations=request.max_combinations,
            allowed_keys=allowed_grid_keys,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    ablation_id = uuid4()
    run_ids: list[UUID] = []
    base_payload = request.model_dump(exclude={"grid", "max_combinations", "ablation_label_prefix"})
    for index, variant in enumerate(variants):
        try:
            variant_request = RagasRegressionRunCreateRequest.model_validate({**base_payload, **variant})
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid ablation variant {index + 1}: {exc}") from exc

        run = _create_regression_run_and_enqueue(
            request=variant_request,
            background_tasks=background_tasks,
            tenant_id=tenant_id,
            account_id=account_id,
            db=db,
        )
        params = dict(getattr(run, "params", None) or {})
        params["ablation_id"] = str(ablation_id)
        params["ablation_variant_index"] = int(index)
        params["ablation_variant"] = dict(variant)
        if request.ablation_label_prefix:
            params["ablation_label"] = f"{request.ablation_label_prefix}-{index + 1}"
        run.params = params
        db.add(run)
        db.commit()
        db.refresh(run)
        run_ids.append(run.id)

    return {
        "ablation_id": ablation_id,
        "total": len(run_ids),
        "run_ids": run_ids,
        "variants": variants,
        "status": "queued",
    }


@router.get("/ragas/regression/runs", response_model=RagasRegressionRunList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def list_ragas_regression_runs(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    dataset_id: Annotated[UUID | None, Query(description="Optional dataset scope")] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """List regression runs."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(RagasRegressionRun).filter(RagasRegressionRun.tenant_id == tenant_id)
    if dataset_id is not None:
        DatasetService.get_dataset(db, tenant_id, dataset_id)
        query = query.filter(RagasRegressionRun.dataset_id == dataset_id)
    total = query.count()
    runs = (
        query.order_by(RagasRegressionRun.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {"total": total, "items": runs}


@router.get("/ragas/regression/runs/leaderboard", response_model=RagasRegressionRunLeaderboardResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_ragas_regression_run_leaderboard(
    dataset_id: Annotated[UUID, Query(..., description="Dataset to scope runs (required)")],
    metric_key: Annotated[str, Query(description='Metric key from run.summary')] = "retrieval_mrr",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    include_incomplete: Annotated[
        bool, Query(description='Include pending/failed runs (default: false)')
    ] = False,
    max_candidates: Annotated[
        int, Query(ge=1, le=5000, description='Max runs to consider (recency window)')
    ] = 500,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Rank regression runs by a retrieval-only metric and attach retrieval_config_hash (PII-safe)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    query = (
        db.query(RagasRegressionRun)
        .filter(
            RagasRegressionRun.tenant_id == tenant_id,
            RagasRegressionRun.dataset_id == dataset_id,
        )
        .order_by(RagasRegressionRun.created_at.desc())
    )
    if not include_incomplete:
        query = query.filter(RagasRegressionRun.status == "completed")

    runs = query.limit(max_candidates).all()
    items = build_regression_run_leaderboard(runs=runs, metric_key=metric_key, limit=limit)
    return {"metric_key": metric_key, "items": items}


@router.get("/ragas/regression/runs/{run_id}", response_model=RagasRegressionRunDetail, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_ragas_regression_run(
    run_id: UUID,
    include_items: bool = True,
    include_contexts: bool = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get a regression run detail (optional items and contexts)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    run = (
        db.query(RagasRegressionRun)
        .filter(RagasRegressionRun.id == run_id, RagasRegressionRun.tenant_id == tenant_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail=_DETAIL_RUN_NOT_FOUND)

    items_out = []
    if include_items:
        items = (
            db.query(RagasRegressionItem)
            .filter(RagasRegressionItem.run_id == run_id, RagasRegressionItem.tenant_id == tenant_id)
            .order_by(RagasRegressionItem.created_at.asc())
            .all()
        )
        for item in items:
            payload = RagasRegressionItemSchema.model_validate(item).model_dump()
            if not include_contexts:
                payload["retrieved_contexts"] = None
            items_out.append(payload)

    return {"run": run, "items": items_out}


@router.get("/ragas/regression/runs/{run_id}/export-bundle", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def export_ragas_regression_run_bundle_api(
    run_id: UUID,
    include_text: Annotated[bool, Query(description='Include raw question/response (may include PII; default false)')] = False,
    include_contexts: Annotated[bool, Query(description='Include retrieved_contexts (may include PII; requires include_text=true)')] = False,
    redact_ids: Annotated[bool, Query(description='Redact internal ids (tenant/dataset/case/run) into stable hashes for sharing (default true)')] = True,
    max_items: Annotated[int, Query(ge=1, le=5000, description='Max regression items to include')] = 500,
    max_citations: Annotated[
        int, Query(ge=0, le=500, description='Max citations per item (PII-safe allowlist)')
    ] = 80,
    download: Annotated[bool, Query(description='Set Content-Disposition to download as a file')] = True,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Export a compact regression run bundle (PII-safe by default)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    run = (
        db.query(RagasRegressionRun)
        .filter(RagasRegressionRun.id == run_id, RagasRegressionRun.tenant_id == tenant_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail=_DETAIL_RUN_NOT_FOUND)

    ds_id = getattr(run, "dataset_id", None)
    if ds_id is not None:
        ds = DatasetService.get_dataset(db, tenant_id, UUID(str(ds_id)))
        DatasetService.assert_dataset_readable(db, ds, account_id)

    items = (
        db.query(RagasRegressionItem)
        .filter(RagasRegressionItem.run_id == run_id, RagasRegressionItem.tenant_id == tenant_id)
        .order_by(RagasRegressionItem.created_at.asc())
        .limit(int(max_items))
        .all()
    )

    bundle = export_regression_run_bundle(
        run,
        items,
        include_text=bool(include_text),
        include_contexts=bool(include_contexts),
        redact_ids=bool(redact_ids),
        max_items=int(max_items),
        max_citations=int(max_citations),
        now=datetime.now(UTC),
    )

    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if download:
        filename = f"regression-run.{str(run_id)[:8]}.json"
        set_download_content_disposition(headers, filename)

    return JSONResponse(content=bundle, headers=headers)


@router.post("/ragas/regression/runs/purge")
def purge_ragas_regression_runs(
    retention_days: Annotated[int, Query(ge=1, le=3650, description='Delete runs older than N days')] = 90,
    max_delete: Annotated[int, Query(ge=1, le=5000, description='Max runs to delete in this call')] = 200,
    dry_run: Annotated[bool, Query(description='Plan only; do not delete rows')] = True,
    dataset_id: Annotated[UUID | None, Query(description='Optional dataset scope')] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Purge old regression runs for the current tenant (bounded).

    Security:
    - Admin-only (lifecycle.manage). Evaluation artifacts can contain sensitive content.
    """
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.LIFECYCLE_MANAGE,
        detail="No permission to manage evaluation retention",
    )

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=int(retention_days or 0))

    eligible = int(
        plan_regression_run_purge(
            db,
            tenant_id=tenant_id,
            cutoff=cutoff,
            max_delete=int(max_delete or 0),
            dataset_id=dataset_id,
        )
        or 0
    )

    deleted_runs = 0
    deleted_items = 0
    if not bool(dry_run):
        deleted_runs, deleted_items = purge_regression_run_rows(
            db,
            tenant_id=tenant_id,
            cutoff=cutoff,
            max_delete=int(max_delete or 0),
            dataset_id=dataset_id,
            commit=True,
        )

    # Best-effort audit log (PII-safe metadata only).
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="evaluations.regression_runs.purge",
            resource_type="ragas_regression_runs",
            resource_id=str(dataset_id) if dataset_id is not None else None,
            details={
                "dry_run": bool(dry_run),
                "retention_days": int(retention_days or 0),
                "cutoff": cutoff.isoformat(),
                "max_delete": int(max_delete or 0),
                "eligible": int(eligible),
                "deleted_runs": int(deleted_runs),
                "deleted_items": int(deleted_items),
            },
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug(_EVALUATIONS_ROUTER_FALLBACK_LOG_MESSAGE, exc)

    return {
        "dry_run": bool(dry_run),
        "retention_days": int(retention_days or 0),
        "cutoff": cutoff,
        "max_delete": int(max_delete or 0),
        "dataset_id": str(dataset_id) if dataset_id is not None else None,
        "eligible_runs": int(eligible),
        "deleted_runs": int(deleted_runs),
        "deleted_items": int(deleted_items),
    }


@router.get("/ragas/regression/runs/{run_id}/diff", response_model=RagasRegressionRunDiffResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def diff_ragas_regression_runs(
    run_id: UUID,
    base_run_id: Annotated[UUID, Query(..., description="Base run id to compare against")],
    include_significance: Annotated[
        bool, Query(description="Compute per-case paired significance statistics when items are available")
    ] = True,
    include_per_case: Annotated[bool, Query(description="Include bounded per-case metric diffs")] = False,
    max_case_diffs: Annotated[int, Query(ge=1, le=5000, description="Max case diffs to include")] = 500,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Diff two regression runs (objective numbers + retrieval slices only)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    base = (
        db.query(RagasRegressionRun)
        .filter(RagasRegressionRun.id == base_run_id, RagasRegressionRun.tenant_id == tenant_id)
        .first()
    )
    if base is None:
        raise HTTPException(status_code=404, detail="Base run not found")

    target = (
        db.query(RagasRegressionRun)
        .filter(RagasRegressionRun.id == run_id, RagasRegressionRun.tenant_id == tenant_id)
        .first()
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Target run not found")

    base_summary = getattr(base, "summary", None)
    base_summary = base_summary if isinstance(base_summary, dict) else {}
    target_summary = getattr(target, "summary", None)
    target_summary = target_summary if isinstance(target_summary, dict) else {}
    if not base_summary or not target_summary:
        raise HTTPException(status_code=404, detail="Summary not available")

    diff = diff_regression_run_summaries(
        base_run_id=base_run_id,
        target_run_id=run_id,
        base_summary=base_summary,
        target_summary=target_summary,
        max_slice_buckets=40,
    )
    if include_significance or include_per_case:
        base_items = (
            db.query(RagasRegressionItem)
            .filter(RagasRegressionItem.run_id == base_run_id, RagasRegressionItem.tenant_id == tenant_id)
            .order_by(RagasRegressionItem.created_at.asc())
            .all()
        )
        target_items = (
            db.query(RagasRegressionItem)
            .filter(RagasRegressionItem.run_id == run_id, RagasRegressionItem.tenant_id == tenant_id)
            .order_by(RagasRegressionItem.created_at.asc())
            .all()
        )
        comparison = compare_regression_items(
            base_items=base_items,
            target_items=target_items,
            metric_keys=[str(row.get("key")) for row in diff.get("metric_diffs", []) if isinstance(row, dict)],
            max_case_diffs=max_case_diffs,
        )
        if include_significance:
            diff["significance"] = comparison.get("significance") or []
            diff["significance_summary"] = comparison.get("summary") or {}
        if include_per_case:
            diff["case_diffs"] = comparison.get("case_diffs") or []
    diff["base_params"] = dict(getattr(base, "params", None) or {})
    diff["target_params"] = dict(getattr(target, "params", None) or {})
    return RagasRegressionRunDiffResponse(**diff)


@router.get("/ragas/regression/runs/{run_id}/diff/export-html", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def export_ragas_regression_run_diff_html(
    run_id: UUID,
    base_run_id: Annotated[UUID, Query(..., description="Base run id to compare against")],
    redact: Annotated[bool, Query(description='Whether to redact run ids for sharing')] = True,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    # Reuse the JSON diff logic (single source of truth).
    payload = await diff_ragas_regression_runs(
        run_id=run_id,
        base_run_id=base_run_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    diff = payload.model_dump(mode="json")

    html = render_regression_run_diff_html(
        title="MimirQ · Regression Run Diff（Before vs After）",
        base_run_id=str(base_run_id),
        target_run_id=str(run_id),
        generated_at=diff.get("generated_at"),
        diff=diff,
        redact=bool(redact),
    )

    filename = f"regression_diff.{str(run_id)[:8]}.html"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers=download_response_headers(filename),
    )


@router.post("/ragas/test-gen/from-documents", response_model=TestGenResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def generate_test_cases_from_documents(
    request: TestGenFromDocsRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Generate test questions from documents."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    try:
        # Generate questions.
        questions = generate_questions_from_documents(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=request.dataset_id,
            document_ids=request.document_ids or None,
            num_questions=request.num_questions,
            question_types=request.question_types,
            prompt_template_id=request.prompt_template_id,
            prompt_template_key=request.prompt_template_key,
            prompt_ab_experiment_key=request.prompt_ab_experiment_key,
        )

        # Auto-save as regression cases when requested.
        #
        # Gap7 (P2): generated cases must carry `reference_sources` so they can be used for
        # retrieval gates and regression slicing.
        saved_case_ids: list[UUID] = []
        if request.auto_save_as_cases and questions:
            # Lazy imports (keeps endpoint import-time side effects low).
            from app.models.document import Document as DBDocument

            # Best-effort: infer dataset_id per question when request.dataset_id is omitted.
            doc_ids: list[UUID] = []
            for q in questions:
                raw_doc = str((q.metadata or {}).get("source_id") or "").strip()
                if not raw_doc:
                    continue
                try:
                    doc_ids.append(UUID(raw_doc))
                except Exception:
                    logging.getLogger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
                    continue

            doc_to_dataset: dict[str, UUID | None] = {}
            if doc_ids:
                rows = (
                    db.query(DBDocument.id, DBDocument.dataset_id)
                    .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(list(set(doc_ids))))
                    .all()
                )
                doc_to_dataset = {str(doc_id): (ds_id if ds_id is not None else None) for doc_id, ds_id in rows}

            ds_cache: dict[UUID, Any] = {}

            def _validate_reference_chunk_hit(
                *,
                question: str,
                dataset_id: UUID,
                chunk_id: UUID,
            ) -> dict[str, Any]:
                """
                Best-effort vector recall validation for the reference chunk.

                This is intentionally non-blocking: failures do not abort generation/saving.
                """
                top_k = 20
                try:
                    from app.rag.retriever import HybridRetriever

                    retriever = HybridRetriever(
                        k=top_k,
                        retrieval_mode="vector",
                        score_threshold=0.0,
                        enable_reranker=False,
                        enable_weight_rerank=False,
                        dedup_enabled=False,
                        max_chunks_per_doc=max(50, top_k),
                        min_distinct_docs=0,
                        tenant_id=tenant_id,
                        account_id=account_id,
                        dataset_id=dataset_id,
                    )
                    docs = retriever.get_relevant_documents(str(question or ""))
                    rank: int | None = None
                    for i, d in enumerate(docs or []):
                        meta = getattr(d, "metadata", None) or {}
                        if str(meta.get("chunk_id") or "").strip() == str(chunk_id):
                            rank = int(i + 1)
                            break
                    return {"mode": "vector_topk", "top_k": top_k, "hit": bool(rank is not None), "rank": rank}
                except Exception as exc:  # noqa: BLE001
                    return {
                        "mode": "vector_topk",
                        "top_k": top_k,
                        "hit": None,
                        "reason": f"{type(exc).__name__}:{str(exc)[:160]}",
                    }

            for q in questions:
                meta = dict(q.metadata or {})
                doc_id_raw = str(meta.get("source_id") or "").strip()
                chunk_ids_raw = meta.get("reference_chunk_ids") or [meta.get("chunk_id")]

                # Resolve dataset_id for this case.
                ds_id: UUID | None = request.dataset_id
                if ds_id is None and doc_id_raw:
                    ds_id = doc_to_dataset.get(doc_id_raw)

                if ds_id is None:
                    meta["auto_save"] = {"saved": False, "reason": "missing_dataset_id"}
                    q.metadata = meta
                    continue

                # Governance: saving regression cases is a write operation.
                if ds_id not in ds_cache:
                    try:
                        ds = DatasetService.get_dataset(db, tenant_id, ds_id)
                        DatasetService.assert_dataset_writable(db, ds, account_id)
                        ds_cache[ds_id] = ds
                    except HTTPException as exc:
                        meta["auto_save"] = {"saved": False, "reason": f"dataset_not_writable:{exc.detail}"}
                        q.metadata = meta
                        continue

                # Build reference_sources payloads (doc_id + chunk_id).
                ref_payloads: list[dict[str, Any]] = []
                for cid_raw in (chunk_ids_raw or []):
                    cid = str(cid_raw or "").strip()
                    if not cid or not doc_id_raw:
                        continue
                    ref_payloads.append({"document_id": doc_id_raw, "chunk_id": cid})

                # Normalize + enrich reference_sources (ACL + dataset scope + quote fallback).
                try:
                    reference_sources = _finalize_reference_sources(
                        db,
                        tenant_id=tenant_id,
                        account_id=account_id,
                        dataset_id=ds_id,
                        reference_sources=ref_payloads,
                    )
                except HTTPException as exc:
                    meta["auto_save"] = {"saved": False, "reason": f"invalid_reference_sources:{exc.detail}"}
                    q.metadata = meta
                    continue

                # Best-effort embedding/vector validation.
                try:
                    if ref_payloads:
                        chunk0 = UUID(str(ref_payloads[0].get("chunk_id")))
                        meta["reference_validation"] = _validate_reference_chunk_hit(
                            question=q.question,
                            dataset_id=ds_id,
                            chunk_id=chunk0,
                        )
                except Exception as exc:
                    logger.debug(_EVALUATIONS_ROUTER_FALLBACK_LOG_MESSAGE, exc)

                case = RagasRegressionCase(
                    tenant_id=tenant_id,
                    dataset_id=ds_id,
                    # Keep retrieval dataset-scoped by default (do NOT scope to a single document).
                    document_ids=[],
                    question=q.question,
                    expected_answer=q.expected_answer,
                    reference_sources=reference_sources,
                    tags=["auto_generated", "from_documents"],
                    extra=meta,
                    created_by=account_id,
                )
                db.add(case)
                db.flush()
                saved_case_ids.append(case.id)

                meta["auto_save"] = {"saved": True, "case_id": str(case.id)}
                q.metadata = meta

            db.commit()

        # Convert to response format (after auto-save, so metadata can include case ids).
        generated_questions = [
            GeneratedQuestion(
                question=q.question,
                expected_answer=q.expected_answer,
                context=q.context,
                source_type="document",
                source_id=(q.metadata or {}).get("source_id", ""),
                metadata=q.metadata,
            )
            for q in questions
        ]

        return TestGenResponse(
            status="completed",
            generated_questions=generated_questions,
            saved_case_ids=saved_case_ids,
        )

    except Exception as e:
        db.rollback()
        return TestGenResponse(
            status="failed",
            generated_questions=[],
            saved_case_ids=[],
            error_message=str(e),
        )


@router.post("/kg/search/diagnostics", response_model=KGSearchDiagnosticsResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def run_kg_search_diagnostics(
    payload: KGSearchDiagnosticsRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Run a Dynamic OneEval-style diagnostics pass for KG search.

    Seed source: RAGAS regression cases (human-verified evidence pointers).
    """
    if not bool(getattr(settings, "KG_ENABLED", False)):
        raise HTTPException(status_code=503, detail=_DETAIL_KG_DISABLED)

    DatasetService.ensure_member(db, tenant_id, account_id)
    ds = DatasetService.get_dataset(db, tenant_id, payload.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    # Lazy import to keep module import side-effects smaller (Milvus/LLM config, etc).
    from app.rag.evaluation.kg_search_diagnostics import run_kg_search_diagnostics as run_impl

    resp = await run_impl(db=db, tenant_id=tenant_id, account_id=account_id, req=payload)

    # Optional: persist a compact run snapshot for diffing over time.
    if bool(getattr(payload, "persist_run", False)):
        try:
            # JSONB persistence needs JSON-serializable primitives.
            # Pydantic's default `model_dump()` returns UUID objects; use mode="json" to coerce to strings.
            params: dict[str, Any] = dict(payload.model_dump(mode="json") if hasattr(payload, "model_dump") else {})
            params["settings_snapshot"] = {
                "KG_ENABLED": bool(getattr(settings, "KG_ENABLED", False)),
                "KG_RELATION_ENABLED": bool(getattr(settings, "KG_RELATION_ENABLED", False)),
                "KG_SKILL_ENABLED": bool(getattr(settings, "KG_SKILL_ENABLED", False)),
                "KG_EXTRACT_EVIDENCE_REQUIRED": bool(getattr(settings, "KG_EXTRACT_EVIDENCE_REQUIRED", False)),
                "KG_SKILL_EVIDENCE_REQUIRED": bool(getattr(settings, "KG_SKILL_EVIDENCE_REQUIRED", False)),
                "KG_SEARCH_VECTOR_RECALL_ENABLED": bool(getattr(settings, "KG_SEARCH_VECTOR_RECALL_ENABLED", True)),
                "KG_SEARCH_GRAPH_EMBEDDINGS_ENABLED": bool(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_ENABLED", False)),
                "KG_SEARCH_GRAPH_EMBEDDINGS_DIM": int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_DIM", 0) or 0),
                "KG_SEARCH_GRAPH_EMBEDDINGS_NUM_WALKS": int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_NUM_WALKS", 0) or 0),
                "KG_SEARCH_GRAPH_EMBEDDINGS_WALK_LENGTH": int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_WALK_LENGTH", 0) or 0),
                "KG_SEARCH_GRAPH_EMBEDDINGS_WINDOW_SIZE": int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_WINDOW_SIZE", 0) or 0),
                "KG_SEARCH_GRAPH_EMBEDDINGS_SEED": int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_SEED", 0) or 0),
                "KG_SEARCH_GRAPH_EMBEDDINGS_MAX_EVENTS": int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_MAX_EVENTS", 0) or 0),
                "KG_SEARCH_GRAPH_EMBEDDINGS_MAX_ENTITIES": int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_MAX_ENTITIES", 0) or 0),
                "KG_SEARCH_GRAPH_EMBEDDINGS_MAX_RELATIONS": int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_MAX_RELATIONS", 0) or 0),
                "KG_SEARCH_GRAPH_EMBEDDINGS_TOP_K": int(getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_TOP_K", 0) or 0),
                "KG_SEARCH_GRAPH_EMBEDDINGS_MIN_SIMILARITY": float(
                    getattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_MIN_SIMILARITY", 0.0) or 0.0
                ),
                "KG_SEARCH_RELATION_EXPANSION_ENABLED": bool(
                    getattr(settings, "KG_SEARCH_RELATION_EXPANSION_ENABLED", False)
                ),
                "KG_SEARCH_RELATION_MIN_CONFIDENCE": float(getattr(settings, "KG_SEARCH_RELATION_MIN_CONFIDENCE", 0.0) or 0.0),
                "KG_SEARCH_RELATION_MAX_EDGES": int(getattr(settings, "KG_SEARCH_RELATION_MAX_EDGES", 0) or 0),
                "KG_SEARCH_RELATION_MAX_NEIGHBORS": int(getattr(settings, "KG_SEARCH_RELATION_MAX_NEIGHBORS", 0) or 0),
            }

            summary_obj = getattr(resp, "summary", None)
            summary = summary_obj.model_dump(mode="json") if hasattr(summary_obj, "model_dump") else {}

            # Compact per-case records to keep the persisted payload small.
            items_compact: list[dict[str, Any]] = []
            for item in (getattr(resp, "items", []) or []):
                baseline = getattr(item, "baseline", None)
                baseline_metrics_obj = getattr(baseline, "metrics", None)
                baseline_metrics = (
                    baseline_metrics_obj.model_dump(mode="json") if hasattr(baseline_metrics_obj, "model_dump") else {}
                )

                hardcases_compact: list[dict[str, Any]] = []
                for hc in (getattr(item, "hardcases", []) or []):
                    run = getattr(hc, "run", None)
                    m_obj = getattr(run, "metrics", None)
                    hardcases_compact.append(
                        {
                            "kind": str(getattr(hc, "kind", "") or ""),
                            "metrics": (m_obj.model_dump(mode="json") if hasattr(m_obj, "model_dump") else {}),
                            "error": (str(getattr(run, "error", "") or "") or None),
                        }
                    )

                attr = getattr(item, "attribution", None)
                attr_dict = attr.model_dump(mode="json") if hasattr(attr, "model_dump") else {}

                items_compact.append(
                    {
                        "case_id": str(getattr(item, "case_id", "") or ""),
                        "question": str(getattr(item, "question", "") or "")[:500],
                        "tags": list(getattr(item, "tags", []) or []),
                        "evidence_chunk_ids": list(getattr(item, "evidence_chunk_ids", []) or []),
                        "attribution": attr_dict,
                        "baseline": {
                            "metrics": baseline_metrics,
                            "error": (str(getattr(baseline, "error", "") or "") or None),
                            "returned_events": int(len(getattr(baseline, "events", []) or [])),
                            "selected_entities": int(len(getattr(baseline, "entities", []) or [])),
                            "clues_total": int(len(getattr(baseline, "clues", []) or [])),
                        },
                        "hardcases": hardcases_compact,
                    }
                )

            run = KGSearchDiagnosticsRun(
                id=uuid4(),
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=payload.dataset_id,
                status="completed",
                params=params,
                summary=summary,
                items=items_compact,
                error_message=None,
            )
            db.add(run)
            db.flush()
            db.commit()

            try:
                resp.run_id = run.id
            except Exception as exc:
                # Best-effort: if response is immutable for any reason, skip run_id propagation.
                logger.debug("Failed to attach KG diagnostics run_id to response: %s", exc)
        except Exception as exc:
            logger.warning("Failed to persist KG diagnostics run snapshot: %s", str(exc)[:200])
            try:
                db.rollback()
            except Exception as exc:
                logger.debug(_EVALUATIONS_ROUTER_FALLBACK_LOG_MESSAGE, exc)

    return resp


@router.get("/kg/search/diagnostics/runs", response_model=KGSearchDiagnosticsRunList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def list_kg_search_diagnostics_runs(
    dataset_id: Annotated[UUID, Query(..., description="Dataset ID (required)")],
    limit: Annotated[int, Query(ge=1, le=200, description='Max runs to return (default: 20)')] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    if not bool(getattr(settings, "KG_ENABLED", False)):
        raise HTTPException(status_code=503, detail=_DETAIL_KG_DISABLED)

    DatasetService.ensure_member(db, tenant_id, account_id)
    ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    query = db.query(KGSearchDiagnosticsRun).filter(
        KGSearchDiagnosticsRun.tenant_id == tenant_id,
        KGSearchDiagnosticsRun.dataset_id == dataset_id,
    )
    total = int(query.count())
    items = query.order_by(KGSearchDiagnosticsRun.created_at.desc()).limit(int(limit)).all()
    return KGSearchDiagnosticsRunList(total=total, items=items)


@router.get("/kg/search/diagnostics/runs/{run_id}", response_model=KGSearchDiagnosticsRunDetail, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_kg_search_diagnostics_run(
    run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    if not bool(getattr(settings, "KG_ENABLED", False)):
        raise HTTPException(status_code=503, detail=_DETAIL_KG_DISABLED)

    run = (
        db.query(KGSearchDiagnosticsRun)
        .filter(KGSearchDiagnosticsRun.id == run_id, KGSearchDiagnosticsRun.tenant_id == tenant_id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Diagnostics run not found")

    DatasetService.ensure_member(db, tenant_id, account_id)
    ds = DatasetService.get_dataset(db, tenant_id, run.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    items = list(run.items or []) if isinstance(getattr(run, "items", None), list) else []
    return KGSearchDiagnosticsRunDetail(run=run, items=items)


@router.get("/kg/quality/report", response_model=dict[str, Any], responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_kg_quality_report(
    dataset_id: Annotated[UUID, Query(..., description="Dataset ID (required)")],
    document_limit: Annotated[int, Query(ge=1, le=2000, description="Max documents sampled for the report")] = 200,
    pipeline_hash: Annotated[str | None, Query(min_length=1, max_length=200, description="Optional pipeline hash filter")] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Aggregate KG extraction quality report for a dataset (PII-minimal).

    This is intentionally best-effort and returns only aggregate statistics (counts/ratios).
    """
    if not bool(getattr(settings, "KG_ENABLED", False)):
        raise HTTPException(status_code=503, detail=_DETAIL_KG_DISABLED)

    DatasetService.ensure_member(db, tenant_id, account_id)
    ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    from app.models.document import Document as DBDocument  # noqa: WPS433
    from app.services.document_access import filter_allowed_document_ids  # noqa: WPS433

    # Sample most recently updated documents in the dataset.
    rows = (
        db.query(DBDocument.id)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.publication_status == "published",
        )
        .order_by(DBDocument.updated_at.desc())
        .limit(int(document_limit))
        .all()
    )
    doc_ids = [row[0] for row in rows if row and row[0] is not None]
    allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, doc_ids)

    from app.rag.kg.quality import build_kg_quality_report  # noqa: WPS433

    report = build_kg_quality_report(
        db,
        tenant_id=tenant_id,
        document_ids=list(allowed_doc_ids or []),
        pipeline_hash=pipeline_hash,
    )
    # Include scope counts for UI diagnostics (no raw ids).
    scope = {
        "dataset_id": str(dataset_id),
        "documents_sampled": int(len(doc_ids)),
        "documents_allowed": int(len(allowed_doc_ids or [])),
    }
    report.setdefault("scope", scope)
    return report


@router.post("/ragas/test-gen/from-conversations", response_model=TestGenResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def generate_test_cases_from_conversations(
    request: TestGenFromConversationsRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Generate test questions from conversation history."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    try:
        # Generate questions.
        questions = generate_questions_from_conversations(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            conversation_ids=request.conversation_ids,
            num_questions=request.num_questions,
            quality_threshold=request.quality_threshold,
        )

        # Convert to response format.
        generated_questions = [
            GeneratedQuestion(
                question=q.question,
                expected_answer=q.expected_answer,
                context=q.context,
                source_type="conversation",
                source_id=q.metadata.get("source_id", ""),
                metadata=q.metadata,
            )
            for q in questions
        ]

        # Auto-save as cases when requested.
        saved_case_ids = []
        if request.auto_save_as_cases:
            for q in questions:
                case = RagasRegressionCase(
                    tenant_id=tenant_id,
                    dataset_id=None,
                    document_ids=[],
                    question=q.question,
                    expected_answer=q.expected_answer,
                    tags=["auto_generated", "from_conversations"],
                    extra=q.metadata,
                    created_by=account_id,
                )
                db.add(case)
                db.flush()
                saved_case_ids.append(case.id)
            
            db.commit()

        return TestGenResponse(
            status="completed",
            generated_questions=generated_questions,
            saved_case_ids=saved_case_ids,
        )

    except Exception as e:
        db.rollback()
        return TestGenResponse(
            status="failed",
            generated_questions=[],
            saved_case_ids=[],
            error_message=str(e),
        )
