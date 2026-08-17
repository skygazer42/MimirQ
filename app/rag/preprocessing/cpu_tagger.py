
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.rag.preprocessing.keyword import extract_keywords
from app.rag.preprocessing.pii_anonymizer import find_pii_matches
from app.rag.preprocessing.secrets import find_secret_matches

DocumentTagType = Literal["topic", "category", "domain", "industry", "doc_type", "sensitivity", "quality", "keyword"]
SpanAnnotationType = Literal["entity", "keyword", "sensitive", "custom"]

_TRIM_PUNCTUATION_CHARS = " \t\r\n，,。.;；:："
_TAG_LABELS: dict[str, str] = {
    "topic": "主题",
    "category": "分类",
    "domain": "领域",
    "industry": "行业",
    "doc_type": "文档类型",
    "sensitivity": "敏感度",
    "quality": "质量线索",
    "keyword": "语义关键词",
}
_DOMAIN_TERMS = (
    "知识库检索",
    "入库质量分析",
    "入库流程",
    "数据治理",
    "治理流程",
    "检索策略",
    "文档解析",
    "结构化提取",
    "全文解析",
    "切块策略",
    "RAG",
)
_ACTION_RE = re.compile(r"[^。！？!?；;\n]{0,50}(?:建议|需要|应当|必须|后续|下一步|待|TODO|完善|优化|修复)[^。！？!?；;\n]{2,100}")
_ACTION_MARKER_RE = re.compile(r"(建议|需要|应当|必须|后续|下一步|待|TODO|完善|优化|修复)")
_RISK_RE = re.compile(r"[^。！？!?；;\n]{0,50}(?:风险|异常|失败|阻断|漏洞|敏感|脱敏|隔离|告警|质量问题)[^。！？!?；;\n]{2,100}")
_NOISE_KEYWORDS = {
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
}


class CPUDocumentTag(BaseModel):
    type: DocumentTagType
    value: str = Field(..., min_length=1, max_length=120)
    label: str = Field(default="")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    source: str = Field(default="cpu", max_length=64)


