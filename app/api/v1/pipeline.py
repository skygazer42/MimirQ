"""
Lightweight parsing and hierarchical chunk preview APIs:
- /pipeline/parse-preview: route parsing by file type (MarkItDown/DeepDoc/MinerU/Basic), return Markdown + image refs
- /pipeline/chunk-preview: hierarchical Markdown chunking (paragraph/sentence) with highlight offsets
"""
from __future__ import annotations

from pathlib import Path
import shutil
import uuid
import zipfile
from uuid import UUID

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.orm import Session

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
    PipelineCapabilitiesResponse,
    ParserBackendInfo,
    ChunkStrategyInfo,
    ZipWithImagesResponse,
)
from app.parsing.processors.parser_service import document_parser_service
from app.parsing.backends import normalize_parser_backend
from app.parsing.factory import ParserFactory
from app.rag.chunking import hierarchical_chunk_markdown
from app.rag.chunking import chunker_factory
from app.parsing.utils.zip_processor import zip_image_processor
from app.api.dependencies.auth import get_current_account_id
from app.rag.preprocessing.cleaning import clean_markdown, RegexRule, build_repeated_line_signatures
from app.rag.preprocessing.rules import DEFAULT_MARKDOWN_RULES
from app.services.dataset_service import DatasetService
from app.services.prompt_resolver import resolve_prompt_template
from app.rag.core.errors import ConfigError
from app.rag.llm.factory import create_llm_client
from app.rag.llm.models import LLMMessage, LLMRole
from app.api.utils.upload import save_upload_file

router = APIRouter()

def _check_python_import(module_name: str, *, attr: str | None = None) -> tuple[bool, str | None]:
    try:
        mod = __import__(module_name, fromlist=[attr] if attr else [])
        if attr:
            getattr(mod, attr)
        return True, None
    except Exception as exc:
        return False, str(exc)[:200] or "import failed"


@router.get("/capabilities", response_model=PipelineCapabilitiesResponse)
async def get_pipeline_capabilities(
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Return available parsers and chunking strategies for the frontend.

    Note: only availability info is returned (no sensitive config like API keys).
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    default_parser_backend = normalize_parser_backend(getattr(settings, "DEFAULT_PARSER_BACKEND", "auto") or "auto") or "auto"
    default_chunk_strategy = (getattr(settings, "DEFAULT_CHUNK_STRATEGY", "langchain_recursive") or "langchain_recursive").strip().lower()

    def magicpdf_available() -> tuple[bool, str | None]:
        if not bool(getattr(settings, "MAGIC_PDF_ENABLED", False)):
            return False, "MAGIC_PDF_ENABLED=false"
        cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
        if not shutil.which(cli):
            return False, f"MagicPDF CLI not found: {cli}"
        return True, None

    pdf_backends: list[ParserBackendInfo] = []
    for name in sorted(ParserFactory.SUPPORTED_PDF_BACKENDS):
        b = (name or "").strip().lower()
        available = False
        notes: str | None = None

        if b == "auto":
            available = True
            notes = "Auto routes to the best enabled backend."
        elif b == "basic":
            available = True
        elif b == "mineru":
            available = bool(settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL))
            if not available:
                notes = "Set MINERU_ENABLED=true and configure MINERU_API_TOKEN or MINERU_LOCAL_SERVER_URL."
        elif b == "deepdoc":
            available = bool(getattr(settings, "DEEPDOC_ENABLED", False))
            if not available:
                notes = "Set DEEPDOC_ENABLED=true."
        elif b == "markitdown":
            if not bool(getattr(settings, "MARKITDOWN_ENABLED", False)):
                available = False
                notes = "Set MARKITDOWN_ENABLED=true."
            else:
                ok, err = _check_python_import("markitdown", attr="MarkItDown")
                available = ok
                if not ok:
                    notes = f"markitdown not installed: {err}"
        elif b == "docling":
            if not bool(getattr(settings, "DOCLING_ENABLED", False)):
                available = False
                notes = "Set DOCLING_ENABLED=true."
            else:
                ok, err = _check_python_import("docling.document_converter", attr="DocumentConverter")
                available = ok
                if not ok:
                    notes = f"docling not installed: {err}"
        elif b == "magicpdf":
            available, notes = magicpdf_available()
        else:  # pragma: no cover
            available = False
            notes = "Unknown backend"

        pdf_backends.append(ParserBackendInfo(name=b, available=bool(available), notes=notes))

    chunk_strategies: list[ChunkStrategyInfo] = []
    # Expose all strategies known to the backend (frontends may choose a subset).
    all_strats = set(chunker_factory.SUPPORTED_STRATEGIES.keys()) | set(chunker_factory.RAGFLOW_STRATEGIES)
    for name in sorted(all_strats):
        s = (name or "").strip().lower()
        available = True
        notes: str | None = None
        if s == "auto":
            available = True
            notes = "Auto-selects a chunker per document (markdown/json/plain text)."
        if s.startswith("llama_index"):
            if not bool(getattr(settings, "LLAMA_INDEX_ENABLED", False)):
                available = False
                notes = "Set LLAMA_INDEX_ENABLED=true."
            else:
                ok, err = _check_python_import("llama_index.core")
                available = ok
                if not ok:
                    notes = f"llama-index-core not installed: {err}"
        elif s in chunker_factory.RAGFLOW_STRATEGIES:
            available = True
            notes = "RAGFlow integrated pipeline (parse+chunk)."
        elif s == "markdown":
            available = True
            notes = "Alias of markdown_header."

        chunk_strategies.append(ChunkStrategyInfo(name=s, available=bool(available), notes=notes))

    return PipelineCapabilitiesResponse(
        default_parser_backend=default_parser_backend,
        default_chunk_strategy=default_chunk_strategy,
        pdf_backends=pdf_backends,
        chunk_strategies=chunk_strategies,
    )


