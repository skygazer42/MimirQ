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
        resolved = options or GovernanceCleanOptions()
        if legacy_overrides:
            # Backward compatible: older callsites pass many keyword args.
            resolved = replace(resolved, **legacy_overrides)

        extract_frontmatter = resolved.extract_frontmatter
        strip_frontmatter = resolved.strip_frontmatter
        detect_language = resolved.detect_language
        language_min_chars = resolved.language_min_chars
        normalize_urls = resolved.normalize_urls
        normalize_urls_strip_tracking = resolved.normalize_urls_strip_tracking
        drop_duplicate_paragraphs = resolved.drop_duplicate_paragraphs
        drop_duplicate_paragraphs_min_occurrences = resolved.drop_duplicate_paragraphs_min_occurrences
        drop_duplicate_paragraphs_min_chars = resolved.drop_duplicate_paragraphs_min_chars
        drop_duplicate_paragraphs_max_chars = resolved.drop_duplicate_paragraphs_max_chars
        trim_references = resolved.trim_references
        extract_keywords = resolved.extract_keywords
        keywords_provider = resolved.keywords_provider
        keywords_top_k = resolved.keywords_top_k
        keywords_max_chars = resolved.keywords_max_chars
        remove_toc_lines = resolved.remove_toc_lines
        remove_noise_lines = resolved.remove_noise_lines
        unwrap_lines = resolved.unwrap_lines
        remove_common_lines = resolved.remove_common_lines
        remove_boilerplate = resolved.remove_boilerplate
        remove_images = resolved.remove_images
        normalize_tables = resolved.normalize_tables
        strip_code_line_numbers = resolved.strip_code_line_numbers
        pii_anonymize = resolved.pii_anonymize
        pii_mode = resolved.pii_mode
        pii_mask = resolved.pii_mask
        pii_max_hits = resolved.pii_max_hits
        secrets_redact = resolved.secrets_redact
        secrets_mode = resolved.secrets_mode
        secrets_mask = resolved.secrets_mask
        secrets_max_hits = resolved.secrets_max_hits
        max_blank_lines = resolved.max_blank_lines
        drop_outline_only = resolved.drop_outline_only
        drop_outline_min_content_chars = resolved.drop_outline_min_content_chars
        drop_outline_max_heading_ratio = resolved.drop_outline_max_heading_ratio
        drop_low_density = resolved.drop_low_density
        drop_low_density_threshold = resolved.drop_low_density_threshold
        drop_high_perplexity = resolved.drop_high_perplexity
        drop_high_perplexity_threshold = resolved.drop_high_perplexity_threshold
        drop_high_perplexity_min_tokens = resolved.drop_high_perplexity_min_tokens
        collapse_blank_lines = resolved.collapse_blank_lines
        unwrap_max_line_length = resolved.unwrap_max_line_length
        noise_min_chars = resolved.noise_min_chars
        noise_ratio_threshold = resolved.noise_ratio_threshold
        common_lines_min_docs = resolved.common_lines_min_docs
        common_lines_min_ratio = resolved.common_lines_min_ratio

        if not documents:
            return [], GovernanceStats(documents=0, changed=0, applied_rules=0, dropped=0, drop_reasons={})

        active_rules = list(rules) if rules is not None else self._rules
        doc_count = len(documents)
        min_docs_eff = max(2, int(common_lines_min_docs or 0))
        if doc_count >= 2:
            min_docs_eff = min(min_docs_eff, doc_count)
        else:
            min_docs_eff = 0
        global_common_lines = (
            build_common_line_signatures(
                [doc.page_content or "" for doc in documents],
                min_docs=min_docs_eff,
                min_ratio=common_lines_min_ratio,
                max_line_length=unwrap_max_line_length,
            )
            if remove_common_lines and min_docs_eff >= 2
            else set()
        )
        cleaned: list[Document] = []
        changed = 0
        applied_total = 0
        dropped = 0
        drop_reasons: dict[str, int] = {}
        pii_hits_total: dict[str, int] = {}
        secrets_hits_total: dict[str, int] = {}
        frontmatter_docs = 0
        frontmatter_stripped_docs = 0
        paragraphs_dropped_total = 0
        references_removed_total = 0
        urls_changed_total = 0
        boilerplate_removed_sections_total = 0
        boilerplate_removed_lines_total = 0
        images_removed_total = 0
        tables_normalized_total = 0
        table_rows_changed_total = 0
        code_blocks_changed_total = 0
        code_lines_stripped_total = 0
        keywords_docs = 0
        keywords_total = 0
        languages: dict[str, int] = {}
        titles_docs = 0
        tags_docs = 0

        for doc in documents:
            original_text = doc.page_content or ""
            working_text = original_text

            frontmatter_present = False
            frontmatter_end_char: int | None = None
            frontmatter_data: dict[str, object] | None = None
            frontmatter_changed = False
            title: str | None = None
            tags: list[str] | None = None

            if extract_frontmatter or strip_frontmatter:
                try:
                    fm = extract_markdown_frontmatter_fn(original_text, strip=bool(strip_frontmatter))
                except Exception:
                    fm = None
                if fm is not None:
                    frontmatter_present = True
                    frontmatter_end_char = int(getattr(fm, "end_char", 0) or 0)
                    frontmatter_changed = bool(getattr(fm, "changed", False))
                    if strip_frontmatter:
                        working_text = getattr(fm, "stripped_text", original_text) or ""

                    data = getattr(fm, "data", None)
                    if isinstance(data, dict) and data:
                        frontmatter_data = dict(data)
                        raw_title = frontmatter_data.get("title")
                        if isinstance(raw_title, str) and raw_title.strip():
                            title = raw_title.strip()[:200]

                        raw_tags = (
                            frontmatter_data.get("tags")
                            or frontmatter_data.get("tag")
                            or frontmatter_data.get("categories")
                            or frontmatter_data.get("category")
                            or frontmatter_data.get("keywords")
                        )
                        if isinstance(raw_tags, list):
                            cleaned_tags: list[str] = []
                            seen_tags: set[str] = set()
                            for item in raw_tags:
                                if item is None:
                                    continue
                                s = str(item).strip()
                                if not s:
                                    continue
                                key = s.casefold()
                                if key in seen_tags:
                                    continue
                                seen_tags.add(key)
                                cleaned_tags.append(s[:64])
                            if cleaned_tags:
                                tags = cleaned_tags[:50]
                        elif isinstance(raw_tags, str) and raw_tags.strip():
                            parts = [p.strip() for p in raw_tags.replace(";", ",").split(",") if p.strip()]
                            if parts:
                                tags = parts[:50]

            if frontmatter_present:
                frontmatter_docs += 1
            if frontmatter_changed:
                frontmatter_stripped_docs += 1

            local_common_lines = (
                build_repeated_line_signatures(
                    working_text or "",
                    min_occurrences=common_lines_min_docs,
                    max_line_length=unwrap_max_line_length,
                )
                if remove_common_lines
                else set()
            )
            common_lines = (global_common_lines | local_common_lines) if remove_common_lines else None
            result = clean_markdown(
                working_text or "",
                rules=active_rules,
                regex_timeout_ms=int(getattr(settings, "GOVERNANCE_REGEX_TIMEOUT_MS", 100) or 100),
                common_lines=common_lines,
                remove_toc_lines=remove_toc_lines,
                remove_noise_lines=remove_noise_lines,
                unwrap_lines=unwrap_lines,
                remove_common_lines=remove_common_lines,
                collapse_blank_lines=collapse_blank_lines,
                max_blank_lines=max_blank_lines,
                unwrap_max_line_length=unwrap_max_line_length,
                noise_min_chars=noise_min_chars,
                noise_ratio_threshold=noise_ratio_threshold,
            )
            applied_total += int(result.applied_rules or 0)
            text = result.markdown
            changed_any = bool(result.changed) or bool(frontmatter_changed)

            table_rows_changed = 0
            table_count = 0
            if normalize_tables:
                tbl = normalize_markdown_tables(text)
                text = tbl.text
                table_count = int(tbl.tables or 0)
                table_rows_changed = int(tbl.rows_changed or 0)
                changed_any = changed_any or bool(tbl.changed)
                tables_normalized_total += int(table_count or 0)
                table_rows_changed_total += int(table_rows_changed or 0)

            code_blocks_changed = 0
            code_lines_stripped = 0
            if strip_code_line_numbers:
                code = strip_fenced_code_line_numbers(text)
                text = code.text
                code_blocks_changed = int(code.blocks_changed or 0)
                code_lines_stripped = int(code.lines_stripped or 0)
                changed_any = changed_any or bool(code.changed)
                code_blocks_changed_total += int(code_blocks_changed or 0)
                code_lines_stripped_total += int(code_lines_stripped or 0)

            boilerplate = None
            if remove_boilerplate:
                boilerplate = remove_markdown_boilerplate(text)
                text = boilerplate.text
                changed_any = changed_any or bool(boilerplate.changed)
                boilerplate_removed_sections_total += int(getattr(boilerplate, "removed_sections", 0) or 0)
                boilerplate_removed_lines_total += int(getattr(boilerplate, "removed_lines", 0) or 0)

            images_removed = 0
            if str(remove_images or "none").strip().lower() in {"decorative", "all"}:
                img = strip_images(text, mode=str(remove_images).strip().lower())  # type: ignore[arg-type]
                text = img.text
                images_removed = int(img.removed or 0)
                changed_any = changed_any or bool(img.changed)
                images_removed_total += int(images_removed or 0)

            pii_hits: dict[str, int] = {}
            if pii_anonymize:
                pii = anonymize_pii(
                    text, enabled=True, mode=str(pii_mode or "mask"), mask=str(pii_mask or "[REDACTED]")
                )  # type: ignore[arg-type]
                text = pii.text
                pii_hits = dict(pii.hits or {})
                changed_any = changed_any or bool(pii.changed)
                for k, v in pii_hits.items():
                    pii_hits_total[k] = pii_hits_total.get(k, 0) + int(v)

            secrets_hits: dict[str, int] = {}
            if secrets_redact:
                sec = redact_secrets(
                    text, enabled=True, mode=str(secrets_mode or "mask"), mask=str(secrets_mask or "[SECRET]")
                )  # type: ignore[arg-type]
                text = sec.text
                secrets_hits = dict(sec.hits or {})
                changed_any = changed_any or bool(sec.changed)
                for k, v in secrets_hits.items():
                    secrets_hits_total[k] = secrets_hits_total.get(k, 0) + int(v)

            paragraphs_dropped = 0
            references_removed_lines = 0
            urls_changed = 0

            if drop_duplicate_paragraphs:
                try:
                    para = drop_duplicate_paragraphs_fn(
                        text,
                        min_occurrences=int(drop_duplicate_paragraphs_min_occurrences or 0),
                        min_paragraph_chars=int(drop_duplicate_paragraphs_min_chars or 0),
                        max_paragraph_chars=int(drop_duplicate_paragraphs_max_chars or 0),
                    )
                    text = para.text
                    paragraphs_dropped = int(getattr(para, "paragraphs_dropped", 0) or 0)
                    changed_any = changed_any or bool(getattr(para, "changed", False))
                except Exception as exc:
                    logger.debug(_MARKDOWN_GOVERNANCE_FALLBACK_LOG_MESSAGE, exc)

            if trim_references:
                try:
                    ref = trim_references_section_fn(text)
                    text = ref.text
                    references_removed_lines = int(getattr(ref, "removed_lines", 0) or 0)
                    changed_any = changed_any or bool(getattr(ref, "changed", False))
                except Exception as exc:
                    logger.debug(_MARKDOWN_GOVERNANCE_FALLBACK_LOG_MESSAGE, exc)

            if normalize_urls:
                try:
                    url = normalize_urls_fn(text, strip_tracking=bool(normalize_urls_strip_tracking))
                    text = url.text
                    urls_changed = int(getattr(url, "urls_changed", 0) or 0)
                    changed_any = changed_any or bool(getattr(url, "changed", False))
                except Exception as exc:
                    logger.debug(_MARKDOWN_GOVERNANCE_FALLBACK_LOG_MESSAGE, exc)

            paragraphs_dropped_total += int(paragraphs_dropped or 0)
            references_removed_total += int(references_removed_lines or 0)
            urls_changed_total += int(urls_changed or 0)

            drop_reason: str | None = None
            if drop_outline_only:
                decision = drop_if_outline_only(
                    text,
                    min_content_chars=int(drop_outline_min_content_chars or 0),
                    max_heading_ratio=float(drop_outline_max_heading_ratio or 0.0),
                )
                if decision.dropped:
                    drop_reason = decision.reason or "outline_only"

            if drop_reason is None and drop_low_density:
                decision = drop_if_low_density(text, threshold=float(drop_low_density_threshold or 0.0))
                if decision.dropped:
                    drop_reason = decision.reason or "low_density"

            if drop_reason is None and drop_high_perplexity:
                decision = drop_if_high_perplexity_proxy(
                    text,
                    threshold=float(drop_high_perplexity_threshold or 0.0),
                    min_tokens=int(drop_high_perplexity_min_tokens or 0),
                )
                if decision.dropped:
                    drop_reason = decision.reason or "perplexity_proxy_high"

            if drop_reason is not None:
                dropped += 1
                key = str(drop_reason or "dropped")
                drop_reasons[key] = drop_reasons.get(key, 0) + 1
                # Skip this document to avoid producing empty/noisy chunks.
                continue

            if title is None:
                try:
                    title = extract_markdown_title_fn(text)
                except Exception:
                    title = None

            lang_val: str | None = None
            lang_conf: float | None = None
            if detect_language:
                try:
                    lang = detect_language_fn(text, min_chars=int(language_min_chars or 0))
                    lang_val = str(getattr(lang, "language", "") or "").strip() or None
                    lang_conf = float(getattr(lang, "confidence", 0.0) or 0.0)
                except Exception:
                    lang_val = None
                    lang_conf = None

            keywords: list[str] | None = None
            if extract_keywords:
                try:
                    max_chars = max(0, int(keywords_max_chars or 0))
                    snippet = text[:max_chars] if max_chars > 0 else text
                    kws = extract_keywords_fn(
                        snippet,
                        provider=str(keywords_provider or "auto"),
                        top_k=int(keywords_top_k or 10),
                    )
                    keywords = list(kws) if kws else None
                except Exception:
                    keywords = None

            if title:
                titles_docs += 1
            if tags:
                tags_docs += 1
            if lang_val:
                languages[lang_val] = languages.get(lang_val, 0) + 1
            if keywords:
                keywords_docs += 1
                keywords_total += len(keywords)

            if changed_any:
                changed += 1
            meta = dict(doc.metadata or {})
            meta["governance_version"] = GOVERNANCE_RULESET_VERSION
            meta["governance_applied"] = True
            meta["governance_rules_applied"] = int(result.applied_rules or 0)
            meta["governance_changed"] = bool(changed_any)
            if frontmatter_present:
                meta["frontmatter_present"] = True
                if frontmatter_end_char and int(frontmatter_end_char) > 0:
                    meta["frontmatter_end_char"] = int(frontmatter_end_char)
                if strip_frontmatter:
                    meta["frontmatter_stripped"] = True
                if frontmatter_data:
                    meta["document_frontmatter"] = frontmatter_data
            if title:
                meta["document_title"] = str(title)
            if tags:
                meta["document_tags"] = tags
            if lang_val:
                meta["document_language"] = lang_val
                meta["document_language_confidence"] = round(float(lang_conf or 0.0), 3)
            if keywords:
                meta["document_keywords"] = keywords
                meta["document_keywords_provider"] = str(keywords_provider or "auto")
            if paragraphs_dropped:
                meta["governance_paragraphs_dropped"] = int(paragraphs_dropped)
            if references_removed_lines:
                meta["governance_references_removed_lines"] = int(references_removed_lines)
            if urls_changed:
                meta["governance_urls_changed"] = int(urls_changed)
            if boilerplate is not None:
                meta["governance_boilerplate_removed_sections"] = int(boilerplate.removed_sections or 0)
                meta["governance_boilerplate_removed_lines"] = int(boilerplate.removed_lines or 0)
            if images_removed:
                meta["governance_images_removed"] = int(images_removed)
            if pii_hits:
                meta["governance_pii_hits"] = pii_hits
            if secrets_hits:
                meta["governance_secrets_hits"] = secrets_hits
            if table_count:
                meta["governance_tables_normalized"] = int(table_count)
                meta["governance_table_rows_changed"] = int(table_rows_changed)
            if code_lines_stripped:
                meta["governance_code_blocks_changed"] = int(code_blocks_changed)
                meta["governance_code_lines_stripped"] = int(code_lines_stripped)

            # Always attach lightweight quality metrics for observability/tuning.
            try:
                density_metrics = drop_if_low_density(text, threshold=-1.0).metrics or {}
                outline_metrics = drop_if_outline_only(text, min_content_chars=0, max_heading_ratio=2.0).metrics or {}
                perplexity_metrics = drop_if_high_perplexity_proxy(text, threshold=2.0, min_tokens=0).metrics or {}
                meta["governance_quality"] = {
                    "density": float(density_metrics.get("density") or 0.0),
                    "chars_non_space": int(density_metrics.get("chars_non_space") or 0),
                    "chars_alnum_cjk": int(density_metrics.get("chars_alnum_cjk") or 0),
                    "heading_ratio": float(outline_metrics.get("heading_ratio") or 0.0),
                    "lines_total": int(outline_metrics.get("lines_total") or 0),
                    "lines_outline": int(outline_metrics.get("lines_outline") or 0),
                    "content_chars": int(outline_metrics.get("content_chars") or 0),
                    "perplexity_proxy": float(perplexity_metrics.get("perplexity_proxy") or 0.0),
                    "token_count": int(perplexity_metrics.get("token_count") or 0),
                }
            except Exception as exc:
                # Best-effort only; never fail ingestion due to metrics.
                logger.debug(_MARKDOWN_GOVERNANCE_FALLBACK_LOG_MESSAGE, exc)
            cleaned.append(Document(page_content=text, metadata=meta, id=getattr(doc, "id", None)))

        # Compliance gates (PII/Secrets): if enabled (>=0), quarantine/drop the entire
        # document when total hits exceed the threshold.
        #
        # This is intentionally applied at the aggregate level (across all parsed pages/items)
        # to avoid partially indexing a sensitive document. The ingestion pipeline can route
        # dropped docs to quarantine via governance_quarantine_on_drop.
        pii_gate = int(pii_max_hits) if isinstance(pii_max_hits, (int, float)) else -1
        secrets_gate = int(secrets_max_hits) if isinstance(secrets_max_hits, (int, float)) else -1

        pii_total_hits = sum(int(v or 0) for v in (pii_hits_total or {}).values())
        secrets_total_hits = sum(int(v or 0) for v in (secrets_hits_total or {}).values())

        gate_reasons: dict[str, int] = {}
        if pii_gate >= 0 and pii_total_hits > pii_gate:
            gate_reasons["pii_exceeded"] = int(doc_count)
        if secrets_gate >= 0 and secrets_total_hits > secrets_gate:
            gate_reasons["secrets_exceeded"] = int(doc_count)

        if gate_reasons:
            # Replace dropped doc-level output entirely.
            merged_reasons = dict(drop_reasons or {})
            merged_reasons.update(gate_reasons)
            return [], GovernanceStats(
                documents=len(documents),
                changed=0,
                applied_rules=applied_total,
                dropped=int(doc_count),
                drop_reasons=merged_reasons,
                pii_hits=pii_hits_total,
                secrets_hits=secrets_hits_total,
                frontmatter_docs=int(frontmatter_docs),
                frontmatter_stripped_docs=int(frontmatter_stripped_docs),
                paragraphs_dropped=int(paragraphs_dropped_total),
                references_removed_lines=int(references_removed_total),
                urls_changed=int(urls_changed_total),
                boilerplate_removed_sections=int(boilerplate_removed_sections_total),
                boilerplate_removed_lines=int(boilerplate_removed_lines_total),
                images_removed=int(images_removed_total),
                tables_normalized=int(tables_normalized_total),
                table_rows_changed=int(table_rows_changed_total),
                code_blocks_changed=int(code_blocks_changed_total),
                code_lines_stripped=int(code_lines_stripped_total),
                keywords_docs=int(keywords_docs),
                keywords_total=int(keywords_total),
                languages=languages,
                titles_docs=int(titles_docs),
                tags_docs=int(tags_docs),
            )

        return cleaned, GovernanceStats(
            documents=len(documents),
            changed=changed,
            applied_rules=applied_total,
            dropped=dropped,
            drop_reasons=drop_reasons,
            pii_hits=pii_hits_total,
            secrets_hits=secrets_hits_total,
            frontmatter_docs=int(frontmatter_docs),
            frontmatter_stripped_docs=int(frontmatter_stripped_docs),
            paragraphs_dropped=int(paragraphs_dropped_total),
            references_removed_lines=int(references_removed_total),
            urls_changed=int(urls_changed_total),
            boilerplate_removed_sections=int(boilerplate_removed_sections_total),
            boilerplate_removed_lines=int(boilerplate_removed_lines_total),
            images_removed=int(images_removed_total),
            tables_normalized=int(tables_normalized_total),
            table_rows_changed=int(table_rows_changed_total),
            code_blocks_changed=int(code_blocks_changed_total),
            code_lines_stripped=int(code_lines_stripped_total),
            keywords_docs=int(keywords_docs),
            keywords_total=int(keywords_total),
            languages=languages,
            titles_docs=int(titles_docs),
            tags_docs=int(tags_docs),
        )


governance_processor = GovernanceProcessor()
