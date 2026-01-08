"""
RAGAS evaluation API.

Provides evaluation endpoints for the RAG system, including task creation,
querying, and results.
"""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
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
    TestGenFromDocsRequest,
    TestGenFromConversationsRequest,
    TestGenResponse,
    GeneratedQuestion,
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
from app.rag.evaluation.test_generator import (
    generate_questions_from_documents,
    generate_questions_from_conversations,
)

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
    """Create a regression case (question + optional dataset scope)."""
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
