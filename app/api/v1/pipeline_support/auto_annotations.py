"""Auto-annotation and common-lines learning helpers for the pipeline API.

Owns provider collection, candidate normalization, and common-lines sampling.
"""

import asyncio
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.api.schemas.pipelines import (
    AutoAnnotationItem,
    AutoAnnotationRequest,
    AutoDocumentTag,
)
from app.core.async_bridge import run_blocking_in_thread
from app.models.document import Document as DBDocument
from app.models.document import DocumentParsedContent
from app.rag.preprocessing.cpu_tagger import CPUDocumentTag, CPUSpanAnnotation, extract_cpu_tags
from app.rag.preprocessing.llm_tagger import LLMDocumentTag, LLMSpanAnnotation, extract_llm_tags
from app.rag.preprocessing.pii_anonymizer import PiiMatch, find_pii_matches
from app.rag.preprocessing.secrets import SecretMatch, find_secret_matches
from app.services.document_access import get_allowed_document_id_sets

_AUTO_TAGGER_LLM_TIMEOUT_S = 3.0
_TRIM_PUNCTUATION_CHARS = " \t\r\n，,。.;；:："
_TOPIC_KEYWORD_LABEL = "主题关键词"
_AUTO_PROVIDER_ALIASES = {
    "entity": ("regex",),
    "regex_entity": ("regex",),
    "sensitive": ("pii", "secret"),
}
_SENSITIVE_PROVIDER_SOURCES = {"pii", "secret"}
_FOCUS_SENTENCE_TERMS = ("知识库", "数据治理", "检索", "入库", "流程", "质量", "风险", "建议", "核心")

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
        re.compile(
            r"[^。！？!?；;\n]{0,50}(?:建议|需要|应当|必须|后续|下一步|待|TODO|完善|优化|修复)[^。！？!?；;\n]{2,100}[。！？!?；;]?"
        ),
        0.82,
    ),
    (
        "风险线索",
        "custom",
        re.compile(
            r"[^。！？!?；;\n]{0,50}(?:风险|异常|失败|阻断|漏洞|敏感|脱敏|隔离|告警|质量问题)[^。！？!?；;\n]{2,100}[。！？!?；;]?"
        ),
        0.8,
    ),
    (
        "文档重点",
        "custom",
        re.compile(
            r"[^。！？!?；;\n]{0,50}(?:核心能力|重点|结论|目标|范围|方案|流程|策略|指标|知识库|数据治理|检索|入库)[^。！？!?；;\n]{2,120}[。！？!?；;]?"
        ),
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
    text = raw.strip(_TRIM_PUNCTUATION_CHARS)
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
        label=label,
        start=start,
        end=end,
        confidence=confidence,
        source=source,
    )


def _annotation_overlaps(item: AutoAnnotationItem, other: AutoAnnotationItem) -> bool:
    return item.start < other.end and item.end > other.start


def _trim_match_span(source_text: str, start: int, end: int) -> tuple[int, int]:
    left = start
    right = end
    while left < right and source_text[left] in _TRIM_PUNCTUATION_CHARS:
        left += 1
    while right > left and source_text[right - 1] in _TRIM_PUNCTUATION_CHARS:
        right -= 1
    return left, right


def _find_keyword_offsets(text: str, keyword: str, *, limit: int = 2) -> list[tuple[int, int]]:
    kw = keyword.strip()
    if len(kw) < 2:
        return []

    flags = re.IGNORECASE if kw.isascii() else 0
    out: list[tuple[int, int]] = []
    for match in re.finditer(re.escape(kw), text, flags=flags):
        start, end = match.start(), match.end()
        out.append((start, end))
        if len(out) >= limit:
            break
    return out


def _is_focus_keyword(text: str) -> bool:
    token = text.strip()
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
            item.start,
            priority[item.type],
            -item.confidence,
            item.end,
            item.text,
        ),
    )

    seen: set[tuple[str, int, int, str]] = set()
    out: list[AutoAnnotationItem] = []
    for item in sorted_items:
        key = (item.type, item.start, item.end, item.text)
        if key in seen:
            continue
        if item.type == "keyword" and any(
            _annotation_overlaps(item, kept) and kept.type in {"sensitive", "entity"} for kept in out
        ):
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= max_items:
            break
    return out


def _normalize_auto_annotation_providers(body: AutoAnnotationRequest) -> set[str]:
    providers: set[str] = set()
    if body.providers is not None:
        for provider in body.providers:
            providers.update(_AUTO_PROVIDER_ALIASES.get(provider, (provider,)))
        return providers

    if body.mode == "document_focus":
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
    value_s = value.strip()
    if not value_s:
        return None
    return AutoDocumentTag(
        type=tag_type,  # type: ignore[arg-type]
        value=value_s,
        label=label or tag_type,
        confidence=min(1.0, max(0.0, confidence)),
        source=source,
    )


