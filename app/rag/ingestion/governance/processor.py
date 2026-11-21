"""
Markdown governance processor shared by parsing and indexing pipelines.
"""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.rag.ingestion.governance.cleaning import (
    RegexRule,
    build_common_line_signatures,
    build_repeated_line_signatures,
    clean_markdown,
)
from app.rag.ingestion.governance.contracts import (
    GOVERNANCE_RULESET_VERSION,
    GovernanceCleanOptions,
    GovernanceStats,
)
from app.rag.ingestion.governance.deduplication.paragraph_dedup import (
    drop_duplicate_paragraphs as drop_duplicate_paragraphs_fn,
)
from app.rag.ingestion.governance.markup.boilerplate import BoilerplateRemovalResult, remove_markdown_boilerplate
from app.rag.ingestion.governance.markup.code_blocks import strip_fenced_code_line_numbers
from app.rag.ingestion.governance.markup.frontmatter import (
    FrontmatterExtractResult,
)
from app.rag.ingestion.governance.markup.frontmatter import (
    extract_markdown_frontmatter as extract_markdown_frontmatter_fn,
)
from app.rag.ingestion.governance.markup.frontmatter import extract_markdown_title as extract_markdown_title_fn
from app.rag.ingestion.governance.markup.frontmatter import normalize_frontmatter_tags as normalize_frontmatter_tags_fn
from app.rag.ingestion.governance.markup.images import strip_images
from app.rag.ingestion.governance.markup.references import trim_references_section as trim_references_section_fn
from app.rag.ingestion.governance.markup.tables import normalize_markdown_tables
from app.rag.ingestion.governance.markup.urls import normalize_urls as normalize_urls_fn
from app.rag.ingestion.governance.quality_filters import (
    drop_if_high_perplexity_proxy,
    drop_if_low_density,
    drop_if_outline_only,
    measure_governance_quality,
)
from app.rag.ingestion.governance.redaction.pii_anonymizer import anonymize_pii
from app.rag.ingestion.governance.redaction.secrets import redact_secrets
from app.rag.ingestion.governance.rules import DEFAULT_MARKDOWN_RULES
from app.rag.ingestion.governance.tagging.keyword import KeywordProviderUnavailable
from app.rag.ingestion.governance.tagging.keyword import extract_keywords as extract_keywords_fn
from app.rag.ingestion.governance.tagging.language import LanguageDetectResult
from app.rag.ingestion.governance.tagging.language import detect_language as detect_language_fn

logger = logging.getLogger(__name__)


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
    regex_timeout_rules: list[dict[str, Any]] = field(default_factory=list)
    frontmatter: FrontmatterExtractResult | None = None
    title: str | None = None
    tags: list[str] | None = None
    table_count: int = 0
    table_rows_changed: int = 0
    code_blocks_changed: int = 0
    code_lines_stripped: int = 0
    boilerplate: BoilerplateRemovalResult | None = None
    images_removed: int = 0
    pii_hits: dict[str, int] = field(default_factory=dict)
    secrets_hits: dict[str, int] = field(default_factory=dict)
    paragraphs_dropped: int = 0
    references_removed_lines: int = 0
    urls_changed: int = 0
    language_detection: LanguageDetectResult | None = None
    keywords: list[str] = field(default_factory=list)


def _global_common_lines(
    documents: Sequence[Document],
    options: GovernanceCleanOptions,
) -> set[str]:
    if not options.remove_common_lines or len(documents) < 2:
        return set()
    return build_common_line_signatures(
        [doc.page_content for doc in documents],
        min_docs=min(max(2, options.common_lines_min_docs), len(documents)),
        min_ratio=options.common_lines_min_ratio,
        max_line_length=options.unwrap_max_line_length,
    )


