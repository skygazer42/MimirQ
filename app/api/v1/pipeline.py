"""
Lightweight parsing and hierarchical chunk preview APIs:
- /pipeline/parse-preview: route parsing by file type (auto/Pandoc/MarkItDown/DeepDoc/MinerU/...), return Markdown + image refs
- /pipeline/chunk-preview: hierarchical Markdown chunking (paragraph/sentence) with highlight offsets
"""
import asyncio
import importlib.metadata as importlib_metadata
import json
import re
import shutil
import uuid
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher, unified_diff
from pathlib import Path
from typing import Annotated, Any
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
    PipelinePluginChunkReportRequest,
    PipelinePluginChunkReportResponse,
    PipelinePluginGoldenDraftImportRequest,
    PipelinePluginGoldenDraftImportResponse,
    PipelinePluginGoldenDraftRequest,
    PipelinePluginGoldenDraftResponse,
    PipelinePluginListResponse,
    ZipWithImagesResponse,
)
from app.api.utils.response_headers import download_response_headers
from app.api.utils.upload import save_upload_file
from app.core.config import settings
from app.core.database import get_db
from app.core.optional_deps import check_dependency
from app.core.pipeline_versions import build_doc_pipeline_key, get_active_pipeline_hash
from app.core.regex_runtime import RegexSubstitutionTimeoutError
from app.core.regex_safety import RegexRulesValidationError, validate_regex_rules
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk, DocumentParsedContent
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
from app.rag.pipeline_plugins.golden_drafts import build_golden_draft_bundle_from_chunks
from app.rag.pipeline_plugins.registry import (
    PipelinePluginRegistryError,
    default_plugin_directories,
    list_pipeline_plugins_with_errors,
    resolve_registered_plugin_descriptor,
)
from app.rag.pipeline_plugins.reports import (
    build_pipeline_plugin_chunk_report as build_pipeline_plugin_chunk_report_data,
)
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
# Redaction placeholder, not a credential.
SECRET_MASK = "[SECRET]"  # noqa: S105
_AUTO_TAGGER_LLM_TIMEOUT_S = 3.0
_TRIM_PUNCTUATION_CHARS = " \t\r\n，,。.;；:："
_TOPIC_KEYWORD_LABEL = "主题关键词"
_PIPELINE_FALLBACK_LOG_MESSAGE = "Ignoring non-critical pipeline fallback failure: %s"
_AUTO_PROVIDER_ALIASES = {
    "entity": ("regex",),
    "regex_entity": ("regex",),
    "sensitive": ("pii", "secret"),
}
_SENSITIVE_PROVIDER_SOURCES = {"pii", "secret"}
_FOCUS_SENTENCE_TERMS = ("知识库", "数据治理", "检索", "入库", "流程", "质量", "风险", "建议", "核心")
_FRONTMATTER_TAG_KEYS = ("tags", "tag", "categories", "category", "keywords")

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


@dataclass
class _AutoAnnotationDraft:
    candidates: list[AutoAnnotationItem] = field(default_factory=list)
    document_tags: list[AutoDocumentTag] = field(default_factory=list)
    keyword_provider: str | None = None
    warnings: list[str] = field(default_factory=list)
    providers_used: list[str] = field(default_factory=list)
    strategy: str = "rules"
    summary: str | None = None


def _trim_entity_span(raw: str) -> tuple[str, int]:
    """
    Trim common left-context words from regex entity candidates.

    Lightweight entity extraction intentionally stays dependency-free. This
    post-trim keeps matches like "项目由星海智能有限公司" usable without pretending
    to be a full NER model.
    """
    text = str(raw or "").strip(_TRIM_PUNCTUATION_CHARS)
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
        text = text[best_idx + 1 :].strip(_TRIM_PUNCTUATION_CHARS)
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
    while left < right and source_text[left] in _TRIM_PUNCTUATION_CHARS:
        left += 1
    while right > left and source_text[right - 1] in _TRIM_PUNCTUATION_CHARS:
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
    if token.startswith(("项目由", "本文")):
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


def _add_auto_annotation_provider(providers: set[str], raw_provider: object) -> None:
    provider = str(raw_provider or "").strip().lower()
    if not provider:
        return
    providers.update(_AUTO_PROVIDER_ALIASES.get(provider, (provider,)))


def _default_auto_annotation_providers(body: AutoAnnotationRequest) -> set[str]:
    providers = set()
    if str(body.mode or "document_focus").strip().lower() == "document_focus":
        providers.add("cpu")
    if body.enable_llm or body.enable_llm_topics:
        providers.add("llm")
    if body.enable_keywords:
        providers.add("keyword")
    if body.enable_entities:
        providers.add("regex")
    if body.enable_sensitive:
        providers.update(_SENSITIVE_PROVIDER_SOURCES)
    return providers


def _normalize_auto_annotation_providers(body: AutoAnnotationRequest) -> set[str]:
    if body.providers is None:
        return _default_auto_annotation_providers(body)

    providers: set[str] = set()
    for raw_provider in body.providers:
        _add_auto_annotation_provider(providers, raw_provider)
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


def _normalize_auto_document_tags(raw_tags: list[Any]) -> list[AutoDocumentTag]:
    document_tags: list[AutoDocumentTag] = []
    for tag in raw_tags:
        item = _make_auto_document_tag(
            tag_type=str(tag.type),
            value=tag.value,
            label=tag.label,
            confidence=float(tag.confidence),
            source=tag.source,
        )
        if item is not None:
            document_tags.append(item)
    return document_tags


def _normalize_span_annotations(
    text: str,
    raw_annotations: list[Any],
    *,
    max_items: int,
) -> list[AutoAnnotationItem]:
    annotations: list[AutoAnnotationItem] = []
    for raw in raw_annotations:
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
    return annotations


def _derive_document_tags_from_annotations(items: list[AutoAnnotationItem], *, max_items: int) -> list[AutoDocumentTag]:
    out: list[AutoDocumentTag] = []
    for item in items:
        tag_type = None
        label = ""
        if str(item.type) == "keyword" and str(item.label) == _TOPIC_KEYWORD_LABEL:
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
                label=_TOPIC_KEYWORD_LABEL,
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
                label=_TOPIC_KEYWORD_LABEL,
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


def _gliner_entity_confidence(entity: dict[str, Any]) -> float:
    try:
        confidence = float(entity.get("score") or 0.78)
    except Exception:
        confidence = 0.78
    return min(0.99, max(0.0, confidence))


def _make_gliner_entity_annotation(text: str, entity: dict[str, Any]) -> AutoAnnotationItem | None:
    quote = str(entity.get("evidence_quote") or entity.get("name") or "").strip()
    if not quote:
        return None

    label = str(entity.get("type") or "entity").strip() or "entity"
    for start, end in _find_keyword_offsets(text, quote, limit=1):
        return _make_auto_annotation(
            source_text=text,
            start=start,
            end=end,
            annotation_type="entity",
            label=label,
            confidence=_gliner_entity_confidence(entity),
            source="gliner",
        )
    return None


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
        item = _make_gliner_entity_annotation(text, entity)
        if item is not None:
            out.append(item)
        if len(out) >= max_items:
            break
    return out


def _append_sensitive_match_annotations(
    text: str,
    out: list[AutoAnnotationItem],
    matches: Iterable[Any],
    *,
    max_items: int,
    source: str,
    confidence: float,
) -> bool:
    for match in matches:
        item = _make_auto_annotation(
            source_text=text,
            start=int(match.start),
            end=int(match.end),
            annotation_type="sensitive",
            label=str(match.kind),
            confidence=confidence,
            source=source,
        )
        if item is not None:
            out.append(item)
        if len(out) >= max_items:
            return True
    return False


def _append_focus_rule_candidates(
    text: str,
    candidates: list[AutoAnnotationItem],
    blocked: list[AutoAnnotationItem],
    *,
    max_items: int,
) -> None:
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
                return


def _focus_sentence_has_signal(sentence: str) -> bool:
    return any(key in sentence for key in _FOCUS_SENTENCE_TERMS)


def _append_focus_sentence_candidate(
    text: str,
    candidates: list[AutoAnnotationItem],
    blocked: list[AutoAnnotationItem],
) -> None:
    for match in _FOCUS_SENTENCE_RE.finditer(text):
        sentence = (match.group(0) or "").strip()
        if not sentence or not _focus_sentence_has_signal(sentence):
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
            return


def _extend_focus_entity_candidates(
    text: str,
    candidates: list[AutoAnnotationItem],
    blocked: list[AutoAnnotationItem],
    *,
    max_items: int,
) -> None:
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
            return


def _collect_sensitive_annotations(
    text: str,
    *,
    max_items: int,
    providers: set[str] | None = None,
) -> list[AutoAnnotationItem]:
    provider_set = providers or _SENSITIVE_PROVIDER_SOURCES
    out: list[AutoAnnotationItem] = []
    if "pii" in provider_set and _append_sensitive_match_annotations(
        text,
        out,
        find_pii_matches(text, max_matches=max_items),
        max_items=max_items,
        source="pii",
        confidence=0.95,
    ):
        return out

    remaining = max_items - len(out)
    if remaining <= 0 or "secret" not in provider_set:
        return out

    _append_sensitive_match_annotations(
        text,
        out,
        find_secret_matches(text, max_matches=remaining),
        max_items=max_items,
        source="secret",
        confidence=0.98,
    )
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

    _append_focus_rule_candidates(text, candidates, blocked, max_items=max_items)
    if len(candidates) >= max_items:
        return None, candidates

    if not candidates:
        _append_focus_sentence_candidate(text, candidates, blocked)

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
        _extend_focus_entity_candidates(text, candidates, blocked, max_items=max_items)

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

    document_tags = _normalize_auto_document_tags(result.document_tags)
    annotations = _normalize_span_annotations(text, result.span_annotations, max_items=max_items)
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

    document_tags = _normalize_auto_document_tags(result.document_tags)
    annotations = _normalize_span_annotations(text, result.span_annotations, max_items=max_items)
    return result.summary, document_tags, annotations


def _remaining_auto_slots(draft: _AutoAnnotationDraft, max_items: int) -> int:
    return max(0, max_items - len(draft.candidates))


def _collect_cpu_auto_provider(draft: _AutoAnnotationDraft, scan_text: str, body: AutoAnnotationRequest, max_items: int) -> None:
    cpu_summary, cpu_tags, cpu_items = _collect_cpu_focus_annotations(
        scan_text,
        keyword_provider=str(body.keyword_provider or "simple"),
        keyword_top_k=int(body.keyword_top_k or 12),
        max_items=max_items,
    )
    if cpu_summary and draft.summary is None:
        draft.summary = cpu_summary
    draft.document_tags.extend(cpu_tags)
    draft.candidates.extend(cpu_items)
    if cpu_items:
        _append_provider_used(draft.providers_used, "cpu")