def _dedupe_auto_document_tags(items: list[AutoDocumentTag], *, max_items: int) -> list[AutoDocumentTag]:
    seen: set[tuple[str, str]] = set()
    out: list[AutoDocumentTag] = []
    for item in items:
        key = (item.type, item.value.casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= max_items:
            break
    return out


def _normalize_auto_document_tags(raw_tags: Iterable[CPUDocumentTag | LLMDocumentTag]) -> list[AutoDocumentTag]:
    document_tags: list[AutoDocumentTag] = []
    for tag in raw_tags:
        item = _make_auto_document_tag(
            tag_type=tag.type,
            value=tag.value,
            label=tag.label,
            confidence=tag.confidence,
            source=tag.source,
        )
        if item is not None:
            document_tags.append(item)
    return document_tags


def _normalize_span_annotations(
    text: str,
    raw_annotations: Iterable[CPUSpanAnnotation | LLMSpanAnnotation],
    *,
    max_items: int,
) -> list[AutoAnnotationItem]:
    annotations: list[AutoAnnotationItem] = []
    for raw in raw_annotations:
        quote = raw.text.strip()
        if not quote:
            continue
        for start, end in _find_keyword_offsets(text, quote, limit=1):
            item = _make_auto_annotation(
                source_text=text,
                start=start,
                end=end,
                annotation_type=raw.type,
                label=raw.label,
                confidence=min(0.99, raw.confidence),
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
        if item.type == "keyword" and item.label == _TOPIC_KEYWORD_LABEL:
            tag_type = "topic"
            label = "主题"
        elif item.type == "custom" and item.label in {"动作项", "风险线索"}:
            tag_type = "quality"
            label = "质量线索"
        else:
            continue
        tag = _make_auto_document_tag(
            tag_type=tag_type,
            value=item.text,
            label=label,
            confidence=min(0.9, item.confidence),
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
        keywords = extract_keywords_fn(text, provider=provider_key, top_k=top_k)
    except Exception:
        provider_key = "simple"
        keywords = extract_keywords_fn(text, provider=provider_key, top_k=top_k)

    out: list[AutoAnnotationItem] = []
    for keyword in keywords:
        for start, end in _find_keyword_offsets(text, keyword, limit=2):
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
                confidence=max(item.confidence, 0.72),
                source="keyword",
            )
        )
        if len(out) >= max_items:
            break
    return provider_key, out


def _collect_domain_focus_terms(
    text: str, *, max_items: int, blocked: list[AutoAnnotationItem]
) -> list[AutoAnnotationItem]:
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
        marker_start = match.start()
    if marker_start is not None:
        start += marker_start
    return _trim_match_span(text, start, end)


def _collect_entity_annotations(text: str, *, max_items: int) -> list[AutoAnnotationItem]:
    out: list[AutoAnnotationItem] = []
    for pattern in (_ZH_ENTITY_RE, _EN_ENTITY_RE):
        for match in pattern.finditer(text):
            raw = match.group(0)
            trimmed, offset = _trim_entity_span(raw)
            if len(trimmed) < 2:
                continue
            start = match.start() + offset
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


def _append_sensitive_match_annotations(
    text: str,
    out: list[AutoAnnotationItem],
    matches: Iterable[PiiMatch | SecretMatch],
    *,
    max_items: int,
    source: str,
    confidence: float,
) -> bool:
    for match in matches:
        item = _make_auto_annotation(
            source_text=text,
            start=match.start,
            end=match.end,
            annotation_type="sensitive",
            label=match.kind,
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
            start, end = _trim_focus_rule_span(text, label, match.start(), match.end())
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


def _append_focus_sentence_candidate(
    text: str,
    candidates: list[AutoAnnotationItem],
    blocked: list[AutoAnnotationItem],
) -> None:
    for match in _FOCUS_SENTENCE_RE.finditer(text):
        sentence = match.group(0).strip()
        if not any(key in sentence for key in _FOCUS_SENTENCE_TERMS):
            continue
        start, end = _trim_match_span(text, match.start(), match.end())
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


def _remaining_auto_slots(draft: _AutoAnnotationDraft, max_items: int) -> int:
    return max(0, max_items - len(draft.candidates))


def _collect_cpu_auto_provider(
    draft: _AutoAnnotationDraft, scan_text: str, body: AutoAnnotationRequest, max_items: int
) -> None:
    result = extract_cpu_tags(
        text=scan_text,
        keyword_provider=body.keyword_provider,
        keyword_top_k=body.keyword_top_k,
        max_items=max_items,
    )
    cpu_tags = _normalize_auto_document_tags(result.document_tags)
    cpu_items = _normalize_span_annotations(scan_text, result.span_annotations, max_items=max_items)
    if result.summary and draft.summary is None:
        draft.summary = result.summary
    draft.document_tags.extend(cpu_tags)
    draft.candidates.extend(cpu_items)
    if cpu_items:
        _append_provider_used(draft.providers_used, "cpu")


async def _collect_llm_auto_provider(
    draft: _AutoAnnotationDraft, scan_text: str, body: AutoAnnotationRequest, max_items: int
) -> None:
    try:
        result = await asyncio.wait_for(
            extract_llm_tags(
                text=scan_text,
                max_items=max_items,
                max_chars=body.max_chars,
                model=body.llm_model,
            ),
            timeout=_AUTO_TAGGER_LLM_TIMEOUT_S,
        )
        llm_tags = _normalize_auto_document_tags(result.document_tags)
        llm_items = _normalize_span_annotations(scan_text, result.span_annotations, max_items=max_items)
    except Exception:
        draft.warnings.append("LLM focus extraction unavailable; used rules fallback.")
        return

    if result.summary:
        draft.summary = result.summary
    draft.document_tags.extend(llm_tags)
    draft.candidates.extend(llm_items)
    if result.summary or llm_tags or llm_items:
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
        keyword_provider=body.keyword_provider,
        keyword_top_k=body.keyword_top_k,
        max_items=_remaining_auto_slots(draft, max_items),
    )
    draft.candidates.extend(rule_items)
    if not rule_items:
        return
    if any(item.source == "keyword" for item in rule_items):
        _append_provider_used(draft.providers_used, "keyword")
    if any(item.source == "regex_entity" for item in rule_items):
        _append_provider_used(draft.providers_used, "regex")
    if any(item.source == "rule_focus" for item in rule_items):
        _append_provider_used(draft.providers_used, "rule_focus")
    draft.strategy = "hybrid" if draft.strategy == "llm" else "rules"


def _collect_sensitive_auto_provider(
    draft: _AutoAnnotationDraft,
    scan_text: str,
    providers: set[str],
    max_items: int,
) -> None:
    sensitive_providers = providers & _SENSITIVE_PROVIDER_SOURCES
    if not sensitive_providers or _remaining_auto_slots(draft, max_items) <= 0:
        return
    sensitive_items = _collect_sensitive_annotations(
        scan_text,
        max_items=_remaining_auto_slots(draft, max_items),
        providers=sensitive_providers,
    )
    draft.candidates.extend(sensitive_items)
    for source in {item.source for item in sensitive_items}:
        _append_provider_used(draft.providers_used, source)


def _collect_regex_auto_provider(draft: _AutoAnnotationDraft, scan_text: str, max_items: int) -> None:
    if _remaining_auto_slots(draft, max_items) <= 0:
        return
    entity_items = _collect_entity_annotations(scan_text, max_items=_remaining_auto_slots(draft, max_items))
    draft.candidates.extend(entity_items)
    if entity_items:
        _append_provider_used(draft.providers_used, "regex")


def _collect_keyword_auto_provider(
    draft: _AutoAnnotationDraft, scan_text: str, body: AutoAnnotationRequest, max_items: int
) -> None:
    if _remaining_auto_slots(draft, max_items) <= 0:
        return
    draft.keyword_provider, keyword_items = _collect_keyword_annotations(
        scan_text,
        provider=body.keyword_provider,
        top_k=body.keyword_top_k,
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
        await run_blocking_in_thread(_collect_cpu_auto_provider, draft, scan_text, body, max_items)
    if "llm" in providers:
        await _collect_llm_auto_provider(draft, scan_text, body, max_items)

    await run_blocking_in_thread(_collect_document_focus_rule_fallback, draft, scan_text, body, providers, max_items)

    if providers & _SENSITIVE_PROVIDER_SOURCES and _remaining_auto_slots(draft, max_items) > 0:
        await run_blocking_in_thread(_collect_sensitive_auto_provider, draft, scan_text, providers, max_items)
        draft.strategy = "hybrid" if draft.candidates else draft.strategy


async def _collect_compliance_annotations(
    draft: _AutoAnnotationDraft,
    scan_text: str,
    body: AutoAnnotationRequest,
    providers: set[str],
    max_items: int,
) -> None:
    await run_blocking_in_thread(_collect_sensitive_auto_provider, draft, scan_text, providers, max_items)
    if "regex" in providers:
        await run_blocking_in_thread(_collect_regex_auto_provider, draft, scan_text, max_items)
    if "keyword" in providers:
        await run_blocking_in_thread(_collect_keyword_auto_provider, draft, scan_text, body, max_items)
    draft.strategy = "rules"


def _finalize_auto_annotation_keyword_provider(
    keyword_provider: str | None,
    body: AutoAnnotationRequest,
    providers: set[str],
) -> str | None:
    if keyword_provider is not None or "keyword" not in providers:
        return keyword_provider
    provider = body.keyword_provider.strip().lower() or "simple"
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
    return total


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
    return [row[0] for row in rows]


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
    return [doc_id for doc_id in raw_doc_ids if doc_id in allowed_ids][:limit_docs]


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
    return {doc_id: (original, cleaned) for doc_id, original, cleaned in rows}


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