@router.post("/parse-preview", response_model=ParsePreviewResponse)
async def parse_preview(
    file: UploadFile = File(...),
    parser_backend: str | None = Form(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Parse a file into a Markdown preview without persisting it; extract inline images to uploads/{tenant}/images.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}",
        )

    # Save to a temporary path.
    preview_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    temp_path = preview_dir / f"{uuid.uuid4()}{file_ext}"
    try:
        await save_upload_file(file, temp_path, max_bytes=settings.MAX_FILE_SIZE)

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
async def chunk_preview(
    body: ChunkPreviewRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Perform hierarchical chunking for Markdown text and return highlight offsets.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    chunks = hierarchical_chunk_markdown(body.markdown)
    return ChunkPreviewResponse(**chunks)


@router.post("/clean-preview", response_model=CleanPreviewResponse)
async def clean_preview(
    body: CleanPreviewRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Preview governance-style cleaning for Markdown (no persistence) to compare before/after.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
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
async def list_clean_rules(
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Return default governance rules for UI selection/editing.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    return CleanRulesResponse(
        rules=[RegexRuleModel(pattern=r.pattern, repl=r.repl, flags=r.flags) for r in DEFAULT_MARKDOWN_RULES]
    )


@router.post("/extract-keywords", response_model=KeywordExtractResponse)
async def extract_keywords(
    body: KeywordExtractRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Extract keywords (for governance/annotation/classification).

    Supported providers:
    - provider=auto (prefer HanLP, fallback to jieba)
    - provider=jieba / jieba_tfidf (default)
    - provider=jieba_textrank
    - provider=hanlp (optional dependency; requires `hanlp` and `HANLP_TOKENIZER_MODEL`)
    - provider=simple (lightweight regex tokenization + term frequency)
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    from app.rag.preprocessing.keyword import (
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
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Use an LLM to preview governance-style cleaning for Markdown (no persistence).

    Notes:
    - This endpoint calls an LLM (requires `LLM_API_KEY/LLM_API_BASE/LLM_MODEL`).
    - PromptTemplate can override the cleaning strategy via `prompt_template_id` / `template_key` / `ab_experiment_key`.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

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

    try:
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
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM request failed: {str(exc)[:200]}") from exc

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



@router.post("/upload-zip-with-images", response_model=ZipWithImagesResponse)
async def upload_zip_with_images(
    file: UploadFile = File(...),
    dataset_id: str = Form(...),
    document_id: str | None = Form(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Upload a ZIP that contains Markdown + images.

    Auto processing:
    1. Unzip the archive
    2. Upload all images to MinIO
    3. Replace Markdown image refs with MinIO URLs
    4. Return the rewritten Markdown and image list

    Args:
        file: ZIP file (Markdown + images)
        dataset_id: Dataset ID (used for MinIO paths)
        document_id: Optional document ID (defaults to file name)

    Returns:
        {
            "markdown": "rewritten Markdown",
            "images": [{"img_id": "...", "url": "...", "original_path": "..."}],
            "image_count": count
        }
    """
    if not settings.MINIO_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="MinIO 未启用，无法处理图片上传。请设置 MINIO_ENABLED=true"
        )
    
    # Validate file type.
    if not file.filename.endswith('.zip'):
        raise HTTPException(
            status_code=400,
            detail="仅支持 ZIP 格式文件"
        )

    try:
        dataset_uuid = UUID(str(dataset_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid dataset_id")
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_uuid)
    DatasetService.assert_dataset_writable(db, dataset, account_id)
    
    # Save to a temporary file.
    temp_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "temp_zip"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    temp_zip_path = temp_dir / f"{uuid.uuid4()}.zip"
    
    try:
        # Write to a temporary file (streamed, size-limited).
        await save_upload_file(file, temp_zip_path, max_bytes=settings.MAX_FILE_SIZE)
        
        # Process ZIP: extract images and upload to MinIO.
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
        
    except HTTPException:
        raise
    except (ValueError, zipfile.BadZipFile) as e:
        raise HTTPException(
            status_code=400,
            detail=f"ZIP 格式/内容不合法: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"ZIP 处理失败: {str(e)}"
        )
    finally:
        # Clean up temporary files.
        try:
            if temp_zip_path.exists():
                temp_zip_path.unlink()
        except Exception:
            pass
