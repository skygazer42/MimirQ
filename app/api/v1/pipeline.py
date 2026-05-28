"""
Lightweight parsing and hierarchical chunk preview APIs:
- /pipeline/parse-preview: route parsing by file type (auto/Pandoc/MarkItDown/DeepDoc/MinerU/...), return Markdown + image refs
- /pipeline/chunk-preview: hierarchical Markdown chunking (paragraph/sentence) with highlight offsets
"""
import asyncio
import json
import re
import shutil
import uuid
import zipfile
from difflib import SequenceMatcher, unified_diff
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.governance_profile import (
    BuiltinProcessingScriptListResponse,
    BuiltinProcessingScriptOut,
    GovernanceProfileCreate,
    GovernanceProfileImportResponse,
    GovernanceProfileListResponse,
    GovernanceProfileOut,
    GovernanceProfilePayload,
    GovernanceProfileResolvedResponse,
    GovernanceProfileSummary,
    GovernanceProfileUpdate,
)
from app.api.schemas.ingestion_policy import IngestionPolicy, IngestionRule
from app.api.schemas.pipeline import (
    AutoAnnotationItem,
    AutoAnnotationRequest,
    AutoAnnotationResponse,
    AutoDocumentTag,
    ChunkStrategyInfo,
    CleanPreviewRequest,
    CleanPreviewResponse,
    CleanRegexRuleModel,
    CleanRulesResponse,
    GovernanceAnalyzeRequest,
    GovernanceAnalyzeResponse,
    GovernanceCommonLineCandidate,
    GovernanceCommonLinesLearnRequest,
    GovernanceCommonLinesLearnResponse,
    GovernanceIssue,
    IngestionPreviewResponse,
    KeywordExtractRequest,
    KeywordExtractResponse,
    LLMCleanPreviewRequest,
    LLMCleanPreviewResponse,
    ParsePreviewResponse,
    ParserBackendInfo,
    PipelineCapabilitiesResponse,
    PipelineChunkPreviewRequest,
    PipelineChunkPreviewResponse,
    ZipWithImagesResponse,
)
from app.api.utils.upload import save_upload_file
from app.core.config import settings
from app.core.database import get_db
from app.core.optional_deps import check_dependency
from app.core.regex_runtime import RegexSubstitutionTimeoutError
from app.core.regex_safety import RegexRulesValidationError, validate_regex_rules
from app.models.document import Document as DBDocument
from app.models.document import DocumentParsedContent
from app.models.governance_profile import GovernanceProfile as DBGovernanceProfile
from app.parsing.backends import normalize_parser_backend
from app.parsing.factory import ParserFactory
from app.parsing.parsers.magic_pdf_parser import magicpdf_service_configured, resolve_magicpdf_models_dir
from app.parsing.preprocess.file_preprocessor import preprocess_file
from app.parsing.subprocess_runner import SubprocessCancelled, SubprocessWorkerError, run_subprocess_worker
from app.parsing.utils.cli import resolve_cli_command
from app.parsing.utils.zip_processor import zip_image_processor
from app.rag.chunking import chunker_factory, hierarchical_chunk_markdown
from app.rag.chunking.recommendations import decorate_chunk_strategy_note
from app.rag.core.errors import ConfigError
from app.rag.core.logging import get_logger
from app.rag.llm.factory import create_llm_client
from app.rag.llm.models import LLMMessage, LLMRole
from app.rag.preprocessing.boilerplate import remove_markdown_boilerplate
from app.rag.preprocessing.cleaning import (
    RegexRule,
    build_repeated_line_signatures,
    clean_markdown,
    learn_common_line_candidates,
)
from app.rag.preprocessing.code_blocks import strip_fenced_code_line_numbers
from app.rag.preprocessing.cpu_tagger import extract_cpu_tags
from app.rag.preprocessing.diagnostics import analyze_governance
from app.rag.preprocessing.frontmatter import extract_markdown_frontmatter, extract_markdown_title
from app.rag.preprocessing.html_xpath import extract_text_from_html
from app.rag.preprocessing.images import strip_images
from app.rag.preprocessing.keyword import extract_keywords as extract_keywords_preview
from app.rag.preprocessing.language import detect_language
from app.rag.preprocessing.llm_tagger import extract_llm_tags
from app.rag.preprocessing.paragraph_dedup import drop_duplicate_paragraphs
from app.rag.preprocessing.pii_anonymizer import anonymize_pii, find_pii_matches
from app.rag.preprocessing.quality_filters import drop_if_low_density, drop_if_outline_only
from app.rag.preprocessing.references import trim_references_section
from app.rag.preprocessing.rule_packs import GOVERNANCE_RULE_PACKS
from app.rag.preprocessing.rules import DEFAULT_MARKDOWN_RULES
from app.rag.preprocessing.secrets import find_secret_matches, redact_secrets
from app.rag.preprocessing.tables import normalize_markdown_tables
from app.rag.preprocessing.urls import normalize_urls
from app.services.dataset_service import DatasetService
from app.services.document_access import get_allowed_document_id_sets
from app.services.governance_processing_scripts import list_builtin_processing_scripts
from app.services.governance_profiles import (
    builtin_profile_to_out,
    get_builtin_governance_profiles,
    validate_and_normalize_payload,
    validate_profile_key,
)
from app.services.governance_profiles_resolver import resolve_governance_profile_ref_effective
from app.services.ingestion_policy import export_policy_json, match_ingestion_rule, parse_ingestion_policy_from_metadata
from app.services.pipeline_config import resolve_pipeline_effective
from app.services.prompt_resolver import resolve_prompt_template
from app.types.pipeline import PipelineOptions

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)

_BUILTIN_GOVERNANCE_PROFILES = get_builtin_governance_profiles()
_BUILTIN_GOVERNANCE_BY_KEY = {p.key: p for p in _BUILTIN_GOVERNANCE_PROFILES}
_BUILTIN_PROCESSING_SCRIPTS = list_builtin_processing_scripts()
GOVERNANCE_PROFILE_NOT_FOUND_DETAIL = "Governance profile not found"
REDACTED_MASK = "[REDACTED]"
SECRET_MASK = "[SECRET]"
_AUTO_TAGGER_LLM_TIMEOUT_S = 3.0

_ZH_ENTITY_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9（）()·]{2,40}"
    r"(?:股份有限公司|有限公司|集团|银行|大学|学院|医院|政府|委员会|部门|平台|系统|项目)"
)
_EN_ENTITY_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*){1,4}\s+"
    r"(?:Inc|LLC|Ltd|Corp|Corporation|University|Bank|Group)\b"
)
_ENTITY_LEFT_TRIM_MARKERS = ("由", "为", "是", "属", "在", "向", "给", "和", "与", "及", "：", ":", "，", ",")
_FOCUS_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]{6,180}[。！？!?；;]?")
_FOCUS_RULES: tuple[tuple[str, str, re.Pattern[str], float], ...] = (
    (
        "动作项",
        "custom",
        re.compile(r"[^。！？!?；;\n]{0,50}(?:建议|需要|应当|必须|后续|下一步|待|TODO|完善|优化|修复)[^。！？!?；;\n]{2,100}[。！？!?；;]?"),
        0.82,
    ),
    (
        "风险线索",
        "custom",
        re.compile(r"[^。！？!?；;\n]{0,50}(?:风险|异常|失败|阻断|漏洞|敏感|脱敏|隔离|告警|质量问题)[^。！？!?；;\n]{2,100}[。！？!?；;]?"),
        0.8,
    ),
    (
        "文档重点",
        "custom",
        re.compile(r"[^。！？!?；;\n]{0,50}(?:核心能力|重点|结论|目标|范围|方案|流程|策略|指标|知识库|数据治理|检索|入库)[^。！？!?；;\n]{2,120}[。！？!?；;]?"),
        0.76,
    ),
)
_FOCUS_KEYWORD_STOPWORDS = {
    "联系人",
    "手机号",
    "电话",
    "邮箱",
    "email",
    "example",
    "com",
    "www",
    "http",
    "https",
    "项目",
    "本文",
}
_DOMAIN_FOCUS_TERMS = (
    "知识库检索",
    "入库质量分析",
    "入库流程",
    "数据治理",
    "治理流程",
    "检索策略",
    "文档解析",
    "结构化提取",
    "元解析",
    "全文解析",
    "切块策略",
    "RAG",
    "知识库",
    "入库",
    "检索",
    "治理",
)
_ACTION_MARKER_RE = re.compile(r"(建议|需要|应当|必须|后续|下一步|待|TODO|完善|优化|修复)")


def _trim_entity_span(raw: str) -> tuple[str, int]:
    """
    Trim common left-context words from regex entity candidates.

    Lightweight entity extraction intentionally stays dependency-free. This
    post-trim keeps matches like "项目由星海智能有限公司" usable without pretending
    to be a full NER model.
    """
    text = str(raw or "").strip(" \t\r\n，,。.;；:：")
    offset = raw.find(text) if text else 0
    if not text:
        return "", max(0, offset)

    best_idx = -1
    for marker in _ENTITY_LEFT_TRIM_MARKERS:
        idx = text.rfind(marker)
        if idx > best_idx and idx < len(text) - 2:
            best_idx = idx
    if best_idx >= 0:
        offset += best_idx + 1
        text = text[best_idx + 1 :].strip(" \t\r\n，,。.;；:：")
    return text, max(0, offset)


def _make_auto_annotation(
    *,
    source_text: str,
    start: int,
    end: int,
    annotation_type: str,
    label: str,
    confidence: float,
    source: str,
) -> AutoAnnotationItem | None:
    if start < 0 or end <= start or end > len(source_text):
        return None
    text = source_text[start:end]
    if not text.strip():
        return None
    return AutoAnnotationItem(
        text=text,
        type=annotation_type,  # type: ignore[arg-type]
        label=str(label or annotation_type),
        start=int(start),
        end=int(end),
        confidence=float(confidence),
        source=str(source or "keyword"),
    )


def _annotation_overlaps(item: AutoAnnotationItem, other: AutoAnnotationItem) -> bool:
    return int(item.start) < int(other.end) and int(item.end) > int(other.start)


def _trim_match_span(source_text: str, start: int, end: int) -> tuple[int, int]:
    left = int(start)
    right = int(end)
    while left < right and source_text[left] in " \t\r\n，,。.;；:：":
        left += 1
    while right > left and source_text[right - 1] in " \t\r\n，,。.;；:：":
        right -= 1
    return left, right


def _find_keyword_offsets(text: str, keyword: str, *, limit: int = 2) -> list[tuple[int, int]]:
    kw = str(keyword or "").strip()
    if len(kw) < 2:
        return []

    flags = re.IGNORECASE if kw.isascii() else 0
    out: list[tuple[int, int]] = []
    for match in re.finditer(re.escape(kw), text, flags=flags):
        start, end = int(match.start()), int(match.end())
        if end <= start:
            continue
        out.append((start, end))
        if len(out) >= max(1, int(limit or 1)):
            break
    return out


def _is_focus_keyword(text: str) -> bool:
    token = str(text or "").strip()
    if len(token) < 2:
        return False
    if token.casefold() in _FOCUS_KEYWORD_STOPWORDS:
        return False
    if re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", token):
        return False
    if re.fullmatch(r"\d[\d\s().-]{6,}\d", token):
        return False
    if token.isascii() and len(token) < 4:
        return False
    if not token.isascii() and len(token) > 12:
        return False
    if token.startswith("项目由") or token.startswith("本文"):
        return False
    return True


def _dedupe_auto_annotations(items: list[AutoAnnotationItem], *, max_items: int) -> list[AutoAnnotationItem]:
    priority = {"sensitive": 0, "entity": 1, "keyword": 2, "custom": 3}
    sorted_items = sorted(
        items,
        key=lambda item: (
            int(item.start),
            priority.get(str(item.type), 9),
            -float(item.confidence),
            int(item.end),
            str(item.text),
        ),
    )

    seen: set[tuple[str, int, int, str]] = set()
    out: list[AutoAnnotationItem] = []
    for item in sorted_items:
        key = (str(item.type), int(item.start), int(item.end), str(item.text))
        if key in seen:
            continue
        if str(item.type) == "keyword" and any(
            _annotation_overlaps(item, kept) and str(kept.type) in {"sensitive", "entity"} for kept in out
        ):
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= max_items:
            break
    return out


