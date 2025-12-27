"""
API v1 路由
"""
from fastapi import APIRouter, Depends
from app.api.v1 import (
    chat,
    datasets,
    documents,
    settings,
    evaluations,
    prompt_templates,
    feedback,
    pipeline,
)
from app.rag.kg.api import routes as kg

router = APIRouter()

router.include_router(documents.router, prefix="/documents", tags=["Documents"])
router.include_router(chat.router, prefix="/chat", tags=["Chat"])
router.include_router(datasets.router, prefix="/datasets", tags=["Datasets"])
router.include_router(kg.router, prefix="/kg", tags=["Knowledge Graph (KG)"])
router.include_router(
    kg.router,
    prefix="/sag",
    tags=["Knowledge Graph (KG) - alias (/sag)"],
    dependencies=[Depends(kg.deprecate_sag_alias)],
)
router.include_router(settings.router, prefix="/settings", tags=["Settings"])
router.include_router(evaluations.router, prefix="/evaluations", tags=["Evaluations"])
router.include_router(prompt_templates.router, prefix="/prompt-templates", tags=["Prompt Templates"])
router.include_router(feedback.router, prefix="/feedback", tags=["Feedback"])
router.include_router(pipeline.router, prefix="/pipeline", tags=["Pipeline"])
