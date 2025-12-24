"""
轻量解析与分层切块预览 API：
- /pipeline/parse-preview: 按文件类型分流解析（MarkItDown/DeepDoc/MinerU/Basic），返回 Markdown 与图片引用
- /pipeline/chunk-preview: 对 Markdown 做分层切块（段落/句子），返回可高亮的起止位置
"""
from __future__ import annotations

from pathlib import Path
import uuid

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends

from app.core.config import settings
from app.dependencies.tenant import get_tenant_id
from app.schemas.pipeline import (
    ParsePreviewResponse,
    ChunkPreviewRequest,
    ChunkPreviewResponse,
)
from app.services.document_parser_service import document_parser_service
from app.services.hierarchical_chunking import hierarchical_chunk_markdown

router = APIRouter()


@router.post("/parse-preview", response_model=ParsePreviewResponse)
async def parse_preview(
    file: UploadFile = File(...),
    parser_backend: str | None = Form(default=None),
    tenant_id=Depends(get_tenant_id),
):
    """
    解析文件为 Markdown 预览，不入库；提取内嵌图片到 uploads/{tenant}/images。
    """
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}",
        )

    # 保存到临时路径
    preview_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    temp_path = preview_dir / f"{uuid.uuid4()}{file_ext}"
    try:
        content = await file.read()
        temp_path.write_bytes(content)

        result = document_parser_service.parse_for_preview(
            file_path=temp_path,
            tenant_id=tenant_id,
            parser_backend=parser_backend,
        )
        return result
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception:
            pass


@router.post("/chunk-preview", response_model=ChunkPreviewResponse)
async def chunk_preview(body: ChunkPreviewRequest):
    """
    对 Markdown 文本进行分层切块（段落/句子），返回可用于高亮的起止位置。
    """
    chunks = hierarchical_chunk_markdown(body.markdown)
    return ChunkPreviewResponse(**chunks)

