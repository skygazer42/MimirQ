"""
RAGAS evaluation API.

Provides evaluation endpoints for the RAG system, including task creation,
querying, and results.
"""

import logging
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
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
)
from app.core.config import settings
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
from app.rag.evaluation.ragas import run_conversation_ragas_evaluation, run_regression_ragas_evaluation
from app.rag.evaluation.test_generator import (
    generate_questions_from_conversations,
    generate_questions_from_documents,
)
from app.services.dataset_service import DatasetService
from app.services.regression_case_bundle import export_case_bundle, plan_case_import
from app.services.regression_leaderboard import build_regression_run_leaderboard
from app.services.regression_run_diff import diff_regression_run_summaries
from app.services.regression_run_diff_html import render_regression_run_diff_html
from app.services.regression_run_scope import (
    DatasetMismatchError,
    MissingCasesError,
    validate_case_ids_belong_to_dataset,
)

router = APIRouter()
logger = logging.getLogger(__name__)


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
        except Exception:
            pass

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
            continue
        try:
            chunk_ids.append(UUID(str(src.get("chunk_id"))))
        except Exception:
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


@router.post("/ragas/runs", response_model=RagasRunSchema, status_code=201)
async def create_ragas_run(
    request: RagasRunCreateRequest,
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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


@router.get("/ragas/runs", response_model=RagasRunList)
async def list_ragas_runs(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    conversation_id: UUID | None = None,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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


@router.get("/ragas/runs/{run_id}", response_model=RagasRunDetail)
async def get_ragas_run(
    run_id: UUID,
    include_items: bool = True,
    include_contexts: bool = False,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Get a single run and (optionally) its items."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    run = (
        db.query(RagasEvaluationRun)
        .filter(RagasEvaluationRun.id == run_id, RagasEvaluationRun.tenant_id == tenant_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

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


@router.post("/ragas/regression/cases", response_model=RagasRegressionCaseOut, status_code=201)
async def create_ragas_regression_case(
    request: RagasRegressionCaseCreateRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Create a regression case (per-dataset; requires evidence sources)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    ds = DatasetService.get_dataset(db, tenant_id, request.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    reference_sources = _finalize_reference_sources(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=request.dataset_id,
        reference_sources=request.reference_sources,
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
        extra=request.extra,
        created_by=account_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/ragas/regression/cases/{case_id}", response_model=RagasRegressionCaseOut)
async def patch_ragas_regression_case(
    case_id: UUID,
    request: RagasRegressionCasePatchRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
        DatasetService.assert_dataset_readable(db, ds, account_id)

    fields = set(getattr(request, "model_fields_set", set()) or set())
    if "question" in fields and request.question is not None:
        row.question = request.question
    if "expected_answer" in fields:
        row.expected_answer = request.expected_answer
    if "tags" in fields and request.tags is not None:
        row.tags = request.tags
    if "extra" in fields and request.extra is not None:
        row.extra = request.extra
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
    return row


@router.get("/ragas/regression/cases", response_model=RagasRegressionCaseList)
async def list_ragas_regression_cases(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    dataset_id: UUID | None = None,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
    return {"total": total, "items": items}


@router.get("/ragas/regression/cases/export")
async def export_ragas_regression_cases(
    dataset_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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


@router.post("/ragas/regression/cases/import")
async def import_ragas_regression_cases(
    payload: RagasRegressionCaseImportRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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


@router.delete("/ragas/regression/cases/{case_id}", status_code=204)
async def delete_ragas_regression_case(
    case_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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

    db.delete(row)
    db.commit()
    return None


@router.post("/ragas/regression/runs", response_model=RagasRegressionRunSchema, status_code=201)
async def create_ragas_regression_run(
    request: RagasRegressionRunCreateRequest,
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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

    run = RagasRegressionRun(
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=request.dataset_id,
        status="pending",
        metrics=request.metrics,
        params={
            "case_ids": [str(x) for x in (request.case_ids or [])],
            "dataset_id": str(request.dataset_id),
            "skip_empty_contexts": request.skip_empty_contexts,
            "max_cases": request.max_cases,
            "rag_params": {
                "top_k": request.top_k,
                "score_threshold": request.score_threshold,
                "retrieval_mode": request.retrieval_mode,
                "alpha": request.alpha,
                "enable_weight_rerank": request.enable_weight_rerank,
                "vector_weight": request.vector_weight,
                "keyword_weight": request.keyword_weight,
                "mmr_lambda": request.mmr_lambda,
                "enable_reranker": request.enable_reranker,
                "reranker_provider": request.reranker_provider,
                "reranker_top_n": request.reranker_top_n,
                "prompt_template_id": str(request.prompt_template_id) if request.prompt_template_id else None,
                "prompt_template_key": request.prompt_template_key,
                "prompt_ab_experiment_key": request.prompt_ab_experiment_key,
            },
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
        case_ids=list(request.case_ids or []),
        dataset_id=request.dataset_id,
        metric_names=request.metrics,
        skip_empty_contexts=request.skip_empty_contexts,
        max_cases=request.max_cases,
        rag_params={
            "top_k": request.top_k,
            "score_threshold": request.score_threshold,
            "retrieval_mode": request.retrieval_mode,
            "alpha": request.alpha,
            "enable_weight_rerank": request.enable_weight_rerank,
            "vector_weight": request.vector_weight,
            "keyword_weight": request.keyword_weight,
            "mmr_lambda": request.mmr_lambda,
            "enable_reranker": request.enable_reranker,
            "reranker_provider": request.reranker_provider,
            "reranker_top_n": request.reranker_top_n,
            "prompt_template_id": request.prompt_template_id,
            "prompt_template_key": request.prompt_template_key,
            "prompt_ab_experiment_key": request.prompt_ab_experiment_key,
        },
    )

    return run


@router.get("/ragas/regression/runs", response_model=RagasRegressionRunList)
async def list_ragas_regression_runs(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """List regression runs."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(RagasRegressionRun).filter(RagasRegressionRun.tenant_id == tenant_id)
    total = query.count()
    runs = (
        query.order_by(RagasRegressionRun.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {"total": total, "items": runs}


@router.get("/ragas/regression/runs/leaderboard", response_model=RagasRegressionRunLeaderboardResponse)
async def get_ragas_regression_run_leaderboard(
    dataset_id: UUID = Query(..., description="Dataset to scope runs (required)"),
    metric_key: str = Query(default="retrieval_mrr", description="Metric key from run.summary"),
    limit: int = Query(default=50, ge=1, le=200),
    include_incomplete: bool = Query(default=False, description="Include pending/failed runs (default: false)"),
    max_candidates: int = Query(default=500, ge=1, le=5000, description="Max runs to consider (recency window)"),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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


@router.get("/ragas/regression/runs/{run_id}", response_model=RagasRegressionRunDetail)
async def get_ragas_regression_run(
    run_id: UUID,
    include_items: bool = True,
    include_contexts: bool = False,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Get a regression run detail (optional items and contexts)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    run = (
        db.query(RagasRegressionRun)
        .filter(RagasRegressionRun.id == run_id, RagasRegressionRun.tenant_id == tenant_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

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


@router.get("/ragas/regression/runs/{run_id}/diff", response_model=RagasRegressionRunDiffResponse)
async def diff_ragas_regression_runs(
    run_id: UUID,
    base_run_id: UUID = Query(..., description="Base run id to compare against"),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
    diff["base_params"] = dict(getattr(base, "params", None) or {})
    diff["target_params"] = dict(getattr(target, "params", None) or {})
    return RagasRegressionRunDiffResponse(**diff)


@router.get("/ragas/regression/runs/{run_id}/diff/export-html")
async def export_ragas_regression_run_diff_html(
    run_id: UUID,
    base_run_id: UUID = Query(..., description="Base run id to compare against"),
    redact: bool = Query(default=True, description="Whether to redact run ids for sharing"),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/ragas/test-gen/from-documents", response_model=TestGenResponse)
async def generate_test_cases_from_documents(
    request: TestGenFromDocsRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
        )

        # Convert to response format.
        generated_questions = [
            GeneratedQuestion(
                question=q.question,
                expected_answer=q.expected_answer,
                context=q.context,
                source_type="document",
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
                    dataset_id=request.dataset_id,
                    document_ids=[q.metadata.get("source_id")] if q.metadata.get("source_id") else [],
                    question=q.question,
                    expected_answer=q.expected_answer,
                    tags=["auto_generated", "from_documents"],
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


@router.post("/kg/search/diagnostics", response_model=KGSearchDiagnosticsResponse)
async def run_kg_search_diagnostics(
    payload: KGSearchDiagnosticsRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Run a Dynamic OneEval-style diagnostics pass for KG search.

    Seed source: RAGAS regression cases (human-verified evidence pointers).
    """
    if not bool(getattr(settings, "KG_ENABLED", False)):
        raise HTTPException(status_code=503, detail="KG is disabled (KG_ENABLED=false)")

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
            for item in list(getattr(resp, "items", []) or []):
                baseline = getattr(item, "baseline", None)
                baseline_metrics_obj = getattr(baseline, "metrics", None)
                baseline_metrics = (
                    baseline_metrics_obj.model_dump(mode="json") if hasattr(baseline_metrics_obj, "model_dump") else {}
                )

                hardcases_compact: list[dict[str, Any]] = []
                for hc in list(getattr(item, "hardcases", []) or []):
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
            except Exception:
                # Best-effort: if response is immutable for any reason, skip run_id propagation.
                pass
        except Exception as exc:
            logger.warning("Failed to persist KG diagnostics run snapshot: %s", str(exc)[:200])
            try:
                db.rollback()
            except Exception:
                pass

    return resp


@router.get("/kg/search/diagnostics/runs", response_model=KGSearchDiagnosticsRunList)
async def list_kg_search_diagnostics_runs(
    dataset_id: UUID = Query(..., description="Dataset ID (required)"),
    limit: int = Query(20, ge=1, le=200, description="Max runs to return (default: 20)"),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    if not bool(getattr(settings, "KG_ENABLED", False)):
        raise HTTPException(status_code=503, detail="KG is disabled (KG_ENABLED=false)")

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


@router.get("/kg/search/diagnostics/runs/{run_id}", response_model=KGSearchDiagnosticsRunDetail)
async def get_kg_search_diagnostics_run(
    run_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    if not bool(getattr(settings, "KG_ENABLED", False)):
        raise HTTPException(status_code=503, detail="KG is disabled (KG_ENABLED=false)")

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


@router.post("/ragas/test-gen/from-conversations", response_model=TestGenResponse)
async def generate_test_cases_from_conversations(
    request: TestGenFromConversationsRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