def _normalize_auto_annotation_providers(body: AutoAnnotationRequest) -> set[str]:
    if body.providers is None:
        providers: set[str] = set()
        if str(body.mode or "document_focus").strip().lower() == "document_focus":
            providers.add("cpu")
        if body.enable_llm or body.enable_llm_topics:
            providers.add("llm")
        if body.enable_keywords:
            providers.add("keyword")
        if body.enable_entities:
            providers.add("regex")
        if body.enable_sensitive:
            providers.update({"pii", "secret"})
        return providers

    providers = set()
    for raw_provider in body.providers:
        provider = str(raw_provider or "").strip().lower()
        if not provider:
            continue
        if provider in {"entity", "regex_entity"}:
            providers.add("regex")
        elif provider == "sensitive":
            providers.update({"pii", "secret"})
        else:
            providers.add(provider)
    return providers


def _append_provider_used(providers_used: list[str], provider: str) -> None:
    if provider not in providers_used:
        providers_used.append(provider)


def _make_auto_document_tag(
    *,
    tag_type: str,
    value: str,
    label: str,
    confidence: float,
    source: str,
) -> AutoDocumentTag | None:
    value_s = str(value or "").strip()
    if not value_s:
        return None
    allowed = {"topic", "category", "domain", "industry", "doc_type", "sensitivity", "quality", "keyword"}
    if tag_type not in allowed:
        return None
    return AutoDocumentTag(
        type=tag_type,  # type: ignore[arg-type]
        value=value_s,
        label=str(label or tag_type),
        confidence=min(1.0, max(0.0, float(confidence))),
        source=str(source or "llm"),
    )


def _dedupe_auto_document_tags(items: list[AutoDocumentTag], *, max_items: int) -> list[AutoDocumentTag]:
    seen: set[tuple[str, str]] = set()
    out: list[AutoDocumentTag] = []
    for item in items:
        key = (str(item.type), str(item.value).casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= max_items:
            break
    return out


def _derive_document_tags_from_annotations(items: list[AutoAnnotationItem], *, max_items: int) -> list[AutoDocumentTag]:
    out: list[AutoDocumentTag] = []
    for item in items:
        tag_type = None
        label = ""
        if str(item.type) == "keyword" and str(item.label) == "主题关键词":
            tag_type = "topic"
            label = "主题"
        elif str(item.type) == "custom" and str(item.label) in {"动作项", "风险线索"}:
            tag_type = "quality"
            label = "质量线索"
        if tag_type is None:
            continue
        tag = _make_auto_document_tag(
            tag_type=tag_type,
            value=item.text,
            label=label,
            confidence=min(0.9, max(0.0, float(item.confidence))),
            source=item.source,
        )
        if tag is not None:
            out.append(tag)
        if len(out) >= max_items:
            break
    return _dedupe_auto_document_tags(out, max_items=max_items)


def _collect_keyword_annotations(
    text: str,
    *,
    provider: str,
    top_k: int,
    max_items: int,
) -> tuple[str, list[AutoAnnotationItem]]:
    from app.rag.preprocessing.keyword import (
        extract_keywords as extract_keywords_fn,
    )

    provider_key = (provider or "simple").strip().lower() or "simple"
    if provider_key == "auto":
        provider_key = "simple"
    try:
        keywords = extract_keywords_fn(text, provider=provider_key, top_k=int(top_k))
    except Exception:
        provider_key = "simple"
        keywords = extract_keywords_fn(text, provider=provider_key, top_k=int(top_k))

    out: list[AutoAnnotationItem] = []
    for keyword in keywords or []:
        for start, end in _find_keyword_offsets(text, str(keyword), limit=2):
            item = _make_auto_annotation(
                source_text=text,
                start=start,
                end=end,
                annotation_type="keyword",
                label="keyword",
                confidence=0.68,
                source="keyword",
            )
            if item is not None:
                out.append(item)
            if len(out) >= max_items:
                return provider_key, out
    return provider_key, out


def _collect_focus_keyword_annotations(
    text: str,
    *,
    provider: str,
    top_k: int,
    max_items: int,
    blocked: list[AutoAnnotationItem],
) -> tuple[str, list[AutoAnnotationItem]]:
    provider_key, raw_items = _collect_keyword_annotations(
        text,
        provider=provider,
        top_k=top_k,
        max_items=max_items * 3,
    )
    out: list[AutoAnnotationItem] = []
    for item in raw_items:
        if not _is_focus_keyword(item.text):
            continue
        if any(_annotation_overlaps(item, blocked_item) for blocked_item in blocked):
            continue
        out.append(
            AutoAnnotationItem(
                text=item.text,
                type="keyword",
                label="主题关键词",
                start=item.start,
                end=item.end,
                confidence=max(float(item.confidence), 0.72),
                source="keyword",
            )
        )
        if len(out) >= max_items:
            break
    return provider_key, out


def _collect_domain_focus_terms(text: str, *, max_items: int, blocked: list[AutoAnnotationItem]) -> list[AutoAnnotationItem]:
    out: list[AutoAnnotationItem] = []
    for term in _DOMAIN_FOCUS_TERMS:
        for start, end in _find_keyword_offsets(text, term, limit=1):
            item = _make_auto_annotation(
                source_text=text,
                start=start,
                end=end,
                annotation_type="keyword",
                label="主题关键词",
                confidence=0.78,
                source="keyword",
            )
            if item is None or any(_annotation_overlaps(item, blocked_item) for blocked_item in blocked + out):
                continue
            out.append(item)
            break
        if len(out) >= max_items:
            break
    return out


def _trim_focus_rule_span(text: str, label: str, start: int, end: int) -> tuple[int, int]:
    if label != "动作项":
        return _trim_match_span(text, start, end)
    snippet = text[start:end]
    marker_start = None
    for match in _ACTION_MARKER_RE.finditer(snippet):
        marker_start = int(match.start())
    if marker_start is not None:
        start += marker_start
    return _trim_match_span(text, start, end)


def _collect_entity_annotations(text: str, *, max_items: int) -> list[AutoAnnotationItem]:
    out: list[AutoAnnotationItem] = []
    for pattern in (_ZH_ENTITY_RE, _EN_ENTITY_RE):
        for match in pattern.finditer(text):
            raw = match.group(0) or ""
            trimmed, offset = _trim_entity_span(raw)
            if len(trimmed) < 2:
                continue
            start = int(match.start()) + int(offset)
            end = start + len(trimmed)
            item = _make_auto_annotation(
                source_text=text,
                start=start,
                end=end,
                annotation_type="entity",
                label="entity",
                confidence=0.72,
                source="regex_entity",
            )
            if item is not None:
                out.append(item)
            if len(out) >= max_items:
                return out
    return out


async def _collect_gliner_entity_annotations(text: str, *, max_items: int) -> list[AutoAnnotationItem]:
    try:
        from app.rag.kg.extraction.gliner_extractor import GLiNERExtractor
    except Exception:
        return []

    try:
        if not GLiNERExtractor.is_available():
            return []
        extractor = GLiNERExtractor()
        entities = await extractor.extract_entities(
            text=text,
            entity_types=["person", "organization", "location", "product", "policy", "time", "money"],
        )
    except Exception:
        return []

    out: list[AutoAnnotationItem] = []
    for entity in entities:
        quote = str(entity.get("evidence_quote") or entity.get("name") or "").strip()
        if not quote:
            continue
        label = str(entity.get("type") or "entity").strip() or "entity"
        try:
            confidence = float(entity.get("score") or 0.78)
        except Exception:
            confidence = 0.78
        for start, end in _find_keyword_offsets(text, quote, limit=1):
            item = _make_auto_annotation(
                source_text=text,
                start=start,
                end=end,
                annotation_type="entity",
                label=label,
                confidence=min(0.99, max(0.0, confidence)),
                source="gliner",
            )
            if item is not None:
                out.append(item)
            break
        if len(out) >= max_items:
            break
    return out


def _collect_sensitive_annotations(
    text: str,
    *,
    max_items: int,
    providers: set[str] | None = None,
) -> list[AutoAnnotationItem]:
    provider_set = providers or {"pii", "secret"}
    out: list[AutoAnnotationItem] = []
    if "pii" in provider_set:
        for match in find_pii_matches(text, max_matches=max_items):
            item = _make_auto_annotation(
                source_text=text,
                start=int(match.start),
                end=int(match.end),
                annotation_type="sensitive",
                label=str(match.kind),
                confidence=0.95,
                source="pii",
            )
            if item is not None:
                out.append(item)
            if len(out) >= max_items:
                return out

    remaining = max_items - len(out)
    if remaining <= 0:
        return out
    if "secret" not in provider_set:
        return out

    for match in find_secret_matches(text, max_matches=remaining):
        item = _make_auto_annotation(
            source_text=text,
            start=int(match.start),
            end=int(match.end),
            annotation_type="sensitive",
            label=str(match.kind),
            confidence=0.98,
            source="secret",
        )
        if item is not None:
            out.append(item)
        if len(out) >= max_items:
            return out
    return out


def _collect_rule_focus_annotations(
    text: str,
    *,
    enable_keywords: bool,
    enable_entities: bool,
    keyword_provider: str,
    keyword_top_k: int,
    max_items: int,
) -> tuple[str | None, list[AutoAnnotationItem]]:
    candidates: list[AutoAnnotationItem] = []

    # Keep sensitive values out of default document-focus suggestions.
    blocked = _collect_sensitive_annotations(text, max_items=100)

    for label, annotation_type, pattern, confidence in _FOCUS_RULES:
        for match in pattern.finditer(text):
            start, end = _trim_focus_rule_span(text, label, int(match.start()), int(match.end()))
            item = _make_auto_annotation(
                source_text=text,
                start=start,
                end=end,
                annotation_type=annotation_type,
                label=label,
                confidence=confidence,
                source="rule_focus",
            )
            if item is None or any(_annotation_overlaps(item, blocked_item) for blocked_item in blocked):
                continue
            candidates.append(item)
            if len(candidates) >= max_items:
                return None, candidates

    if not candidates:
        for match in _FOCUS_SENTENCE_RE.finditer(text):
            sentence = (match.group(0) or "").strip()
            if not sentence:
                continue
            if not any(key in sentence for key in ("知识库", "数据治理", "检索", "入库", "流程", "质量", "风险", "建议", "核心")):
                continue
            start, end = _trim_match_span(text, int(match.start()), int(match.end()))
            item = _make_auto_annotation(
                source_text=text,
                start=start,
                end=end,
                annotation_type="custom",
                label="文档重点",
                confidence=0.7,
                source="rule_focus",
            )
            if item is not None and not any(_annotation_overlaps(item, blocked_item) for blocked_item in blocked):
                candidates.append(item)
                break

    keyword_provider_used: str | None = None
    if enable_keywords and len(candidates) < max_items:
        domain_items = _collect_domain_focus_terms(
            text,
            max_items=max_items - len(candidates),
            blocked=blocked,
        )
        candidates.extend(domain_items)

    if enable_keywords and len(candidates) < max_items:
        keyword_provider_used, keyword_items = _collect_focus_keyword_annotations(
            text,
            provider=keyword_provider,
            top_k=keyword_top_k,
            max_items=max_items - len(candidates),
            blocked=blocked + candidates,
        )
        candidates.extend(keyword_items)

    if enable_entities and len(candidates) < max_items:
        entity_items = _collect_entity_annotations(text, max_items=max_items - len(candidates))
        for item in entity_items:
            if any(_annotation_overlaps(item, blocked_item) for blocked_item in blocked + candidates):
                continue
            candidates.append(
                AutoAnnotationItem(
                    text=item.text,
                    type="entity",
                    label="关键实体",
                    start=item.start,
                    end=item.end,
                    confidence=item.confidence,
                    source=item.source,
                )
            )
            if len(candidates) >= max_items:
                break

    return keyword_provider_used, candidates


async def _collect_llm_focus_annotations(
    text: str,
    *,
    max_items: int,
    max_chars: int,
    model: str | None,
) -> tuple[str | None, list[AutoDocumentTag], list[AutoAnnotationItem]]:
    result = await extract_llm_tags(
        text=text,
        model=model,
        max_chars=max_chars,
        max_items=max_items,
    )

    document_tags: list[AutoDocumentTag] = []
    for tag in result.document_tags:
        item = _make_auto_document_tag(
            tag_type=str(tag.type),
            value=tag.value,
            label=tag.label,
            confidence=float(tag.confidence),
            source=tag.source,
        )
        if item is not None:
            document_tags.append(item)

    annotations: list[AutoAnnotationItem] = []
    for raw in result.span_annotations:
        quote = str(raw.text or "").strip()
        if not quote:
            continue
        for start, end in _find_keyword_offsets(text, quote, limit=1):
            item = _make_auto_annotation(
                source_text=text,
                start=start,
                end=end,
                annotation_type=str(raw.type),
                label=raw.label,
                confidence=min(0.99, max(0.0, float(raw.confidence))),
                source=raw.source,
            )
            if item is not None:
                annotations.append(item)
            break
        if len(annotations) >= max_items:
            break
    return result.summary, document_tags, annotations


def _collect_cpu_focus_annotations(
    text: str,
    *,
    keyword_provider: str,
    keyword_top_k: int,
    max_items: int,
) -> tuple[str | None, list[AutoDocumentTag], list[AutoAnnotationItem]]:
    result = extract_cpu_tags(
        text=text,
        keyword_provider=keyword_provider,
        keyword_top_k=keyword_top_k,
        max_items=max_items,
    )

    document_tags: list[AutoDocumentTag] = []
    for tag in result.document_tags:
        item = _make_auto_document_tag(
            tag_type=str(tag.type),
            value=tag.value,
            label=tag.label,
            confidence=float(tag.confidence),
            source=tag.source,
        )
        if item is not None:
            document_tags.append(item)

    annotations: list[AutoAnnotationItem] = []
    for raw in result.span_annotations:
        quote = str(raw.text or "").strip()
        if not quote:
            continue
        for start, end in _find_keyword_offsets(text, quote, limit=1):
            item = _make_auto_annotation(
                source_text=text,
                start=start,
                end=end,
                annotation_type=str(raw.type),
                label=raw.label,
                confidence=min(0.99, max(0.0, float(raw.confidence))),
                source=raw.source,
            )
            if item is not None:
                annotations.append(item)
            break
        if len(annotations) >= max_items:
            break
    return result.summary, document_tags, annotations


def _collect_common_lines_texts(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    limit_docs: int,
    use_original: bool,
) -> tuple[int, list[str]]:
    """
    Collect a bounded list of parsed markdown texts for common-lines learning.

    Returns (total_with_parsed_content_in_dataset, texts[]).
    """
    # Count eligible docs (best-effort; does not enforce document ACL).
    total = (
        db.query(func.count(DocumentParsedContent.document_id))
        .join(
            DBDocument,
            and_(
                DBDocument.id == DocumentParsedContent.document_id,
                DBDocument.tenant_id == DocumentParsedContent.tenant_id,
            ),
        )
        .filter(
            DocumentParsedContent.tenant_id == tenant_id,
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
        )
        .scalar()
    )
    total_with_content = int(total or 0)

    # Pull a small batch of latest docs with parsed content, then enforce document ACL.
    # We over-fetch to avoid ending up with too few after ACL filtering.
    raw_doc_rows = (
        db.query(DBDocument.id)
        .join(
            DocumentParsedContent,
            and_(
                DocumentParsedContent.document_id == DBDocument.id,
                DocumentParsedContent.tenant_id == tenant_id,
            ),
        )
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
        )
        .order_by(DBDocument.updated_at.desc())
        .limit(200)
        .all()
    )
    raw_doc_ids = [row[0] for row in raw_doc_rows if row and row[0]]

    allowed_ids, _missing = get_allowed_document_id_sets(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        doc_ids=raw_doc_ids,
        check_member=False,
    )
    allowed_ordered = [doc_id for doc_id in raw_doc_ids if doc_id in allowed_ids][: int(limit_docs or 20)]

    if not allowed_ordered:
        return total_with_content, []

    rows = (
        db.query(
            DocumentParsedContent.document_id,
            DocumentParsedContent.original_markdown_content,
            DocumentParsedContent.markdown_content,
        )
        .filter(
            DocumentParsedContent.tenant_id == tenant_id,
            DocumentParsedContent.document_id.in_(allowed_ordered),
        )
        .all()
    )
    by_id: dict[UUID, tuple[str, str]] = {}
    for doc_id, original, cleaned in rows:
        by_id[doc_id] = (str(original or ""), str(cleaned or ""))

    texts: list[str] = []
    for doc_id in allowed_ordered:
        original, cleaned = by_id.get(doc_id, ("", ""))
        if use_original and original.strip():
            text = original
        elif cleaned.strip():
            text = cleaned
        else:
            text = original
        if not text.strip():
            continue
        texts.append(text)

    return total_with_content, texts


