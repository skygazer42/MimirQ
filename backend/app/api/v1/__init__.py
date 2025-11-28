"""
API v1 路由
"""
from fastapi import APIRouter
from app.api.v1 import documents, chat

router = APIRouter()

router.include_router(documents.router, prefix="/documents", tags=["Documents"])
router.include_router(chat.router, prefix="/chat", tags=["Chat"])