async def _collect_llm_auto_provider(draft: _AutoAnnotationDraft, scan_text: str, body: AutoAnnotationRequest, max_items: int) -> None:
    try:
        llm_summary, llm_tags, llm_items = await asyncio.wait_for(
            _collect_llm_focus_annotations(
                scan_text,
                max_items=max_items,
                max_chars=max(1, min(int(body.max_chars or 20_000), 200_000)),
                model=body.llm_model,
            ),
            timeout=_AUTO_TAGGER_LLM_TIMEOUT_S,
        )
    except Exception:
        draft.warnings.append("LLM focus extraction unavailable; used rules fallback.")
        return

    if llm_summary:
        draft.summary = llm_summary
    draft.document_tags.extend(llm_tags)
    draft.candidates.extend(llm_items)
    if llm_summary or llm_tags or llm_items:
        _append_provider_used(draft.providers_used, "llm")
        draft.strategy = "hybrid" if "cpu" in draft.providers_used else "llm"


def _collect_document_focus_rule_fallback(
    draft: _AutoAnnotationDraft,
    scan_text: str,
    body: AutoAnnotationRequest,
    providers: set[str],
    max_items: int,
) -> None:
    if _remaining_auto_slots(draft, max_items) <= 0:
        return
    if draft.candidates and not any(provider in providers for provider in {"keyword", "regex"}):
        return

    draft.keyword_provider, rule_items = _collect_rule_focus_annotations(
        scan_text,
        enable_keywords="keyword" in providers,
        enable_entities="regex" in providers,
        keyword_provider=str(body.keyword_provider or "simple"),
        keyword_top_k=int(body.keyword_top_k or 12),
        max_items=_remaining_auto_slots(draft, max_items),
    )
    draft.candidates.extend(rule_items)
    if not rule_items:
        return
    if any(str(item.source) == "keyword" for item in rule_items):
        _append_provider_used(draft.providers_used, "keyword")
    if any(str(item.source) == "regex_entity" for item in rule_items):
        _append_provider_used(draft.providers_used, "regex")
    if any(str(item.source) == "rule_focus" for item in rule_items):
        _append_provider_used(draft.providers_used, "rule_focus")
    draft.strategy = "hybrid" if draft.strategy == "llm" else "rules"


async def _collect_gliner_auto_provider(draft: _AutoAnnotationDraft, scan_text: str, max_items: int) -> list[AutoAnnotationItem]:
    if _remaining_auto_slots(draft, max_items) <= 0:
        return []
    gliner_items = await _collect_gliner_entity_annotations(scan_text, max_items=_remaining_auto_slots(draft, max_items))
    draft.candidates.extend(gliner_items)
    if gliner_items:
        _append_provider_used(draft.providers_used, "gliner")
    return gliner_items


def _collect_sensitive_auto_provider(
    draft: _AutoAnnotationDraft,
    scan_text: str,
    providers: set[str],
    max_items: int,
) -> list[AutoAnnotationItem]:
    sensitive_providers = providers & _SENSITIVE_PROVIDER_SOURCES
    if not sensitive_providers or _remaining_auto_slots(draft, max_items) <= 0:
        return []
    sensitive_items = _collect_sensitive_annotations(
        scan_text,
        max_items=_remaining_auto_slots(draft, max_items),
        providers=sensitive_providers,
    )
    draft.candidates.extend(sensitive_items)
    for source in {str(item.source) for item in sensitive_items}:
        _append_provider_used(draft.providers_used, source)
    return sensitive_items


def _collect_regex_auto_provider(draft: _AutoAnnotationDraft, scan_text: str, max_items: int) -> None:
    if _remaining_auto_slots(draft, max_items) <= 0:
        return
    entity_items = _collect_entity_annotations(scan_text, max_items=_remaining_auto_slots(draft, max_items))
    draft.candidates.extend(entity_items)
    if entity_items:
        _append_provider_used(draft.providers_used, "regex")


def _collect_keyword_auto_provider(draft: _AutoAnnotationDraft, scan_text: str, body: AutoAnnotationRequest, max_items: int) -> None:
    if _remaining_auto_slots(draft, max_items) <= 0:
        return
    draft.keyword_provider, keyword_items = _collect_keyword_annotations(
        scan_text,
        provider=str(body.keyword_provider or "simple"),
        top_k=int(body.keyword_top_k or 12),
        max_items=_remaining_auto_slots(draft, max_items),
    )
    draft.candidates.extend(keyword_items)
    if keyword_items:
        _append_provider_used(draft.providers_used, "keyword")


async def _collect_document_focus_annotations(
    draft: _AutoAnnotationDraft,
    scan_text: str,
    body: AutoAnnotationRequest,
    providers: set[str],
    max_items: int,
) -> None:
    if "cpu" in providers:
        _collect_cpu_auto_provider(draft, scan_text, body, max_items)
    if "llm" in providers:
        await _collect_llm_auto_provider(draft, scan_text, body, max_items)

    _collect_document_focus_rule_fallback(draft, scan_text, body, providers, max_items)

    if "gliner" in providers:
        gliner_items = await _collect_gliner_auto_provider(draft, scan_text, max_items)
        if gliner_items:
            draft.strategy = "hybrid" if draft.strategy == "llm" else "rules"

    if providers & _SENSITIVE_PROVIDER_SOURCES and _remaining_auto_slots(draft, max_items) > 0:
        _collect_sensitive_auto_provider(draft, scan_text, providers, max_items)
        draft.strategy = "hybrid" if draft.candidates else draft.strategy


async def _collect_compliance_annotations(
    draft: _AutoAnnotationDraft,
    scan_text: str,
    body: AutoAnnotationRequest,
    providers: set[str],
    max_items: int,
) -> None:
    _collect_sensitive_auto_provider(draft, scan_text, providers, max_items)
    if "gliner" in providers:
        await _collect_gliner_auto_provider(draft, scan_text, max_items)
    if "regex" in providers:
        _collect_regex_auto_provider(draft, scan_text, max_items)
    if "keyword" in providers:
        _collect_keyword_auto_provider(draft, scan_text, body, max_items)
    draft.strategy = "rules"


def _finalize_auto_annotation_keyword_provider(
    keyword_provider: str | None,
    body: AutoAnnotationRequest,
    providers: set[str],
) -> str | None:
    if keyword_provider is not None or "keyword" not in providers:
        return keyword_provider
    provider = str(body.keyword_provider or "simple").strip().lower() or "simple"
    return "simple" if provider == "auto" else provider


def _count_dataset_parsed_content(db: Session, tenant_id: UUID, dataset_id: UUID) -> int:
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
    return int(total or 0)