def _profile_key_for_row(row: DBGovernanceProfile) -> str:
    raw = str(getattr(row, "key", "") or "").strip()
    if raw:
        return raw
    return f"custom:{str(row.id)}"


def _profile_summary_from_row(row: DBGovernanceProfile) -> GovernanceProfileSummary:
    return GovernanceProfileSummary(
        id=row.id,
        key=_profile_key_for_row(row),
        name=str(getattr(row, "name", "") or ""),
        description=getattr(row, "description", None),
        is_system=bool(getattr(row, "is_system", False)),
    )


def _profile_out_from_row(row: DBGovernanceProfile) -> GovernanceProfileOut:
    payload_raw = getattr(row, "payload", None)
    if not isinstance(payload_raw, dict):
        payload_raw = {}
    payload = GovernanceProfilePayload(**payload_raw)
    return GovernanceProfileOut(
        id=row.id,
        key=_profile_key_for_row(row),
        name=str(getattr(row, "name", "") or ""),
        description=getattr(row, "description", None),
        is_system=bool(getattr(row, "is_system", False)),
        payload=payload,
        created_at=getattr(row, "created_at", None),
        updated_at=getattr(row, "updated_at", None),
    )


def _resolve_profile_ref(
    *,
    db: Session,
    tenant_id: UUID,
    profile_ref: str,
) -> GovernanceProfileOut:
    ref = str(profile_ref or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="profile_ref is required")

    if ref in _BUILTIN_GOVERNANCE_BY_KEY:
        return builtin_profile_to_out(_BUILTIN_GOVERNANCE_BY_KEY[ref])

    # Allow UUID lookup.
    try:
        ref_uuid = UUID(ref)
    except Exception:
        ref_uuid = None

    q = db.query(DBGovernanceProfile).filter(DBGovernanceProfile.tenant_id == tenant_id)
    if ref_uuid is not None:
        row = q.filter(DBGovernanceProfile.id == ref_uuid).first()
        if row is not None:
            return _profile_out_from_row(row)
    # Allow key lookup (tenant-scoped).
    row = q.filter(DBGovernanceProfile.key == ref).first()
    if row is not None:
        return _profile_out_from_row(row)

    raise HTTPException(status_code=404, detail=GOVERNANCE_PROFILE_NOT_FOUND_DETAIL)


def _line_diff_stats(before: str, after: str) -> tuple[int, int, int]:
    """
    Compute coarse line-level diff stats for governance preview.

    Returns: (added_lines, removed_lines, changed_lines)
    - changed_lines counts "replaced" blocks (approximate: max(len(a), len(b))).
    """
    a = (before or "").splitlines()
    b = (after or "").splitlines()
    sm = SequenceMatcher(a=a, b=b, autojunk=False)
    added = 0
    removed = 0
    changed = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            added += (j2 - j1)
        elif tag == "delete":
            removed += (i2 - i1)
        elif tag == "replace":
            # Count replaced region as changed (best-effort).
            changed += max(i2 - i1, j2 - j1)
    return added, removed, changed

def _unified_diff_text(before: str, after: str, *, max_lines: int) -> tuple[str | None, bool]:
    """
    Build a unified diff for UI preview (best-effort).

    Returns: (diff_text_or_none, truncated)
    """
    cap = max(0, int(max_lines or 0))
    if cap == 0:
        return None, False

    diff_lines = list(
        unified_diff(
            (before or "").splitlines(),
            (after or "").splitlines(),
            fromfile="before",
            tofile="after",
            lineterm="",
        )
    )
    if not diff_lines:
        return "", False
    if len(diff_lines) > cap:
        hidden = len(diff_lines) - cap
        diff_lines = diff_lines[:cap] + [f"... (truncated, {hidden} more lines)"]
        return "\n".join(diff_lines), True
    return "\n".join(diff_lines), False


