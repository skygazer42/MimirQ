"""
Evaluation APIs (RAGAS).
"""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.models.chat import Conversation
from app.models.evaluation import (
    RagasEvaluationItem,
    RagasEvaluationRun,
    RagasRegressionCase,
    RagasRegressionItem,
    RagasRegressionRun,
)
from app.api.schemas.evaluation import (
    RagasItemSchema,
    RagasRunCreateRequest,
    RagasRunDetail,
    RagasRunList,
    RagasRunSchema,
)
from app.api.schemas.regression import (
    RagasRegressionCaseCreateRequest,
    RagasRegressionCaseList,
    RagasRegressionCaseOut,
    RagasRegressionItemSchema,
    RagasRegressionRunCreateRequest,
    RagasRegressionRunDetail,
    RagasRegressionRunList,
    RagasRegressionRunSchema,
)
from app.services.dataset_service import DatasetService
from app.rag.evaluation.ragas import run_conversation_ragas_evaluation, run_regression_ragas_evaluation

router = APIRouter()


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
    skip: int = 0,
    limit: int = 50,
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
    """创建一条回归用例（问题 + 可选知识库范围）。"""
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = RagasRegressionCase(
        tenant_id=tenant_id,
        dataset_id=request.dataset_id,
        document_ids=[str(x) for x in (request.document_ids or [])],
        question=request.question,
        expected_answer=request.expected_answer,
        tags=request.tags,
        extra=request.extra,
        created_by=account_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/ragas/regression/cases", response_model=RagasRegressionCaseList)
async def list_ragas_regression_cases(
    skip: int = 0,
    limit: int = 50,
    dataset_id: UUID | None = None,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """列出回归用例（tenant 隔离，可按 dataset_id 过滤）。"""
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


@router.post("/ragas/regression/runs", response_model=RagasRegressionRunSchema, status_code=201)
async def create_ragas_regression_run(
    request: RagasRegressionRunCreateRequest,
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """创建一次回归评测运行，并在后台执行。"""
    DatasetService.ensure_member(db, tenant_id, account_id)

    run = RagasRegressionRun(
        tenant_id=tenant_id,
        account_id=account_id,
        status="pending",
        metrics=request.metrics,
        params={
            "case_ids": [str(x) for x in (request.case_ids or [])],
            "dataset_id": str(request.dataset_id) if request.dataset_id else None,
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
    skip: int = 0,
    limit: int = 50,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """列出回归运行记录。"""
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


@router.get("/ragas/regression/runs/{run_id}", response_model=RagasRegressionRunDetail)
async def get_ragas_regression_run(
    run_id: UUID,
    include_items: bool = True,
    include_contexts: bool = False,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """获取某次回归运行详情（可选返回 items 与 contexts）。"""
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