def _candidate_common_line_doc_ids(db: Session, tenant_id: UUID, dataset_id: UUID) -> list[UUID]:
    rows = (
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
    return [row[0] for row in rows if row and row[0]]


def _allowed_common_line_doc_ids(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    raw_doc_ids: list[UUID],
    limit_docs: int,
) -> list[UUID]:
    allowed_ids, _missing = get_allowed_document_id_sets(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        doc_ids=raw_doc_ids,
        check_member=False,
    )
    return [doc_id for doc_id in raw_doc_ids if doc_id in allowed_ids][: int(limit_docs or 20)]


def _parsed_content_by_doc_id(
    db: Session,
    tenant_id: UUID,
    doc_ids: list[UUID],
) -> dict[UUID, tuple[str, str]]:
    rows = (
        db.query(
            DocumentParsedContent.document_id,
            DocumentParsedContent.original_markdown_content,
            DocumentParsedContent.markdown_content,
        )
        .filter(
            DocumentParsedContent.tenant_id == tenant_id,
            DocumentParsedContent.document_id.in_(doc_ids),
        )
        .all()
    )
    return {doc_id: (str(original or ""), str(cleaned or "")) for doc_id, original, cleaned in rows}


def _select_common_line_text(original: str, cleaned: str, *, use_original: bool) -> str:
    if use_original and original.strip():
        return original
    if cleaned.strip():
        return cleaned
    return original


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
    total_with_content = _count_dataset_parsed_content(db, tenant_id, dataset_id)

    # Pull a small batch of latest docs with parsed content, then enforce document ACL.
    # We over-fetch to avoid ending up with too few after ACL filtering.
    raw_doc_ids = _candidate_common_line_doc_ids(db, tenant_id, dataset_id)
    allowed_ordered = _allowed_common_line_doc_ids(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        raw_doc_ids=raw_doc_ids,
        limit_docs=limit_docs,
    )
    if not allowed_ordered:
        return total_with_content, []

    by_id = _parsed_content_by_doc_id(db, tenant_id, allowed_ordered)
    texts: list[str] = []
    for doc_id in allowed_ordered:
        original, cleaned = by_id.get(doc_id, ("", ""))
        text = _select_common_line_text(original, cleaned, use_original=use_original)
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


def _resolve_custom_profile_row(
    *,
    db: Session,
    tenant_id: UUID,
    profile_ref: str,
) -> DBGovernanceProfile:
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
    return row


@dataclass
class _GovernanceProfileImportRecord:
    name: str
    key: str | None
    description: str | None
    payload: GovernanceProfilePayload


async def _read_governance_profile_import_json(file: UploadFile) -> object:
    max_bytes = 256 * 1024
    raw = await file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Profile script too large (max={max_bytes} bytes)")
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON file") from exc


def _raw_governance_profile_import_items(data: object) -> list[object]:
    if isinstance(data, dict) and isinstance(data.get("profiles"), list):
        return list(data.get("profiles") or [])
    return [data]


def _reject_unknown_import_keys(item: dict[str, object], allowed: set[str], *, label: str) -> None:
    unknown_keys = set(item.keys()) - allowed
    if unknown_keys:
        unknown_sorted = ", ".join(sorted(map(str, unknown_keys))[:20])
        raise HTTPException(status_code=400, detail=f"Unknown {label} fields: {unknown_sorted}")


def _normalize_governance_profile_import_record(item: object) -> _GovernanceProfileImportRecord:
    if not isinstance(item, dict):
        raise HTTPException(status_code=400, detail="Invalid profile item (expected object)")

    _reject_unknown_import_keys(item, {"name", "description", "key", "payload"}, label="profile")
    name = str(item.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name is required")

    try:
        key = validate_profile_key(item.get("key"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload_raw = item.get("payload")
    if not isinstance(payload_raw, dict):
        raise HTTPException(status_code=400, detail="payload is required and must be an object")

    _reject_unknown_import_keys(
        payload_raw,
        {"version", "extends", "input_formats", "pipeline_patch", "regex_rules", "processing_scripts"},
        label="payload",
    )
    try:
        payload = GovernanceProfilePayload(**payload_raw)
        payload = validate_and_normalize_payload(payload)
    except RegexRulesValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.to_detail()) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(exc)[:200]}") from exc

    description = item.get("description")
    desc = str(description or "").strip()[:2000] if description is not None else None
    return _GovernanceProfileImportRecord(name=name, key=key, description=desc, payload=payload)


def _find_existing_governance_profile(
    db: Session,
    tenant_id: UUID,
    key: str | None,
) -> DBGovernanceProfile | None:
    if not key:
        return None
    return (
        db.query(DBGovernanceProfile)
        .filter(DBGovernanceProfile.tenant_id == tenant_id, DBGovernanceProfile.key == key)
        .first()
    )


def _upsert_governance_profile_import_record(
    *,
    db: Session,
    tenant_id: UUID,
    record: _GovernanceProfileImportRecord,
    overwrite: bool,
) -> tuple[int, int, GovernanceProfileSummary]:
    existing = _find_existing_governance_profile(db, tenant_id, record.key)
    if existing is not None:
        if not overwrite:
            raise HTTPException(status_code=409, detail=f"Profile key already exists: {record.key}")
        existing.name = record.name[:200]
        existing.description = record.description
        existing.payload = record.payload.model_dump()
        return 0, 1, _profile_summary_from_row(existing)

    row = DBGovernanceProfile(
        tenant_id=tenant_id,
        key=record.key,
        name=record.name[:200],
        description=record.description,
        is_system=False,
        payload=record.payload.model_dump(),
    )
    db.add(row)
    db.flush()
    return 1, 0, _profile_summary_from_row(row)


def _governance_analysis_options(body: CleanPreviewRequest | GovernanceAnalyzeRequest) -> dict[str, object]:
    return {
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


def _remove_images_mode(body: CleanPreviewRequest | GovernanceAnalyzeRequest) -> str:
    return str(body.remove_images or "none").strip().lower()


def _extract_governance_input_text(body: CleanPreviewRequest | GovernanceAnalyzeRequest) -> str:
    raw_input = body.markdown or ""
    if body.input_format != "html":
        return raw_input

    html = raw_input
    if _remove_images_mode(body) in {"decorative", "all"}:
        html = strip_images(html, mode=_remove_images_mode(body)).text  # type: ignore[arg-type]
    extracted = extract_text_from_html(html, xpath=body.html_xpath)
    if body.html_xpath and extracted.xpath_error and extracted.xpath_error.startswith("xpath_failed:"):
        raise HTTPException(status_code=400, detail=f"Invalid XPath: {extracted.xpath_error}")
    return extracted.text or ""


def _governance_issue_models(raw_issues: list[Any]) -> list[GovernanceIssue]:
    out: list[GovernanceIssue] = []
    for it in raw_issues:
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
    return out


def _analyze_governance_preview(
    baseline_text: str,
    after_text: str,
    body: CleanPreviewRequest | GovernanceAnalyzeRequest,
    analysis_opts: dict[str, object],
) -> tuple[list[GovernanceIssue], dict[str, object]]:
    issues, patch = analyze_governance(
        baseline_text,
        after_text,
        input_format=str(body.input_format or "markdown"),
        options=analysis_opts,
    )
    return _governance_issue_models(issues), dict(patch or {})


def _normalize_frontmatter_tags(raw_tags: object) -> list[str] | None:
    if isinstance(raw_tags, list):
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in raw_tags:
            if item is None:
                continue
            value = str(item).strip()
            key = value.casefold()
            if not value or key in seen:
                continue
            seen.add(key)
            cleaned.append(value[:64])
        return cleaned[:50] or None

    if isinstance(raw_tags, str) and raw_tags.strip():
        parts = [part.strip() for part in raw_tags.replace(";", ",").split(",") if part.strip()]
        return parts[:50] or None
    return None


def _extract_clean_preview_frontmatter(
    input_text: str,
    body: CleanPreviewRequest,
) -> tuple[str, dict[str, Any] | None, str | None, list[str] | None]:
    if not (body.extract_frontmatter or body.strip_frontmatter):
        return input_text, None, None, None

    try:
        fm = extract_markdown_frontmatter(input_text, strip=bool(body.strip_frontmatter))
    except Exception:
        fm = None
    if fm is None:
        return input_text, None, None, None

    data = getattr(fm, "data", None)
    frontmatter = dict(data) if isinstance(data, dict) and data else None
    title = None
    tags = None
    if frontmatter:
        raw_title = frontmatter.get("title")
        if isinstance(raw_title, str) and raw_title.strip():
            title = raw_title.strip()[:200]
        raw_tags = next((frontmatter.get(key) for key in _FRONTMATTER_TAG_KEYS if frontmatter.get(key)), None)
        tags = _normalize_frontmatter_tags(raw_tags)

    if body.strip_frontmatter:
        input_text = getattr(fm, "stripped_text", input_text) or ""
    return input_text, frontmatter, title, tags


def _append_clean_preview_rules(
    rules: list[RegexRule],
    rule_meta: list[dict[str, object]],
    new_rules: Iterable[RegexRule],
    *,
    source: str,
    pack: str | None,
) -> None:
    for rule in new_rules:
        rules.append(rule)
        rule_meta.append({"source": source, "pack": pack})


def _selected_rule_pack_keys(raw_packs: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    keys: list[str] = []
    for raw in raw_packs:
        if not isinstance(raw, str):
            continue
        key = raw.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def _build_clean_preview_rules(body: CleanPreviewRequest) -> tuple[list[RegexRule], list[dict[str, object]]]:
    rules: list[RegexRule] = []
    rule_meta: list[dict[str, object]] = []
    if body.use_default_rules:
        _append_clean_preview_rules(rules, rule_meta, DEFAULT_MARKDOWN_RULES, source="default", pack=None)

    for key in _selected_rule_pack_keys(body.rule_packs or []):
        pack = GOVERNANCE_RULE_PACKS.get(key)
        if pack:
            _append_clean_preview_rules(rules, rule_meta, pack, source="pack", pack=key)

    try:
        custom_rules_norm = validate_regex_rules(body.rules)
    except RegexRulesValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.to_detail()) from exc

    custom_rules = [RegexRule(pattern=r["pattern"], repl=r["repl"], flags=r["flags"]) for r in (custom_rules_norm or [])]
    _append_clean_preview_rules(rules, rule_meta, custom_rules, source="custom", pack=None)
    return rules, rule_meta


def _clean_preview_rule_stats(
    rules: list[RegexRule],
    rule_meta: list[dict[str, object]],
    rule_hits: list[int],
) -> list[dict[str, object]]:
    rule_stats: list[dict[str, object]] = []
    for i, rule in enumerate(rules or []):
        meta = rule_meta[i] if i < len(rule_meta) and isinstance(rule_meta[i], dict) else {}
        rule_stats.append(
            {
                "index": i,
                "pattern": str(getattr(rule, "pattern", "") or ""),
                "repl": (getattr(rule, "repl", "") if isinstance(getattr(rule, "repl", ""), str) else ""),
                "flags": int(getattr(rule, "flags", 0) or 0),
                "hits": int(rule_hits[i] if i < len(rule_hits) else 0),
                "source": str(meta.get("source") or "") or None,
                "pack": str(meta.get("pack") or "") or None,
            }
        )
    return rule_stats


def _apply_preview_format_transforms(text: str, body: CleanPreviewRequest) -> str:
    if body.normalize_tables:
        text = normalize_markdown_tables(text).text
    if body.strip_code_line_numbers:
        text = strip_fenced_code_line_numbers(text).text
    if body.remove_boilerplate:
        text = remove_markdown_boilerplate(text).text
    if _remove_images_mode(body) in {"decorative", "all"}:
        text = strip_images(text, mode=_remove_images_mode(body)).text  # type: ignore[arg-type]
    return text


def _apply_preview_sensitive_redaction(
    text: str,
    body: CleanPreviewRequest,
) -> tuple[str, dict[str, int] | None, dict[str, int] | None]:
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
    return text, pii_hits, secrets_hits


def _try_drop_duplicate_paragraphs(text: str, body: CleanPreviewRequest) -> tuple[str, int]:
    if not body.drop_duplicate_paragraphs:
        return text, 0
    try:
        para = drop_duplicate_paragraphs(
            text,
            min_occurrences=int(body.drop_duplicate_paragraphs_min_occurrences or 0),
            min_paragraph_chars=int(body.drop_duplicate_paragraphs_min_chars or 0),
            max_paragraph_chars=int(body.drop_duplicate_paragraphs_max_chars or 0),
        )
        return para.text, int(getattr(para, "paragraphs_dropped", 0) or 0)
    except Exception as exc:
        logger.debug(_PIPELINE_FALLBACK_LOG_MESSAGE, exc)
        return text, 0


def _try_trim_references(text: str, body: CleanPreviewRequest) -> tuple[str, int]:
    if not body.trim_references:
        return text, 0
    try:
        ref = trim_references_section(text)
        return ref.text, int(getattr(ref, "removed_lines", 0) or 0)
    except Exception as exc:
        logger.debug(_PIPELINE_FALLBACK_LOG_MESSAGE, exc)
        return text, 0


def _try_normalize_urls(text: str, body: CleanPreviewRequest) -> tuple[str, int]:
    if not body.normalize_urls:
        return text, 0
    try:
        url = normalize_urls(text, strip_tracking=bool(body.normalize_urls_strip_tracking))
        return url.text, int(getattr(url, "urls_changed", 0) or 0)
    except Exception as exc:
        logger.debug(_PIPELINE_FALLBACK_LOG_MESSAGE, exc)
        return text, 0


def _apply_preview_cleanup_stats(text: str, body: CleanPreviewRequest) -> tuple[str, int, int, int]:
    text, paragraphs_dropped = _try_drop_duplicate_paragraphs(text, body)
    text, references_removed_lines = _try_trim_references(text, body)
    text, urls_changed = _try_normalize_urls(text, body)
    return text, paragraphs_dropped, references_removed_lines, urls_changed


def _preview_drop_reason(text: str, body: CleanPreviewRequest) -> str | None:
    if body.drop_outline_only:
        decision = drop_if_outline_only(
            text,
            min_content_chars=int(body.drop_outline_min_content_chars or 0),
            max_heading_ratio=float(body.drop_outline_max_heading_ratio or 0.0),
        )
        if decision.dropped:
            return decision.reason or "outline_only"
    if body.drop_low_density:
        decision = drop_if_low_density(text, threshold=float(body.drop_low_density_threshold or 0.0))
        if decision.dropped:
            return decision.reason or "low_density"
    return None


def _extract_preview_title(text: str, current_title: str | None) -> str | None:
    if current_title is not None:
        return current_title
    try:
        return extract_markdown_title(text)
    except Exception:
        return None


def _detect_preview_language(text: str, body: CleanPreviewRequest) -> tuple[str | None, float | None]:
    if not body.detect_language:
        return None, None
    try:
        lang = detect_language(text, min_chars=int(body.language_min_chars or 0))
        language = str(getattr(lang, "language", "") or "").strip() or None
        confidence = float(getattr(lang, "confidence", 0.0) or 0.0)
        return language, confidence
    except Exception:
        return None, None


def _extract_preview_keywords(text: str, body: CleanPreviewRequest) -> list[str] | None:
    if not body.extract_keywords:
        return None
    try:
        max_chars = max(0, int(body.keywords_max_chars or 0))
        snippet = text[:max_chars] if max_chars > 0 else text
        keywords = extract_keywords_preview(
            snippet,
            provider=str(body.keywords_provider or "auto"),
            top_k=int(body.keywords_top_k or 10),
        )
        return list(keywords) if keywords else None
    except Exception:
        return None


@dataclass
class _CleanPreviewResponseContext:
    baseline_text: str
    body: CleanPreviewRequest
    clean_result: Any
    rule_stats: list[dict[str, object]]
    pii_hits: dict[str, int] | None
    secrets_hits: dict[str, int] | None
    frontmatter: dict[str, Any] | None
    title: str | None
    tags: list[str] | None
    urls_changed: int
    paragraphs_dropped: int
    references_removed_lines: int
    analysis_opts: dict[str, object]
    language: str | None = None
    language_confidence: float | None = None
    keywords: list[str] | None = None


def _build_clean_preview_response(
    context: _CleanPreviewResponseContext,
    *,
    markdown: str,
    dropped: bool,
    drop_reason: str | None,
) -> CleanPreviewResponse:
    diff_unified, diff_truncated = (None, False)
    if context.body.include_diff:
        diff_unified, diff_truncated = _unified_diff_text(
            context.baseline_text,
            markdown,
            max_lines=context.body.diff_max_lines,
        )
    added, removed, changed_lines = _line_diff_stats(context.baseline_text, markdown)
    issues_out, suggested_patch = _analyze_governance_preview(
        context.baseline_text,
        markdown,
        context.body,
        context.analysis_opts,
    )
    return CleanPreviewResponse(
        markdown=markdown,
        applied_rules=context.clean_result.applied_rules,
        changed=bool(dropped or markdown != context.baseline_text),
        rule_stats=context.rule_stats,
        dropped=dropped,
        drop_reason=drop_reason,
        pii_hits=context.pii_hits,
        secrets_hits=context.secrets_hits,
        frontmatter=context.frontmatter,
        title=context.title,
        tags=context.tags,
        language=context.language,
        language_confidence=context.language_confidence,
        keywords=context.keywords,
        urls_changed=int(context.urls_changed),
        paragraphs_dropped=int(context.paragraphs_dropped),
        references_removed_lines=int(context.references_removed_lines),
        input_chars=len(context.baseline_text),
        output_chars=len(markdown or ""),
        input_lines=len((context.baseline_text or "").splitlines()),
        output_lines=len((markdown or "").splitlines()),
        added_lines=added,
        removed_lines=removed,
        changed_lines=changed_lines,
        diff_unified=diff_unified,
        diff_truncated=bool(diff_truncated),
        issues=issues_out,
        suggested_pipeline_patch=suggested_patch,
    )


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


def _dependency_backend_availability(
    *,
    enabled_setting: str,
    enable_note: str,
    module: str,
    attr: str | None = None,
    package_name: str,
) -> tuple[bool, str | None]:
    _ = (module, attr)
    if not bool(getattr(settings, enabled_setting, False)):
        return False, enable_note
    try:
        importlib_metadata.version(package_name)
    except importlib_metadata.PackageNotFoundError as exc:
        return False, f"{package_name} not installed: {str(exc)[:200] or 'package not found'}"
    return True, None


def _enabled_api_backend_availability(
    *,
    enabled_setting: str,
    api_url_setting: str,
    enable_note: str,
    api_url_note: str,
) -> tuple[bool, str | None]:
    enabled = bool(getattr(settings, enabled_setting, False))
    api_url = bool((getattr(settings, api_url_setting, "") or "").strip())
    if not enabled:
        return False, enable_note
    if not api_url:
        return False, api_url_note
    return True, None


def _mineru_backend_availability() -> tuple[bool, str | None]:
    available = bool(settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL))
    if available:
        return True, None
    return False, "Set MINERU_ENABLED=true and configure MINERU_API_TOKEN or MINERU_LOCAL_SERVER_URL."


def _deepseek_ocr_backend_availability() -> tuple[bool, str | None]:
    enabled = bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False))
    api_key = bool((getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip())
    if not enabled:
        return False, "Set DEEPSEEK_OCR_ENABLED=true."
    if not api_key:
        return False, "Configure SILICONFLOW_API_KEY."
    return True, None


def _qianfan_ocr_backend_availability() -> tuple[bool, str | None]:
    return _enabled_api_backend_availability(
        enabled_setting="QIANFAN_OCR_ENABLED",
        api_url_setting="QIANFAN_OCR_API_URL",
        enable_note="Set QIANFAN_OCR_ENABLED=true.",
        api_url_note="Configure QIANFAN_OCR_API_URL (e.g., http://localhost:2090/convert).",
    )


def _textin_backend_availability() -> tuple[bool, str | None]:
    enabled = bool(getattr(settings, "TEXTIN_ENABLED", False))
    api_url = bool((getattr(settings, "TEXTIN_API_URL", "") or "").strip())
    app_id = bool((getattr(settings, "TEXTIN_APP_ID", "") or "").strip())
    secret_code = bool((getattr(settings, "TEXTIN_SECRET_CODE", "") or "").strip())
    if not enabled:
        return False, "Set TEXTIN_ENABLED=true."
    if not api_url:
        return False, "Configure TEXTIN_API_URL."
    if not app_id:
        return False, "Configure TEXTIN_APP_ID."
    if not secret_code:
        return False, "Configure TEXTIN_SECRET_CODE."
    return True, None


def _etl4llm_backend_availability() -> tuple[bool, str | None]:
    return _enabled_api_backend_availability(
        enabled_setting="ETL4LLM_ENABLED",
        api_url_setting="ETL4LLM_API_URL",
        enable_note="Set ETL4LLM_ENABLED=true.",
        api_url_note="Configure ETL4LLM_API_URL (e.g., http://localhost:10001/v1/etl4llm/predict).",
    )


def _marker_backend_availability() -> tuple[bool, str | None]:
    return _enabled_api_backend_availability(
        enabled_setting="MARKER_ENABLED",
        api_url_setting="MARKER_API_URL",
        enable_note="Set MARKER_ENABLED=true.",
        api_url_note="Configure MARKER_API_URL (e.g., http://localhost:2080/convert).",
    )


def _paddle_vl_backend_availability() -> tuple[bool, str | None]:
    return _enabled_api_backend_availability(
        enabled_setting="PADDLE_VL_ENABLED",
        api_url_setting="PADDLE_VL_API_URL",
        enable_note="Set PADDLE_VL_ENABLED=true.",
        api_url_note="Configure PADDLE_VL_API_URL (e.g., http://localhost:9030/convert).",
    )


def _olmocr_backend_availability() -> tuple[bool, str | None]:
    return _enabled_api_backend_availability(
        enabled_setting="OLMOCR_ENABLED",
        api_url_setting="OLMOCR_API_URL",
        enable_note="Set OLMOCR_ENABLED=true.",
        api_url_note="Configure OLMOCR_API_URL (e.g., http://localhost:2085/convert).",
    )


def _magicpdf_backend_availability() -> tuple[bool, str | None]:
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


_PARSER_BACKEND_CHECKS: dict[str, Callable[[], tuple[bool, str | None]]] = {
    "mineru": _mineru_backend_availability,
    "deepdoc": lambda: (True, None)
    if bool(getattr(settings, "DEEPDOC_ENABLED", False))
    else (False, "Set DEEPDOC_ENABLED=true."),
    "deepseek_ocr": _deepseek_ocr_backend_availability,
    "qianfan_ocr": _qianfan_ocr_backend_availability,
    "textin": _textin_backend_availability,
    "markitdown": lambda: _dependency_backend_availability(
        enabled_setting="MARKITDOWN_ENABLED",
        enable_note="Set MARKITDOWN_ENABLED=true.",
        module="markitdown",
        attr="MarkItDown",
        package_name="markitdown",
    ),
    "docling": lambda: _dependency_backend_availability(
        enabled_setting="DOCLING_ENABLED",
        enable_note="Set DOCLING_ENABLED=true.",
        module="docling.document_converter",
        attr="DocumentConverter",
        package_name="docling",
    ),
    "etl4llm": _etl4llm_backend_availability,
    "marker": _marker_backend_availability,
    "paddle_vl": _paddle_vl_backend_availability,
    "olmocr": _olmocr_backend_availability,
    "magicpdf": _magicpdf_backend_availability,
}


def _pipeline_parser_backend_info(name: str) -> ParserBackendInfo:
    backend = (name or "").strip().lower()
    if backend == "auto":
        return ParserBackendInfo(name=backend, available=True, notes="Auto routes to the best enabled backend.")
    if backend == "basic":
        return ParserBackendInfo(name=backend, available=True, notes=None)

    check = _PARSER_BACKEND_CHECKS.get(backend)
    if check is None:
        return ParserBackendInfo(name=backend, available=False, notes="Unknown backend")
    available, notes = check()
    return ParserBackendInfo(name=backend, available=bool(available), notes=notes)


_AUTO_CHUNK_STRATEGY_NOTE = (
    "Auto-selects a chunker per document (git_commit_log/diff/patch/subtitles/logs/stacktrace/http_trace/"
    "terraform_plan/xml/junit_xml/sitemap_xml/maven_pom/xml_feed/openapi/github_actions/docker_compose/gitlab_ci/"
    "ansible_playbook/yaml/toml/sql/terraform/nginx/dockerfile/makefile/kv-config/jsonl/graphql/proto/api/"
    "changelog/csv/spreadsheet/chat/email/jira/postmortem/qa/qa_markdown/prd/sop/glossary/meeting_minutes/"
    "timeline/resume/slides/laws/paper/book/outline/transcript/rst/asciidoc/latex/org/wiki/html/markdown_table/"
    "markdown_frontmatter/markdown/json/plain text)."
)
_MANUSCRIPT_CHUNK_STRATEGY_NOTE = (
    "Preset for manuscript-like documents (git_commit_log/diff/patch/subtitles/logs/stacktrace/http_trace/"
    "terraform_plan/xml/junit_xml/sitemap_xml/maven_pom/xml_feed/openapi/github_actions/docker_compose/gitlab_ci/"
    "ansible_playbook/yaml/toml/sql/terraform/nginx/dockerfile/makefile/kv-config/jsonl/graphql/proto/api/"
    "changelog/csv/spreadsheet/chat/email/jira/postmortem/qa/qa_markdown/prd/sop/glossary/meeting_minutes/"
    "timeline/resume/slides/laws/paper/book/outline/transcript/rst/asciidoc/latex/org/wiki/html/markdown_table/"
    "markdown_frontmatter/markdown/...)."
)
_CHUNK_STRATEGY_NOTES = {
    "auto": _AUTO_CHUNK_STRATEGY_NOTE,
    "manuscript": _MANUSCRIPT_CHUNK_STRATEGY_NOTE,
    "pdf_layout": "PDF layout-aware chunking. Requires parsers that emit position tags like @@page\\tl\\tr\\tt\\tb##; strips tags from chunk text and records bbox/column metadata.",
    "outline": "Numbered-outline aware chunking (keeps section heading context).",
    "transcript": "Transcript/dialogue aware chunking (keeps speaker turns together).",
    "qa_pairs": "FAQ / Q&A aware chunking (keeps Q/A pairs together).",
    "paper": "Academic paper/report aware chunking (splits by common paper sections).",
    "book_structured": "Book chapter/part aware chunking (keeps chapter context).",
    "laws_structured": "Legal/policy aware chunking (splits by articles/clauses).",
    "email_thread": "Email thread aware chunking (keeps whole messages together).",
    "sop_steps": "SOP/procedure aware chunking (splits by Step/步骤 headings).",
    "glossary": "Glossary/dictionary aware chunking (splits by term-definition entries).",
    "resume_structured": "Resume/CV section-aware chunking (splits by common resume headings).",
    "presentation_slides": "Slide-aware chunking (splits by separators/markers like '---' or 'Slide 1').",
    "csv_rows": "CSV row-aware chunking (groups 'row N:' blocks; best with CsvParser output).",
    "spreadsheet_sheet": "Spreadsheet sheet-aware chunking (splits by '## Sheet:' sections; best with ExcelParser output).",
    "markdown_table": "Markdown table-aware chunking (avoids splitting rows; splits large tables at row boundaries).",
    "chat_history": "Timestamped chat history chunking (keeps whole messages together with message-level overlap).",
    "changelog": "Changelog/release-notes aware chunking (splits by release headings like '## [1.2.3] - 2024-01-01').",
    "log_events": "Log-events aware chunking (keeps multi-line log entries together; entry-level overlap).",
    "subtitles": "Subtitles aware chunking (SRT/VTT-like; splits by timecode cues).",
    "api_reference": "API reference aware chunking (splits by endpoint signatures like 'GET /path').",
    "diff_patch": "Diff/patch aware chunking (splits by file blocks and @@ hunks).",
    "git_commit_log": "Git commit-log aware chunking (splits by 'commit <sha>' blocks; preserves commit context even with patches).",
    "kv_config": "Key-value config aware chunking (groups KEY=VALUE entries; supports INI sections).",
    "qa_markdown": "Markdown Q/A aware chunking (supports bullets/headings like '**Q:**' / '### Q:').",
    "meeting_minutes": "Meeting-minutes aware chunking (splits by common sections like agenda/actions/decisions).",
    "timeline_events": "Timeline/date-event aware chunking (keeps dated events together).",
    "html_sections": "HTML heading-aware chunking (splits by <h1>-<h6> tags).",
    "rst_sections": "reStructuredText section-aware chunking (splits by underlined headings).",
    "asciidoc_sections": "AsciiDoc section-aware chunking (splits by '=' heading lines).",
    "latex_sections": "LaTeX section-aware chunking (splits by \\section/\\chapter commands).",
    "orgmode_sections": "Org-mode section-aware chunking (splits by '*' heading lines).",
    "mediawiki_sections": "MediaWiki section-aware chunking (splits by '== Heading ==' lines).",
    "yaml_manifest": "YAML manifest aware chunking (splits by '---' documents; extracts kind/name when present).",
    "toml_config": "TOML config aware chunking (splits by [tables] and groups key/value entries).",
    "sql_schema": "SQL schema/DDL aware chunking (splits by CREATE/ALTER statements).",
    "stacktrace": "Stacktrace aware chunking (groups traceback blocks; for timestamped logs prefer log_events).",
    "http_trace": "HTTP trace aware chunking (splits by HTTP request blocks; keeps request+response together).",
    "terraform_plan": "Terraform plan output aware chunking (splits by '# ... will be ...' change headers).",
    "xml_feed": "XML feed (RSS/Atom) item-aware chunking (splits by <item>/<entry> blocks).",
    "junit_xml": "JUnit XML report aware chunking (splits by <testcase> blocks; preserves offsets).",
    "sitemap_xml": "Sitemap XML aware chunking (splits by <url>/<sitemap> entry blocks).",
    "maven_pom": "Maven POM XML aware chunking (chunks <dependency>/<plugin> records; preserves offsets).",
    "openapi_spec": "OpenAPI/Swagger spec aware chunking (splits by per-path blocks under `paths:`).",
    "github_actions": "GitHub Actions workflow aware chunking (splits by job blocks under `jobs:`).",
    "docker_compose": "Docker Compose YAML aware chunking (splits by service blocks under `services:`).",
    "gitlab_ci": "GitLab CI YAML aware chunking (splits by top-level job/config blocks).",
    "ansible_playbook": "Ansible playbook aware chunking (splits by top-level plays; preserves offsets).",
    "dockerfile": "Dockerfile aware chunking (splits by FROM stages and instruction blocks).",
    "makefile": "Makefile aware chunking (splits by target blocks and recipes).",
    "nginx_config": "Nginx config aware chunking (splits by server blocks; brace-aware).",
    "terraform_hcl": "Terraform/HCL block-aware chunking (splits by resource/module/variable blocks; brace-aware).",
    "graphql_schema": "GraphQL schema aware chunking (splits by top-level type/input/enum/interface/union/scalar/directive/schema definitions).",
    "proto_schema": "Protocol Buffers schema aware chunking (splits by message/enum/service blocks; brace-aware).",
    "jira_ticket": "Jira/issue-ticket aware chunking (splits by common fields like Summary/Description/Steps/Expected/Actual).",
    "prd_spec": "PRD/spec aware chunking (splits by common sections like Background/Goals/Scope/Requirements/Acceptance/Risks).",
    "postmortem_report": "Incident postmortem/RCA aware chunking (splits by common sections like Summary/Impact/Timeline/Root Cause/Action Items).",
    "jsonl_records": "JSONL/NDJSON record-aware chunking (groups whole JSON records per line; preserves offsets).",
    "markdown_frontmatter": "Markdown frontmatter aware chunking (keeps YAML frontmatter, then chunks the body).",
    "sentence_window": "Sentence window chunking with sentence-level overlap.",
}


def _llama_index_chunk_availability() -> tuple[bool, str | None]:
    if not bool(getattr(settings, "LLAMA_INDEX_ENABLED", False)):
        return False, "Set LLAMA_INDEX_ENABLED=true."
    ok, err = check_dependency("llama_index.core")
    return ok, None if ok else f"llama-index-core not installed: {err}"


def _integrated_pipeline_chunk_note() -> str:
    vision_enabled = bool(getattr(settings, "VISION_LLM_ENABLED", False))
    vision_key_ok = bool(((getattr(settings, "VISION_LLM_API_KEY", "") or getattr(settings, "LLM_API_KEY", "") or "").strip()))
    vision_model = (getattr(settings, "VISION_LLM_MODEL", "") or "").strip()
    if vision_enabled and vision_key_ok:
        return f"Integrated pipeline (parse+chunk). Vision enrichment enabled (model={vision_model or 'configured'})."
    if vision_enabled and not vision_key_ok:
        return "Integrated pipeline (parse+chunk). Vision enrichment enabled but missing API key (set MIMIRQ_VISION_LLM_API_KEY or LLM_API_KEY)."
    return "Integrated pipeline (parse+chunk). Vision enrichment disabled by default (set MIMIRQ_VISION_LLM_ENABLED=true to enable)."


def _pipeline_chunk_strategy_info(name: str) -> ChunkStrategyInfo:
    strategy = (name or "").strip().lower()
    available = True
    notes = _CHUNK_STRATEGY_NOTES.get(strategy)
    if strategy.startswith("llama_index"):
        available, notes = _llama_index_chunk_availability()
    elif strategy in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
        notes = _integrated_pipeline_chunk_note()
    elif strategy == "markdown":
        notes = "Alias of markdown_header."
    return ChunkStrategyInfo(name=strategy, available=bool(available), notes=decorate_chunk_strategy_note(strategy, notes))


def _safe_pipeline_plugin_error_path(path: Path | None, roots: Iterable[Path]) -> str:
    if path is None:
        return ""
    try:
        resolved = path.expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return path.name or str(path)

    for root in sorted((Path(item).expanduser() for item in roots), key=lambda item: len(str(item)), reverse=True):
        try:
            rel = resolved.relative_to(root.resolve())
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        rel_text = rel.as_posix()
        return rel_text if rel_text and rel_text != "." else resolved.name
    return resolved.name


@router.get(
    "/plugins",
    response_model=PipelinePluginListResponse,
    response_model_exclude_none=True,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def list_pipeline_plugins_endpoint():
    """
    List registered local pipeline plugins.

    Plugins become executable only after their package manifest is published and
    the local runner report matches the current package hash.
    """
    plugins, errors = list_pipeline_plugins_with_errors()
    plugin_roots = default_plugin_directories()
    items = []
    for plugin in plugins:
        items.append(
            {
                "id": plugin.id,
                "version": plugin.version,
                "name": plugin.name,
                "description": plugin.description,
                "published": plugin.published,
                "executable": plugin.executable,
                "test_status": plugin.test_status,
                "package_hash": plugin.package_hash,
                "test_report": plugin.test_report,
                "stages": sorted(plugin.entries.keys()),
                "refs": plugin.refs,
                "contract": plugin.contract_summary,
                "processing_templates": plugin.processing_templates,
                "suggested_pipeline_patch": plugin.suggested_pipeline_patch,
            }
        )
    return {
        "items": items,
        "errors": [
            {
                "plugin_dir": _safe_pipeline_plugin_error_path(error.plugin_dir, plugin_roots),
                "manifest_path": _safe_pipeline_plugin_error_path(error.manifest_path, plugin_roots),
                "error": error.error,
            }
            for error in errors
        ],
    }


def _plugin_marker_refs(plugin_ref: str, descriptor: Any) -> set[str]:
    refs = {str(plugin_ref or "").strip()}
    raw_refs = getattr(descriptor, "refs", {}) or {}
    if isinstance(raw_refs, dict):
        refs.update(str(value or "").strip() for value in raw_refs.values())
    return {ref for ref in refs if ref}


def _assert_pipeline_plugin_executable(plugin_ref: str, descriptor: Any) -> None:
    if getattr(descriptor, "published", True) is not True or getattr(descriptor, "executable", True) is not True:
        plugin_id = str(getattr(descriptor, "id", "") or plugin_ref)
        version = str(getattr(descriptor, "version", "") or "")
        status = str(getattr(descriptor, "test_status", "") or "unknown")
        qualified = f"{plugin_id}@{version}" if version else plugin_id
        raise HTTPException(
            status_code=409,
            detail=f"plugin '{qualified}' is not executable; local test report status is {status}",
        )


def _assert_pipeline_plugin_ready_for_golden(plugin_ref: str, descriptor: Any) -> None:
    _assert_pipeline_plugin_executable(plugin_ref, descriptor)


def _resolve_plugin_relative_input_path(plugin_dir: Path, input_path: str) -> Path:
    raw = str(input_path or "").strip() or "sample.json"
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise HTTPException(status_code=400, detail="input_path must stay inside the plugin directory")
    try:
        plugin_root = plugin_dir.expanduser().resolve()
        resolved = (plugin_root / candidate).resolve()
        resolved.relative_to(plugin_root)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="input_path must stay inside the plugin directory") from exc
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="plugin chunk report input_path not found")
    return resolved


