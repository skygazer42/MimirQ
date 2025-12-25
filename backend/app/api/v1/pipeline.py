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
    CleanPreviewRequest,
    CleanPreviewResponse,
    CleanRulesResponse,
    RegexRuleModel,
)
from app.parsing.processors.parser_service import document_parser_service
from app.parsing.chunking.hierarchical import hierarchical_chunk_markdown
from app.parsing.utils.zip_processor import zip_image_processor
from app.dependencies.auth import get_current_account_id
from app.governance.cleaning import clean_markdown, RegexRule
from app.governance.rules import DEFAULT_MARKDOWN_RULES

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


@router.post("/clean-preview", response_model=CleanPreviewResponse)
async def clean_preview(body: CleanPreviewRequest):
    """
    对 Markdown 做“数据治理”清洗预览（不入库），用于人工调整前/后对比。
    """
    if body.rules:
        rules = [RegexRule(pattern=r.pattern, repl=r.repl, flags=r.flags) for r in body.rules]
    else:
        rules = DEFAULT_MARKDOWN_RULES
    result = clean_markdown(
        body.markdown,
        rules=rules,
        normalize_line_endings=body.normalize_line_endings,
        trim_trailing_spaces=body.trim_trailing_spaces,
        collapse_blank_lines=body.collapse_blank_lines,
        remove_control_chars=body.remove_control_chars,
        remove_toc_lines=body.remove_toc_lines,
        remove_noise_lines=body.remove_noise_lines,
        unwrap_lines=body.unwrap_lines,
        unwrap_max_line_length=body.unwrap_max_line_length,
        noise_min_chars=body.noise_min_chars,
        noise_ratio_threshold=body.noise_ratio_threshold,
    )
    return CleanPreviewResponse(
        markdown=result.markdown,
        applied_rules=result.applied_rules,
        changed=result.changed,
    )


@router.get("/clean-rules", response_model=CleanRulesResponse)
async def list_clean_rules():
    """
    返回默认“数据治理”规则列表，供前端做默认勾选/编辑。
    """
    return CleanRulesResponse(
        rules=[RegexRuleModel(pattern=r.pattern, repl=r.repl, flags=r.flags) for r in DEFAULT_MARKDOWN_RULES]
    )



@router.post("/upload-zip-with-images")
async def upload_zip_with_images(
    file: UploadFile = File(...),
    dataset_id: str = Form(...),
    document_id: str | None = Form(default=None),
    tenant_id=Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
):
    """
    上传包含 Markdown + images 的 ZIP 文件。
    
    自动处理：
    1. 解压 ZIP
    2. 提取所有图片并上传到 MinIO
    3. 替换 Markdown 中的图片引用为 MinIO URL
    4. 返回处理后的 Markdown 和图片列表
    
    Args:
        file: ZIP 文件（包含 Markdown 和图片）
        dataset_id: 知识库 ID（用于 MinIO 路径）
        document_id: 文档 ID（可选，默认使用文件名）
    
    Returns:
        {
            "markdown": "处理后的 Markdown",
            "images": [{"img_id": "...", "url": "...", "original_path": "..."}],
            "image_count": 数量
        }
    """
    if not settings.MINIO_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="MinIO 未启用，无法处理图片上传。请设置 MINIO_ENABLED=true"
        )
    
    # 检查文件类型
    if not file.filename.endswith('.zip'):
        raise HTTPException(
            status_code=400,
            detail="仅支持 ZIP 格式文件"
        )
    
    # 保存到临时文件
    temp_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "temp_zip"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    temp_zip_path = temp_dir / f"{uuid.uuid4()}.zip"
    
    try:
        # 写入临时文件
        content = await file.read()
        temp_zip_path.write_bytes(content)
        
        # 处理 ZIP：提取图片并上传到 MinIO
        doc_id = document_id or file.filename.rsplit('.', 1)[0]
        result = zip_image_processor.process_zip_with_images(
            zip_path=temp_zip_path,
            tenant_id=str(tenant_id),
            dataset_id=dataset_id,
            document_id=doc_id
        )
        
        return {
            "markdown": result["markdown"],
            "images": result["images"],
            "image_count": result["image_count"],
            "dataset_id": dataset_id,
            "document_id": doc_id,
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"ZIP 处理失败: {str(e)}"
        )
    finally:
        # 清理临时文件
        try:
            if temp_zip_path.exists():
                temp_zip_path.unlink()
        except Exception:
            pass
