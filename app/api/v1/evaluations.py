"""
RAGAS evaluation API.

Provides evaluation endpoints for the RAG system, including task creation,
querying, and results.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.evaluation import (
    GeneratedQuestion,
    KGQualityReportQuery,
    KGSearchDiagnosticsRequest,
    KGSearchDiagnosticsResponse,
    KGSearchDiagnosticsRunDetail,
    KGSearchDiagnosticsRunList,
    KGSearchDiagnosticsRunListQuery,
    RagasConversationReadinessRequest,
    RagasConversationReadinessResponse,
    RagasItemSchema,
    RagasRegressionAblationBatchRequest,
    RagasRegressionAblationBatchResponse,
    RagasRegressionCaseCreateRequest,
    RagasRegressionCaseExportQuery,
    RagasRegressionCaseImportRequest,
    RagasRegressionCaseImportResponse,
    RagasRegressionCaseList,
    RagasRegressionCaseListQuery,
    RagasRegressionCaseOut,
    RagasRegressionCasePatchRequest,
    RagasRegressionItemSchema,
    RagasRegressionRunBundleQuery,
    RagasRegressionRunCreateRequest,
    RagasRegressionRunDetail,
    RagasRegressionRunDiffHtmlQuery,
    RagasRegressionRunDiffQuery,
    RagasRegressionRunDiffResponse,
    RagasRegressionRunLeaderboardQuery,
    RagasRegressionRunLeaderboardResponse,
    RagasRegressionRunList,
    RagasRegressionRunListQuery,
    RagasRegressionRunPurgeQuery,
    RagasRegressionRunSchema,
    RagasRunCreateRequest,
    RagasRunDetail,
    RagasRunDetailQuery,
    RagasRunList,
    RagasRunListQuery,
    RagasRunSchema,
    SyntheticHardcaseGenerateRequest,
    SyntheticHardcaseGenerateResponse,
    TestGenFromConversationsRequest,
    TestGenFromDocsRequest,
    TestGenResponse,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.api.utils import file_response_headers, set_content_disposition
from app.core.config import settings
from app.core.database import get_db
from app.models.chat import Conversation, Message
from app.models.document import Document as DBDocument
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
    GeneratedQuestion as _GeneratedTestQuestion,
)
from app.rag.evaluation.test_generator import (
    generate_questions_from_conversations,
    generate_questions_from_documents,
)
from app.services import dataset_service
from app.services.audit_log_service import audit_log_event
from app.services.chat_conversation_access import ensure_conversation_access
from app.services.document_access import filter_allowed_document_ids
from app.services.evaluation_case_import import (
    import_regression_cases,
    merge_regression_case_extra,
    normalize_evidence_chain,
    normalize_reasoning_hops,
)
from app.services.evaluation_reference_sources import finalize_reference_sources
from app.services.rag_runtime_limiter import run_blocking_call_with_managed_session
from app.services.ragas_conversation_readiness import conversation_readiness_items
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission
from app.services.regression_case_bundle import export_case_bundle
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

if TYPE_CHECKING:
    from app.rag.evaluation.kg_hardcase_generator import Hardcase

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
_REGRESSION_RAG_FIELDS = set(RagasRegressionRunCreateRequest.model_fields) - _REGRESSION_RUN_CONTROL_FIELDS


def _assert_regression_cases_available(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    case_ids: list[UUID],
) -> None:
    if case_ids:
        return
    exists = (
        db.query(RagasRegressionCase.id)
        .filter(
            RagasRegressionCase.tenant_id == tenant_id,
            RagasRegressionCase.dataset_id == dataset_id,
        )
        .first()
    )
    if exists is None:
        raise HTTPException(status_code=400, detail="No regression cases found for selected dataset")


def _load_accessible_conversation(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    conversation_id: UUID,
    not_found_detail: str,
) -> Conversation:
    conversation = (
        db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id).first()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    ensure_conversation_access(db, tenant_id, account_id, conversation)
    return conversation


def _accessible_requested_conversation_ids(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    conversation_ids: list[UUID],
) -> list[UUID]:
    requested_ids = list(dict.fromkeys(conversation_ids))
    if not requested_ids:
        return []
    conversations = (
        db.query(Conversation)
        .filter(
            Conversation.tenant_id == tenant_id,
            Conversation.id.in_(requested_ids),
        )
        .all()
    )
    by_id = {conversation.id: conversation for conversation in conversations}
    scoped_ids: list[UUID] = []
    for conversation_id in requested_ids:
        conversation = by_id.get(conversation_id)
        if conversation is None:
            continue
        ensure_conversation_access(db, tenant_id, account_id, conversation)
        scoped_ids.append(conversation_id)
    return scoped_ids


def _create_regression_run_and_enqueue(
    *,
    request: RagasRegressionRunCreateRequest,
    background_tasks: BackgroundTasks,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> RagasRegressionRun:
    rag_params = request.model_dump(include=_REGRESSION_RAG_FIELDS)
    run = RagasRegressionRun(
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=request.dataset_id,
        status="pending",
        metrics=request.metrics,
        params={
            "case_ids": [str(case_id) for case_id in request.case_ids],
            "dataset_id": str(request.dataset_id),
            "skip_empty_contexts": request.skip_empty_contexts,
            "max_cases": request.max_cases,
            "use_llm_judge": request.use_llm_judge,
            "rag_params": request.model_dump(mode="json", include=_REGRESSION_RAG_FIELDS),
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    background_tasks.add_task(
        run_regression_ragas_evaluation,
        run_id=run.id,
        tenant_id=tenant_id,
        account_id=account_id,
        case_ids=request.case_ids,
        dataset_id=request.dataset_id,
        metric_names=request.metrics,
        use_llm_judge=request.use_llm_judge,
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

    allowed = set(filter_allowed_document_ids(db, tenant_id, account_id, document_ids))
    want = set(document_ids)
    if want - allowed:
        raise HTTPException(status_code=403, detail="Some scope documents are not accessible")

    rows = (
        db.query(DBDocument.id, DBDocument.dataset_id)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(sorted(allowed)))
        .all()
    )
    if any(document_dataset_id != dataset_id for _, document_dataset_id in rows):
        raise HTTPException(status_code=400, detail="Some scope documents do not belong to dataset_id")

    return [str(x) for x in sorted(allowed)]


def _attach_reasoning_fields(case_row: RagasRegressionCase) -> RagasRegressionCase:
    extra = case_row.extra
    extra = extra if isinstance(extra, dict) else {}
    case_row.reasoning_hops = normalize_reasoning_hops(extra.get("reasoning_hops"))
    case_row.evidence_chain = normalize_evidence_chain(extra.get("evidence_chain"))
    return case_row


@router.post(
    "/ragas/conversation-readiness",
    response_model=RagasConversationReadinessResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_ragas_conversation_readiness(
    request: RagasConversationReadinessRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagasConversationReadinessResponse:
    """Return citation-backed evaluation readiness for a batch of conversations."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    scoped_ids = _accessible_requested_conversation_ids(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        conversation_ids=request.conversation_ids,
    )
    if not scoped_ids:
        return RagasConversationReadinessResponse(total=0, items=[])

    assistant_rows = (
        db.query(Message.conversation_id, Message.citations)
        .filter(
            Message.tenant_id == tenant_id,
            Message.conversation_id.in_(scoped_ids),
            Message.role == "assistant",
        )
        .all()
    )
    items = conversation_readiness_items(scoped_ids, assistant_rows)
    return RagasConversationReadinessResponse(total=len(items), items=items)


