"""
API v1 路由
"""
from fastapi import APIRouter
from app.api.v1 import chat, datasets, documents, sag, settings, evaluations, prompt_templates, feedback

router = APIRouter()

router.include_router(documents.router, prefix="/documents", tags=["Documents"])
router.include_router(chat.router, prefix="/chat", tags=["Chat"])
router.include_router(datasets.router, prefix="/datasets", tags=["Datasets"])
router.include_router(sag.router, prefix="/sag", tags=["SAG"])
router.include_router(settings.router, prefix="/settings", tags=["Settings"])
router.include_router(evaluations.router, prefix="/evaluations", tags=["Evaluations"])
router.include_router(prompt_templates.router, prefix="/prompt-templates", tags=["Prompt Templates"])
router.include_router(feedback.router, prefix="/feedback", tags=["Feedback"])