class CPUSpanAnnotation(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    type: SpanAnnotationType = "custom"
    label: str = Field(default="文档重点", min_length=1, max_length=80)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    source: str = Field(default="cpu", max_length=64)


class CPUTaggingResult(BaseModel):
    summary: str | None = None
    document_tags: list[CPUDocumentTag] = Field(default_factory=list)
    span_annotations: list[CPUSpanAnnotation] = Field(default_factory=list)
    provider: str = "cpu"


def _append_doc_tag(
    out: list[CPUDocumentTag],
    *,
    tag_type: DocumentTagType,
    value: str,
    confidence: float,
) -> None:
    normalized = str(value or "").strip(_TRIM_PUNCTUATION_CHARS)
    if not normalized:
        return
    key = (tag_type, normalized.casefold())
    if any((item.type, item.value.casefold()) == key for item in out):
        return
    out.append(
        CPUDocumentTag(
            type=tag_type,
            value=normalized,
            label=_TAG_LABELS[tag_type],
            confidence=min(1.0, max(0.0, confidence)),
            source="cpu",
        )
    )


def _append_span(
    out: list[CPUSpanAnnotation],
    *,
    text: str,
    annotation_type: SpanAnnotationType,
    label: str,
    confidence: float,
) -> None:
    normalized = str(text or "").strip(_TRIM_PUNCTUATION_CHARS)
    if len(normalized) < 2:
        return
    key = (annotation_type, normalized.casefold(), label.casefold())
    if any((item.type, item.text.casefold(), item.label.casefold()) == key for item in out):
        return
    out.append(
        CPUSpanAnnotation(
            text=normalized,
            type=annotation_type,
            label=label,
            confidence=min(1.0, max(0.0, confidence)),
            source="cpu",
        )
    )


def _looks_sensitive_or_noise(token: str) -> bool:
    text = str(token or "").strip()
    if not text:
        return True
    if text.casefold() in _NOISE_KEYWORDS:
        return True
    if re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", text):
        return True
    if re.fullmatch(r"\d[\d\s().-]{6,}\d", text):
        return True
    if text.isascii() and len(text) < 4:
        return True
    if not text.isascii() and len(text) > 10:
        return True
    if text.startswith(("建议", "需要", "应当", "必须", "后续", "下一步")):
        return True
    return False


def _trim_action_phrase(value: str) -> str:
    text = str(value or "").strip(_TRIM_PUNCTUATION_CHARS)
    marker_start = None
    for match in _ACTION_MARKER_RE.finditer(text):
        marker_start = int(match.start())
    if marker_start is not None:
        text = text[marker_start:]
    return text.strip(_TRIM_PUNCTUATION_CHARS)


def _classify_document(text: str, tags: list[CPUDocumentTag]) -> None:
    if any(term in text for term in ("知识库", "RAG", "检索", "入库", "文档治理", "数据治理")):
        _append_doc_tag(tags, tag_type="domain", value="企业知识库", confidence=0.78)
        _append_doc_tag(tags, tag_type="industry", value="通用企业服务", confidence=0.66)

    if any(term in text for term in ("入库", "解析", "切块", "治理流程", "文档治理")):
        _append_doc_tag(tags, tag_type="category", value="入库流程", confidence=0.76)
    if any(term in text for term in ("检索", "召回", "rerank", "重排")):
        _append_doc_tag(tags, tag_type="category", value="检索治理", confidence=0.7)
    if any(term in text for term in ("质量", "异常", "风险", "人工复核", "脱敏")):
        _append_doc_tag(tags, tag_type="category", value="质量评估", confidence=0.68)

    if any(term in text for term in ("治理方案", "解决方案", "方案")):
        _append_doc_tag(tags, tag_type="doc_type", value="治理方案", confidence=0.78)
    elif any(term in text for term in ("测试报告", "评测报告", "报告")):
        _append_doc_tag(tags, tag_type="doc_type", value="测试报告", confidence=0.74)
    elif any(term in text for term in ("合同", "协议")):
        _append_doc_tag(tags, tag_type="doc_type", value="合同", confidence=0.78)
    elif any(term in text for term in ("政策", "制度", "规则", "规范")):
        _append_doc_tag(tags, tag_type="doc_type", value="制度规范", confidence=0.72)


def _apply_sensitivity_tags(
    *,
    source: str,
    document_tags: list[CPUDocumentTag],
) -> set[str]:
    pii_hits = find_pii_matches(source, max_matches=5)
    secret_hits = find_secret_matches(source, max_matches=5)
    sensitive_texts = {str(match.text or "").casefold() for match in [*pii_hits, *secret_hits] if str(match.text or "").strip()}
    if pii_hits or secret_hits:
        _append_doc_tag(document_tags, tag_type="sensitivity", value="restricted", confidence=0.92)
        _append_doc_tag(document_tags, tag_type="quality", value="含敏感信息，建议人工复核", confidence=0.9)
    else:
        _append_doc_tag(document_tags, tag_type="sensitivity", value="internal", confidence=0.62)
    return sensitive_texts


def _append_domain_terms(
    *,
    source: str,
    document_tags: list[CPUDocumentTag],
    spans: list[CPUSpanAnnotation],
    max_items: int,
) -> None:
    for term in _DOMAIN_TERMS:
        if term in source and not _looks_sensitive_or_noise(term):
            _append_doc_tag(document_tags, tag_type="topic", value=term, confidence=0.78)
            _append_span(spans, text=term, annotation_type="keyword", label="主题关键词", confidence=0.78)
        if len(spans) >= max_items:
            break


def _extract_source_keywords(source: str, *, keyword_provider: str, keyword_top_k: int) -> list[str]:
    try:
        return extract_keywords(source, provider=keyword_provider or "simple", top_k=keyword_top_k)
    except Exception:
        return extract_keywords(source, provider="simple", top_k=keyword_top_k)


def _append_keyword_tags(
    *,
    source: str,
    keywords: list[str],
    sensitive_texts: set[str],
    document_tags: list[CPUDocumentTag],
    spans: list[CPUSpanAnnotation],
    max_items: int,
) -> None:
    for keyword in keywords:
        keyword_cf = str(keyword or "").casefold()
        if _looks_sensitive_or_noise(keyword) or keyword not in source:
            continue
        if any(keyword_cf in sensitive_text or sensitive_text in keyword_cf for sensitive_text in sensitive_texts):
            continue
        _append_doc_tag(document_tags, tag_type="topic", value=keyword, confidence=0.68)
        _append_span(spans, text=keyword, annotation_type="keyword", label="主题关键词", confidence=0.68)
        if len(spans) >= max_items:
            break


def _append_action_and_risk_tags(
    *,
    source: str,
    document_tags: list[CPUDocumentTag],
    spans: list[CPUSpanAnnotation],
) -> None:
    for match in _ACTION_RE.finditer(source):
        phrase = _trim_action_phrase(match.group(0))
        _append_doc_tag(document_tags, tag_type="quality", value=phrase, confidence=0.74)
        _append_span(spans, text=phrase, annotation_type="custom", label="动作项", confidence=0.82)
        break

    for match in _RISK_RE.finditer(source):
        phrase = str(match.group(0) or "").strip(_TRIM_PUNCTUATION_CHARS)
        _append_doc_tag(document_tags, tag_type="quality", value=phrase, confidence=0.74)
        _append_span(spans, text=phrase, annotation_type="custom", label="风险线索", confidence=0.8)
        break


def extract_cpu_tags(
    *,
    text: str,
    keyword_provider: str = "simple",
    keyword_top_k: int = 12,
    max_items: int = 80,
) -> CPUTaggingResult:
    source = str(text or "").strip()
    max_items_i = max(1, int(max_items or 80))
    document_tags: list[CPUDocumentTag] = []
    spans: list[CPUSpanAnnotation] = []
    if not source:
        return CPUTaggingResult(document_tags=[], span_annotations=[], provider="cpu")

    _classify_document(source, document_tags)
    sensitive_texts = _apply_sensitivity_tags(source=source, document_tags=document_tags)
    _append_domain_terms(source=source, document_tags=document_tags, spans=spans, max_items=max_items_i)
    keywords = _extract_source_keywords(source, keyword_provider=keyword_provider, keyword_top_k=keyword_top_k)
    _append_keyword_tags(
        source=source,
        keywords=keywords,
        sensitive_texts=sensitive_texts,
        document_tags=document_tags,
        spans=spans,
        max_items=max_items_i,
    )
    _append_action_and_risk_tags(source=source, document_tags=document_tags, spans=spans)

    return CPUTaggingResult(
        summary=None,
        document_tags=document_tags[:max_items_i],
        span_annotations=spans[:max_items_i],
        provider="cpu",
    )


__all__ = [
    "CPUDocumentTag",
    "CPUSpanAnnotation",
    "CPUTaggingResult",
    "extract_cpu_tags",
]