@router.post("/ragas/runs", response_model=RagasRunSchema, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_ragas_run(
    request: RagasRunCreateRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagasEvaluationRun:
    """Create a RAGAS evaluation run and execute it in background."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    _load_accessible_conversation(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        conversation_id=request.conversation_id,
        not_found_detail="Conversation not found",
    )

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
def list_ragas_runs(
    params: Annotated[RagasRunListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagasRunList:
    """List RAGAS evaluation runs for current tenant."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    if params.conversation_id is not None:
        _load_accessible_conversation(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            conversation_id=params.conversation_id,
            not_found_detail="Conversation not found",
        )

    query = db.query(RagasEvaluationRun).filter(
        RagasEvaluationRun.tenant_id == tenant_id,
        RagasEvaluationRun.account_id == account_id,
    )
    if params.conversation_id is not None:
        query = query.filter(RagasEvaluationRun.conversation_id == params.conversation_id)

    total = query.count()
    runs = query.order_by(RagasEvaluationRun.created_at.desc()).offset(params.skip).limit(params.limit).all()
    return RagasRunList(total=total, items=runs)


@router.get("/ragas/runs/{run_id}", response_model=RagasRunDetail, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_ragas_run(
    run_id: UUID,
    params: Annotated[RagasRunDetailQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagasRunDetail:
    """Get a single run and (optionally) its items."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    run = (
        db.query(RagasEvaluationRun)
        .filter(
            RagasEvaluationRun.id == run_id,
            RagasEvaluationRun.tenant_id == tenant_id,
            RagasEvaluationRun.account_id == account_id,
        )
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail=_DETAIL_RUN_NOT_FOUND)

    if run.conversation_id is not None:
        _load_accessible_conversation(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            conversation_id=run.conversation_id,
            not_found_detail=_DETAIL_RUN_NOT_FOUND,
        )

    items_out: list[RagasItemSchema] = []
    if params.include_items:
        items = (
            db.query(RagasEvaluationItem)
            .filter(RagasEvaluationItem.run_id == run_id, RagasEvaluationItem.tenant_id == tenant_id)
            .order_by(RagasEvaluationItem.turn_index.asc())
            .all()
        )
        for item in items:
            payload = RagasItemSchema.model_validate(item)
            if not params.include_contexts:
                payload.retrieved_contexts = None
            items_out.append(payload)

    return RagasRunDetail(run=run, items=items_out)


@router.post(
    "/ragas/regression/cases",
    response_model=RagasRegressionCaseOut,
    status_code=201,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def create_ragas_regression_case(
    request: RagasRegressionCaseCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagasRegressionCase:
    """Create a regression case (per-dataset; requires evidence sources)."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    ds = dataset_service.get_dataset(db, tenant_id, request.dataset_id)
    # Governance: regression cases back CI gates ("golden questions") and are a write operation.
    dataset_service.assert_dataset_writable(db, ds, account_id)

    reference_sources = finalize_reference_sources(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=request.dataset_id,
        reference_sources=request.reference_sources,
    )
    merged_extra = merge_regression_case_extra(
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
            document_ids=request.document_ids,
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


@router.patch(
    "/ragas/regression/cases/{case_id}",
    response_model=RagasRegressionCaseOut,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def patch_ragas_regression_case(
    case_id: UUID,
    request: RagasRegressionCasePatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagasRegressionCase:
    """Patch a regression case (dataset_id is immutable)."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    row = (
        db.query(RagasRegressionCase)
        .filter(RagasRegressionCase.id == case_id, RagasRegressionCase.tenant_id == tenant_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found")

    dataset_id = row.dataset_id
    if dataset_id is not None:
        ds = dataset_service.get_dataset(db, tenant_id, dataset_id)
        # Governance: patching cases can alter golden suites and should be gated as a write action.
        dataset_service.assert_dataset_writable(db, ds, account_id)

    fields = request.model_fields_set
    if "question" in fields and request.question is not None:
        row.question = request.question
    if "expected_answer" in fields:
        row.expected_answer = request.expected_answer
    if "tags" in fields and request.tags is not None:
        row.tags = request.tags
    if fields & {"extra", "reasoning_hops", "evidence_chain"}:
        base_extra = request.extra if ("extra" in fields and request.extra is not None) else row.extra
        base_extra = base_extra if isinstance(base_extra, dict) else {}
        row.extra = merge_regression_case_extra(
            base_extra=base_extra,
            reasoning_hops=(request.reasoning_hops if "reasoning_hops" in fields else base_extra.get("reasoning_hops")),
            evidence_chain=(request.evidence_chain if "evidence_chain" in fields else base_extra.get("evidence_chain")),
        )
    if "document_ids" in fields and request.document_ids is not None:
        if dataset_id is None:
            raise HTTPException(status_code=400, detail="Cannot patch document_ids without dataset_id")
        row.document_ids = _finalize_scope_document_ids(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            document_ids=request.document_ids,
        )
    if "reference_sources" in fields and request.reference_sources is not None:
        if dataset_id is None:
            raise HTTPException(status_code=400, detail="Cannot patch reference_sources without dataset_id")
        row.reference_sources = finalize_reference_sources(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            reference_sources=request.reference_sources,
        )

    db.add(row)
    db.commit()
    db.refresh(row)
    return _attach_reasoning_fields(row)


@router.get(
    "/ragas/regression/cases", response_model=RagasRegressionCaseList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def list_ragas_regression_cases(
    params: Annotated[RagasRegressionCaseListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagasRegressionCaseList:
    """List regression cases (tenant isolated, filterable by dataset_id)."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    query = db.query(RagasRegressionCase).filter(RagasRegressionCase.tenant_id == tenant_id)
    if params.dataset_id is not None:
        query = query.filter(RagasRegressionCase.dataset_id == params.dataset_id)

    total = query.count()
    items = query.order_by(RagasRegressionCase.updated_at.desc()).offset(params.skip).limit(params.limit).all()
    items = [_attach_reasoning_fields(x) for x in items]
    return RagasRegressionCaseList(total=total, items=items)


@router.get("/ragas/regression/cases/export", response_model=None, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_ragas_regression_cases(
    params: Annotated[RagasRegressionCaseExportQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Export regression cases as a dataset-scoped bundle (no internal ids)."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    ds = dataset_service.get_dataset(db, tenant_id, params.dataset_id)
    dataset_service.assert_dataset_readable(db, ds, account_id)

    items = (
        db.query(RagasRegressionCase)
        .filter(
            RagasRegressionCase.tenant_id == tenant_id,
            RagasRegressionCase.dataset_id == params.dataset_id,
        )
        .order_by(RagasRegressionCase.updated_at.desc())
        .all()
    )

    return export_case_bundle(items, params.dataset_id)


@router.post(
    "/ragas/regression/cases/import",
    response_model=RagasRegressionCaseImportResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def import_ragas_regression_cases(
    payload: RagasRegressionCaseImportRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagasRegressionCaseImportResponse:
    result = import_regression_cases(payload, tenant_id=tenant_id, account_id=account_id, db=db)
    return RagasRegressionCaseImportResponse.model_validate(result)


@router.post(
    "/ragas/regression/cases/synthetic-hardcases",
    response_model=SyntheticHardcaseGenerateResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def generate_synthetic_hardcases(
    payload: SyntheticHardcaseGenerateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> SyntheticHardcaseGenerateResponse:
    """
    Generate synthetic "hardcase" regression cases (PII-safe, deterministic).

    This is a quality-program helper:
    - Takes existing regression cases as seeds
    - Generates harder query variants (alias/skill pressure) using KG-derived candidates
    - Reuses the same reference_sources so evaluation remains grounded
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    if not settings.KG_ENABLED:
        raise HTTPException(status_code=503, detail=_DETAIL_KG_DISABLED)

    ds = dataset_service.get_dataset(db, tenant_id, payload.dataset_id)
    if payload.dry_run:
        dataset_service.assert_dataset_readable(db, ds, account_id)
    else:
        # Creating many cases is a write action (governance).
        dataset_service.assert_dataset_writable(db, ds, account_id)

    _validate_regression_case_scope(db, tenant_id=tenant_id, dataset_id=payload.dataset_id, case_ids=payload.case_ids)

    per_case = payload.hardcases_per_case
    max_created = payload.max_created
    tag = payload.tag.strip() or "synthetic_hardcase"

    base_total, base_cases = _load_synthetic_base_cases(
        db,
        tenant_id=tenant_id,
        dataset_id=payload.dataset_id,
        case_ids=payload.case_ids,
        max_cases=payload.max_cases,
    )
    existing_keys = _load_existing_synthetic_question_keys(
        db,
        tenant_id=tenant_id,
        dataset_id=payload.dataset_id,
    )

    created_ids: list[UUID] = []
    skipped_dup = 0
    hardcases_generated = 0
    base_used = 0

    for case in base_cases:
        if per_case <= 0:
            break
        if max_created > 0 and len(created_ids) >= max_created:
            break

        used, generated, duplicates = _generate_hardcases_for_base_case(
            db=db,
            case=case,
            tenant_id=tenant_id,
            dataset_id=payload.dataset_id,
            account_id=account_id,
            per_case=per_case,
            max_created=max_created,
            tag=tag,
            dry_run=payload.dry_run,
            existing_keys=existing_keys,
            created_ids=created_ids,
        )
        base_used += used
        hardcases_generated += generated
        skipped_dup += duplicates

    if not payload.dry_run:
        try:
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            raise

    return SyntheticHardcaseGenerateResponse(
        dataset_id=payload.dataset_id,
        base_cases_total=base_total,
        base_cases_evaluated=base_used,
        hardcases_generated=hardcases_generated,
        created=0 if payload.dry_run else len(created_ids),
        skipped_duplicates=skipped_dup,
        created_case_ids=created_ids,
    )


def _validate_regression_case_scope(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    case_ids: list[UUID],
) -> None:
    if not case_ids:
        return
    rows = (
        db.query(RagasRegressionCase.id, RagasRegressionCase.dataset_id)
        .filter(
            RagasRegressionCase.tenant_id == tenant_id,
            RagasRegressionCase.id.in_(case_ids),
        )
        .all()
    )
    try:
        validate_case_ids_belong_to_dataset(
            dataset_id=dataset_id,
            case_ids=case_ids,
            rows=rows,
        )
    except MissingCasesError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatasetMismatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _load_synthetic_base_cases(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    case_ids: list[UUID],
    max_cases: int,
) -> tuple[int, list[RagasRegressionCase]]:
    query = db.query(RagasRegressionCase).filter(
        RagasRegressionCase.tenant_id == tenant_id,
        RagasRegressionCase.dataset_id == dataset_id,
    )
    if case_ids:
        query = query.filter(RagasRegressionCase.id.in_(case_ids))
    total = query.count()
    cases = query.order_by(RagasRegressionCase.updated_at.desc(), RagasRegressionCase.id.asc()).limit(max_cases).all()
    return total, cases


def _synthetic_question_key(text: str) -> str:
    return " ".join(text.strip().split()).casefold()


def _load_existing_synthetic_question_keys(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
) -> set[str]:
    rows = (
        db.query(RagasRegressionCase.question)
        .filter(RagasRegressionCase.tenant_id == tenant_id, RagasRegressionCase.dataset_id == dataset_id)
        .all()
    )
    return {_synthetic_question_key(question) for (question,) in rows if question}


def _synthetic_evidence_chunk_ids(reference_sources: list[Any]) -> list[str]:
    chunk_ids: list[str] = []
    for source in reference_sources:
        if not isinstance(source, dict):
            continue
        raw_chunk_id = source.get("chunk_id")
        if raw_chunk_id is None:
            continue
        chunk_id = str(raw_chunk_id).strip()
        if chunk_id:
            chunk_ids.append(chunk_id)
    return chunk_ids


def _generate_hardcases_for_base_case(
    *,
    db: Session,
    case: RagasRegressionCase,
    tenant_id: UUID,
    dataset_id: UUID,
    account_id: str,
    per_case: int,
    max_created: int,
    tag: str,
    dry_run: bool,
    existing_keys: set[str],
    created_ids: list[UUID],
) -> tuple[int, int, int]:
    question = case.question.strip()
    if not question:
        return 0, 0, 0

    from app.rag.evaluation.kg_hardcase_deterministic import generate_hardcases_deterministic
    from app.rag.evaluation.kg_search_diagnostics import (
        _deterministic_hardcase_candidates,
        _resolve_ground_truth_event_ids,
    )

    reference_sources = case.reference_sources
    if not isinstance(reference_sources, list):
        reference_sources = []
    event_ids = _resolve_ground_truth_event_ids(
        db,
        tenant_id=tenant_id,
        evidence_chunk_ids=_synthetic_evidence_chunk_ids(reference_sources),
    )
    alias_pairs, skills, tags = _deterministic_hardcase_candidates(
        db,
        tenant_id=tenant_id,
        ground_truth_event_ids=event_ids,
    )
    hardcases = generate_hardcases_deterministic(
        question=question,
        alias_pairs=alias_pairs,
        skills=skills,
        tags=tags,
        max_items=per_case,
    )
    if not hardcases:
        return 0, 0, 0

    generated, duplicates = _persist_generated_hardcases(
        db=db,
        hardcases=hardcases,
        base_case=case,
        reference_sources=reference_sources,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        account_id=account_id,
        max_created=max_created,
        tag=tag,
        dry_run=dry_run,
        existing_keys=existing_keys,
        created_ids=created_ids,
    )
    return 1, generated, duplicates


def _persist_generated_hardcases(
    *,
    db: Session,
    hardcases: list[Hardcase],
    base_case: RagasRegressionCase,
    reference_sources: list[Any],
    tenant_id: UUID,
    dataset_id: UUID,
    account_id: str,
    max_created: int,
    tag: str,
    dry_run: bool,
    existing_keys: set[str],
    created_ids: list[UUID],
) -> tuple[int, int]:
    generated = 0
    duplicates = 0
    for hardcase in hardcases:
        question = hardcase.question.strip()
        if not question:
            continue
        generated += 1
        key = _synthetic_question_key(question)
        if key in existing_keys:
            duplicates += 1
            continue
        if dry_run:
            existing_keys.add(key)
            continue

        row = _build_synthetic_regression_case(
            base_case=base_case,
            hardcase=hardcase,
            reference_sources=reference_sources,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            account_id=account_id,
            question=question,
            tag=tag,
        )
        db.add(row)
        db.flush()
        created_ids.append(row.id)
        existing_keys.add(key)
        if max_created > 0 and len(created_ids) >= max_created:
            break
    return generated, duplicates


def _build_synthetic_regression_case(
    *,
    base_case: RagasRegressionCase,
    hardcase: Hardcase,
    reference_sources: list[Any],
    tenant_id: UUID,
    dataset_id: UUID,
    account_id: str,
    question: str,
    tag: str,
) -> RagasRegressionCase:
    tags = [
        *list(base_case.tags or []),
        tag,
        f"hardcase:{hardcase.kind}",
    ]
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_tag in tags:
        if raw_tag is None:
            continue
        normalized = str(raw_tag).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized[:80])
    base_extra = base_case.extra
    extra = dict(base_extra) if isinstance(base_extra, dict) else {}
    extra.setdefault("synthetic_from_case_id", str(base_case.id))
    extra["hardcase_kind"] = hardcase.kind
    if hardcase.rationale:
        extra["hardcase_rationale"] = hardcase.rationale[:400]
    return RagasRegressionCase(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_ids=list(base_case.document_ids or []),
        question=question,
        expected_answer=base_case.expected_answer,
        reference_sources=list(reference_sources),
        tags=cleaned,
        extra=extra,
        created_by=account_id,
    )


@router.delete("/ragas/regression/cases/{case_id}", status_code=204, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def delete_ragas_regression_case(
    case_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Delete a regression case."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    row = (
        db.query(RagasRegressionCase)
        .filter(RagasRegressionCase.id == case_id, RagasRegressionCase.tenant_id == tenant_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found")

    dataset_id = row.dataset_id
    if dataset_id is None:
        raise HTTPException(status_code=400, detail="Cannot delete case without dataset_id")
    ds = dataset_service.get_dataset(db, tenant_id, dataset_id)
    # Governance: deletion is a write action; protect golden suites.
    dataset_service.assert_dataset_writable(db, ds, account_id)

    db.delete(row)
    db.commit()
    return None


@router.post(
    "/ragas/regression/runs",
    response_model=RagasRegressionRunSchema,
    status_code=201,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def create_ragas_regression_run(
    request: RagasRegressionRunCreateRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagasRegressionRun:
    """Create a regression evaluation run and execute it in background."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    ds = dataset_service.get_dataset(db, tenant_id, request.dataset_id)
    dataset_service.assert_dataset_readable(db, ds, account_id)

    _validate_regression_case_scope(db, tenant_id=tenant_id, dataset_id=request.dataset_id, case_ids=request.case_ids)
    _assert_regression_cases_available(
        db=db,
        tenant_id=tenant_id,
        dataset_id=request.dataset_id,
        case_ids=request.case_ids,
    )

    return _create_regression_run_and_enqueue(
        request=request,
        background_tasks=background_tasks,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post(
    "/ragas/regression/ablation/batch",
    response_model=RagasRegressionAblationBatchResponse,
    status_code=201,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def create_ragas_regression_ablation_batch(
    request: RagasRegressionAblationBatchRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagasRegressionAblationBatchResponse:
    """Create a bounded cartesian batch of regression runs for ablation analysis."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    ds = dataset_service.get_dataset(db, tenant_id, request.dataset_id)
    dataset_service.assert_dataset_readable(db, ds, account_id)

    _validate_regression_case_scope(db, tenant_id=tenant_id, dataset_id=request.dataset_id, case_ids=request.case_ids)
    _assert_regression_cases_available(
        db=db,
        tenant_id=tenant_id,
        dataset_id=request.dataset_id,
        case_ids=request.case_ids,
    )

    try:
        variants = expand_ablation_grid(
            request.grid,
            max_combinations=request.max_combinations,
            allowed_keys=_REGRESSION_RAG_FIELDS,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    base_payload = request.model_dump(exclude={"grid", "max_combinations", "ablation_label_prefix"})
    variant_requests: list[RagasRegressionRunCreateRequest] = []
    for index, variant in enumerate(variants):
        try:
            variant_request = RagasRegressionRunCreateRequest.model_validate({**base_payload, **variant})
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid ablation variant {index + 1}: {exc}") from exc
        variant_requests.append(variant_request)

    ablation_id = uuid4()
    run_ids: list[UUID] = []
    for index, variant_request in enumerate(variant_requests):
        variant = variants[index]
        run = _create_regression_run_and_enqueue(
            request=variant_request,
            background_tasks=background_tasks,
            tenant_id=tenant_id,
            account_id=account_id,
            db=db,
        )
        params = dict(run.params)
        params["ablation_id"] = str(ablation_id)
        params["ablation_variant_index"] = index
        params["ablation_variant"] = dict(variant)
        if request.ablation_label_prefix:
            params["ablation_label"] = f"{request.ablation_label_prefix}-{index + 1}"
        run.params = params
        db.add(run)
        db.commit()
        db.refresh(run)
        run_ids.append(run.id)

    return RagasRegressionAblationBatchResponse(
        ablation_id=ablation_id,
        total=len(run_ids),
        run_ids=run_ids,
        variants=variants,
        status="queued",
    )


@router.get(
    "/ragas/regression/runs", response_model=RagasRegressionRunList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def list_ragas_regression_runs(
    params: Annotated[RagasRegressionRunListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagasRegressionRunList:
    """List regression runs."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    query = db.query(RagasRegressionRun).filter(RagasRegressionRun.tenant_id == tenant_id)
    if params.dataset_id is not None:
        dataset_service.get_dataset(db, tenant_id, params.dataset_id)
        query = query.filter(RagasRegressionRun.dataset_id == params.dataset_id)
    total = query.count()
    runs = query.order_by(RagasRegressionRun.created_at.desc()).offset(params.skip).limit(params.limit).all()
    return RagasRegressionRunList(total=total, items=runs)


@router.get(
    "/ragas/regression/runs/leaderboard",
    response_model=RagasRegressionRunLeaderboardResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_ragas_regression_run_leaderboard(
    params: Annotated[RagasRegressionRunLeaderboardQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagasRegressionRunLeaderboardResponse:
    """Rank regression runs by a retrieval-only metric and attach retrieval_config_hash (PII-safe)."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    ds = dataset_service.get_dataset(db, tenant_id, params.dataset_id)
    dataset_service.assert_dataset_readable(db, ds, account_id)

    query = (
        db.query(RagasRegressionRun)
        .filter(
            RagasRegressionRun.tenant_id == tenant_id,
            RagasRegressionRun.dataset_id == params.dataset_id,
        )
        .order_by(RagasRegressionRun.created_at.desc())
    )
    if not params.include_incomplete:
        query = query.filter(RagasRegressionRun.status == "completed")

    runs = query.limit(params.max_candidates).all()
    items = build_regression_run_leaderboard(runs=runs, metric_key=params.metric_key, limit=params.limit)
    return RagasRegressionRunLeaderboardResponse(metric_key=params.metric_key, items=items)


@router.get(
    "/ragas/regression/runs/{run_id}",
    response_model=RagasRegressionRunDetail,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_ragas_regression_run(
    run_id: UUID,
    params: Annotated[RagasRunDetailQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagasRegressionRunDetail:
    """Get a regression run detail (optional items and contexts)."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    run = (
        db.query(RagasRegressionRun)
        .filter(RagasRegressionRun.id == run_id, RagasRegressionRun.tenant_id == tenant_id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail=_DETAIL_RUN_NOT_FOUND)

    items_out: list[RagasRegressionItemSchema] = []
    if params.include_items:
        items = (
            db.query(RagasRegressionItem)
            .filter(RagasRegressionItem.run_id == run_id, RagasRegressionItem.tenant_id == tenant_id)
            .order_by(RagasRegressionItem.created_at.asc())
            .all()
        )
        for item in items:
            payload = RagasRegressionItemSchema.model_validate(item)
            if not params.include_contexts:
                payload.retrieved_contexts = None
            items_out.append(payload)

    return RagasRegressionRunDetail(run=run, items=items_out)


@router.get("/ragas/regression/runs/{run_id}/export-bundle", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_ragas_regression_run_bundle_api(
    run_id: UUID,
    params: Annotated[RagasRegressionRunBundleQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> JSONResponse:
    """Export a compact regression run bundle (PII-safe by default)."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    run = (
        db.query(RagasRegressionRun)
        .filter(RagasRegressionRun.id == run_id, RagasRegressionRun.tenant_id == tenant_id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail=_DETAIL_RUN_NOT_FOUND)

    if run.dataset_id is not None:
        ds = dataset_service.get_dataset(db, tenant_id, run.dataset_id)
        dataset_service.assert_dataset_readable(db, ds, account_id)

    items = (
        db.query(RagasRegressionItem)
        .filter(RagasRegressionItem.run_id == run_id, RagasRegressionItem.tenant_id == tenant_id)
        .order_by(RagasRegressionItem.created_at.asc())
        .limit(params.max_items)
        .all()
    )

    bundle = export_regression_run_bundle(
        run,
        items,
        include_text=params.include_text,
        include_contexts=params.include_contexts,
        redact_ids=params.redact_ids,
        max_items=params.max_items,
        max_citations=params.max_citations,
        now=datetime.now(UTC),
    )

    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if params.download:
        filename = f"regression-run.{str(run_id)[:8]}.json"
        set_content_disposition(headers, filename)

    return JSONResponse(content=bundle, headers=headers)


@router.post("/ragas/regression/runs/purge", response_model=None)
def purge_ragas_regression_runs(
    params: Annotated[RagasRegressionRunPurgeQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
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
    cutoff = now - timedelta(days=params.retention_days)

    eligible = plan_regression_run_purge(
        db,
        tenant_id=tenant_id,
        cutoff=cutoff,
        max_delete=params.max_delete,
        dataset_id=params.dataset_id,
    )

    deleted_runs = 0
    deleted_items = 0
    if not params.dry_run:
        deleted_runs, deleted_items = purge_regression_run_rows(
            db,
            tenant_id=tenant_id,
            cutoff=cutoff,
            max_delete=params.max_delete,
            dataset_id=params.dataset_id,
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
            resource_id=str(params.dataset_id) if params.dataset_id is not None else None,
            details={
                "dry_run": params.dry_run,
                "retention_days": params.retention_days,
                "cutoff": cutoff.isoformat(),
                "max_delete": params.max_delete,
                "eligible": eligible,
                "deleted_runs": deleted_runs,
                "deleted_items": deleted_items,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Regression purge completed but its audit record failed", exc_info=True)

    return {
        "dry_run": params.dry_run,
        "retention_days": params.retention_days,
        "cutoff": cutoff,
        "max_delete": params.max_delete,
        "dataset_id": str(params.dataset_id) if params.dataset_id is not None else None,
        "eligible_runs": eligible,
        "deleted_runs": deleted_runs,
        "deleted_items": deleted_items,
    }


@router.get(
    "/ragas/regression/runs/{run_id}/diff",
    response_model=RagasRegressionRunDiffResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def diff_ragas_regression_runs(
    run_id: UUID,
    params: Annotated[RagasRegressionRunDiffQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagasRegressionRunDiffResponse:
    """Diff two regression runs (objective numbers + retrieval slices only)."""
    dataset_service.ensure_member(db, tenant_id, account_id)
    return _build_regression_run_diff(
        db=db,
        tenant_id=tenant_id,
        run_id=run_id,
        base_run_id=params.base_run_id,
        include_significance=params.include_significance,
        include_per_case=params.include_per_case,
        max_case_diffs=params.max_case_diffs,
    )


def _build_regression_run_diff(
    *,
    db: Session,
    tenant_id: UUID,
    run_id: UUID,
    base_run_id: UUID,
    include_significance: bool,
    include_per_case: bool,
    max_case_diffs: int,
) -> RagasRegressionRunDiffResponse:

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

    base_summary = base.summary
    base_summary = base_summary if isinstance(base_summary, dict) else {}
    target_summary = target.summary
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
            metric_keys=[row["key"] for row in diff["metric_diffs"]],
            max_case_diffs=max_case_diffs,
        )
        if include_significance:
            diff["significance"] = comparison["significance"]
            diff["significance_summary"] = comparison["summary"]
        if include_per_case:
            diff["case_diffs"] = comparison["case_diffs"]
    diff["base_params"] = dict(base.params or {})
    diff["target_params"] = dict(target.params or {})
    return RagasRegressionRunDiffResponse(**diff)


@router.get("/ragas/regression/runs/{run_id}/diff/export-html", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_ragas_regression_run_diff_html(
    run_id: UUID,
    params: Annotated[RagasRegressionRunDiffHtmlQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    dataset_service.ensure_member(db, tenant_id, account_id)

    payload = _build_regression_run_diff(
        run_id=run_id,
        base_run_id=params.base_run_id,
        tenant_id=tenant_id,
        db=db,
        include_significance=True,
        include_per_case=False,
        max_case_diffs=500,
    )
    diff = payload.model_dump(mode="json")

    html = render_regression_run_diff_html(
        title="MimirQ · Regression Run Diff（Before vs After）",
        base_run_id=str(params.base_run_id),
        target_run_id=str(run_id),
        generated_at=diff["generated_at"],
        diff=diff,
        redact=params.redact,
    )

    filename = f"regression_diff.{str(run_id)[:8]}.html"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers=file_response_headers(filename),
    )


@router.post(
    "/ragas/test-gen/from-documents", response_model=TestGenResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def generate_test_cases_from_documents(
    request: TestGenFromDocsRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TestGenResponse:
    """Generate test questions from documents."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    try:
        questions = generate_questions_from_documents(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=request.dataset_id,
            document_ids=request.document_ids,
            num_questions=request.num_questions,
            question_types=request.question_types,
            prompt_template_id=request.prompt_template_id,
            prompt_template_key=request.prompt_template_key,
            prompt_ab_experiment_key=request.prompt_ab_experiment_key,
        )
        saved_case_ids: list[UUID] = []
        if request.auto_save_as_cases and questions:
            saved_case_ids = _auto_save_generated_document_questions(
                db=db,
                questions=questions,
                requested_dataset_id=request.dataset_id,
                tenant_id=tenant_id,
                account_id=account_id,
            )

        return TestGenResponse(
            status="completed",
            generated_questions=_document_questions_response(questions),
            saved_case_ids=saved_case_ids,
        )

    except Exception as exc:
        db.rollback()
        return TestGenResponse(
            status="failed",
            generated_questions=[],
            saved_case_ids=[],
            error_message=str(exc),
        )


def _auto_save_generated_document_questions(
    *,
    db: Session,
    questions: list[_GeneratedTestQuestion],
    requested_dataset_id: UUID | None,
    tenant_id: UUID,
    account_id: str,
) -> list[UUID]:
    document_to_dataset = _document_dataset_map(db, tenant_id=tenant_id, questions=questions)
    writable_dataset_ids: set[UUID] = set()
    saved_case_ids: list[UUID] = []
    for question in questions:
        case_id = _auto_save_generated_document_question(
            db=db,
            question=question,
            requested_dataset_id=requested_dataset_id,
            document_to_dataset=document_to_dataset,
            writable_dataset_ids=writable_dataset_ids,
            tenant_id=tenant_id,
            account_id=account_id,
        )
        if case_id is not None:
            saved_case_ids.append(case_id)
    db.commit()
    return saved_case_ids


def _document_dataset_map(
    db: Session,
    *,
    tenant_id: UUID,
    questions: list[_GeneratedTestQuestion],
) -> dict[str, UUID | None]:
    document_ids = {UUID(question.metadata["source_id"]) for question in questions}
    if not document_ids:
        return {}
    rows = (
        db.query(DBDocument.id, DBDocument.dataset_id)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(document_ids))
        .all()
    )
    return {str(document_id): dataset_id for document_id, dataset_id in rows}


def _auto_save_generated_document_question(
    *,
    db: Session,
    question: _GeneratedTestQuestion,
    requested_dataset_id: UUID | None,
    document_to_dataset: dict[str, UUID | None],
    writable_dataset_ids: set[UUID],
    tenant_id: UUID,
    account_id: str,
) -> UUID | None:
    metadata = dict(question.metadata)
    document_id = metadata["source_id"]
    dataset_id = requested_dataset_id
    if dataset_id is None:
        dataset_id = document_to_dataset.get(document_id)
    if dataset_id is None:
        _mark_generated_question_unsaved(question, metadata, "missing_dataset_id")
        return None
    if dataset_id not in writable_dataset_ids:
        try:
            dataset = dataset_service.get_dataset(db, tenant_id, dataset_id)
            dataset_service.assert_dataset_writable(db, dataset, account_id)
        except HTTPException as exc:
            _mark_generated_question_unsaved(question, metadata, f"dataset_not_writable:{exc.detail}")
            return None
        writable_dataset_ids.add(dataset_id)

    reference_payloads = [
        {"document_id": document_id, "chunk_id": chunk_id} for chunk_id in metadata["reference_chunk_ids"]
    ]
    try:
        reference_sources = finalize_reference_sources(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            reference_sources=reference_payloads,
        )
    except HTTPException as exc:
        _mark_generated_question_unsaved(question, metadata, f"invalid_reference_sources:{exc.detail}")
        return None

    try:
        metadata["reference_validation"] = _validate_generated_reference_chunk_hit(
            question=question.question,
            dataset_id=dataset_id,
            chunk_id=UUID(reference_payloads[0]["chunk_id"]),
            tenant_id=tenant_id,
            account_id=account_id,
        )
    except Exception as exc:
        logger.debug(_EVALUATIONS_ROUTER_FALLBACK_LOG_MESSAGE, exc, exc_info=True)
    case = RagasRegressionCase(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_ids=[],
        question=question.question,
        expected_answer=question.expected_answer,
        reference_sources=reference_sources,
        tags=["auto_generated", "from_documents"],
        extra=metadata,
        created_by=account_id,
    )
    db.add(case)
    db.flush()
    metadata["auto_save"] = {"saved": True, "case_id": str(case.id)}
    question.metadata = metadata
    return case.id


def _mark_generated_question_unsaved(question: _GeneratedTestQuestion, metadata: dict[str, Any], reason: str) -> None:
    metadata["auto_save"] = {"saved": False, "reason": reason}
    question.metadata = metadata


def _validate_generated_reference_chunk_hit(
    *,
    question: str,
    dataset_id: UUID,
    chunk_id: UUID,
    tenant_id: UUID,
    account_id: str,
) -> dict[str, Any]:
    """Best-effort vector recall validation for a generated question's reference chunk."""
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
            max_chunks_per_doc=50,
            min_distinct_docs=0,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
        )
        docs = retriever.get_relevant_documents(question)
        rank: int | None = None
        for index, document in enumerate(docs):
            candidate_chunk_id = document.metadata.get("chunk_id")
            if candidate_chunk_id is not None and str(candidate_chunk_id).strip() == str(chunk_id):
                rank = index + 1
                break
        return {"mode": "vector_topk", "top_k": top_k, "hit": rank is not None, "rank": rank}
    except Exception as exc:  # noqa: BLE001
        return {
            "mode": "vector_topk",
            "top_k": top_k,
            "hit": None,
            "reason": f"{type(exc).__name__}:{str(exc)[:160]}",
        }


def _document_questions_response(questions: list[_GeneratedTestQuestion]) -> list[GeneratedQuestion]:
    return [
        GeneratedQuestion(
            question=question.question,
            expected_answer=question.expected_answer,
            context=question.context,
            source_type="document",
            source_id=question.metadata["source_id"],
            metadata=question.metadata,
        )
        for question in questions
    ]


@router.post(
    "/kg/search/diagnostics", response_model=KGSearchDiagnosticsResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
async def run_kg_search_diagnostics(
    payload: KGSearchDiagnosticsRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> KGSearchDiagnosticsResponse:
    """Run KG diagnostics while keeping its synchronous database work off-loop."""
    if not settings.KG_ENABLED:
        raise HTTPException(status_code=503, detail=_DETAIL_KG_DISABLED)

    def authorize_dataset(worker_db: Session) -> None:
        dataset_service.ensure_member(worker_db, tenant_id, account_id)
        dataset = dataset_service.get_dataset(worker_db, tenant_id, payload.dataset_id)
        dataset_service.assert_dataset_readable(worker_db, dataset, account_id)

    await run_blocking_call_with_managed_session(authorize_dataset, request_db=None)
    from app.rag.evaluation.kg_search_diagnostics import run_kg_search_diagnostics as run_impl

    response = await run_impl(db=db, tenant_id=tenant_id, account_id=account_id, req=payload)
    if payload.persist_run:
        run_id = await run_blocking_call_with_managed_session(
            lambda worker_db: _persist_kg_diagnostics_run(
                db=worker_db,
                tenant_id=tenant_id,
                account_id=account_id,
                payload=payload,
                response=response,
            ),
            request_db=None,
        )
        if run_id is not None:
            response.run_id = run_id
    return response


def _persist_kg_diagnostics_run(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    payload: KGSearchDiagnosticsRequest,
    response: KGSearchDiagnosticsResponse,
) -> UUID | None:
    """Persist an optional diagnostic snapshot; a failed rollback remains fatal."""
    try:
        params = payload.model_dump(mode="json")
        params["settings_snapshot"] = {
            "KG_ENABLED": settings.KG_ENABLED,
            "KG_RELATION_ENABLED": settings.KG_RELATION_ENABLED,
            "KG_SKILL_ENABLED": settings.KG_SKILL_ENABLED,
            "KG_EXTRACT_EVIDENCE_REQUIRED": settings.KG_EXTRACT_EVIDENCE_REQUIRED,
            "KG_SKILL_EVIDENCE_REQUIRED": settings.KG_SKILL_EVIDENCE_REQUIRED,
            "KG_SEARCH_VECTOR_RECALL_ENABLED": settings.KG_SEARCH_VECTOR_RECALL_ENABLED,
            "KG_SEARCH_GRAPH_EMBEDDINGS_ENABLED": settings.KG_SEARCH_GRAPH_EMBEDDINGS_ENABLED,
            "KG_SEARCH_GRAPH_EMBEDDINGS_DIM": settings.KG_SEARCH_GRAPH_EMBEDDINGS_DIM,
            "KG_SEARCH_GRAPH_EMBEDDINGS_NUM_WALKS": settings.KG_SEARCH_GRAPH_EMBEDDINGS_NUM_WALKS,
            "KG_SEARCH_GRAPH_EMBEDDINGS_WALK_LENGTH": settings.KG_SEARCH_GRAPH_EMBEDDINGS_WALK_LENGTH,
            "KG_SEARCH_GRAPH_EMBEDDINGS_SEED": settings.KG_SEARCH_GRAPH_EMBEDDINGS_SEED,
            "KG_SEARCH_GRAPH_EMBEDDINGS_MIN_SIMILARITY": settings.KG_SEARCH_GRAPH_EMBEDDINGS_MIN_SIMILARITY,
            "KG_SEARCH_RELATION_MAX_EDGES": settings.KG_SEARCH_RELATION_MAX_EDGES,
            "KG_SEARCH_RELATION_MAX_NEIGHBORS": settings.KG_SEARCH_RELATION_MAX_NEIGHBORS,
        }
        items = []
        for item in response.items:
            baseline = item.baseline
            hardcases = [
                {
                    "kind": hardcase.kind,
                    "metrics": hardcase.run.metrics.model_dump(mode="json") if hardcase.run is not None else {},
                    "error": hardcase.run.error if hardcase.run is not None else None,
                }
                for hardcase in item.hardcases
            ]
            items.append(
                {
                    "case_id": str(item.case_id),
                    "question": item.question[:500],
                    "tags": list(item.tags),
                    "evidence_chunk_ids": list(item.evidence_chunk_ids),
                    "attribution": item.attribution.model_dump(mode="json"),
                    "baseline": {
                        "metrics": baseline.metrics.model_dump(mode="json"),
                        "error": baseline.error,
                        "returned_events": len(baseline.events),
                        "selected_entities": len(baseline.entities),
                        "clues_total": len(baseline.clues),
                    },
                    "hardcases": hardcases,
                }
            )
        run = KGSearchDiagnosticsRun(
            id=uuid4(),
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=payload.dataset_id,
            status="completed",
            params=params,
            summary=response.summary.model_dump(mode="json"),
            items=items,
            error_message=None,
        )
        db.add(run)
        db.flush()
        db.commit()
    except Exception as exc:  # noqa: BLE001 - diagnostic snapshots are optional
        logger.warning("Failed to persist KG diagnostics run snapshot: %s", str(exc)[:200], exc_info=True)
        db.rollback()
        return None
    return run.id


@router.get(
    "/kg/search/diagnostics/runs",
    response_model=KGSearchDiagnosticsRunList,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def list_kg_search_diagnostics_runs(
    params: Annotated[KGSearchDiagnosticsRunListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> KGSearchDiagnosticsRunList:
    if not settings.KG_ENABLED:
        raise HTTPException(status_code=503, detail=_DETAIL_KG_DISABLED)

    dataset_service.ensure_member(db, tenant_id, account_id)
    ds = dataset_service.get_dataset(db, tenant_id, params.dataset_id)
    dataset_service.assert_dataset_readable(db, ds, account_id)

    query = db.query(KGSearchDiagnosticsRun).filter(
        KGSearchDiagnosticsRun.tenant_id == tenant_id,
        KGSearchDiagnosticsRun.dataset_id == params.dataset_id,
    )
    total = query.count()
    items = query.order_by(KGSearchDiagnosticsRun.created_at.desc()).limit(params.limit).all()
    return KGSearchDiagnosticsRunList(total=total, items=items)


@router.get(
    "/kg/search/diagnostics/runs/{run_id}",
    response_model=KGSearchDiagnosticsRunDetail,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_kg_search_diagnostics_run(
    run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> KGSearchDiagnosticsRunDetail:
    if not settings.KG_ENABLED:
        raise HTTPException(status_code=503, detail=_DETAIL_KG_DISABLED)

    run = (
        db.query(KGSearchDiagnosticsRun)
        .filter(KGSearchDiagnosticsRun.id == run_id, KGSearchDiagnosticsRun.tenant_id == tenant_id)
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Diagnostics run not found")

    dataset_service.ensure_member(db, tenant_id, account_id)
    ds = dataset_service.get_dataset(db, tenant_id, run.dataset_id)
    dataset_service.assert_dataset_readable(db, ds, account_id)

    items = run.items if isinstance(run.items, list) else []
    return KGSearchDiagnosticsRunDetail(run=run, items=items)


@router.get("/kg/quality/report", response_model=dict[str, Any], responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_kg_quality_report(
    params: Annotated[KGQualityReportQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """
    Aggregate KG extraction quality report for a dataset (PII-minimal).

    This is intentionally best-effort and returns only aggregate statistics (counts/ratios).
    """
    if not settings.KG_ENABLED:
        raise HTTPException(status_code=503, detail=_DETAIL_KG_DISABLED)

    dataset_service.ensure_member(db, tenant_id, account_id)
    ds = dataset_service.get_dataset(db, tenant_id, params.dataset_id)
    dataset_service.assert_dataset_readable(db, ds, account_id)

    # Sample most recently updated documents in the dataset.
    rows = (
        db.query(DBDocument.id)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == params.dataset_id,
            DBDocument.publication_status == "published",
        )
        .order_by(DBDocument.updated_at.desc())
        .limit(params.document_limit)
        .all()
    )
    doc_ids = [document_id for (document_id,) in rows]
    allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, doc_ids)

    from app.rag.kg.quality import build_kg_quality_report  # noqa: WPS433

    report = build_kg_quality_report(
        db,
        tenant_id=tenant_id,
        document_ids=allowed_doc_ids,
        pipeline_hash=params.pipeline_hash,
    )
    # Include scope counts for UI diagnostics (no raw ids).
    scope = {
        "dataset_id": str(params.dataset_id),
        "documents_sampled": len(doc_ids),
        "documents_allowed": len(allowed_doc_ids),
    }
    report.setdefault("scope", scope)
    return report


@router.post(
    "/ragas/test-gen/from-conversations", response_model=TestGenResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def generate_test_cases_from_conversations(
    request: TestGenFromConversationsRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TestGenResponse:
    """Generate test questions from conversation history."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    try:
        questions = generate_questions_from_conversations(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            conversation_ids=request.conversation_ids,
            num_questions=request.num_questions,
            quality_threshold=request.quality_threshold,
        )

        generated_questions = [
            GeneratedQuestion(
                question=question.question,
                expected_answer=question.expected_answer,
                context=question.context,
                source_type="conversation",
                source_id=question.metadata.get("source_id", ""),
                metadata=question.metadata,
            )
            for question in questions
        ]

        saved_case_ids: list[UUID] = []
        if request.auto_save_as_cases:
            for question in questions:
                case = RagasRegressionCase(
                    tenant_id=tenant_id,
                    dataset_id=None,
                    document_ids=[],
                    question=question.question,
                    expected_answer=question.expected_answer,
                    tags=["auto_generated", "from_conversations"],
                    extra=question.metadata,
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

    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        return TestGenResponse(
            status="failed",
            generated_questions=[],
            saved_case_ids=[],
            error_message=str(exc),
        )
