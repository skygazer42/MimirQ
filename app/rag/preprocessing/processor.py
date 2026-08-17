"""
Markdown governance processor shared by parsing and indexing pipelines.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.preprocessing.boilerplate import remove_markdown_boilerplate
from app.rag.preprocessing.cleaning import (
    RegexRule,
    build_common_line_signatures,
    build_repeated_line_signatures,
    clean_markdown,
)
from app.rag.preprocessing.code_blocks import strip_fenced_code_line_numbers
from app.rag.preprocessing.frontmatter import (
    extract_markdown_frontmatter as extract_markdown_frontmatter_fn,
)
from app.rag.preprocessing.frontmatter import (
    extract_markdown_title as extract_markdown_title_fn,
)
from app.rag.preprocessing.images import strip_images
from app.rag.preprocessing.keyword import extract_keywords as extract_keywords_fn
from app.rag.preprocessing.language import detect_language as detect_language_fn
from app.rag.preprocessing.paragraph_dedup import drop_duplicate_paragraphs as drop_duplicate_paragraphs_fn
from app.rag.preprocessing.pii_anonymizer import anonymize_pii
from app.rag.preprocessing.quality_filters import (
    drop_if_high_perplexity_proxy,
    drop_if_low_density,
    drop_if_outline_only,
)
from app.rag.preprocessing.references import trim_references_section as trim_references_section_fn
from app.rag.preprocessing.rules import DEFAULT_MARKDOWN_RULES
from app.rag.preprocessing.secrets import redact_secrets
from app.rag.preprocessing.tables import normalize_markdown_tables
from app.rag.preprocessing.urls import normalize_urls as normalize_urls_fn

logger = get_logger(__name__)
_MARKDOWN_GOVERNANCE_FALLBACK_LOG_MESSAGE = "Ignoring non-critical markdown governance fallback failure: %s"

GOVERNANCE_RULESET_VERSION = "1"


@dataclass(frozen=True)
class GovernanceStats:
    documents: int
    changed: int
    applied_rules: int
    version: str = GOVERNANCE_RULESET_VERSION
    dropped: int = 0
    drop_reasons: dict[str, int] = field(default_factory=dict)
    pii_hits: dict[str, int] = field(default_factory=dict)
    secrets_hits: dict[str, int] = field(default_factory=dict)
    frontmatter_docs: int = 0
    frontmatter_stripped_docs: int = 0
    paragraphs_dropped: int = 0
    references_removed_lines: int = 0
    urls_changed: int = 0
    boilerplate_removed_sections: int = 0
    boilerplate_removed_lines: int = 0
    images_removed: int = 0
    tables_normalized: int = 0
    table_rows_changed: int = 0
    code_blocks_changed: int = 0
    code_lines_stripped: int = 0
    keywords_docs: int = 0
    keywords_total: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    titles_docs: int = 0
    tags_docs: int = 0


@dataclass(frozen=True)
class GovernanceCleanOptions:
    extract_frontmatter: bool = False
    strip_frontmatter: bool = False
    detect_language: bool = False
    language_min_chars: int = 40
    normalize_urls: bool = False
    normalize_urls_strip_tracking: bool = True
    drop_duplicate_paragraphs: bool = False
    drop_duplicate_paragraphs_min_occurrences: int = 3
    drop_duplicate_paragraphs_min_chars: int = 40
    drop_duplicate_paragraphs_max_chars: int = 1200
    trim_references: bool = False
    extract_keywords: bool = False
    keywords_provider: str = "auto"
    keywords_top_k: int = 10
    keywords_max_chars: int = 20_000
    remove_toc_lines: bool = True
    remove_noise_lines: bool = True
    unwrap_lines: bool = True
    remove_common_lines: bool = True
    remove_boilerplate: bool = False
    remove_images: str = "none"
    normalize_tables: bool = False
    strip_code_line_numbers: bool = False
    pii_anonymize: bool = False
    pii_mode: str = "mask"
    pii_mask: str = "[REDACTED]"
    pii_max_hits: int = -1
    secrets_redact: bool = False
    secrets_mode: str = "mask"
    secrets_mask: str = "[SECRET]"
    secrets_max_hits: int = -1
    max_blank_lines: int = 1
    drop_outline_only: bool = False
    drop_outline_min_content_chars: int = 200
    drop_outline_max_heading_ratio: float = 0.85
    drop_low_density: bool = False
    drop_low_density_threshold: float = 0.12
    drop_high_perplexity: bool = False
    drop_high_perplexity_threshold: float = 0.55
    drop_high_perplexity_min_tokens: int = 20
    collapse_blank_lines: bool = True
    unwrap_max_line_length: int = 120
    noise_min_chars: int = 2
    noise_ratio_threshold: float = 0.2
    common_lines_min_docs: int = 3
    common_lines_min_ratio: float = 0.35


@dataclass
class _GovernanceTotals:
    changed: int = 0
    applied_rules: int = 0
    dropped: int = 0
    drop_reasons: dict[str, int] = field(default_factory=dict)
    pii_hits: dict[str, int] = field(default_factory=dict)
    secrets_hits: dict[str, int] = field(default_factory=dict)
    frontmatter_docs: int = 0
    frontmatter_stripped_docs: int = 0
    paragraphs_dropped: int = 0
    references_removed_lines: int = 0
    urls_changed: int = 0
    boilerplate_removed_sections: int = 0
    boilerplate_removed_lines: int = 0
    images_removed: int = 0
    tables_normalized: int = 0
    table_rows_changed: int = 0
    code_blocks_changed: int = 0
    code_lines_stripped: int = 0
    keywords_docs: int = 0
    keywords_total: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    titles_docs: int = 0
    tags_docs: int = 0


@dataclass
class _DocumentState:
    source: Document
    original_text: str
    text: str
    changed: bool = False
    applied_rules: int = 0
    frontmatter_present: bool = False
    frontmatter_end_char: int | None = None
    frontmatter_data: dict[str, object] | None = None
    frontmatter_changed: bool = False
    title: str | None = None
    tags: list[str] | None = None
    table_count: int = 0
    table_rows_changed: int = 0
    code_blocks_changed: int = 0
    code_lines_stripped: int = 0
    boilerplate: Any | None = None
    images_removed: int = 0
    pii_hits: dict[str, int] = field(default_factory=dict)
    secrets_hits: dict[str, int] = field(default_factory=dict)
    paragraphs_dropped: int = 0
    references_removed_lines: int = 0
    urls_changed: int = 0
    language: str | None = None
    language_confidence: float | None = None
    keywords: list[str] | None = None


def _resolved_options(
    options: GovernanceCleanOptions | None,
    legacy_overrides: dict[str, Any],
) -> GovernanceCleanOptions:
    resolved = options or GovernanceCleanOptions()
    return replace(resolved, **legacy_overrides) if legacy_overrides else resolved


def _global_common_lines(
    documents: Sequence[Document],
    options: GovernanceCleanOptions,
) -> set[str]:
    if not options.remove_common_lines:
        return set()
    doc_count = len(documents)
    min_docs = max(2, int(options.common_lines_min_docs or 0))
    min_docs = min(min_docs, doc_count) if doc_count >= 2 else 0
    if min_docs < 2:
        return set()
    return build_common_line_signatures(
        [doc.page_content or "" for doc in documents],
        min_docs=min_docs,
        min_ratio=options.common_lines_min_ratio,
        max_line_length=options.unwrap_max_line_length,
    )


def _normalize_frontmatter_tags(raw_tags: object) -> list[str] | None:
    if isinstance(raw_tags, str) and raw_tags.strip():
        parts = [part.strip() for part in raw_tags.replace(";", ",").split(",") if part.strip()]
        return parts[:50] or None
    if not isinstance(raw_tags, list):
        return None
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_tags:
        value = str(item).strip() if item is not None else ""
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        cleaned.append(value[:64])
    return cleaned[:50] or None


def _extract_frontmatter(
    state: _DocumentState,
    options: GovernanceCleanOptions,
    totals: _GovernanceTotals,
) -> None:
    if not (options.extract_frontmatter or options.strip_frontmatter):
        return
    try:
        frontmatter = extract_markdown_frontmatter_fn(state.original_text, strip=bool(options.strip_frontmatter))
    except Exception:
        frontmatter = None
    if frontmatter is None:
        return

    state.frontmatter_present = True
    state.frontmatter_end_char = int(getattr(frontmatter, "end_char", 0) or 0)
    state.frontmatter_changed = bool(getattr(frontmatter, "changed", False))
    if options.strip_frontmatter:
        state.text = getattr(frontmatter, "stripped_text", state.original_text) or ""
    data = getattr(frontmatter, "data", None)
    if isinstance(data, dict) and data:
        state.frontmatter_data = dict(data)
        raw_title = state.frontmatter_data.get("title")
        if isinstance(raw_title, str) and raw_title.strip():
            state.title = raw_title.strip()[:200]
        raw_tags = (
            state.frontmatter_data.get("tags")
            or state.frontmatter_data.get("tag")
            or state.frontmatter_data.get("categories")
            or state.frontmatter_data.get("category")
            or state.frontmatter_data.get("keywords")
        )
        state.tags = _normalize_frontmatter_tags(raw_tags)
    totals.frontmatter_docs += 1
    if state.frontmatter_changed:
        totals.frontmatter_stripped_docs += 1


def _apply_base_cleanup(
    state: _DocumentState,
    *,
    options: GovernanceCleanOptions,
    active_rules: list[RegexRule],
    global_common_lines: set[str],
    totals: _GovernanceTotals,
) -> None:
    local_common_lines = (
        build_repeated_line_signatures(
            state.text or "",
            min_occurrences=options.common_lines_min_docs,
            max_line_length=options.unwrap_max_line_length,
        )
        if options.remove_common_lines
        else set()
    )
    common_lines = (global_common_lines | local_common_lines) if options.remove_common_lines else None
    result = clean_markdown(
        state.text or "",
        rules=active_rules,
        regex_timeout_ms=int(getattr(settings, "GOVERNANCE_REGEX_TIMEOUT_MS", 100) or 100),
        common_lines=common_lines,
        remove_toc_lines=options.remove_toc_lines,
        remove_noise_lines=options.remove_noise_lines,
        unwrap_lines=options.unwrap_lines,
        remove_common_lines=options.remove_common_lines,
        collapse_blank_lines=options.collapse_blank_lines,
        max_blank_lines=options.max_blank_lines,
        unwrap_max_line_length=options.unwrap_max_line_length,
        noise_min_chars=options.noise_min_chars,
        noise_ratio_threshold=options.noise_ratio_threshold,
    )
    state.text = result.markdown
    state.applied_rules = int(result.applied_rules or 0)
    state.changed = bool(result.changed) or state.frontmatter_changed
    totals.applied_rules += state.applied_rules


def _apply_structural_transforms(
    state: _DocumentState,
    options: GovernanceCleanOptions,
    totals: _GovernanceTotals,
) -> None:
    if options.normalize_tables:
        table_result = normalize_markdown_tables(state.text)
        state.text = table_result.text
        state.table_count = int(table_result.tables or 0)
        state.table_rows_changed = int(table_result.rows_changed or 0)
        state.changed = state.changed or bool(table_result.changed)
        totals.tables_normalized += state.table_count
        totals.table_rows_changed += state.table_rows_changed
    if options.strip_code_line_numbers:
        code_result = strip_fenced_code_line_numbers(state.text)
        state.text = code_result.text
        state.code_blocks_changed = int(code_result.blocks_changed or 0)
        state.code_lines_stripped = int(code_result.lines_stripped or 0)
        state.changed = state.changed or bool(code_result.changed)
        totals.code_blocks_changed += state.code_blocks_changed
        totals.code_lines_stripped += state.code_lines_stripped
    if options.remove_boilerplate:
        state.boilerplate = remove_markdown_boilerplate(state.text)
        state.text = state.boilerplate.text
        state.changed = state.changed or bool(state.boilerplate.changed)
        totals.boilerplate_removed_sections += int(getattr(state.boilerplate, "removed_sections", 0) or 0)
        totals.boilerplate_removed_lines += int(getattr(state.boilerplate, "removed_lines", 0) or 0)
    image_mode = str(options.remove_images or "none").strip().lower()
    if image_mode in {"decorative", "all"}:
        image_result = strip_images(state.text, mode=image_mode)  # type: ignore[arg-type]
        state.text = image_result.text
        state.images_removed = int(image_result.removed or 0)
        state.changed = state.changed or bool(image_result.changed)
        totals.images_removed += state.images_removed


def _merge_hit_counts(target: dict[str, int], additions: dict[str, int]) -> None:
    for key, value in additions.items():
        target[key] = target.get(key, 0) + int(value)


def _apply_sensitive_transforms(
    state: _DocumentState,
    options: GovernanceCleanOptions,
    totals: _GovernanceTotals,
) -> None:
    if options.pii_anonymize:
        pii_result = anonymize_pii(
            state.text,
            enabled=True,
            mode=str(options.pii_mode or "mask"),
            mask=str(options.pii_mask or "[REDACTED]"),
        )  # type: ignore[arg-type]
        state.text = pii_result.text
        state.pii_hits = dict(pii_result.hits or {})
        state.changed = state.changed or bool(pii_result.changed)
        _merge_hit_counts(totals.pii_hits, state.pii_hits)
    if options.secrets_redact:
        secret_result = redact_secrets(
            state.text,
            enabled=True,
            mode=str(options.secrets_mode or "mask"),
            mask=str(options.secrets_mask or "[SECRET]"),
        )  # type: ignore[arg-type]
        state.text = secret_result.text
        state.secrets_hits = dict(secret_result.hits or {})
        state.changed = state.changed or bool(secret_result.changed)
        _merge_hit_counts(totals.secrets_hits, state.secrets_hits)


def _apply_best_effort_cleanup(
    state: _DocumentState,
    options: GovernanceCleanOptions,
    totals: _GovernanceTotals,
) -> None:
    if options.drop_duplicate_paragraphs:
        try:
            result = drop_duplicate_paragraphs_fn(
                state.text,
                min_occurrences=int(options.drop_duplicate_paragraphs_min_occurrences or 0),
                min_paragraph_chars=int(options.drop_duplicate_paragraphs_min_chars or 0),
                max_paragraph_chars=int(options.drop_duplicate_paragraphs_max_chars or 0),
            )
            state.text = result.text
            state.paragraphs_dropped = int(getattr(result, "paragraphs_dropped", 0) or 0)
            state.changed = state.changed or bool(getattr(result, "changed", False))
        except Exception as exc:
            logger.debug(_MARKDOWN_GOVERNANCE_FALLBACK_LOG_MESSAGE, exc)
    if options.trim_references:
        try:
            result = trim_references_section_fn(state.text)
            state.text = result.text
            state.references_removed_lines = int(getattr(result, "removed_lines", 0) or 0)
            state.changed = state.changed or bool(getattr(result, "changed", False))
        except Exception as exc:
            logger.debug(_MARKDOWN_GOVERNANCE_FALLBACK_LOG_MESSAGE, exc)
    if options.normalize_urls:
        try:
            result = normalize_urls_fn(state.text, strip_tracking=bool(options.normalize_urls_strip_tracking))
            state.text = result.text
            state.urls_changed = int(getattr(result, "urls_changed", 0) or 0)
            state.changed = state.changed or bool(getattr(result, "changed", False))
        except Exception as exc:
            logger.debug(_MARKDOWN_GOVERNANCE_FALLBACK_LOG_MESSAGE, exc)
    totals.paragraphs_dropped += state.paragraphs_dropped
    totals.references_removed_lines += state.references_removed_lines
    totals.urls_changed += state.urls_changed


def _quality_drop_reason(state: _DocumentState, options: GovernanceCleanOptions) -> str | None:
    if options.drop_outline_only:
        decision = drop_if_outline_only(
            state.text,
            min_content_chars=int(options.drop_outline_min_content_chars or 0),
            max_heading_ratio=float(options.drop_outline_max_heading_ratio or 0.0),
        )
        if decision.dropped:
            return decision.reason or "outline_only"
    if options.drop_low_density:
        decision = drop_if_low_density(state.text, threshold=float(options.drop_low_density_threshold or 0.0))
        if decision.dropped:
            return decision.reason or "low_density"
    if options.drop_high_perplexity:
        decision = drop_if_high_perplexity_proxy(
            state.text,
            threshold=float(options.drop_high_perplexity_threshold or 0.0),
            min_tokens=int(options.drop_high_perplexity_min_tokens or 0),
        )
        if decision.dropped:
            return decision.reason or "perplexity_proxy_high"
    return None


def _extract_title(state: _DocumentState) -> None:
    if state.title is not None:
        return
    try:
        state.title = extract_markdown_title_fn(state.text)
    except Exception:
        state.title = None


def _extract_language_and_keywords(state: _DocumentState, options: GovernanceCleanOptions) -> None:
    if options.detect_language:
        try:
            result = detect_language_fn(state.text, min_chars=int(options.language_min_chars or 0))
            state.language = str(getattr(result, "language", "") or "").strip() or None
            state.language_confidence = float(getattr(result, "confidence", 0.0) or 0.0)
        except Exception:
            state.language = None
            state.language_confidence = None
    if options.extract_keywords:
        try:
            max_chars = max(0, int(options.keywords_max_chars or 0))
            snippet = state.text[:max_chars] if max_chars > 0 else state.text
            keywords = extract_keywords_fn(
                snippet,
                provider=str(options.keywords_provider or "auto"),
                top_k=int(options.keywords_top_k or 10),
            )
            state.keywords = list(keywords) if keywords else None
        except Exception:
            state.keywords = None


def _record_enrichment(state: _DocumentState, totals: _GovernanceTotals) -> None:
    if state.title:
        totals.titles_docs += 1
    if state.tags:
        totals.tags_docs += 1
    if state.language:
        totals.languages[state.language] = totals.languages.get(state.language, 0) + 1
    if state.keywords:
        totals.keywords_docs += 1
        totals.keywords_total += len(state.keywords)
    if state.changed:
        totals.changed += 1


def _add_frontmatter_metadata(meta: dict[str, Any], state: _DocumentState, options: GovernanceCleanOptions) -> None:
    if not state.frontmatter_present:
        return
    meta["frontmatter_present"] = True
    if state.frontmatter_end_char and state.frontmatter_end_char > 0:
        meta["frontmatter_end_char"] = state.frontmatter_end_char
    if options.strip_frontmatter:
        meta["frontmatter_stripped"] = True
    if state.frontmatter_data:
        meta["document_frontmatter"] = state.frontmatter_data


def _add_enrichment_metadata(
    meta: dict[str, Any],
    state: _DocumentState,
    options: GovernanceCleanOptions,
) -> None:
    if state.title:
        meta["document_title"] = str(state.title)
    if state.tags:
        meta["document_tags"] = state.tags
    if state.language:
        meta["document_language"] = state.language
        meta["document_language_confidence"] = round(float(state.language_confidence or 0.0), 3)
    if state.keywords:
        meta["document_keywords"] = state.keywords
        meta["document_keywords_provider"] = str(options.keywords_provider or "auto")


def _add_cleanup_metadata(meta: dict[str, Any], state: _DocumentState) -> None:
    if state.paragraphs_dropped:
        meta["governance_paragraphs_dropped"] = state.paragraphs_dropped
    if state.references_removed_lines:
        meta["governance_references_removed_lines"] = state.references_removed_lines
    if state.urls_changed:
        meta["governance_urls_changed"] = state.urls_changed
    if state.boilerplate is not None:
        meta["governance_boilerplate_removed_sections"] = int(state.boilerplate.removed_sections or 0)
        meta["governance_boilerplate_removed_lines"] = int(state.boilerplate.removed_lines or 0)
    if state.images_removed:
        meta["governance_images_removed"] = state.images_removed


def _add_transform_metadata(meta: dict[str, Any], state: _DocumentState) -> None:
    if state.pii_hits:
        meta["governance_pii_hits"] = state.pii_hits
    if state.secrets_hits:
        meta["governance_secrets_hits"] = state.secrets_hits
    if state.table_count:
        meta["governance_tables_normalized"] = state.table_count
        meta["governance_table_rows_changed"] = state.table_rows_changed
    if state.code_lines_stripped:
        meta["governance_code_blocks_changed"] = state.code_blocks_changed
        meta["governance_code_lines_stripped"] = state.code_lines_stripped


def _add_quality_metadata(meta: dict[str, Any], text: str) -> None:
    try:
        density = drop_if_low_density(text, threshold=-1.0).metrics or {}
        outline = drop_if_outline_only(text, min_content_chars=0, max_heading_ratio=2.0).metrics or {}
        perplexity = drop_if_high_perplexity_proxy(text, threshold=2.0, min_tokens=0).metrics or {}
        meta["governance_quality"] = {
            "density": float(density.get("density") or 0.0),
            "chars_non_space": int(density.get("chars_non_space") or 0),
            "chars_alnum_cjk": int(density.get("chars_alnum_cjk") or 0),
            "heading_ratio": float(outline.get("heading_ratio") or 0.0),
            "lines_total": int(outline.get("lines_total") or 0),
            "lines_outline": int(outline.get("lines_outline") or 0),
            "content_chars": int(outline.get("content_chars") or 0),
            "perplexity_proxy": float(perplexity.get("perplexity_proxy") or 0.0),
            "token_count": int(perplexity.get("token_count") or 0),
        }
    except Exception as exc:
        logger.debug(_MARKDOWN_GOVERNANCE_FALLBACK_LOG_MESSAGE, exc)


def _build_clean_document(state: _DocumentState, options: GovernanceCleanOptions) -> Document:
    meta = dict(state.source.metadata or {})
    meta.update(
        {
            "governance_version": GOVERNANCE_RULESET_VERSION,
            "governance_applied": True,
            "governance_rules_applied": state.applied_rules,
            "governance_changed": state.changed,
        }
    )
    _add_frontmatter_metadata(meta, state, options)
    _add_enrichment_metadata(meta, state, options)
    _add_cleanup_metadata(meta, state)
    _add_transform_metadata(meta, state)
    _add_quality_metadata(meta, state.text)
    return Document(page_content=state.text, metadata=meta, id=getattr(state.source, "id", None))


def _process_document(
    document: Document,
    *,
    options: GovernanceCleanOptions,
    active_rules: list[RegexRule],
    global_common_lines: set[str],
    totals: _GovernanceTotals,
) -> Document | None:
    original_text = document.page_content or ""
    state = _DocumentState(source=document, original_text=original_text, text=original_text)
    _extract_frontmatter(state, options, totals)
    _apply_base_cleanup(
        state,
        options=options,
        active_rules=active_rules,
        global_common_lines=global_common_lines,
        totals=totals,
    )
    _apply_structural_transforms(state, options, totals)
    _apply_sensitive_transforms(state, options, totals)
    _apply_best_effort_cleanup(state, options, totals)
    drop_reason = _quality_drop_reason(state, options)
    if drop_reason is not None:
        totals.dropped += 1
        totals.drop_reasons[drop_reason] = totals.drop_reasons.get(drop_reason, 0) + 1
        return None
    _extract_title(state)
    _extract_language_and_keywords(state, options)
    _record_enrichment(state, totals)
    return _build_clean_document(state, options)


def _gate_reasons(
    options: GovernanceCleanOptions,
    totals: _GovernanceTotals,
    document_count: int,
) -> dict[str, int]:
    pii_gate = int(options.pii_max_hits) if isinstance(options.pii_max_hits, (int, float)) else -1
    secrets_gate = int(options.secrets_max_hits) if isinstance(options.secrets_max_hits, (int, float)) else -1
    pii_hits = sum(int(value or 0) for value in totals.pii_hits.values())
    secrets_hits = sum(int(value or 0) for value in totals.secrets_hits.values())
    reasons: dict[str, int] = {}
    if pii_gate >= 0 and pii_hits > pii_gate:
        reasons["pii_exceeded"] = document_count
    if secrets_gate >= 0 and secrets_hits > secrets_gate:
        reasons["secrets_exceeded"] = document_count
    return reasons


def _build_governance_stats(
    totals: _GovernanceTotals,
    *,
    document_count: int,
    gate_reasons: dict[str, int] | None = None,
) -> GovernanceStats:
    reasons = dict(totals.drop_reasons)
    reasons.update(gate_reasons or {})
    gated = bool(gate_reasons)
    return GovernanceStats(
        documents=document_count,
        changed=0 if gated else totals.changed,
        applied_rules=totals.applied_rules,
        dropped=document_count if gated else totals.dropped,
        drop_reasons=reasons,
        pii_hits=totals.pii_hits,
        secrets_hits=totals.secrets_hits,
        frontmatter_docs=totals.frontmatter_docs,
        frontmatter_stripped_docs=totals.frontmatter_stripped_docs,
        paragraphs_dropped=totals.paragraphs_dropped,
        references_removed_lines=totals.references_removed_lines,
        urls_changed=totals.urls_changed,
        boilerplate_removed_sections=totals.boilerplate_removed_sections,
        boilerplate_removed_lines=totals.boilerplate_removed_lines,
        images_removed=totals.images_removed,
        tables_normalized=totals.tables_normalized,
        table_rows_changed=totals.table_rows_changed,
        code_blocks_changed=totals.code_blocks_changed,
        code_lines_stripped=totals.code_lines_stripped,
        keywords_docs=totals.keywords_docs,
        keywords_total=totals.keywords_total,
        languages=totals.languages,
        titles_docs=totals.titles_docs,
        tags_docs=totals.tags_docs,
    )


class GovernanceProcessor:
    """Apply conservative markdown cleanup rules before chunking."""

    def __init__(self, rules: Iterable[RegexRule] | None = None) -> None:
        self._rules = list(rules) if rules is not None else list(DEFAULT_MARKDOWN_RULES)

    def clean_documents(
        self,
        documents: Sequence[Document],
        *,
        rules: Iterable[RegexRule] | None = None,
        options: GovernanceCleanOptions | None = None,
        **legacy_overrides: Any,
    ) -> tuple[list[Document], GovernanceStats]:
        resolved = _resolved_options(options, legacy_overrides)
        if not documents:
            return [], GovernanceStats(documents=0, changed=0, applied_rules=0, dropped=0, drop_reasons={})

        active_rules = list(rules) if rules is not None else self._rules
        document_count = len(documents)
        common_lines = _global_common_lines(documents, resolved)
        totals = _GovernanceTotals()
        cleaned: list[Document] = []
        for document in documents:
            result = _process_document(
                document,
                options=resolved,
                active_rules=active_rules,
                global_common_lines=common_lines,
                totals=totals,
            )
            if result is not None:
                cleaned.append(result)

        gate_reasons = _gate_reasons(resolved, totals, document_count)
        stats = _build_governance_stats(
            totals,
            document_count=document_count,
            gate_reasons=gate_reasons or None,
        )
        return ([], stats) if gate_reasons else (cleaned, stats)


governance_processor = GovernanceProcessor()
