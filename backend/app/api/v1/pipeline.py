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
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.api.schemas.pipeline import (
    ParsePreviewResponse,
    ChunkPreviewRequest,
    ChunkPreviewResponse,
    CleanPreviewRequest,
    CleanPreviewResponse,
    CleanRulesResponse,
    RegexRuleModel,
    KeywordExtractRequest,
    KeywordExtractResponse,
    LLMCleanPreviewRequest,
    LLMCleanPreviewResponse,
)
from app.parsing.processors.parser_service import document_parser_service
from app.parsing.chunking.hierarchical import hierarchical_chunk_markdown
from app.parsing.utils.zip_processor import zip_image_processor
from app.api.dependencies.auth import get_current_account_id
from app.governance.cleaning import clean_markdown, RegexRule, build_repeated_line_signatures
from app.governance.rules import DEFAULT_MARKDOWN_RULES
from app.services.prompt_template_selector import resolve_prompt_template
from app.kg.utils import ConfigError
from app.rag.llm.factory import create_llm_client
from app.rag.llm.models import LLMMessage, LLMRole

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
    elif body.use_default_rules:
        rules = DEFAULT_MARKDOWN_RULES
    else:
        rules = []
    common_lines = (
        build_repeated_line_signatures(
            body.markdown or "",
            min_occurrences=body.common_lines_min_occurrences,
            max_line_length=body.unwrap_max_line_length,
        )
        if body.remove_common_lines
        else None
    )
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
        remove_common_lines=body.remove_common_lines,
        common_lines=common_lines,
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


@router.post("/extract-keywords", response_model=KeywordExtractResponse)
async def extract_keywords(body: KeywordExtractRequest):
    """
    提取关键词（用于治理/标注/分类等）。

    支持：
    - provider=auto（优先 HanLP，不可用则回退 jieba）
    - provider=jieba / jieba_tfidf（默认）
    - provider=jieba_textrank
    - provider=hanlp（可选依赖：需安装 `hanlp`，并可用 `HANLP_TOKENIZER_MODEL` 指定 tokenizer 模型）
    - provider=simple（轻量正则分词 + 词频）
    """
    from app.governance.keyword import (
        KeywordProviderUnavailable,
        UnsupportedKeywordProvider,
        extract_keywords as extract_keywords_fn,
    )

    provider = (body.provider or "jieba").lower()
    try:
        keywords = extract_keywords_fn(body.text or "", provider=provider, top_k=int(body.top_k))
        return KeywordExtractResponse(provider=provider, keywords=keywords)
    except KeywordProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except UnsupportedKeywordProvider as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Keyword extraction failed: {str(exc)}") from exc


@router.post("/llm-clean-preview", response_model=LLMCleanPreviewResponse)
async def llm_clean_preview(
    body: LLMCleanPreviewRequest,
    tenant_id=Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db=Depends(get_db),
):
    """
    使用大模型对 Markdown 做“数据治理”清洗预览（不入库）。

    说明：
    - 该接口会调用 LLM（需要正确配置 `LLM_API_KEY/LLM_API_BASE/LLM_MODEL`）。
    - 支持通过 PromptTemplate 指定清洗策略：`prompt_template_id` / `template_key` / `ab_experiment_key`。
    """
    _ = account_id

    markdown = body.markdown or ""
    if len(markdown) > int(body.max_chars):
        raise HTTPException(
            status_code=413,
            detail=f"Markdown too large for LLM preview (len={len(markdown)} > max_chars={body.max_chars}).",
        )

    system_prompt = (
        "你是一个“Markdown 数据治理清洗器”。\n"
        "目标：清理解析/复制导致的噪声与格式问题，但不要改变语义，不要编造或补充内容。\n"
        "要求：\n"
        "1) 保留标题/列表/表格/代码块结构；不要修改代码块内容。\n"
        "2) 移除明显页眉页脚/页码/目录引导/重复短行/控制字符/零宽字符。\n"
        "3) 规范化空白：合并多余空行、去除行尾空格，必要时合并“软换行”。\n"
        "4) 不要翻译、不做改写；仅做清洗/规范化。\n"
        "输出：严格返回 JSON，字段包含 markdown/changes/warnings。\n"
    )
    selected_prompt_template_id: str | None = None
    selected_prompt_template_key: str | None = None
    selected_prompt_ab_experiment_key: str | None = None
    selected_prompt_ab_variant: str | None = None

    if body.prompt_template_id or body.template_key or body.ab_experiment_key:
        chosen = resolve_prompt_template(
            db=db,
            tenant_id=tenant_id,
            prompt_template_id=body.prompt_template_id,
            template_key=body.template_key,
            ab_experiment_key=body.ab_experiment_key,
            ab_user_key=body.ab_user_key or account_id,
        )

        if not chosen:
            raise HTTPException(status_code=404, detail="PromptTemplate not found or inactive")

        system_prompt = str(chosen.content or "").strip() or system_prompt
        selected_prompt_template_id = str(chosen.id)
        selected_prompt_template_key = getattr(chosen, "template_key", None)
        selected_prompt_ab_experiment_key = getattr(chosen, "ab_experiment_key", None)
        selected_prompt_ab_variant = getattr(chosen, "ab_variant", None)
        chosen.usage_count += 1
        db.commit()

    model_config = {}
    if body.model:
        model_config["model"] = body.model
    if body.temperature is not None:
        model_config["temperature"] = body.temperature

    llm = await create_llm_client(scenario="governance_cleaning", model_config=model_config or None)
    resp = await llm.chat_with_schema(
        [
            LLMMessage(role=LLMRole.SYSTEM, content=system_prompt),
            LLMMessage(
                role=LLMRole.HUMAN,
                content=f"输入 Markdown：\n```markdown\n{markdown}\n```",
            ),
        ],
        response_schema={
            "markdown": "string",
            "changes": ["string"],
            "warnings": ["string"],
        },
        temperature=body.temperature,
        max_tokens=body.max_tokens,
    )

    warnings: list[str] = []
    cleaned = ""
    if isinstance(resp, dict):
        val = resp.get("markdown")
        if isinstance(val, str):
            cleaned = val
        else:
            raw = resp.get("raw")
            if isinstance(raw, str) and raw.strip():
                cleaned = raw.strip()
                warnings.append("LLM 未按 JSON schema 返回，已回退使用 raw 文本。")

        warn_val = resp.get("warnings")
        if isinstance(warn_val, list):
            warnings.extend([str(w).strip() for w in warn_val if str(w).strip()])

    if not cleaned.strip():
        cleaned = markdown
        warnings.append("LLM 返回为空，已回退原文。")

    return LLMCleanPreviewResponse(
        markdown=cleaned,
        changed=(cleaned != markdown),
        model_used=body.model or settings.LLM_MODEL,
        prompt_template_id=selected_prompt_template_id,
        template_key=selected_prompt_template_key,
        ab_experiment_key=selected_prompt_ab_experiment_key,
        ab_variant=selected_prompt_ab_variant,
        warnings=warnings,
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