@router.post(
    "/plugins/chunk-report",
    response_model=PipelinePluginChunkReportResponse,
    response_model_by_alias=True,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def build_pipeline_plugin_chunk_report_endpoint(
    payload: PipelinePluginChunkReportRequest,
    *,
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> PipelinePluginChunkReportResponse:
    """
    Build a review-only governance/chunk/KG report for a registered plugin sample.

    The sample path is scoped to the plugin directory. This API executes local
    plugin code, so callers select a registered plugin ref rather than arbitrary
    host paths.
    """
    _ = account_id
    try:
        descriptor = resolve_registered_plugin_descriptor(payload.plugin_ref)
    except PipelinePluginRegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_pipeline_plugin_executable(payload.plugin_ref, descriptor)
    input_path = _resolve_plugin_relative_input_path(descriptor.plugin_dir, payload.input_path)
    try:
        report = build_pipeline_plugin_chunk_report_data(
            descriptor.plugin_dir,
            input_path=input_path,
            max_examples_per_section=payload.max_examples_per_section,
            preview_chars=payload.preview_chars,
            governance_params=payload.governance_params,
            chunk_params=payload.chunk_params,
            kg_params=payload.kg_params,
            section_metadata_keys=tuple(payload.section_metadata_keys or ()),
            title_metadata_keys=tuple(payload.title_metadata_keys or ()),
            metadata_highlight_keys=tuple(payload.metadata_highlight_keys or ()),
        )
    except PipelinePluginRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"failed to build plugin chunk report: {exc}") from exc
    return PipelinePluginChunkReportResponse.model_validate(report)


def _assert_unmarked_plugin_golden_chunks_allowed(include_unmarked_chunks: bool) -> None:
    if not include_unmarked_chunks:
        return
    if bool(getattr(settings, "PYTHON_PIPELINE_PLUGIN_ALLOW_UNMARKED_GOLDEN_CHUNKS", False)):
        return
    raise HTTPException(
        status_code=400,
        detail=(
            "include_unmarked_chunks requires "
            "PYTHON_PIPELINE_PLUGIN_ALLOW_UNMARKED_GOLDEN_CHUNKS=true; "
            "plugin Golden drafts normally use only chunks produced by the selected plugin"
        ),
    )


def _chunk_marked_by_plugin(meta: dict[str, Any], plugin_refs: set[str]) -> bool:
    if not plugin_refs:
        return False
    for key in ("chunk_python_plugin", "governance_python_plugin"):
        value = str(meta.get(key) or "").strip()
        if value and value in plugin_refs:
            return True
    return False


def _active_doc_pipeline_key(document_id: UUID, doc_metadata: dict[str, Any]) -> str | None:
    active_hash = get_active_pipeline_hash(doc_metadata)
    return build_doc_pipeline_key(document_id, active_hash) if active_hash else None


def _chunk_matches_active_pipeline(chunk_meta: dict[str, Any], active_key: str | None) -> bool:
    if not active_key:
        return True
    chunk_key = str(chunk_meta.get("doc_pipeline_key") or "").strip()
    return not chunk_key or chunk_key == active_key


def _load_plugin_golden_draft_chunks(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_id: UUID,
    plugin_refs: set[str],
    max_chunks: int,
    include_unmarked_chunks: bool = False,
) -> list[DocumentChunk]:
    cap = max(1, min(50_000, int(max_chunks or 5000)))
    rows = (
        db.query(DocumentChunk, DBDocument)
        .join(
            DBDocument,
            and_(DBDocument.id == DocumentChunk.document_id, DBDocument.tenant_id == DocumentChunk.tenant_id),
        )
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.status == "completed",
            DBDocument.publication_status == "published",
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
            DocumentChunk.disabled_at.is_(None),
        )
        .order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
        .limit(cap)
        .all()
    )
    chunks: list[DocumentChunk] = []
    for chunk, document in rows:
        chunk_meta = dict(getattr(chunk, "doc_metadata", None) or {})
        if not include_unmarked_chunks and not _chunk_marked_by_plugin(chunk_meta, plugin_refs):
            continue
        doc_meta = dict(getattr(document, "doc_metadata", None) or {})
        if not _chunk_matches_active_pipeline(chunk_meta, _active_doc_pipeline_key(document.id, doc_meta)):
            continue
        chunks.append(chunk)
    return chunks


