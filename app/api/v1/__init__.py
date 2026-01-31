"""
API v1 routes.
"""
from fastapi import APIRouter

from app.api.v1 import (
    audit,
    auth,
    chat,
    connectors,
    dataset_categories,
    dataset_precheck,
    dataset_tables,
    datasets,
    documents,
    evaluations,
    feedback,
    health,
    meta,
    observability,
    parsing,
    pipeline,
    prompt_templates,
    rag,
    ragviz,
    reports,
    settings,
    usage,
)
from app.rag.kg.api import routes as kg

router = APIRouter()

router.include_router(health.router, tags=["Health"])
router.include_router(meta.router, tags=["Meta"])
router.include_router(auth.router, prefix="/auth", tags=["Auth"])
router.include_router(documents.router, prefix="/documents", tags=["Documents"])
router.include_router(parsing.router, prefix="/parsing", tags=["Parsing Workspace"])
router.include_router(chat.router, prefix="/chat", tags=["Chat"])
router.include_router(datasets.router, prefix="/datasets", tags=["Datasets"])
router.include_router(dataset_precheck.router, prefix="/datasets", tags=["Datasets Precheck"])
router.include_router(dataset_tables.router, prefix="/datasets", tags=["Dataset Tables (TAG)"])
router.include_router(dataset_categories.router, prefix="/dataset-categories", tags=["Dataset Categories"])
router.include_router(kg.router, prefix="/kg", tags=["Knowledge Graph (KG)"])
router.include_router(settings.router, prefix="/settings", tags=["Settings"])
router.include_router(evaluations.router, prefix="/evaluations", tags=["Evaluations"])
router.include_router(prompt_templates.router, prefix="/prompt-templates", tags=["Prompt Templates"])
router.include_router(feedback.router, prefix="/feedback", tags=["Feedback"])
router.include_router(pipeline.router, prefix="/pipeline", tags=["Pipeline"])
router.include_router(connectors.router, prefix="/connectors", tags=["Connectors"])
router.include_router(rag.router, prefix="/rag", tags=["RAG"])
router.include_router(ragviz.router, prefix="/ragviz", tags=["RAG Visualization (RAGViz)"])
router.include_router(reports.router, prefix="/reports", tags=["Reports"])
router.include_router(observability.router, prefix="/observability", tags=["Observability"])
router.include_router(audit.router, prefix="/audit", tags=["Audit"])
router.include_router(usage.router, prefix="/usage", tags=["Usage"])