@router.get("/capabilities", response_model=PipelineCapabilitiesResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_pipeline_capabilities(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
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
        if magicpdf_service_configured(getattr(settings, "MAGIC_PDF_API_URL", "")):
            return True, None
        cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
        if not resolve_cli_command(cli):
            return False, f"MagicPDF CLI not found: {cli} (try activating the env or set MAGIC_PDF_CLI to full path)"
        models_dir = resolve_magicpdf_models_dir(getattr(settings, "MAGIC_PDF_MODELS_DIR", ""))
        if not models_dir:
            return False, "MagicPDF models not found: mount PDF-Extract-Kit cache or set MAGIC_PDF_MODELS_DIR"
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
        elif b == "deepseek_ocr":
            enabled = bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False))
            api_key = bool((getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip())
            available = bool(enabled and api_key)
            if not enabled:
                notes = "Set DEEPSEEK_OCR_ENABLED=true."
            elif not api_key:
                notes = "Configure SILICONFLOW_API_KEY."
        elif b == "qianfan_ocr":
            enabled = bool(getattr(settings, "QIANFAN_OCR_ENABLED", False))
            api_url = bool((getattr(settings, "QIANFAN_OCR_API_URL", "") or "").strip())
            available = bool(enabled and api_url)
            if not enabled:
                notes = "Set QIANFAN_OCR_ENABLED=true."
            elif not api_url:
                notes = "Configure QIANFAN_OCR_API_URL (e.g., http://localhost:2090/convert)."
        elif b == "textin":
            enabled = bool(getattr(settings, "TEXTIN_ENABLED", False))
            api_url = bool((getattr(settings, "TEXTIN_API_URL", "") or "").strip())
            app_id = bool((getattr(settings, "TEXTIN_APP_ID", "") or "").strip())
            secret_code = bool((getattr(settings, "TEXTIN_SECRET_CODE", "") or "").strip())
            available = bool(enabled and api_url and app_id and secret_code)
            if not enabled:
                notes = "Set TEXTIN_ENABLED=true."
            elif not api_url:
                notes = "Configure TEXTIN_API_URL."
            elif not app_id:
                notes = "Configure TEXTIN_APP_ID."
            elif not secret_code:
                notes = "Configure TEXTIN_SECRET_CODE."
        elif b == "markitdown":
            if not bool(getattr(settings, "MARKITDOWN_ENABLED", False)):
                available = False
                notes = "Set MARKITDOWN_ENABLED=true."
            else:
                ok, err = check_dependency("markitdown", attr="MarkItDown")
                available = ok
                if not ok:
                    notes = f"markitdown not installed: {err}"
        elif b == "docling":
            if not bool(getattr(settings, "DOCLING_ENABLED", False)):
                available = False
                notes = "Set DOCLING_ENABLED=true."
            else:
                ok, err = check_dependency("docling.document_converter", attr="DocumentConverter")
                available = ok
                if not ok:
                    notes = f"docling not installed: {err}"
        elif b == "etl4llm":
            enabled = bool(getattr(settings, "ETL4LLM_ENABLED", False))
            api_url = bool((getattr(settings, "ETL4LLM_API_URL", "") or "").strip())
            available = bool(enabled and api_url)
            if not enabled:
                notes = "Set ETL4LLM_ENABLED=true."
            elif not api_url:
                notes = "Configure ETL4LLM_API_URL (e.g., http://localhost:10001/v1/etl4llm/predict)."
        elif b == "marker":
            enabled = bool(getattr(settings, "MARKER_ENABLED", False))
            api_url = bool((getattr(settings, "MARKER_API_URL", "") or "").strip())
            available = bool(enabled and api_url)
            if not enabled:
                notes = "Set MARKER_ENABLED=true."
            elif not api_url:
                notes = "Configure MARKER_API_URL (e.g., http://localhost:2080/convert)."
        elif b == "paddle_vl":
            enabled = bool(getattr(settings, "PADDLE_VL_ENABLED", False))
            api_url = bool((getattr(settings, "PADDLE_VL_API_URL", "") or "").strip())
            available = bool(enabled and api_url)
            if not enabled:
                notes = "Set PADDLE_VL_ENABLED=true."
            elif not api_url:
                notes = "Configure PADDLE_VL_API_URL (e.g., http://localhost:9030/convert)."
        elif b == "textin":
            enabled = bool(getattr(settings, "TEXTIN_ENABLED", False))
            api_url = bool((getattr(settings, "TEXTIN_API_URL", "") or "").strip())
            app_id = bool((getattr(settings, "TEXTIN_APP_ID", "") or "").strip())
            secret_code = bool((getattr(settings, "TEXTIN_SECRET_CODE", "") or "").strip())
            available = bool(enabled and api_url and app_id and secret_code)
            if not enabled:
                notes = "Set TEXTIN_ENABLED=true."
            elif not api_url:
                notes = "Configure TEXTIN_API_URL."
            elif not app_id:
                notes = "Configure TEXTIN_APP_ID."
            elif not secret_code:
                notes = "Configure TEXTIN_SECRET_CODE."
        elif b == "olmocr":
            enabled = bool(getattr(settings, "OLMOCR_ENABLED", False))
            api_url = bool((getattr(settings, "OLMOCR_API_URL", "") or "").strip())
            available = bool(enabled and api_url)
            if not enabled:
                notes = "Set OLMOCR_ENABLED=true."
            elif not api_url:
                notes = "Configure OLMOCR_API_URL (e.g., http://localhost:2085/convert)."
        elif b == "magicpdf":
            available, notes = magicpdf_available()
        else:  # pragma: no cover
            available = False
            notes = "Unknown backend"

        pdf_backends.append(ParserBackendInfo(name=b, available=bool(available), notes=notes))

    chunk_strategies: list[ChunkStrategyInfo] = []
    # Expose all strategies known to the backend (frontends may choose a subset).
    all_strats = set(chunker_factory.SUPPORTED_STRATEGIES.keys()) | set(chunker_factory.INTEGRATED_PIPELINE_STRATEGIES)
    for name in sorted(all_strats):
        s = (name or "").strip().lower()
        available = True
        notes: str | None = None
        if s == "auto":
            available = True
            notes = "Auto-selects a chunker per document (git_commit_log/diff/patch/subtitles/logs/stacktrace/http_trace/terraform_plan/xml/junit_xml/sitemap_xml/maven_pom/xml_feed/openapi/github_actions/docker_compose/gitlab_ci/ansible_playbook/yaml/toml/sql/terraform/nginx/dockerfile/makefile/kv-config/jsonl/graphql/proto/api/changelog/csv/spreadsheet/chat/email/jira/postmortem/qa/qa_markdown/prd/sop/glossary/meeting_minutes/timeline/resume/slides/laws/paper/book/outline/transcript/rst/asciidoc/latex/org/wiki/html/markdown_table/markdown_frontmatter/markdown/json/plain text)."
        elif s == "manuscript":
            available = True
            notes = "Preset for manuscript-like documents (git_commit_log/diff/patch/subtitles/logs/stacktrace/http_trace/terraform_plan/xml/junit_xml/sitemap_xml/maven_pom/xml_feed/openapi/github_actions/docker_compose/gitlab_ci/ansible_playbook/yaml/toml/sql/terraform/nginx/dockerfile/makefile/kv-config/jsonl/graphql/proto/api/changelog/csv/spreadsheet/chat/email/jira/postmortem/qa/qa_markdown/prd/sop/glossary/meeting_minutes/timeline/resume/slides/laws/paper/book/outline/transcript/rst/asciidoc/latex/org/wiki/html/markdown_table/markdown_frontmatter/markdown/...)."
        elif s == "pdf_layout":
            available = True
            notes = "PDF layout-aware chunking. Requires parsers that emit position tags like @@page\\tl\\tr\\tt\\tb##; strips tags from chunk text and records bbox/column metadata."
        elif s == "outline":
            available = True
            notes = "Numbered-outline aware chunking (keeps section heading context)."
        elif s == "transcript":
            available = True
            notes = "Transcript/dialogue aware chunking (keeps speaker turns together)."
        elif s == "qa_pairs":
            available = True
            notes = "FAQ / Q&A aware chunking (keeps Q/A pairs together)."
        elif s == "paper":
            available = True
            notes = "Academic paper/report aware chunking (splits by common paper sections)."
        elif s == "book_structured":
            available = True
            notes = "Book chapter/part aware chunking (keeps chapter context)."
        elif s == "laws_structured":
            available = True
            notes = "Legal/policy aware chunking (splits by articles/clauses)."
        elif s == "email_thread":
            available = True
            notes = "Email thread aware chunking (keeps whole messages together)."
        elif s == "sop_steps":
            available = True
            notes = "SOP/procedure aware chunking (splits by Step/步骤 headings)."
        elif s == "glossary":
            available = True
            notes = "Glossary/dictionary aware chunking (splits by term-definition entries)."
        elif s == "resume_structured":
            available = True
            notes = "Resume/CV section-aware chunking (splits by common resume headings)."
        elif s == "presentation_slides":
            available = True
            notes = "Slide-aware chunking (splits by separators/markers like '---' or 'Slide 1')."
        elif s == "csv_rows":
            available = True
            notes = "CSV row-aware chunking (groups 'row N:' blocks; best with CsvParser output)."
        elif s == "spreadsheet_sheet":
            available = True
            notes = "Spreadsheet sheet-aware chunking (splits by '## Sheet:' sections; best with ExcelParser output)."
        elif s == "markdown_table":
            available = True
            notes = "Markdown table-aware chunking (avoids splitting rows; splits large tables at row boundaries)."
        elif s == "chat_history":
            available = True
            notes = "Timestamped chat history chunking (keeps whole messages together with message-level overlap)."
        elif s == "changelog":
            available = True
            notes = "Changelog/release-notes aware chunking (splits by release headings like '## [1.2.3] - 2024-01-01')."
        elif s == "log_events":
            available = True
            notes = "Log-events aware chunking (keeps multi-line log entries together; entry-level overlap)."
        elif s == "subtitles":
            available = True
            notes = "Subtitles aware chunking (SRT/VTT-like; splits by timecode cues)."
        elif s == "api_reference":
            available = True
            notes = "API reference aware chunking (splits by endpoint signatures like 'GET /path')."
        elif s == "diff_patch":
            available = True
            notes = "Diff/patch aware chunking (splits by file blocks and @@ hunks)."
        elif s == "git_commit_log":
            available = True
            notes = "Git commit-log aware chunking (splits by 'commit <sha>' blocks; preserves commit context even with patches)."
        elif s == "kv_config":
            available = True
            notes = "Key-value config aware chunking (groups KEY=VALUE entries; supports INI sections)."
        elif s == "qa_markdown":
            available = True
            notes = "Markdown Q/A aware chunking (supports bullets/headings like '**Q:**' / '### Q:')."
        elif s == "meeting_minutes":
            available = True
            notes = "Meeting-minutes aware chunking (splits by common sections like agenda/actions/decisions)."
        elif s == "timeline_events":
            available = True
            notes = "Timeline/date-event aware chunking (keeps dated events together)."
        elif s == "html_sections":
            available = True
            notes = "HTML heading-aware chunking (splits by <h1>-<h6> tags)."
        elif s == "rst_sections":
            available = True
            notes = "reStructuredText section-aware chunking (splits by underlined headings)."
        elif s == "asciidoc_sections":
            available = True
            notes = "AsciiDoc section-aware chunking (splits by '=' heading lines)."
        elif s == "latex_sections":
            available = True
            notes = "LaTeX section-aware chunking (splits by \\section/\\chapter commands)."
        elif s == "orgmode_sections":
            available = True
            notes = "Org-mode section-aware chunking (splits by '*' heading lines)."
        elif s == "mediawiki_sections":
            available = True
            notes = "MediaWiki section-aware chunking (splits by '== Heading ==' lines)."
        elif s == "yaml_manifest":
            available = True
            notes = "YAML manifest aware chunking (splits by '---' documents; extracts kind/name when present)."
        elif s == "toml_config":
            available = True
            notes = "TOML config aware chunking (splits by [tables] and groups key/value entries)."
        elif s == "sql_schema":
            available = True
            notes = "SQL schema/DDL aware chunking (splits by CREATE/ALTER statements)."
        elif s == "stacktrace":
            available = True
            notes = "Stacktrace aware chunking (groups traceback blocks; for timestamped logs prefer log_events)."
        elif s == "http_trace":
            available = True
            notes = "HTTP trace aware chunking (splits by HTTP request blocks; keeps request+response together)."
        elif s == "terraform_plan":
            available = True
            notes = "Terraform plan output aware chunking (splits by '# ... will be ...' change headers)."
        elif s == "xml_feed":
            available = True
            notes = "XML feed (RSS/Atom) item-aware chunking (splits by <item>/<entry> blocks)."
        elif s == "junit_xml":
            available = True
            notes = "JUnit XML report aware chunking (splits by <testcase> blocks; preserves offsets)."
        elif s == "sitemap_xml":
            available = True
            notes = "Sitemap XML aware chunking (splits by <url>/<sitemap> entry blocks)."
        elif s == "maven_pom":
            available = True
            notes = "Maven POM XML aware chunking (chunks <dependency>/<plugin> records; preserves offsets)."
        elif s == "openapi_spec":
            available = True
            notes = "OpenAPI/Swagger spec aware chunking (splits by per-path blocks under `paths:`)."
        elif s == "github_actions":
            available = True
            notes = "GitHub Actions workflow aware chunking (splits by job blocks under `jobs:`)."
        elif s == "docker_compose":
            available = True
            notes = "Docker Compose YAML aware chunking (splits by service blocks under `services:`)."
        elif s == "gitlab_ci":
            available = True
            notes = "GitLab CI YAML aware chunking (splits by top-level job/config blocks)."
        elif s == "ansible_playbook":
            available = True
            notes = "Ansible playbook aware chunking (splits by top-level plays; preserves offsets)."
        elif s == "dockerfile":
            available = True
            notes = "Dockerfile aware chunking (splits by FROM stages and instruction blocks)."
        elif s == "makefile":
            available = True
            notes = "Makefile aware chunking (splits by target blocks and recipes)."
        elif s == "nginx_config":
            available = True
            notes = "Nginx config aware chunking (splits by server blocks; brace-aware)."
        elif s == "terraform_hcl":
            available = True
            notes = "Terraform/HCL block-aware chunking (splits by resource/module/variable blocks; brace-aware)."
        elif s == "graphql_schema":
            available = True
            notes = "GraphQL schema aware chunking (splits by top-level type/input/enum/interface/union/scalar/directive/schema definitions)."
        elif s == "proto_schema":
            available = True
            notes = "Protocol Buffers schema aware chunking (splits by message/enum/service blocks; brace-aware)."
        elif s == "jira_ticket":
            available = True
            notes = "Jira/issue-ticket aware chunking (splits by common fields like Summary/Description/Steps/Expected/Actual)."
        elif s == "prd_spec":
            available = True
            notes = "PRD/spec aware chunking (splits by common sections like Background/Goals/Scope/Requirements/Acceptance/Risks)."
        elif s == "postmortem_report":
            available = True
            notes = "Incident postmortem/RCA aware chunking (splits by common sections like Summary/Impact/Timeline/Root Cause/Action Items)."
        elif s == "jsonl_records":
            available = True
            notes = "JSONL/NDJSON record-aware chunking (groups whole JSON records per line; preserves offsets)."
        elif s == "markdown_frontmatter":
            available = True
            notes = "Markdown frontmatter aware chunking (keeps YAML frontmatter, then chunks the body)."
        elif s == "sentence_window":
            available = True
            notes = "Sentence window chunking with sentence-level overlap."
        if s.startswith("llama_index"):
            if not bool(getattr(settings, "LLAMA_INDEX_ENABLED", False)):
                available = False
                notes = "Set LLAMA_INDEX_ENABLED=true."
            else:
                ok, err = check_dependency("llama_index.core")
                available = ok
                if not ok:
                    notes = f"llama-index-core not installed: {err}"
        elif s in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
            available = True
            vision_enabled = bool(getattr(settings, "VISION_LLM_ENABLED", False))
            vision_key_ok = bool(
                (
                    (getattr(settings, "VISION_LLM_API_KEY", "") or getattr(settings, "LLM_API_KEY", "") or "")
                    .strip()
                )
            )
            vision_model = (getattr(settings, "VISION_LLM_MODEL", "") or "").strip()

            if vision_enabled and vision_key_ok:
                notes = f"Integrated pipeline (parse+chunk). Vision enrichment enabled (model={vision_model or 'configured'})."
            elif vision_enabled and not vision_key_ok:
                notes = "Integrated pipeline (parse+chunk). Vision enrichment enabled but missing API key (set MIMIRQ_VISION_LLM_API_KEY or LLM_API_KEY)."
            else:
                notes = "Integrated pipeline (parse+chunk). Vision enrichment disabled by default (set MIMIRQ_VISION_LLM_ENABLED=true to enable)."
        elif s == "markdown":
            available = True
            notes = "Alias of markdown_header."

        notes = decorate_chunk_strategy_note(s, notes)
        chunk_strategies.append(ChunkStrategyInfo(name=s, available=bool(available), notes=notes))

    return PipelineCapabilitiesResponse(
        default_parser_backend=default_parser_backend,
        default_chunk_strategy=default_chunk_strategy,
        pdf_backends=pdf_backends,
        chunk_strategies=chunk_strategies,
    )


@router.get("/governance-profiles", response_model=GovernanceProfileListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def list_governance_profiles(
    q: str | None = None,
    include_builtin: bool = True,
    limit: int = 200,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    List governance profiles (built-in + tenant custom profiles).

    Notes:
    - Built-in profiles are shipped in code (read-only).
    - Custom profiles are stored in DB (tenant-scoped).
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = (q or "").strip().lower()
    items: list[GovernanceProfileSummary] = []
    builtin_count = 0

    if include_builtin:
        for p in _BUILTIN_GOVERNANCE_PROFILES:
            if query and query not in (p.name.lower() + " " + p.description.lower()):
                continue
            items.append(
                GovernanceProfileSummary(
                    id=None,
                    key=p.key,
                    name=p.name,
                    description=p.description,
                    is_system=True,
                )
            )
        builtin_count = len(items)

    q_db = db.query(DBGovernanceProfile).filter(DBGovernanceProfile.tenant_id == tenant_id)
    if query:
        like = f"%{query}%"
        # Avoid depending on database-specific full-text features.
        q_db = q_db.filter(
            (DBGovernanceProfile.name.ilike(like))
            | (DBGovernanceProfile.description.ilike(like))
            | (DBGovernanceProfile.key.ilike(like))
        )

    total_custom = int(q_db.count() or 0)
    rows = q_db.order_by(DBGovernanceProfile.updated_at.desc()).limit(min(int(limit or 200), 200)).all()
    items.extend([_profile_summary_from_row(r) for r in rows])

    return GovernanceProfileListResponse(total=(builtin_count + total_custom), items=items)


@router.get(
    "/governance-processing-scripts/builtins",
    response_model=BuiltinProcessingScriptListResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def list_builtin_processing_scripts_endpoint(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
):
    """
    List built-in processing script templates exposed on the 重复行学习 page.

    Notes:
    - Templates are read-only and shipped in code.
    - Per ``GovernanceProcessingScript`` schema, scripts are persisted with a
      governance profile only for review/versioning; the ingestion pipeline does
      not execute them. Templates are reference code customers can copy as a
      starting point.
    """
    items = [
        BuiltinProcessingScriptOut(
            key=s.key,
            name=s.name,
            description=s.description,
            language=s.language,
            stage=s.stage,
            content=s.content,
            tags=list(s.tags),
        )
        for s in _BUILTIN_PROCESSING_SCRIPTS
    ]
    return BuiltinProcessingScriptListResponse(total=len(items), items=items)


@router.post("/governance-profiles", response_model=GovernanceProfileOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def create_governance_profile(
    body: GovernanceProfileCreate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    name = str(body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    try:
        key = validate_profile_key(body.key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if key:
        exists = (
            db.query(DBGovernanceProfile.id)
            .filter(DBGovernanceProfile.tenant_id == tenant_id, DBGovernanceProfile.key == key)
            .first()
        )
        if exists:
            raise HTTPException(status_code=409, detail="profile key already exists")

    try:
        payload = validate_and_normalize_payload(body.payload)
    except RegexRulesValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.to_detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row = DBGovernanceProfile(
        tenant_id=tenant_id,
        key=key,
        name=name[:200],
        description=(str(body.description).strip()[:2000] if body.description is not None else None),
        is_system=False,
        payload=payload.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _profile_out_from_row(row)


@router.get("/governance-profiles/{profile_ref}", response_model=GovernanceProfileOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_governance_profile(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    return _resolve_profile_ref(db=db, tenant_id=tenant_id, profile_ref=profile_ref)


@router.get("/governance-profiles/{profile_ref}/resolved", response_model=GovernanceProfileResolvedResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_governance_profile_resolved(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    try:
        resolved = resolve_governance_profile_ref_effective(db=db, tenant_id=tenant_id, profile_ref=profile_ref)
    except ValueError as exc:
        msg = str(exc) or "invalid profile_ref"
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=400, detail=msg) from exc

    return GovernanceProfileResolvedResponse(profile=resolved.profile, chain=resolved.chain, effective=resolved.effective)


@router.patch("/governance-profiles/{profile_ref}", response_model=GovernanceProfileOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def update_governance_profile(
    profile_ref: str,
    body: GovernanceProfileUpdate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    ref = str(profile_ref or "").strip()
    if ref in _BUILTIN_GOVERNANCE_BY_KEY:
        raise HTTPException(status_code=403, detail="built-in profiles are read-only")

    # Resolve custom profile row by UUID or key.
    try:
        ref_uuid = UUID(ref)
    except Exception:
        ref_uuid = None

    q = db.query(DBGovernanceProfile).filter(DBGovernanceProfile.tenant_id == tenant_id)
    row = q.filter(DBGovernanceProfile.id == ref_uuid).first() if ref_uuid else q.filter(DBGovernanceProfile.key == ref).first()
    if row is None:
        raise HTTPException(status_code=404, detail=GOVERNANCE_PROFILE_NOT_FOUND_DETAIL)

    if body.name is not None:
        name = str(body.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name must not be empty")
        row.name = name[:200]

    if body.description is not None:
        desc = str(body.description or "").strip()
        row.description = desc[:2000] if desc else None

    if body.payload is not None:
        try:
            payload = validate_and_normalize_payload(body.payload)
        except RegexRulesValidationError as exc:
            raise HTTPException(status_code=400, detail=exc.to_detail()) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row.payload = payload.model_dump()

    db.commit()
    db.refresh(row)
    return _profile_out_from_row(row)


@router.delete("/governance-profiles/{profile_ref}", status_code=204, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def delete_governance_profile(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    ref = str(profile_ref or "").strip()
    if ref in _BUILTIN_GOVERNANCE_BY_KEY:
        raise HTTPException(status_code=403, detail="built-in profiles are read-only")

    try:
        ref_uuid = UUID(ref)
    except Exception:
        ref_uuid = None

    q = db.query(DBGovernanceProfile).filter(DBGovernanceProfile.tenant_id == tenant_id)
    row = q.filter(DBGovernanceProfile.id == ref_uuid).first() if ref_uuid else q.filter(DBGovernanceProfile.key == ref).first()
    if row is None:
        raise HTTPException(status_code=404, detail=GOVERNANCE_PROFILE_NOT_FOUND_DETAIL)

    db.delete(row)
    db.commit()
    return None


@router.post("/governance-profiles/import", response_model=GovernanceProfileImportResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def import_governance_profiles(
    file: Annotated[UploadFile, File(...)],
    overwrite: Annotated[bool, Form()] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Import governance profile scripts (JSON).

    Security:
    - Only declarative JSON is accepted (no executable code).
    - Strong validation on regex rules and option keys is applied server-side.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    max_bytes = 256 * 1024
    raw = await file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Profile script too large (max={max_bytes} bytes)")

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid JSON file") from exc

    if isinstance(data, dict) and isinstance(data.get("profiles"), list):
        raw_profiles = data.get("profiles") or []
    else:
        raw_profiles = [data]

    created = 0
    updated = 0
    out_items: list[GovernanceProfileSummary] = []

    for item in raw_profiles:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Invalid profile item (expected object)")

        unknown_item_keys = set(item.keys()) - {"name", "description", "key", "payload"}
        if unknown_item_keys:
            unknown_sorted = ", ".join(sorted(map(str, unknown_item_keys))[:20])
            raise HTTPException(status_code=400, detail=f"Unknown profile fields: {unknown_sorted}")

        name = str(item.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Profile name is required")

        raw_key = item.get("key")
        try:
            key = validate_profile_key(raw_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        payload_raw = item.get("payload")
        if not isinstance(payload_raw, dict):
            raise HTTPException(status_code=400, detail="payload is required and must be an object")

        unknown_payload_keys = set(payload_raw.keys()) - {
            "version",
            "extends",
            "input_formats",
            "pipeline_patch",
            "regex_rules",
            "processing_scripts",
        }
        if unknown_payload_keys:
            unknown_sorted = ", ".join(sorted(map(str, unknown_payload_keys))[:20])
            raise HTTPException(status_code=400, detail=f"Unknown payload fields: {unknown_sorted}")

        try:
            payload = GovernanceProfilePayload(**payload_raw)
            payload = validate_and_normalize_payload(payload)
        except RegexRulesValidationError as exc:
            raise HTTPException(status_code=400, detail=exc.to_detail()) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid payload: {str(exc)[:200]}") from exc

        description = item.get("description")
        desc = str(description or "").strip()[:2000] if description is not None else None

        existing = None
        if key:
            existing = (
                db.query(DBGovernanceProfile)
                .filter(DBGovernanceProfile.tenant_id == tenant_id, DBGovernanceProfile.key == key)
                .first()
            )

        if existing is not None:
            if not overwrite:
                raise HTTPException(status_code=409, detail=f"Profile key already exists: {key}")
            existing.name = name[:200]
            existing.description = desc
            existing.payload = payload.model_dump()
            updated += 1
            out_items.append(_profile_summary_from_row(existing))
        else:
            row = DBGovernanceProfile(
                tenant_id=tenant_id,
                key=key,
                name=name[:200],
                description=desc,
                is_system=False,
                payload=payload.model_dump(),
            )
            db.add(row)
            db.flush()
            created += 1
            out_items.append(_profile_summary_from_row(row))

    db.commit()
    return GovernanceProfileImportResponse(created=created, updated=updated, items=out_items)


@router.get("/governance-profiles/{profile_ref}/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def export_governance_profile(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    profile = _resolve_profile_ref(db=db, tenant_id=tenant_id, profile_ref=profile_ref)

    payload = profile.payload.model_dump()
    export_obj = {
        "name": profile.name,
        "description": profile.description,
        "key": profile.key,
        "payload": payload,
    }

    # Best-effort safe filename.
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(profile.key or "profile"))[:64]
    filename = f"{safe_key}.governance-profile.json"
    content = json.dumps(export_obj, ensure_ascii=False, indent=2).encode("utf-8")
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'},
    )


@router.get("/governance-profiles/{profile_ref}/export-ingestion-policy", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def export_governance_profile_ingestion_policy(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Export a minimal, importable dataset ingestion policy that references the given governance profile.

    This "closes the loop" for operators: build custom governance profiles in the UI, then export
    an ingestion_policy JSON snippet to be imported into a dataset.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    profile = _resolve_profile_ref(db=db, tenant_id=tenant_id, profile_ref=profile_ref)

    # Best-effort safe filename + rule id.
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(profile.key or "profile"))[:64] or "profile"
    filename = f"{safe_key}.ingestion_policy.json"

    # Match all files by default; operators can refine extensions/filename_regex after import.
    rule = IngestionRule(
        id=f"gov:{safe_key}"[:100],
        name=f"Governance: {str(profile.name or '').strip() or safe_key}"[:200],
        enabled=True,
        match={"extensions": []},
        preprocess={"enabled": False, "steps": []},
        governance_profile_ref=str(profile.key or "").strip() or None,
        pipeline_patch={},
    )

    policy = IngestionPolicy(version="1", rules=[rule])
    content = export_policy_json(policy)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'},
    )


@router.post("/parse-preview", response_model=ParsePreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def parse_preview(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    parser_backend: Annotated[str | None, Form()] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
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
    run_dir = preview_dir / uuid.uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=True)
    temp_path = run_dir / f"input{file_ext}"
    try:
        await save_upload_file(file, temp_path, max_bytes=settings.MAX_FILE_SIZE)

        result = await run_subprocess_worker(
            tenant_id=tenant_id,
            payload={
                "action": "pipeline_parse_preview",
                "tenant_id": str(tenant_id),
                "file_path": str(temp_path),
                "parser_backend": parser_backend,
            },
            disconnect_check=request.is_disconnected,
            timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
        )
        return result
    except SubprocessCancelled:
        raise HTTPException(status_code=499, detail="Client closed request") from None
    except SubprocessWorkerError as e:
        err_type = (e.details or {}).get("type")
        if err_type == "ValueError":
            raise HTTPException(status_code=400, detail=str(e)) from e
        raise HTTPException(status_code=500, detail="Failed to parse preview") from e
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


@router.post("/ingestion-preview", response_model=IngestionPreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def ingestion_preview(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    dataset_id: Annotated[UUID, Form(...)],
    parser_backend: Annotated[str | None, Form()] = None,
    chunk_strategy: Annotated[str | None, Form()] = None,
    diff_max_lines: Annotated[int, Form()] = 2000,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    One-shot ingestion preview for a dataset:
    - match dataset ingestion policy
    - preprocess file (before parsing)
    - parse to Markdown (preview)
    - run governance clean preview (issues + unified diff)
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}")

    preview_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    run_dir = preview_dir / uuid.uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=True)
    temp_path = run_dir / f"input{file_ext}"

    pre_summary: dict[str, object] = {"changed": False, "size_before": 0, "size_after": 0, "steps": [], "warnings": []}

    try:
        await save_upload_file(file, temp_path, max_bytes=settings.MAX_FILE_SIZE)

        dataset_meta = getattr(dataset, "dataset_metadata", None)
        dataset_meta = dataset_meta if isinstance(dataset_meta, dict) else {}
        policy = parse_ingestion_policy_from_metadata(dataset_meta) or None
        matched_rule = match_ingestion_rule(policy, filename=file.filename, file_ext=file_ext)

        default_pb = (getattr(settings, "DEFAULT_PARSER_BACKEND", "auto") or "auto").strip().lower() or "auto"
        default_cs = (getattr(settings, "DEFAULT_CHUNK_STRATEGY", "langchain_recursive") or "langchain_recursive").strip().lower()

        base_pb = (parser_backend or default_pb).strip().lower() or default_pb
        base_cs = (chunk_strategy or default_cs).strip().lower() or default_cs

        parser_backend_choice = base_pb
        chunk_strategy_choice = base_cs
        preprocess_steps: list[dict] = []
        governance_profile_ref: str | None = None
        patch_dict: dict[str, object] = {}

        if matched_rule is not None:
            if base_pb in {"", "auto", default_pb} and matched_rule.parser_backend:
                parser_backend_choice = str(matched_rule.parser_backend)
            if base_cs in {"", default_cs} and matched_rule.chunk_strategy:
                chunk_strategy_choice = str(matched_rule.chunk_strategy)

            pp = getattr(matched_rule, "preprocess", None)
            steps = getattr(pp, "steps", None) if pp is not None and bool(getattr(pp, "enabled", True)) else None
            if isinstance(steps, list) and steps:
                preprocess_steps = [
                    {
                        "id": str(getattr(s, "id", "") or "").strip(),
                        "params": dict(getattr(s, "params", {}) or {}),
                    }
                    for s in steps
                ]

            governance_profile_ref = getattr(matched_rule, "governance_profile_ref", None)
            if isinstance(governance_profile_ref, str) and governance_profile_ref.strip():
                prof = _resolve_profile_ref(db=db, tenant_id=tenant_id, profile_ref=governance_profile_ref.strip())
                patch_dict.update(dict(prof.payload.pipeline_patch or {}))
                rules = [r.model_dump() for r in (prof.payload.regex_rules or [])]
                if rules:
                    patch_dict["governance_regex_rules"] = rules
            patch_dict.update(dict(getattr(matched_rule, "pipeline_patch", None) or {}))

        # Preprocess file (before parsing).
        parse_path = temp_path
        if preprocess_steps:
            pre = preprocess_file(input_path=temp_path, steps=preprocess_steps)
            pre_summary = {
                "changed": bool(pre.changed),
                "size_before": int(pre.size_before),
                "size_after": int(pre.size_after),
                "steps": [
                    {
                        "id": s.id,
                        "applied": bool(s.applied),
                        "changed": bool(s.changed),
                        "note": s.note,
                        "bytes_before": int(getattr(s, "bytes_before", 0) or 0),
                        "bytes_after": int(getattr(s, "bytes_after", 0) or 0),
                        "elapsed_ms": int(getattr(s, "elapsed_ms", 0) or 0),
                    }
                    for s in (pre.steps or [])
                ],
                "warnings": list(pre.warnings or []),
            }
            if bool(pre.changed):
                parse_path = Path(str(pre.output_path))

        # Compute effective governance options (dataset defaults + rule/profile patches).
        patch_opts = PipelineOptions(**patch_dict) if patch_dict else PipelineOptions()
        effective = resolve_pipeline_effective(dataset_metadata=dataset_meta, document_metadata={}, request_overrides=patch_opts)

        # Parse preview via subprocess worker.
        parsed = await run_subprocess_worker(
            tenant_id=tenant_id,
            payload={
                "action": "pipeline_parse_preview",
                "tenant_id": str(tenant_id),
                "file_path": str(parse_path),
                "parser_backend": parser_backend_choice,
            },
            disconnect_check=request.is_disconnected,
            timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
        )

        # Governance clean preview (issues + diff).
        clean_body = CleanPreviewRequest(
            markdown=str(parsed.get("markdown") or ""),
            rules=[CleanRegexRuleModel(**r) for r in (getattr(effective, "governance_regex_rules", None) or [])],
            use_default_rules=True,
            include_diff=True,
            diff_max_lines=int(diff_max_lines or 0),
            input_format="markdown",
            html_xpath=None,
            normalize_line_endings=True,
            trim_trailing_spaces=True,
            collapse_blank_lines=True,
            max_blank_lines=int(getattr(effective, "governance_max_blank_lines", 1) or 1),
            remove_control_chars=True,
            remove_toc_lines=bool(getattr(effective, "governance_remove_toc_lines", True)),
            remove_noise_lines=bool(getattr(effective, "governance_remove_noise_lines", True)),
            remove_common_lines=bool(getattr(effective, "governance_remove_common_lines", True)),
            unwrap_lines=bool(getattr(effective, "governance_unwrap_lines", True)),
            remove_boilerplate=bool(getattr(effective, "governance_remove_boilerplate", False)),
            remove_images=str(getattr(effective, "governance_remove_images", "none") or "none"),  # type: ignore[arg-type]
            extract_frontmatter=bool(getattr(effective, "governance_extract_frontmatter", False)),
            strip_frontmatter=bool(getattr(effective, "governance_strip_frontmatter", False)),
            detect_language=bool(getattr(effective, "governance_detect_language", False)),
            language_min_chars=int(getattr(effective, "governance_language_min_chars", 40) or 40),
            normalize_urls=bool(getattr(effective, "governance_normalize_urls", False)),
            normalize_urls_strip_tracking=bool(getattr(effective, "governance_normalize_urls_strip_tracking", True)),
            drop_duplicate_paragraphs=bool(getattr(effective, "governance_drop_duplicate_paragraphs", False)),
            drop_duplicate_paragraphs_min_occurrences=int(getattr(effective, "governance_drop_duplicate_paragraphs_min_occurrences", 3) or 3),
            drop_duplicate_paragraphs_min_chars=int(getattr(effective, "governance_drop_duplicate_paragraphs_min_chars", 40) or 40),
            drop_duplicate_paragraphs_max_chars=int(getattr(effective, "governance_drop_duplicate_paragraphs_max_chars", 1200) or 1200),
            trim_references=bool(getattr(effective, "governance_trim_references", False)),
            extract_keywords=bool(getattr(effective, "governance_extract_keywords", False)),
            keywords_provider=str(getattr(effective, "governance_keywords_provider", "auto") or "auto"),
            keywords_top_k=int(getattr(effective, "governance_keywords_top_k", 10) or 10),
            keywords_max_chars=int(getattr(effective, "governance_keywords_max_chars", 20000) or 20000),
            normalize_tables=bool(getattr(effective, "governance_normalize_tables", False)),
            strip_code_line_numbers=bool(getattr(effective, "governance_strip_code_line_numbers", False)),
            pii_anonymize=bool(getattr(effective, "governance_pii_anonymize", False)),
            pii_mode=str(getattr(effective, "governance_pii_mode", "mask") or "mask"),  # type: ignore[arg-type]
            pii_mask=str(getattr(effective, "governance_pii_mask", REDACTED_MASK) or REDACTED_MASK),
            secrets_redact=bool(getattr(effective, "governance_secrets_redact", False)),
            secrets_mode=str(getattr(effective, "governance_secrets_mode", "mask") or "mask"),  # type: ignore[arg-type]
            secrets_mask=str(getattr(effective, "governance_secrets_mask", SECRET_MASK) or SECRET_MASK),
            drop_outline_only=bool(getattr(effective, "governance_drop_outline_only", False)),
            drop_outline_min_content_chars=int(getattr(effective, "governance_drop_outline_min_content_chars", 200) or 200),
            drop_outline_max_heading_ratio=float(getattr(effective, "governance_drop_outline_max_heading_ratio", 0.85) or 0.85),
            drop_low_density=bool(getattr(effective, "governance_drop_low_density", False)),
            drop_low_density_threshold=float(getattr(effective, "governance_drop_low_density_threshold", 0.12) or 0.12),
            unwrap_max_line_length=int(getattr(effective, "governance_unwrap_max_line_length", 120) or 120),
            noise_min_chars=int(getattr(effective, "governance_noise_min_chars", 2) or 2),
            noise_ratio_threshold=float(getattr(effective, "governance_noise_ratio_threshold", 0.2) or 0.2),
            common_lines_min_occurrences=int(getattr(effective, "governance_common_lines_min_docs", 3) or 3),
        )
        cleaned = await clean_preview(body=clean_body, tenant_id=tenant_id, account_id=account_id, db=db)

        rule_out = {
            "matched": matched_rule is not None,
            "rule_id": matched_rule.id if matched_rule is not None else None,
            "rule_name": matched_rule.name if matched_rule is not None else None,
            "governance_profile_ref": governance_profile_ref.strip() if isinstance(governance_profile_ref, str) and governance_profile_ref.strip() else None,
            "preprocess_steps": preprocess_steps,
            "parser_backend": str(parser_backend_choice or "auto"),
            "chunk_strategy": str(chunk_strategy_choice or ""),
        }

        explain = {
            "dataset_id": str(dataset_id),
            "filename": str(getattr(file, "filename", "") or ""),
            "file_type": str(file_ext or ""),
            "requested": {
                "parser_backend": str(base_pb or ""),
                "chunk_strategy": str(base_cs or ""),
            },
            "rule": rule_out,
            # Best-effort config snapshot (intended for export/audit; avoids embedding large markdown).
            "snapshot": {
                "dataset_id": str(dataset_id),
                "filename": str(getattr(file, "filename", "") or ""),
                "file_type": str(file_ext or ""),
                "rule": rule_out,
                "preprocess": dict(pre_summary),
                "pipeline_patch": dict(patch_dict),
                "parser_backend": str(parser_backend_choice or "auto"),
                "chunk_strategy": str(chunk_strategy_choice or ""),
                "parse_backend": str(parsed.get("backend") or ""),
                "pdf_quality": parsed.get("pdf_quality"),
            },
        }

        return {
            "rule": rule_out,
            "preprocess": pre_summary,
            "parse": parsed,
            "clean": cleaned,
            "explain": explain,
        }
    except SubprocessCancelled:
        raise HTTPException(status_code=499, detail="Client closed request") from None
    except SubprocessWorkerError as e:
        err_type = (e.details or {}).get("type")
        if err_type == "ValueError":
            raise HTTPException(status_code=400, detail=str(e)) from e
        raise HTTPException(status_code=500, detail="Failed to parse preview") from e
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


@router.post("/chunk-preview", response_model=PipelineChunkPreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def chunk_preview(
    body: PipelineChunkPreviewRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Perform hierarchical chunking for Markdown text and return highlight offsets.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    chunks = hierarchical_chunk_markdown(body.markdown)
    return PipelineChunkPreviewResponse(**chunks)


@router.post("/clean-preview", response_model=CleanPreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def clean_preview(
    body: CleanPreviewRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Preview governance-style cleaning for Markdown (no persistence) to compare before/after.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    raw_input = body.markdown or ""

    input_text = raw_input
    if body.input_format == "html":
        html = raw_input
        # Optional image stripping before XPath extraction.
        if str(body.remove_images or "none").strip().lower() in {"decorative", "all"}:
            html = strip_images(html, mode=str(body.remove_images).strip().lower()).text  # type: ignore[arg-type]
        extracted = extract_text_from_html(html, xpath=body.html_xpath)
        if body.html_xpath and extracted.xpath_error and extracted.xpath_error.startswith("xpath_failed:"):
            raise HTTPException(status_code=400, detail=f"Invalid XPath: {extracted.xpath_error}")
        input_text = extracted.text or ""

    frontmatter: dict | None = None
    title: str | None = None
    tags: list[str] | None = None
    if body.extract_frontmatter or body.strip_frontmatter:
        try:
            fm = extract_markdown_frontmatter(input_text, strip=bool(body.strip_frontmatter))
        except Exception:
            fm = None
        if fm is not None:
            data = getattr(fm, "data", None)
            if isinstance(data, dict) and data:
                frontmatter = dict(data)
                raw_title = frontmatter.get("title")
                if isinstance(raw_title, str) and raw_title.strip():
                    title = raw_title.strip()[:200]
                raw_tags = (
                    frontmatter.get("tags")
                    or frontmatter.get("tag")
                    or frontmatter.get("categories")
                    or frontmatter.get("category")
                    or frontmatter.get("keywords")
                )
                if isinstance(raw_tags, list):
                    cleaned: list[str] = []
                    seen: set[str] = set()
                    for item in raw_tags:
                        if item is None:
                            continue
                        s = str(item).strip()
                        if not s:
                            continue
                        key = s.casefold()
                        if key in seen:
                            continue
                        seen.add(key)
                        cleaned.append(s[:64])
                    if cleaned:
                        tags = cleaned[:50]
                elif isinstance(raw_tags, str) and raw_tags.strip():
                    parts = [p.strip() for p in raw_tags.replace(";", ",").split(",") if p.strip()]
                    if parts:
                        tags = parts[:50]

            if body.strip_frontmatter:
                input_text = getattr(fm, "stripped_text", input_text) or ""

    baseline_text = input_text or ""

    analysis_opts = {
        "remove_control_chars": bool(body.remove_control_chars),
        "unwrap_lines": bool(body.unwrap_lines),
        "remove_common_lines": bool(body.remove_common_lines),
        "remove_boilerplate": bool(body.remove_boilerplate),
        "normalize_tables": bool(body.normalize_tables),
        "normalize_urls": bool(body.normalize_urls),
        "normalize_urls_strip_tracking": bool(body.normalize_urls_strip_tracking),
        "remove_images": str(body.remove_images or "none"),
        "drop_outline_only": bool(body.drop_outline_only),
        "drop_outline_min_content_chars": int(body.drop_outline_min_content_chars or 0),
        "drop_outline_max_heading_ratio": float(body.drop_outline_max_heading_ratio or 0.0),
        "drop_low_density": bool(body.drop_low_density),
        "drop_low_density_threshold": float(body.drop_low_density_threshold or 0.0),
    }

    def _analyze(after_text: str) -> tuple[list[GovernanceIssue], dict[str, object]]:
        issues, patch = analyze_governance(
            baseline_text,
            after_text,
            input_format=str(body.input_format or "markdown"),
            options=analysis_opts,
        )
        out: list[GovernanceIssue] = []
        for it in issues:
            out.append(
                GovernanceIssue(
                    code=str(it.code),
                    severity=it.severity,  # type: ignore[arg-type]
                    message=str(it.message),
                    count=int(getattr(it, "count", 0) or 0),
                    samples=list(getattr(it, "samples", None) or []),
                    suggested_pipeline_patch=dict(getattr(it, "suggested_pipeline_patch", None) or {}),
                )
            )
        return out, dict(patch or {})

    # Build rules with lightweight attribution so the UI can show which pack/default/custom produced a hit.
    rules: list[RegexRule] = []
    rule_meta: list[dict] = []

    base_rules = list(DEFAULT_MARKDOWN_RULES) if body.use_default_rules else []
    for r in base_rules:
        rules.append(r)
        rule_meta.append({"source": "default", "pack": None})

    if getattr(body, "rule_packs", None):
        seen: set[str] = set()
        for raw in (body.rule_packs or []):
            if not isinstance(raw, str):
                continue
            key = raw.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            pack = GOVERNANCE_RULE_PACKS.get(key)
            if not pack:
                continue
            for r in pack:
                rules.append(r)
                rule_meta.append({"source": "pack", "pack": key})

    try:
        custom_rules_norm = validate_regex_rules(body.rules)
    except RegexRulesValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.to_detail()) from exc

    custom_rules = [RegexRule(pattern=r["pattern"], repl=r["repl"], flags=r["flags"]) for r in (custom_rules_norm or [])]
    for r in custom_rules:
        rules.append(r)
        rule_meta.append({"source": "custom", "pack": None})
    common_lines = (
        build_repeated_line_signatures(
            baseline_text,
            min_occurrences=body.common_lines_min_occurrences,
            max_line_length=body.unwrap_max_line_length,
        )
        if body.remove_common_lines
        else None
    )
    try:
        result = clean_markdown(
            baseline_text,
            rules=rules,
            regex_timeout_ms=int(getattr(settings, "GOVERNANCE_REGEX_TIMEOUT_MS", 100) or 100),
            normalize_line_endings=body.normalize_line_endings,
            trim_trailing_spaces=body.trim_trailing_spaces,
            collapse_blank_lines=body.collapse_blank_lines,
            max_blank_lines=body.max_blank_lines,
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
    except RegexSubstitutionTimeoutError as exc:
        raise HTTPException(status_code=400, detail=exc.to_detail()) from exc

    rule_hits = list(getattr(result, "rule_hits", None) or [])
    rule_stats = []
    for i, r in enumerate(rules or []):
        meta = rule_meta[i] if i < len(rule_meta) and isinstance(rule_meta[i], dict) else {}
        rule_stats.append(
            {
                "index": i,
                "pattern": str(getattr(r, "pattern", "") or ""),
                "repl": (getattr(r, "repl", "") if isinstance(getattr(r, "repl", ""), str) else ""),
                "flags": int(getattr(r, "flags", 0) or 0),
                "hits": int(rule_hits[i] if i < len(rule_hits) else 0),
                "source": str(meta.get("source") or "") or None,
                "pack": str(meta.get("pack") or "") or None,
            }
        )

    text = result.markdown

    if body.normalize_tables:
        text = normalize_markdown_tables(text).text

    if body.strip_code_line_numbers:
        text = strip_fenced_code_line_numbers(text).text

    if body.remove_boilerplate:
        text = remove_markdown_boilerplate(text).text

    if str(body.remove_images or "none").strip().lower() in {"decorative", "all"}:
        text = strip_images(text, mode=str(body.remove_images).strip().lower()).text  # type: ignore[arg-type]

    pii_hits: dict[str, int] | None = None
    secrets_hits: dict[str, int] | None = None
    if body.pii_anonymize:
        pii = anonymize_pii(text, enabled=True, mode=str(body.pii_mode or "mask"), mask=str(body.pii_mask or REDACTED_MASK))  # type: ignore[arg-type]
        text = pii.text
        pii_hits = pii.hits or {}

    if body.secrets_redact:
        sec = redact_secrets(text, enabled=True, mode=str(body.secrets_mode or "mask"), mask=str(body.secrets_mask or SECRET_MASK))  # type: ignore[arg-type]
        text = sec.text
        secrets_hits = sec.hits or {}

    paragraphs_dropped = 0
    references_removed_lines = 0
    urls_changed = 0

    if body.drop_duplicate_paragraphs:
        try:
            para = drop_duplicate_paragraphs(
                text,
                min_occurrences=int(body.drop_duplicate_paragraphs_min_occurrences or 0),
                min_paragraph_chars=int(body.drop_duplicate_paragraphs_min_chars or 0),
                max_paragraph_chars=int(body.drop_duplicate_paragraphs_max_chars or 0),
            )
            text = para.text
            paragraphs_dropped = int(getattr(para, "paragraphs_dropped", 0) or 0)
        except Exception as exc:
            logger.debug("Ignoring non-critical pipeline fallback failure: %s", exc)

    if body.trim_references:
        try:
            ref = trim_references_section(text)
            text = ref.text
            references_removed_lines = int(getattr(ref, "removed_lines", 0) or 0)
        except Exception as exc:
            logger.debug("Ignoring non-critical pipeline fallback failure: %s", exc)

    if body.normalize_urls:
        try:
            url = normalize_urls(text, strip_tracking=bool(body.normalize_urls_strip_tracking))
            text = url.text
            urls_changed = int(getattr(url, "urls_changed", 0) or 0)
        except Exception as exc:
            logger.debug("Ignoring non-critical pipeline fallback failure: %s", exc)

    if body.drop_outline_only:
        decision = drop_if_outline_only(
            text,
            min_content_chars=int(body.drop_outline_min_content_chars or 0),
            max_heading_ratio=float(body.drop_outline_max_heading_ratio or 0.0),
        )
        if decision.dropped:
            added, removed, changed_lines = _line_diff_stats(baseline_text, "")
            diff_unified, diff_truncated = (None, False)
            if body.include_diff:
                diff_unified, diff_truncated = _unified_diff_text(baseline_text, "", max_lines=body.diff_max_lines)
            issues_out, suggested_patch = _analyze("")
            return CleanPreviewResponse(
                markdown="",
                applied_rules=result.applied_rules,
                changed=True,
                rule_stats=rule_stats,
                dropped=True,
                drop_reason=decision.reason or "outline_only",
                pii_hits=pii_hits,
                secrets_hits=secrets_hits,
                frontmatter=frontmatter,
                title=title,
                tags=tags,
                urls_changed=int(urls_changed),
                paragraphs_dropped=int(paragraphs_dropped),
                references_removed_lines=int(references_removed_lines),
                input_chars=len(baseline_text),
                output_chars=0,
                input_lines=len((baseline_text or "").splitlines()),
                output_lines=0,
                added_lines=added,
                removed_lines=removed,
                changed_lines=changed_lines,
                diff_unified=diff_unified,
                diff_truncated=bool(diff_truncated),
                issues=issues_out,
                suggested_pipeline_patch=suggested_patch,
            )

    if body.drop_low_density:
        decision = drop_if_low_density(text, threshold=float(body.drop_low_density_threshold or 0.0))
        if decision.dropped:
            added, removed, changed_lines = _line_diff_stats(baseline_text, "")
            diff_unified, diff_truncated = (None, False)
            if body.include_diff:
                diff_unified, diff_truncated = _unified_diff_text(baseline_text, "", max_lines=body.diff_max_lines)
            issues_out, suggested_patch = _analyze("")
            return CleanPreviewResponse(
                markdown="",
                applied_rules=result.applied_rules,
                changed=True,
                rule_stats=rule_stats,
                dropped=True,
                drop_reason=decision.reason or "low_density",
                pii_hits=pii_hits,
                secrets_hits=secrets_hits,
                frontmatter=frontmatter,
                title=title,
                tags=tags,
                urls_changed=int(urls_changed),
                paragraphs_dropped=int(paragraphs_dropped),
                references_removed_lines=int(references_removed_lines),
                input_chars=len(baseline_text),
                output_chars=0,
                input_lines=len((baseline_text or "").splitlines()),
                output_lines=0,
                added_lines=added,
                removed_lines=removed,
                changed_lines=changed_lines,
                diff_unified=diff_unified,
                diff_truncated=bool(diff_truncated),
                issues=issues_out,
                suggested_pipeline_patch=suggested_patch,
            )

    if title is None:
        try:
            title = extract_markdown_title(text)
        except Exception:
            title = None

    language: str | None = None
    language_confidence: float | None = None
    if body.detect_language:
        try:
            lang = detect_language(text, min_chars=int(body.language_min_chars or 0))
            language = str(getattr(lang, "language", "") or "").strip() or None
            language_confidence = float(getattr(lang, "confidence", 0.0) or 0.0)
        except Exception:
            language = None
            language_confidence = None

    keywords: list[str] | None = None
    if body.extract_keywords:
        try:
            max_chars = max(0, int(body.keywords_max_chars or 0))
            snippet = text[:max_chars] if max_chars > 0 else text
            kws = extract_keywords_preview(
                snippet,
                provider=str(body.keywords_provider or "auto"),
                top_k=int(body.keywords_top_k or 10),
            )
            keywords = list(kws) if kws else None
        except Exception:
            keywords = None

    diff_unified, diff_truncated = (None, False)
    if body.include_diff:
        diff_unified, diff_truncated = _unified_diff_text(baseline_text, text, max_lines=body.diff_max_lines)
    added, removed, changed_lines = _line_diff_stats(baseline_text, text)
    issues_out, suggested_patch = _analyze(text)
    return CleanPreviewResponse(
        markdown=text,
        applied_rules=result.applied_rules,
        changed=bool(text != baseline_text),
        rule_stats=rule_stats,
        dropped=False,
        drop_reason=None,
        pii_hits=pii_hits,
        secrets_hits=secrets_hits,
        frontmatter=frontmatter,
        title=title,
        tags=tags,
        language=language,
        language_confidence=language_confidence,
        keywords=keywords,
        urls_changed=int(urls_changed),
        paragraphs_dropped=int(paragraphs_dropped),
        references_removed_lines=int(references_removed_lines),
        input_chars=len(baseline_text),
        output_chars=len(text or ""),
        input_lines=len((baseline_text or "").splitlines()),
        output_lines=len((text or "").splitlines()),
        added_lines=added,
        removed_lines=removed,
        changed_lines=changed_lines,
        diff_unified=diff_unified,
        diff_truncated=bool(diff_truncated),
        issues=issues_out,
        suggested_pipeline_patch=suggested_patch,
    )


@router.post("/learn-common-lines", response_model=GovernanceCommonLinesLearnResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def learn_common_lines(
    body: GovernanceCommonLinesLearnRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Learn common/repeated header/footer lines across multiple documents in a dataset.

    This endpoint is intended to support "learning mode" in the governance UI:
    discover candidate lines, then turn them into regex rules and write into a custom profile.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = DatasetService.get_dataset(db, tenant_id, body.dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    total, texts = _collect_common_lines_texts(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=body.dataset_id,
        limit_docs=int(body.limit_docs),
        use_original=bool(body.use_original),
    )

    if len(texts) < 2:
        raise HTTPException(
            status_code=400,
            detail="Not enough documents with persisted parsed content. Enable persist_parsed_content and ingest some documents first.",
        )

    candidates_raw = learn_common_line_candidates(
        texts,
        min_docs=int(body.min_docs),
        min_ratio=float(body.min_ratio),
        max_line_length=int(body.max_line_length),
        max_candidates=int(body.max_candidates),
    )
    candidates = [
        GovernanceCommonLineCandidate(
            signature=str(it.get("signature") or ""),
            sample=str(it.get("sample") or "")[:400],
            docs=int(it.get("docs") or 0),
            ratio=float(it.get("ratio") or 0.0),
        )
        for it in candidates_raw
        if isinstance(it, dict) and str(it.get("signature") or "").strip()
    ]

    return GovernanceCommonLinesLearnResponse(
        dataset_id=body.dataset_id,
        total_documents=int(total),
        used_documents=int(len(texts)),
        candidates=candidates,
    )


@router.post("/governance-analyze", response_model=GovernanceAnalyzeResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def governance_analyze(
    body: GovernanceAnalyzeRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Analyze a text for governance issues without performing cleaning/persistence.

    This is intended for "quality check" UI flows to recommend治理配置/预设。
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    raw_input = body.markdown or ""
    input_text = raw_input
    if body.input_format == "html":
        html = raw_input
        if str(body.remove_images or "none").strip().lower() in {"decorative", "all"}:
            html = strip_images(html, mode=str(body.remove_images).strip().lower()).text  # type: ignore[arg-type]
        extracted = extract_text_from_html(html, xpath=body.html_xpath)
        if body.html_xpath and extracted.xpath_error and extracted.xpath_error.startswith("xpath_failed:"):
            raise HTTPException(status_code=400, detail=f"Invalid XPath: {extracted.xpath_error}")
        input_text = extracted.text or ""

    analysis_opts = {
        "remove_control_chars": bool(body.remove_control_chars),
        "unwrap_lines": bool(body.unwrap_lines),
        "remove_common_lines": bool(body.remove_common_lines),
        "remove_boilerplate": bool(body.remove_boilerplate),
        "normalize_tables": bool(body.normalize_tables),
        "normalize_urls": bool(body.normalize_urls),
        "normalize_urls_strip_tracking": bool(body.normalize_urls_strip_tracking),
        "remove_images": str(body.remove_images or "none"),
        "drop_outline_only": bool(body.drop_outline_only),
        "drop_outline_min_content_chars": int(body.drop_outline_min_content_chars or 0),
        "drop_outline_max_heading_ratio": float(body.drop_outline_max_heading_ratio or 0.0),
        "drop_low_density": bool(body.drop_low_density),
        "drop_low_density_threshold": float(body.drop_low_density_threshold or 0.0),
    }

    issues, patch = analyze_governance(
        input_text or "",
        "",
        input_format=str(body.input_format or "markdown"),
        options=analysis_opts,
    )
    out_issues: list[GovernanceIssue] = []
    for it in issues:
        out_issues.append(
            GovernanceIssue(
                code=str(it.code),
                severity=it.severity,  # type: ignore[arg-type]
                message=str(it.message),
                count=int(getattr(it, "count", 0) or 0),
                samples=list(getattr(it, "samples", None) or []),
                suggested_pipeline_patch=dict(getattr(it, "suggested_pipeline_patch", None) or {}),
            )
        )

    base = input_text or ""
    return GovernanceAnalyzeResponse(
        input_chars=len(base),
        input_lines=len(base.splitlines()),
        issues=out_issues,
        suggested_pipeline_patch=dict(patch or {}),
    )


@router.get("/clean-rules", response_model=CleanRulesResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def list_clean_rules(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Return default governance rules for UI selection/editing.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    return CleanRulesResponse(
        rules=[CleanRegexRuleModel(pattern=r.pattern, repl=r.repl, flags=r.flags) for r in DEFAULT_MARKDOWN_RULES]
    )


@router.post("/extract-keywords", response_model=KeywordExtractResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def extract_keywords(
    body: KeywordExtractRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
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
    )
    from app.rag.preprocessing.keyword import (
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


@router.post("/auto-annotations", response_model=AutoAnnotationResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def auto_annotations(
    body: AutoAnnotationRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Generate reviewable annotation candidates for the data-governance UI.

    Default mode extracts document-focus spans for human review:
    - LLM first when configured
    - local keyword/rule extraction as fallback
    - sensitive/compliance detectors only when explicitly requested

    Results are suggestions for human confirmation, not authoritative labels.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    source = str(body.text or "")
    total_chars = len(source)
    max_chars = max(1, min(int(body.max_chars or 20_000), 200_000))
    scan_text = source[:max_chars]
    max_items = max(1, min(int(body.max_annotations or 80), 500))

    candidates: list[AutoAnnotationItem] = []
    document_tags: list[AutoDocumentTag] = []
    keyword_provider: str | None = None
    warnings: list[str] = []
    providers_used: list[str] = []
    strategy = "rules"
    mode = str(body.mode or "document_focus").strip().lower()
    providers = _normalize_auto_annotation_providers(body)
    summary: str | None = None

    try:
        if mode == "document_focus":
            if "cpu" in providers:
                cpu_summary, cpu_tags, cpu_items = _collect_cpu_focus_annotations(
                    scan_text,
                    keyword_provider=str(body.keyword_provider or "simple"),
                    keyword_top_k=int(body.keyword_top_k or 12),
                    max_items=max_items,
                )
                if cpu_summary and summary is None:
                    summary = cpu_summary
                if cpu_tags:
                    document_tags.extend(cpu_tags)
                if cpu_items:
                    candidates.extend(cpu_items)
                    _append_provider_used(providers_used, "cpu")

            if "llm" in providers:
                try:
                    llm_summary, llm_tags, llm_items = await asyncio.wait_for(
                        _collect_llm_focus_annotations(
                            scan_text,
                            max_items=max_items,
                            max_chars=max_chars,
                            model=body.llm_model,
                        ),
                        timeout=_AUTO_TAGGER_LLM_TIMEOUT_S,
                    )
                    if llm_summary:
                        summary = llm_summary
                    if llm_tags:
                        document_tags.extend(llm_tags)
                    if llm_items:
                        candidates.extend(llm_items)
                    if llm_summary or llm_tags or llm_items:
                        _append_provider_used(providers_used, "llm")
                        strategy = "hybrid" if "cpu" in providers_used else "llm"
                except Exception:  # noqa: BLE001
                    warnings.append("LLM focus extraction unavailable; used rules fallback.")

            use_rule_fallback = not candidates or any(provider in providers for provider in {"keyword", "regex"})
            if len(candidates) < max_items and use_rule_fallback:
                keyword_provider, rule_items = _collect_rule_focus_annotations(
                    scan_text,
                    enable_keywords="keyword" in providers,
                    enable_entities="regex" in providers,
                    keyword_provider=str(body.keyword_provider or "simple"),
                    keyword_top_k=int(body.keyword_top_k or 12),
                    max_items=max_items - len(candidates),
                )
                if rule_items:
                    candidates.extend(rule_items)
                    if any(str(item.source) == "keyword" for item in rule_items):
                        _append_provider_used(providers_used, "keyword")
                    if any(str(item.source) == "regex_entity" for item in rule_items):
                        _append_provider_used(providers_used, "regex")
                    if any(str(item.source) == "rule_focus" for item in rule_items):
                        _append_provider_used(providers_used, "rule_focus")
                    strategy = "hybrid" if strategy == "llm" else "rules"

            if "gliner" in providers and len(candidates) < max_items:
                gliner_items = await _collect_gliner_entity_annotations(scan_text, max_items=max_items - len(candidates))
                if gliner_items:
                    candidates.extend(gliner_items)
                    _append_provider_used(providers_used, "gliner")
                    strategy = "hybrid" if strategy == "llm" else "rules"

            sensitive_providers = providers & {"pii", "secret"}
            if sensitive_providers and len(candidates) < max_items:
                sensitive_items = _collect_sensitive_annotations(
                    scan_text,
                    max_items=max_items - len(candidates),
                    providers=sensitive_providers,
                )
                candidates.extend(sensitive_items)
                for source in {str(item.source) for item in sensitive_items}:
                    _append_provider_used(providers_used, source)
                strategy = "hybrid" if candidates else strategy
        else:
            sensitive_providers = providers & {"pii", "secret"}
            if sensitive_providers:
                sensitive_items = _collect_sensitive_annotations(
                    scan_text,
                    max_items=max_items,
                    providers=sensitive_providers,
                )
                candidates.extend(sensitive_items)
                for source in {str(item.source) for item in sensitive_items}:
                    _append_provider_used(providers_used, source)

            if "gliner" in providers and len(candidates) < max_items:
                gliner_items = await _collect_gliner_entity_annotations(scan_text, max_items=max_items - len(candidates))
                candidates.extend(gliner_items)
                if gliner_items:
                    _append_provider_used(providers_used, "gliner")

            if "regex" in providers and len(candidates) < max_items:
                entity_items = _collect_entity_annotations(scan_text, max_items=max_items - len(candidates))
                candidates.extend(entity_items)
                if entity_items:
                    _append_provider_used(providers_used, "regex")

            if "keyword" in providers and len(candidates) < max_items:
                keyword_provider, keyword_items = _collect_keyword_annotations(
                    scan_text,
                    provider=str(body.keyword_provider or "simple"),
                    top_k=int(body.keyword_top_k or 12),
                    max_items=max_items - len(candidates),
                )
                candidates.extend(keyword_items)
                if keyword_items:
                    _append_provider_used(providers_used, "keyword")
            strategy = "rules"
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Auto annotation failed: {str(exc)}") from exc

    if keyword_provider is None and "keyword" in providers:
        keyword_provider = (str(body.keyword_provider or "simple").strip().lower() or "simple")
        if keyword_provider == "auto":
            keyword_provider = "simple"

    annotations = _dedupe_auto_annotations(candidates, max_items=max_items)
    if not document_tags:
        document_tags.extend(_derive_document_tags_from_annotations(annotations, max_items=max_items))
    document_tags = _dedupe_auto_document_tags(document_tags, max_items=max_items)
    return AutoAnnotationResponse(
        annotations=annotations,
        document_tags=document_tags,
        summary=summary,
        text_chars=total_chars,
        scanned_chars=len(scan_text),
        truncated=total_chars > len(scan_text),
        keyword_provider=keyword_provider,
        strategy=strategy,  # type: ignore[arg-type]
        providers_used=providers_used,
        warnings=warnings,
    )


@router.post("/llm-clean-preview", response_model=LLMCleanPreviewResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def llm_clean_preview(
    body: LLMCleanPreviewRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
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
        "You are a 'Markdown data governance cleaner'.\n"
        "Goal: Clean up noise and formatting issues from parsing/copying, but do not change semantics or fabricate content.\n"
        "Requirements:\n"
        "1) Preserve heading/list/table/code block structure; do not modify code block content.\n"
        "2) Remove obvious headers/footers/page numbers/TOC markers/repeated short lines/control characters/zero-width characters.\n"
        "3) Normalize whitespace: merge excess blank lines, remove trailing spaces, merge 'soft line breaks' when necessary.\n"
        "4) Do not translate or rewrite; only clean and normalize.\n"
        "Output: Return strict JSON with fields: markdown/changes/warnings.\n"
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
                    content=f"Input Markdown:\n```markdown\n{markdown}\n```",
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
                warnings.append("LLM did not return JSON schema; falling back to raw text.")

        warn_val = resp.get("warnings")
        if isinstance(warn_val, list):
            warnings.extend([str(w).strip() for w in warn_val if str(w).strip()])

    if not cleaned.strip():
        cleaned = markdown
        warnings.append("LLM returned empty; falling back to original text.")

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



@router.post("/upload-zip-with-images", response_model=ZipWithImagesResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def upload_zip_with_images(
    file: Annotated[UploadFile, File(...)],
    dataset_id: Annotated[str, Form(...)],
    document_id: Annotated[str | None, Form()] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
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
            detail="MinIO is disabled; cannot process image uploads. Set MINIO_ENABLED=true"
        )

    # Validate file type.
    if not file.filename.endswith('.zip'):
        raise HTTPException(
            status_code=400,
            detail="Only ZIP format files are supported"
        )

    try:
        dataset_uuid = UUID(str(dataset_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid dataset_id") from exc
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
            detail=f"Invalid ZIP format/content: {str(e)}",
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"ZIP processing failed: {str(e)}"
        ) from e
    finally:
        # Clean up temporary files.
        try:
            if temp_zip_path.exists():
                temp_zip_path.unlink()
        except Exception as exc:
            logger.debug("Ignoring non-critical pipeline fallback failure: %s", exc)