def _build_plugin_golden_draft_response(
    *,
    dataset_id: UUID,
    plugin_ref: str,
    descriptor: Any,
    chunks: Iterable[DocumentChunk],
    max_items: int,
) -> PipelinePluginGoldenDraftResponse:
    plugin_id = str(getattr(descriptor, "id", ""))
    bundle = build_golden_draft_bundle_from_chunks(
        dataset_id=dataset_id,
        chunks=chunks,
        golden_rules=getattr(descriptor, "golden_rules", {}) or {},
        plugin_id=plugin_id,
        plugin_version=str(getattr(descriptor, "version", "")),
        plugin_ref=plugin_ref,
        plugin_package_hash=str(getattr(descriptor, "package_hash", "")),
        max_items=max_items,
    )
    return PipelinePluginGoldenDraftResponse(
        dataset_id=dataset_id,
        plugin_id=plugin_id,
        plugin_version=str(getattr(descriptor, "version", "")),
        plugin_ref=plugin_ref,
        items_total=len(bundle.get("items") or []),
        bundle=bundle,
    )


async def _import_plugin_golden_draft_bundle(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    bundle: dict[str, Any],
    overwrite: bool,
    max_items: int,
) -> dict[str, Any]:
    items = bundle.get("items") if isinstance(bundle, dict) else []
    if not isinstance(items, list) or not items:
        return {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [],
            "created_case_ids": [],
            "updated_case_ids": [],
            "case_ids": [],
        }

    from app.api.schemas.regression import RagasRegressionCaseImportRequest
    from app.api.v1.evaluations import import_ragas_regression_cases

    payload = RagasRegressionCaseImportRequest(
        dataset_id=dataset_id,
        overwrite=bool(overwrite),
        max_items=max(1, min(2000, int(max_items or 500))),
        items=items,
    )
    result = await import_ragas_regression_cases(
        payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    return result if isinstance(result, dict) else dict(result)


@router.post(
    "/plugins/golden-draft",
    response_model=PipelinePluginGoldenDraftResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def build_pipeline_plugin_golden_draft(
    payload: PipelinePluginGoldenDraftRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> PipelinePluginGoldenDraftResponse:
    """
    Build a review-only regression case bundle from chunks produced by a plugin.

    This endpoint does not import or persist golden cases. Review the returned
    bundle, then import it through the regression case import API or the
    pipeline-side golden-draft/import helper.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = DatasetService.get_dataset(db, tenant_id, payload.dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    try:
        descriptor = resolve_registered_plugin_descriptor(payload.plugin_ref)
    except PipelinePluginRegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_pipeline_plugin_ready_for_golden(payload.plugin_ref, descriptor)
    _assert_unmarked_plugin_golden_chunks_allowed(payload.include_unmarked_chunks)

    chunks = _load_plugin_golden_draft_chunks(
        db=db,
        tenant_id=tenant_id,
        dataset_id=payload.dataset_id,
        plugin_refs=_plugin_marker_refs(payload.plugin_ref, descriptor),
        max_chunks=payload.max_chunks,
        include_unmarked_chunks=payload.include_unmarked_chunks,
    )
    return _build_plugin_golden_draft_response(
        dataset_id=payload.dataset_id,
        plugin_ref=payload.plugin_ref,
        descriptor=descriptor,
        chunks=chunks,
        max_items=payload.max_items,
    )


@router.post(
    "/plugins/golden-draft/import",
    response_model=PipelinePluginGoldenDraftImportResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def import_pipeline_plugin_golden_draft(
    payload: PipelinePluginGoldenDraftImportRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> PipelinePluginGoldenDraftImportResponse:
    """Build a plugin golden draft bundle and import it into regression cases."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = DatasetService.get_dataset(db, tenant_id, payload.dataset_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)

    try:
        descriptor = resolve_registered_plugin_descriptor(payload.plugin_ref)
    except PipelinePluginRegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _assert_pipeline_plugin_ready_for_golden(payload.plugin_ref, descriptor)
    _assert_unmarked_plugin_golden_chunks_allowed(payload.include_unmarked_chunks)

    chunks = _load_plugin_golden_draft_chunks(
        db=db,
        tenant_id=tenant_id,
        dataset_id=payload.dataset_id,
        plugin_refs=_plugin_marker_refs(payload.plugin_ref, descriptor),
        max_chunks=payload.max_chunks,
        include_unmarked_chunks=payload.include_unmarked_chunks,
    )
    draft = _build_plugin_golden_draft_response(
        dataset_id=payload.dataset_id,
        plugin_ref=payload.plugin_ref,
        descriptor=descriptor,
        chunks=chunks,
        max_items=payload.max_items,
    )
    import_result = await _import_plugin_golden_draft_bundle(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=payload.dataset_id,
        bundle=draft.bundle,
        overwrite=payload.overwrite,
        max_items=payload.max_items,
    )
    return PipelinePluginGoldenDraftImportResponse(draft=draft, import_result=import_result)


@router.get("/capabilities", response_model=PipelineCapabilitiesResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_pipeline_capabilities(
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

    pdf_backends = [_pipeline_parser_backend_info(name) for name in sorted(ParserFactory.SUPPORTED_PDF_BACKENDS)]

    # Expose all strategies known to the backend (frontends may choose a subset).
    all_strats = set(chunker_factory.SUPPORTED_STRATEGIES.keys()) | set(chunker_factory.INTEGRATED_PIPELINE_STRATEGIES)
    chunk_strategies = [_pipeline_chunk_strategy_info(name) for name in sorted(all_strats)]

    return PipelineCapabilitiesResponse(
        default_parser_backend=default_parser_backend,
        default_chunk_strategy=default_chunk_strategy,
        pdf_backends=pdf_backends,
        chunk_strategies=chunk_strategies,
    )


@router.get("/governance-profiles", response_model=GovernanceProfileListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_governance_profiles(
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
def create_governance_profile(
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
def get_governance_profile(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    return _resolve_profile_ref(db=db, tenant_id=tenant_id, profile_ref=profile_ref)


@router.get("/governance-profiles/{profile_ref}/resolved", response_model=GovernanceProfileResolvedResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_governance_profile_resolved(
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
def update_governance_profile(
    profile_ref: str,
    body: GovernanceProfileUpdate,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = _resolve_custom_profile_row(db=db, tenant_id=tenant_id, profile_ref=profile_ref)

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
def delete_governance_profile(
    profile_ref: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = _resolve_custom_profile_row(db=db, tenant_id=tenant_id, profile_ref=profile_ref)

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

    raw_profiles = _raw_governance_profile_import_items(await _read_governance_profile_import_json(file))
    created = 0
    updated = 0
    out_items: list[GovernanceProfileSummary] = []
    for item in raw_profiles:
        record = _normalize_governance_profile_import_record(item)
        created_delta, updated_delta, summary = _upsert_governance_profile_import_record(
            db=db,
            tenant_id=tenant_id,
            record=record,
            overwrite=bool(overwrite),
        )
        created += created_delta
        updated += updated_delta
        out_items.append(summary)

    db.commit()
    return GovernanceProfileImportResponse(created=created, updated=updated, items=out_items)


@router.get("/governance-profiles/{profile_ref}/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_governance_profile(
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
        headers=download_response_headers(filename),
    )


@router.get("/governance-profiles/{profile_ref}/export-ingestion-policy", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_governance_profile_ingestion_policy(
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
        headers=download_response_headers(filename),
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


@dataclass
class _IngestionPreviewConfig:
    base_parser_backend: str
    base_chunk_strategy: str
    parser_backend_choice: str
    chunk_strategy_choice: str
    preprocess_steps: list[dict[str, object]] = field(default_factory=list)
    governance_profile_ref: str | None = None
    patch_dict: dict[str, object] = field(default_factory=dict)


def _empty_preprocess_summary() -> dict[str, object]:
    return {"changed": False, "size_before": 0, "size_after": 0, "steps": [], "warnings": []}


def _dataset_metadata_dict(dataset: object) -> dict[str, object]:
    dataset_meta = getattr(dataset, "dataset_metadata", None)
    return dataset_meta if isinstance(dataset_meta, dict) else {}


def _ingestion_preview_defaults(
    parser_backend: str | None,
    chunk_strategy: str | None,
) -> tuple[str, str, str, str]:
    default_pb = (getattr(settings, "DEFAULT_PARSER_BACKEND", "auto") or "auto").strip().lower() or "auto"
    default_cs = (getattr(settings, "DEFAULT_CHUNK_STRATEGY", "langchain_recursive") or "langchain_recursive").strip().lower()
    base_pb = (parser_backend or default_pb).strip().lower() or default_pb
    base_cs = (chunk_strategy or default_cs).strip().lower() or default_cs
    return default_pb, default_cs, base_pb, base_cs


def _ingestion_rule_preprocess_steps(matched_rule: object | None) -> list[dict[str, object]]:
    preprocess = getattr(matched_rule, "preprocess", None) if matched_rule is not None else None
    steps = getattr(preprocess, "steps", None) if preprocess is not None and bool(getattr(preprocess, "enabled", True)) else None
    if not isinstance(steps, list) or not steps:
        return []
    return [
        {
            "id": str(getattr(step, "id", "") or "").strip(),
            "params": dict(getattr(step, "params", {}) or {}),
        }
        for step in steps
    ]


def _profile_pipeline_patch_for_ingestion(
    *,
    db: Session,
    tenant_id: UUID,
    profile_ref: str,
) -> dict[str, object]:
    prof = _resolve_profile_ref(db=db, tenant_id=tenant_id, profile_ref=profile_ref)
    patch_dict = dict(prof.payload.pipeline_patch or {})
    rules = [rule.model_dump() for rule in (prof.payload.regex_rules or [])]
    if rules:
        patch_dict["governance_regex_rules"] = rules
    return patch_dict


def _resolve_ingestion_preview_config(
    *,
    matched_rule: object | None,
    parser_backend: str | None,
    chunk_strategy: str | None,
    db: Session,
    tenant_id: UUID,
) -> _IngestionPreviewConfig:
    default_pb, default_cs, base_pb, base_cs = _ingestion_preview_defaults(parser_backend, chunk_strategy)
    config = _IngestionPreviewConfig(
        base_parser_backend=base_pb,
        base_chunk_strategy=base_cs,
        parser_backend_choice=base_pb,
        chunk_strategy_choice=base_cs,
    )
    if matched_rule is None:
        return config

    if base_pb in {"", "auto", default_pb} and matched_rule.parser_backend:
        config.parser_backend_choice = str(matched_rule.parser_backend)
    if base_cs in {"", default_cs} and matched_rule.chunk_strategy:
        config.chunk_strategy_choice = str(matched_rule.chunk_strategy)

    config.preprocess_steps = _ingestion_rule_preprocess_steps(matched_rule)
    governance_profile_ref = getattr(matched_rule, "governance_profile_ref", None)
    if isinstance(governance_profile_ref, str) and governance_profile_ref.strip():
        config.governance_profile_ref = governance_profile_ref.strip()
        config.patch_dict.update(_profile_pipeline_patch_for_ingestion(db=db, tenant_id=tenant_id, profile_ref=config.governance_profile_ref))
    config.patch_dict.update(dict(getattr(matched_rule, "pipeline_patch", None) or {}))
    return config


def _preprocess_ingestion_preview_file(
    temp_path: Path,
    preprocess_steps: list[dict[str, object]],
) -> tuple[Path, dict[str, object]]:
    if not preprocess_steps:
        return temp_path, _empty_preprocess_summary()

    pre = preprocess_file(input_path=temp_path, steps=preprocess_steps)
    summary = {
        "changed": bool(pre.changed),
        "size_before": int(pre.size_before),
        "size_after": int(pre.size_after),
        "steps": [
            {
                "id": step.id,
                "applied": bool(step.applied),
                "changed": bool(step.changed),
                "note": step.note,
                "bytes_before": int(getattr(step, "bytes_before", 0) or 0),
                "bytes_after": int(getattr(step, "bytes_after", 0) or 0),
                "elapsed_ms": int(getattr(step, "elapsed_ms", 0) or 0),
            }
            for step in (pre.steps or [])
        ],
        "warnings": list(pre.warnings or []),
    }
    parse_path = Path(str(pre.output_path)) if bool(pre.changed) else temp_path
    return parse_path, summary


def _effective_bool(effective: object, name: str, default: bool) -> bool:
    return bool(getattr(effective, name, default))


def _effective_int(effective: object, name: str, default: int) -> int:
    return int(getattr(effective, name, default) or default)


def _effective_float(effective: object, name: str, default: float) -> float:
    return float(getattr(effective, name, default) or default)


def _effective_str(effective: object, name: str, default: str) -> str:
    return str(getattr(effective, name, default) or default)


def _build_ingestion_clean_preview_request(
    *,
    parsed: dict[str, object],
    effective: object,
    diff_max_lines: int,
) -> CleanPreviewRequest:
    return CleanPreviewRequest(
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
        max_blank_lines=_effective_int(effective, "governance_max_blank_lines", 1),
        remove_control_chars=True,
        remove_toc_lines=_effective_bool(effective, "governance_remove_toc_lines", True),
        remove_noise_lines=_effective_bool(effective, "governance_remove_noise_lines", True),
        remove_common_lines=_effective_bool(effective, "governance_remove_common_lines", True),
        unwrap_lines=_effective_bool(effective, "governance_unwrap_lines", True),
        remove_boilerplate=_effective_bool(effective, "governance_remove_boilerplate", False),
        remove_images=_effective_str(effective, "governance_remove_images", "none"),  # type: ignore[arg-type]
        extract_frontmatter=_effective_bool(effective, "governance_extract_frontmatter", False),
        strip_frontmatter=_effective_bool(effective, "governance_strip_frontmatter", False),
        detect_language=_effective_bool(effective, "governance_detect_language", False),
        language_min_chars=_effective_int(effective, "governance_language_min_chars", 40),
        normalize_urls=_effective_bool(effective, "governance_normalize_urls", False),
        normalize_urls_strip_tracking=_effective_bool(effective, "governance_normalize_urls_strip_tracking", True),
        drop_duplicate_paragraphs=_effective_bool(effective, "governance_drop_duplicate_paragraphs", False),
        drop_duplicate_paragraphs_min_occurrences=_effective_int(effective, "governance_drop_duplicate_paragraphs_min_occurrences", 3),
        drop_duplicate_paragraphs_min_chars=_effective_int(effective, "governance_drop_duplicate_paragraphs_min_chars", 40),
        drop_duplicate_paragraphs_max_chars=_effective_int(effective, "governance_drop_duplicate_paragraphs_max_chars", 1200),
        trim_references=_effective_bool(effective, "governance_trim_references", False),
        extract_keywords=_effective_bool(effective, "governance_extract_keywords", False),
        keywords_provider=_effective_str(effective, "governance_keywords_provider", "auto"),
        keywords_top_k=_effective_int(effective, "governance_keywords_top_k", 10),
        keywords_max_chars=_effective_int(effective, "governance_keywords_max_chars", 20000),
        normalize_tables=_effective_bool(effective, "governance_normalize_tables", False),
        strip_code_line_numbers=_effective_bool(effective, "governance_strip_code_line_numbers", False),
        pii_anonymize=_effective_bool(effective, "governance_pii_anonymize", False),
        pii_mode=_effective_str(effective, "governance_pii_mode", "mask"),  # type: ignore[arg-type]
        pii_mask=_effective_str(effective, "governance_pii_mask", REDACTED_MASK),
        secrets_redact=_effective_bool(effective, "governance_secrets_redact", False),
        secrets_mode=_effective_str(effective, "governance_secrets_mode", "mask"),  # type: ignore[arg-type]
        secrets_mask=_effective_str(effective, "governance_secrets_mask", SECRET_MASK),
        drop_outline_only=_effective_bool(effective, "governance_drop_outline_only", False),
        drop_outline_min_content_chars=_effective_int(effective, "governance_drop_outline_min_content_chars", 200),
        drop_outline_max_heading_ratio=_effective_float(effective, "governance_drop_outline_max_heading_ratio", 0.85),
        drop_low_density=_effective_bool(effective, "governance_drop_low_density", False),
        drop_low_density_threshold=_effective_float(effective, "governance_drop_low_density_threshold", 0.12),
        unwrap_max_line_length=_effective_int(effective, "governance_unwrap_max_line_length", 120),
        noise_min_chars=_effective_int(effective, "governance_noise_min_chars", 2),
        noise_ratio_threshold=_effective_float(effective, "governance_noise_ratio_threshold", 0.2),
        common_lines_min_occurrences=_effective_int(effective, "governance_common_lines_min_docs", 3),
    )


def _ingestion_preview_rule_output(
    matched_rule: object | None,
    config: _IngestionPreviewConfig,
) -> dict[str, object]:
    return {
        "matched": matched_rule is not None,
        "rule_id": getattr(matched_rule, "id", None) if matched_rule is not None else None,
        "rule_name": getattr(matched_rule, "name", None) if matched_rule is not None else None,
        "governance_profile_ref": config.governance_profile_ref,
        "preprocess_steps": config.preprocess_steps,
        "parser_backend": str(config.parser_backend_choice or "auto"),
        "chunk_strategy": str(config.chunk_strategy_choice or ""),
    }


def _ingestion_preview_explain(
    *,
    dataset_id: UUID,
    file: UploadFile,
    file_ext: str,
    config: _IngestionPreviewConfig,
    rule_out: dict[str, object],
    pre_summary: dict[str, object],
    parsed: dict[str, object],
) -> dict[str, object]:
    filename = str(getattr(file, "filename", "") or "")
    return {
        "dataset_id": str(dataset_id),
        "filename": filename,
        "file_type": str(file_ext or ""),
        "requested": {
            "parser_backend": str(config.base_parser_backend or ""),
            "chunk_strategy": str(config.base_chunk_strategy or ""),
        },
        "rule": rule_out,
        "snapshot": {
            "dataset_id": str(dataset_id),
            "filename": filename,
            "file_type": str(file_ext or ""),
            "rule": rule_out,
            "preprocess": dict(pre_summary),
            "pipeline_patch": dict(config.patch_dict),
            "parser_backend": str(config.parser_backend_choice or "auto"),
            "chunk_strategy": str(config.chunk_strategy_choice or ""),
            "parse_backend": str(parsed.get("backend") or ""),
            "pdf_quality": parsed.get("pdf_quality"),
        },
    }


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

    try:
        await save_upload_file(file, temp_path, max_bytes=settings.MAX_FILE_SIZE)

        dataset_meta = _dataset_metadata_dict(dataset)
        policy = parse_ingestion_policy_from_metadata(dataset_meta) or None
        matched_rule = match_ingestion_rule(policy, filename=file.filename, file_ext=file_ext)
        config = _resolve_ingestion_preview_config(
            matched_rule=matched_rule,
            parser_backend=parser_backend,
            chunk_strategy=chunk_strategy,
            db=db,
            tenant_id=tenant_id,
        )

        # Preprocess file (before parsing).
        parse_path, pre_summary = _preprocess_ingestion_preview_file(temp_path, config.preprocess_steps)

        # Compute effective governance options (dataset defaults + rule/profile patches).
        patch_opts = PipelineOptions(**config.patch_dict) if config.patch_dict else PipelineOptions()
        effective = resolve_pipeline_effective(dataset_metadata=dataset_meta, document_metadata={}, request_overrides=patch_opts)

        # Parse preview via subprocess worker.
        parsed = await run_subprocess_worker(
            tenant_id=tenant_id,
            payload={
                "action": "pipeline_parse_preview",
                "tenant_id": str(tenant_id),
                "file_path": str(parse_path),
                "parser_backend": config.parser_backend_choice,
            },
            disconnect_check=request.is_disconnected,
            timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
        )

        # Governance clean preview (issues + diff).
        clean_body = _build_ingestion_clean_preview_request(parsed=parsed, effective=effective, diff_max_lines=diff_max_lines)
        cleaned = await clean_preview(body=clean_body, tenant_id=tenant_id, account_id=account_id, db=db)
        rule_out = _ingestion_preview_rule_output(matched_rule, config)
        explain = _ingestion_preview_explain(
            dataset_id=dataset_id,
            file=file,
            file_ext=file_ext,
            config=config,
            rule_out=rule_out,
            pre_summary=pre_summary,
            parsed=parsed,
        )

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
def chunk_preview(
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


@router.post(
    "/clean-preview",
    response_model=CleanPreviewResponse,
    response_model_exclude_none=True,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def clean_preview(
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
    input_text = _extract_governance_input_text(body)
    input_text, frontmatter, title, tags = _extract_clean_preview_frontmatter(input_text, body)
    baseline_text = input_text or ""

    analysis_opts = _governance_analysis_options(body)
    rules, rule_meta = _build_clean_preview_rules(body)
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
    rule_stats = _clean_preview_rule_stats(rules, rule_meta, rule_hits)

    text = _apply_preview_format_transforms(result.markdown, body)
    text, pii_hits, secrets_hits = _apply_preview_sensitive_redaction(text, body)
    text, paragraphs_dropped, references_removed_lines, urls_changed = _apply_preview_cleanup_stats(text, body)
    response_context = _CleanPreviewResponseContext(
        baseline_text=baseline_text,
        body=body,
        clean_result=result,
        rule_stats=rule_stats,
        pii_hits=pii_hits,
        secrets_hits=secrets_hits,
        frontmatter=frontmatter,
        title=title,
        tags=tags,
        urls_changed=urls_changed,
        paragraphs_dropped=paragraphs_dropped,
        references_removed_lines=references_removed_lines,
        analysis_opts=analysis_opts,
    )

    drop_reason = _preview_drop_reason(text, body)
    if drop_reason is not None:
        return _build_clean_preview_response(
            response_context,
            markdown="",
            dropped=True,
            drop_reason=drop_reason,
        )

    response_context.title = _extract_preview_title(text, title)
    response_context.language, response_context.language_confidence = _detect_preview_language(text, body)
    response_context.keywords = _extract_preview_keywords(text, body)
    return _build_clean_preview_response(
        response_context,
        markdown=text,
        dropped=False,
        drop_reason=None,
    )


@router.post("/learn-common-lines", response_model=GovernanceCommonLinesLearnResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def learn_common_lines(
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


@router.post(
    "/governance-analyze",
    response_model=GovernanceAnalyzeResponse,
    response_model_exclude_none=True,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def governance_analyze(
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

    input_text = _extract_governance_input_text(body)
    analysis_opts = _governance_analysis_options(body)
    base = input_text or ""
    out_issues, patch = _analyze_governance_preview(base, "", body, analysis_opts)
    return GovernanceAnalyzeResponse(
        input_chars=len(base),
        input_lines=len(base.splitlines()),
        issues=out_issues,
        suggested_pipeline_patch=dict(patch or {}),
    )


@router.get("/clean-rules", response_model=CleanRulesResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_clean_rules(
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
def extract_keywords(
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

    mode = str(body.mode or "document_focus").strip().lower()
    providers = _normalize_auto_annotation_providers(body)
    draft = _AutoAnnotationDraft()

    try:
        if mode == "document_focus":
            await _collect_document_focus_annotations(draft, scan_text, body, providers, max_items)
        else:
            await _collect_compliance_annotations(draft, scan_text, body, providers, max_items)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Auto annotation failed: {str(exc)}") from exc

    keyword_provider = _finalize_auto_annotation_keyword_provider(draft.keyword_provider, body, providers)

    annotations = _dedupe_auto_annotations(draft.candidates, max_items=max_items)
    if not draft.document_tags:
        draft.document_tags.extend(_derive_document_tags_from_annotations(annotations, max_items=max_items))
    document_tags = _dedupe_auto_document_tags(draft.document_tags, max_items=max_items)
    return AutoAnnotationResponse(
        annotations=annotations,
        document_tags=document_tags,
        summary=draft.summary,
        text_chars=total_chars,
        scanned_chars=len(scan_text),
        truncated=total_chars > len(scan_text),
        keyword_provider=keyword_provider,
        strategy=draft.strategy,  # type: ignore[arg-type]
        providers_used=draft.providers_used,
        warnings=draft.warnings,
    )


@dataclass
class _LLMCleanPromptSelection:
    system_prompt: str
    prompt_template_id: str | None = None
    template_key: str | None = None
    ab_experiment_key: str | None = None
    ab_variant: str | None = None


def _default_llm_clean_system_prompt() -> str:
    return (
        "You are a 'Markdown data governance cleaner'.\n"
        "Goal: Clean up noise and formatting issues from parsing/copying, but do not change semantics or fabricate content.\n"
        "Requirements:\n"
        "1) Preserve heading/list/table/code block structure; do not modify code block content.\n"
        "2) Remove obvious headers/footers/page numbers/TOC markers/repeated short lines/control characters/zero-width characters.\n"
        "3) Normalize whitespace: merge excess blank lines, remove trailing spaces, merge 'soft line breaks' when necessary.\n"
        "4) Do not translate or rewrite; only clean and normalize.\n"
        "Output: Return strict JSON with fields: markdown/changes/warnings.\n"
    )


def _resolve_llm_clean_prompt_selection(
    *,
    body: LLMCleanPreviewRequest,
    db: Session,
    tenant_id: UUID,
    account_id: str,
) -> _LLMCleanPromptSelection:
    selection = _LLMCleanPromptSelection(system_prompt=_default_llm_clean_system_prompt())
    if not (body.prompt_template_id or body.template_key or body.ab_experiment_key):
        return selection

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

    selection.system_prompt = str(chosen.content or "").strip() or selection.system_prompt
    selection.prompt_template_id = str(chosen.id)
    selection.template_key = getattr(chosen, "template_key", None)
    selection.ab_experiment_key = getattr(chosen, "ab_experiment_key", None)
    selection.ab_variant = getattr(chosen, "ab_variant", None)
    chosen.usage_count += 1
    db.commit()
    return selection


def _llm_clean_model_config(body: LLMCleanPreviewRequest) -> dict[str, object] | None:
    model_config: dict[str, object] = {}
    if body.model:
        model_config["model"] = body.model
    if body.temperature is not None:
        model_config["temperature"] = body.temperature
    return model_config or None


async def _request_llm_clean_preview(
    *,
    markdown: str,
    body: LLMCleanPreviewRequest,
    system_prompt: str,
) -> dict[str, Any]:
    try:
        llm = await create_llm_client(scenario="governance_cleaning", model_config=_llm_clean_model_config(body))
        return await llm.chat_with_schema(
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
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {str(exc)[:200]}") from exc


def _parse_llm_clean_response(resp: object, fallback_markdown: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    cleaned = ""
    if isinstance(resp, dict):
        markdown = resp.get("markdown")
        if isinstance(markdown, str):
            cleaned = markdown
        else:
            raw = resp.get("raw")
            if isinstance(raw, str) and raw.strip():
                cleaned = raw.strip()
                warnings.append("LLM did not return JSON schema; falling back to raw text.")

        warn_val = resp.get("warnings")
        if isinstance(warn_val, list):
            warnings.extend([str(item).strip() for item in warn_val if str(item).strip()])

    if not cleaned.strip():
        cleaned = fallback_markdown
        warnings.append("LLM returned empty; falling back to original text.")
    return cleaned, warnings


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

    prompt_selection = _resolve_llm_clean_prompt_selection(body=body, db=db, tenant_id=tenant_id, account_id=account_id)
    resp = await _request_llm_clean_preview(markdown=markdown, body=body, system_prompt=prompt_selection.system_prompt)
    cleaned, warnings = _parse_llm_clean_response(resp, markdown)

    return LLMCleanPreviewResponse(
        markdown=cleaned,
        changed=(cleaned != markdown),
        model_used=body.model or settings.LLM_MODEL,
        prompt_template_id=prompt_selection.prompt_template_id,
        template_key=prompt_selection.template_key,
        ab_experiment_key=prompt_selection.ab_experiment_key,
        ab_variant=prompt_selection.ab_variant,
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
            logger.debug(_PIPELINE_FALLBACK_LOG_MESSAGE, exc)