def _extract_frontmatter(
    state: _DocumentState,
    options: GovernanceCleanOptions,
    totals: _GovernanceTotals,
) -> None:
    if not (options.extract_frontmatter or options.strip_frontmatter):
        return
    frontmatter = extract_markdown_frontmatter_fn(state.original_text, strip=options.strip_frontmatter)
    if frontmatter is None:
        return

    state.frontmatter = frontmatter
    if options.strip_frontmatter:
        state.text = frontmatter.stripped_text
    data = frontmatter.data
    if data:
        raw_title = data.get("title")
        if isinstance(raw_title, str) and raw_title.strip():
            state.title = raw_title.strip()[:200]
        raw_tags = (
            data.get("tags")
            or data.get("tag")
            or data.get("categories")
            or data.get("category")
            or data.get("keywords")
        )
        state.tags = normalize_frontmatter_tags_fn(raw_tags)
    totals.frontmatter_docs += 1
    if frontmatter.changed:
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
            state.text,
            min_occurrences=options.common_lines_min_docs,
            max_line_length=options.unwrap_max_line_length,
        )
        if options.remove_common_lines
        else set()
    )
    common_lines = (global_common_lines | local_common_lines) if options.remove_common_lines else None
    result = clean_markdown(
        state.text,
        rules=active_rules,
        regex_timeout_ms=settings.GOVERNANCE_REGEX_TIMEOUT_MS,
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
    state.applied_rules = result.applied_rules
    state.regex_timeout_rules = result.stats["regex_timeout_rules"]
    if state.regex_timeout_rules:
        logger.warning("Governance skipped timed-out regex rules: count=%s", len(state.regex_timeout_rules))
    state.changed = result.changed or (state.frontmatter is not None and state.frontmatter.changed)
    totals.applied_rules += state.applied_rules


def _apply_structural_transforms(
    state: _DocumentState,
    options: GovernanceCleanOptions,
    totals: _GovernanceTotals,
) -> None:
    if options.normalize_tables:
        table_result = normalize_markdown_tables(state.text)
        state.text = table_result.text
        state.table_count = table_result.tables
        state.table_rows_changed = table_result.rows_changed
        state.changed = state.changed or table_result.changed
        totals.tables_normalized += state.table_count
        totals.table_rows_changed += state.table_rows_changed
    if options.strip_code_line_numbers:
        code_result = strip_fenced_code_line_numbers(state.text)
        state.text = code_result.text
        state.code_blocks_changed = code_result.blocks_changed
        state.code_lines_stripped = code_result.lines_stripped
        state.changed = state.changed or code_result.changed
        totals.code_blocks_changed += state.code_blocks_changed
        totals.code_lines_stripped += state.code_lines_stripped
    if options.remove_boilerplate:
        state.boilerplate = remove_markdown_boilerplate(state.text)
        state.text = state.boilerplate.text
        state.changed = state.changed or state.boilerplate.changed
        totals.boilerplate_removed_sections += state.boilerplate.removed_sections
        totals.boilerplate_removed_lines += state.boilerplate.removed_lines
    image_mode = options.remove_images
    if image_mode in {"decorative", "all"}:
        image_result = strip_images(state.text, mode=image_mode)
        state.text = image_result.text
        state.images_removed = image_result.removed
        state.changed = state.changed or image_result.changed
        totals.images_removed += state.images_removed


def _merge_hit_counts(target: dict[str, int], additions: dict[str, int]) -> None:
    for key, value in additions.items():
        target[key] = target.get(key, 0) + value


def _apply_sensitive_transforms(
    state: _DocumentState,
    options: GovernanceCleanOptions,
    totals: _GovernanceTotals,
) -> None:
    if options.pii_anonymize:
        pii_result = anonymize_pii(
            state.text,
            enabled=True,
            mode=options.pii_mode,
            mask=options.pii_mask,
        )
        state.text = pii_result.text
        state.pii_hits = dict(pii_result.hits)
        state.changed = state.changed or pii_result.changed
        _merge_hit_counts(totals.pii_hits, state.pii_hits)
    if options.secrets_redact:
        secret_result = redact_secrets(
            state.text,
            enabled=True,
            mode=options.secrets_mode,
            mask=options.secrets_mask,
        )
        state.text = secret_result.text
        state.secrets_hits = dict(secret_result.hits)
        state.changed = state.changed or secret_result.changed
        _merge_hit_counts(totals.secrets_hits, state.secrets_hits)


def _apply_text_cleanup(
    state: _DocumentState,
    options: GovernanceCleanOptions,
    totals: _GovernanceTotals,
) -> None:
    if options.drop_duplicate_paragraphs:
        result = drop_duplicate_paragraphs_fn(
            state.text,
            min_occurrences=options.drop_duplicate_paragraphs_min_occurrences,
            min_paragraph_chars=options.drop_duplicate_paragraphs_min_chars,
            max_paragraph_chars=options.drop_duplicate_paragraphs_max_chars,
        )
        state.text = result.text
        state.paragraphs_dropped = result.paragraphs_dropped
        state.changed = state.changed or result.changed
    if options.trim_references:
        result = trim_references_section_fn(state.text)
        state.text = result.text
        state.references_removed_lines = result.removed_lines
        state.changed = state.changed or result.changed
    if options.normalize_urls:
        result = normalize_urls_fn(state.text, strip_tracking=options.normalize_urls_strip_tracking)
        state.text = result.text
        state.urls_changed = result.urls_changed
        state.changed = state.changed or result.changed
    totals.paragraphs_dropped += state.paragraphs_dropped
    totals.references_removed_lines += state.references_removed_lines
    totals.urls_changed += state.urls_changed


def _quality_drop_reason(state: _DocumentState, options: GovernanceCleanOptions) -> str | None:
    if options.drop_outline_only:
        decision = drop_if_outline_only(
            state.text,
            min_content_chars=options.drop_outline_min_content_chars,
            max_heading_ratio=options.drop_outline_max_heading_ratio,
        )
        if decision.dropped:
            return decision.reason
    if options.drop_low_density:
        decision = drop_if_low_density(state.text, threshold=options.drop_low_density_threshold)
        if decision.dropped:
            return decision.reason
    if options.drop_high_perplexity:
        decision = drop_if_high_perplexity_proxy(
            state.text,
            threshold=options.drop_high_perplexity_threshold,
            min_tokens=options.drop_high_perplexity_min_tokens,
        )
        if decision.dropped:
            return decision.reason
    return None


def _extract_title(state: _DocumentState) -> None:
    if state.title is not None:
        return
    state.title = extract_markdown_title_fn(state.text)


def _extract_language_and_keywords(state: _DocumentState, options: GovernanceCleanOptions) -> None:
    if options.detect_language:
        state.language_detection = detect_language_fn(state.text, min_chars=options.language_min_chars)
    if options.extract_keywords:
        try:
            max_chars = options.keywords_max_chars
            snippet = state.text[:max_chars] if max_chars > 0 else state.text
            keywords = extract_keywords_fn(
                snippet,
                provider=options.keywords_provider,
                top_k=options.keywords_top_k,
            )
            state.keywords = keywords
        except KeywordProviderUnavailable as exc:
            logger.warning("Optional governance keyword provider unavailable: %s", exc)


def _record_enrichment(state: _DocumentState, totals: _GovernanceTotals) -> None:
    if state.title:
        totals.titles_docs += 1
    if state.tags:
        totals.tags_docs += 1
    if state.language_detection is not None:
        language = state.language_detection.language
        totals.languages[language] = totals.languages.get(language, 0) + 1
    if state.keywords:
        totals.keywords_docs += 1
        totals.keywords_total += len(state.keywords)
    if state.changed:
        totals.changed += 1


def _add_frontmatter_metadata(meta: dict[str, Any], state: _DocumentState, options: GovernanceCleanOptions) -> None:
    frontmatter = state.frontmatter
    if frontmatter is None:
        return
    meta["frontmatter_present"] = True
    meta["frontmatter_end_char"] = frontmatter.end_char
    if options.strip_frontmatter:
        meta["frontmatter_stripped"] = True
    if frontmatter.data:
        meta["document_frontmatter"] = dict(frontmatter.data)


def _add_enrichment_metadata(
    meta: dict[str, Any],
    state: _DocumentState,
    options: GovernanceCleanOptions,
) -> None:
    if state.title:
        meta["document_title"] = state.title
    if state.tags:
        meta["document_tags"] = state.tags
    if state.language_detection is not None:
        meta["document_language"] = state.language_detection.language
        meta["document_language_confidence"] = round(state.language_detection.confidence, 3)
    if state.keywords:
        meta["document_keywords"] = state.keywords
        meta["document_keywords_provider"] = options.keywords_provider


def _add_cleanup_metadata(meta: dict[str, Any], state: _DocumentState) -> None:
    if state.regex_timeout_rules:
        meta["governance_regex_timeout_count"] = len(state.regex_timeout_rules)
        meta["governance_regex_timeout_rules"] = state.regex_timeout_rules
    if state.paragraphs_dropped:
        meta["governance_paragraphs_dropped"] = state.paragraphs_dropped
    if state.references_removed_lines:
        meta["governance_references_removed_lines"] = state.references_removed_lines
    if state.urls_changed:
        meta["governance_urls_changed"] = state.urls_changed
    if state.boilerplate is not None:
        meta["governance_boilerplate_removed_sections"] = state.boilerplate.removed_sections
        meta["governance_boilerplate_removed_lines"] = state.boilerplate.removed_lines
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
    meta["governance_quality"] = measure_governance_quality(text)


def _build_clean_document(state: _DocumentState, options: GovernanceCleanOptions) -> Document:
    meta = dict(state.source.metadata)
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
    return Document(page_content=state.text, metadata=meta, id=state.source.id)


def _process_document(
    document: Document,
    *,
    options: GovernanceCleanOptions,
    active_rules: list[RegexRule],
    global_common_lines: set[str],
    totals: _GovernanceTotals,
) -> Document | None:
    original_text = document.page_content
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
    _apply_text_cleanup(state, options, totals)
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
    pii_gate = options.pii_max_hits
    secrets_gate = options.secrets_max_hits
    pii_hits = sum(totals.pii_hits.values())
    secrets_hits = sum(totals.secrets_hits.values())
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
    gate_reasons: dict[str, int],
) -> GovernanceStats:
    counts = asdict(totals)
    counts["drop_reasons"].update(gate_reasons)
    if gate_reasons:
        counts["changed"] = 0
        counts["dropped"] = document_count
    return GovernanceStats(documents=document_count, **counts)


def clean_documents(
    documents: Sequence[Document],
    *,
    rules: Iterable[RegexRule] | None = None,
    options: GovernanceCleanOptions | None = None,
    **overrides: Any,
) -> tuple[list[Document], GovernanceStats]:
    """Apply the configured governance steps, then enforce aggregate privacy gates."""
    resolved = GovernanceCleanOptions() if options is None else options
    if overrides:
        resolved = replace(resolved, **overrides)
    if not documents:
        return [], GovernanceStats(documents=0, changed=0, applied_rules=0, dropped=0, drop_reasons={})

    active_rules = list(DEFAULT_MARKDOWN_RULES) if rules is None else list(rules)
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
    stats = _build_governance_stats(totals, document_count=document_count, gate_reasons=gate_reasons)
    return ([], stats) if gate_reasons else (cleaned, stats)
