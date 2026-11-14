"""Governance and LLM cleaning previews, independent of the pipeline router."""

from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher, unified_diff
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.pipelines import (
    CleanPreviewRequest,
    CleanPreviewResponse,
    GovernanceAnalyzeRequest,
    GovernanceIssue,
    LLMCleanPreviewRequest,
)
from app.core.config import settings
from app.core.regex_runtime import RegexSubstitutionTimeoutError
from app.core.regex_safety import RegexRulesValidationError, validate_regex_rules
from app.rag.core.errors import ConfigError
from app.rag.core.logging import get_logger
from app.rag.llm.factory import create_llm_client
from app.rag.llm.models import LLMMessage, LLMRole
from app.rag.preprocessing.boilerplate import remove_markdown_boilerplate
from app.rag.preprocessing.cleaning import RegexRule, build_repeated_line_signatures, clean_markdown
from app.rag.preprocessing.code_blocks import strip_fenced_code_line_numbers
from app.rag.preprocessing.diagnostics import GovernanceIssue as GovernanceAnalysisIssue
from app.rag.preprocessing.diagnostics import analyze_governance
from app.rag.preprocessing.frontmatter import (
    extract_markdown_frontmatter,
    extract_markdown_title,
    normalize_frontmatter_tags,
)
from app.rag.preprocessing.html_xpath import extract_text_from_html
from app.rag.preprocessing.images import strip_images
from app.rag.preprocessing.keyword import extract_keywords as extract_keywords_preview
from app.rag.preprocessing.language import detect_language
from app.rag.preprocessing.paragraph_dedup import drop_duplicate_paragraphs
from app.rag.preprocessing.pii_anonymizer import anonymize_pii
from app.rag.preprocessing.quality_filters import drop_if_low_density, drop_if_outline_only
from app.rag.preprocessing.references import trim_references_section
from app.rag.preprocessing.rule_packs import GOVERNANCE_RULE_PACKS
from app.rag.preprocessing.rules import DEFAULT_MARKDOWN_RULES
from app.rag.preprocessing.secrets import redact_secrets
from app.rag.preprocessing.tables import normalize_markdown_tables
from app.rag.preprocessing.urls import normalize_urls
from app.services.prompt_resolver import resolve_prompt_template

logger = get_logger(__name__)

_PIPELINE_FALLBACK_LOG_MESSAGE = "Ignoring non-critical pipeline fallback failure: %s"
_FRONTMATTER_TAG_KEYS = ("tags", "tag", "categories", "category", "keywords")


def _governance_analysis_options(body: CleanPreviewRequest | GovernanceAnalyzeRequest) -> dict[str, object]:
    return {
        "remove_control_chars": body.remove_control_chars,
        "unwrap_lines": body.unwrap_lines,
        "remove_common_lines": body.remove_common_lines,
        "remove_boilerplate": body.remove_boilerplate,
        "normalize_tables": body.normalize_tables,
        "normalize_urls": body.normalize_urls,
        "normalize_urls_strip_tracking": body.normalize_urls_strip_tracking,
        "remove_images": body.remove_images,
        "drop_outline_only": body.drop_outline_only,
        "drop_outline_min_content_chars": body.drop_outline_min_content_chars,
        "drop_outline_max_heading_ratio": body.drop_outline_max_heading_ratio,
        "drop_low_density": body.drop_low_density,
        "drop_low_density_threshold": body.drop_low_density_threshold,
    }


def _extract_governance_input_text(body: CleanPreviewRequest | GovernanceAnalyzeRequest) -> str:
    raw_input = body.markdown
    if body.input_format != "html":
        return raw_input

    html = raw_input
    if body.remove_images != "none":
        html = strip_images(html, mode=body.remove_images).text
    extracted = extract_text_from_html(html, xpath=body.html_xpath)
    if body.html_xpath and extracted.xpath_error and extracted.xpath_error.startswith("xpath_failed:"):
        raise HTTPException(status_code=400, detail=f"Invalid XPath: {extracted.xpath_error}")
    return extracted.text


def _governance_issue_models(raw_issues: list[GovernanceAnalysisIssue]) -> list[GovernanceIssue]:
    return [
        GovernanceIssue(
            code=issue.code,
            severity=issue.severity,
            message=issue.message,
            count=issue.count,
            samples=issue.samples if issue.samples is not None else [],
            suggested_pipeline_patch=(
                issue.suggested_pipeline_patch if issue.suggested_pipeline_patch is not None else {}
            ),
        )
        for issue in raw_issues
    ]


def _analyze_governance_preview(
    baseline_text: str,
    after_text: str,
    body: CleanPreviewRequest | GovernanceAnalyzeRequest,
    analysis_opts: dict[str, object],
) -> tuple[list[GovernanceIssue], dict[str, object]]:
    issues, patch = analyze_governance(
        baseline_text,
        after_text,
        input_format=body.input_format,
        options=analysis_opts,
    )
    return _governance_issue_models(issues), patch


def _extract_clean_preview_frontmatter(
    input_text: str,
    body: CleanPreviewRequest,
) -> tuple[str, dict[str, Any] | None, str | None, list[str] | None]:
    if not (body.extract_frontmatter or body.strip_frontmatter):
        return input_text, None, None, None

    try:
        fm = extract_markdown_frontmatter(input_text, strip=body.strip_frontmatter)
    except Exception:
        fm = None
    if fm is None:
        return input_text, None, None, None

    frontmatter = fm.data if fm.data else None
    title = None
    tags = None
    if frontmatter:
        raw_title = frontmatter.get("title")
        if isinstance(raw_title, str) and raw_title.strip():
            title = raw_title.strip()[:200]
        raw_tags = next((frontmatter.get(key) for key in _FRONTMATTER_TAG_KEYS if frontmatter.get(key)), None)
        tags = normalize_frontmatter_tags(raw_tags)

    if body.strip_frontmatter:
        input_text = fm.stripped_text
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


def _selected_rule_pack_keys(raw_packs: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    keys: list[str] = []
    for raw in raw_packs:
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

    for key in _selected_rule_pack_keys(body.rule_packs):
        pack = GOVERNANCE_RULE_PACKS.get(key)
        if pack:
            _append_clean_preview_rules(rules, rule_meta, pack, source="pack", pack=key)

    try:
        custom_rules_norm = validate_regex_rules(body.rules)
    except RegexRulesValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.to_detail()) from exc

    custom_rules = [RegexRule(pattern=r["pattern"], repl=r["repl"], flags=r["flags"]) for r in custom_rules_norm]
    _append_clean_preview_rules(rules, rule_meta, custom_rules, source="custom", pack=None)
    return rules, rule_meta


def _clean_preview_rule_stats(
    rules: list[RegexRule],
    rule_meta: list[dict[str, object]],
    rule_hits: list[int],
) -> list[dict[str, object]]:
    rule_stats: list[dict[str, object]] = []
    for i, rule in enumerate(rules):
        meta = rule_meta[i]
        rule_stats.append(
            {
                "index": i,
                "pattern": rule.pattern,
                "repl": rule.repl if isinstance(rule.repl, str) else None,
                "flags": rule.flags,
                "hits": rule_hits[i],
                "source": meta["source"],
                "pack": meta["pack"],
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
    if body.remove_images != "none":
        text = strip_images(text, mode=body.remove_images).text
    return text


def _apply_preview_sensitive_redaction(
    text: str,
    body: CleanPreviewRequest,
) -> tuple[str, dict[str, int] | None, dict[str, int] | None]:
    pii_hits: dict[str, int] | None = None
    secrets_hits: dict[str, int] | None = None
    if body.pii_anonymize:
        pii = anonymize_pii(text, enabled=True, mode=body.pii_mode, mask=body.pii_mask)
        text = pii.text
        pii_hits = pii.hits
    if body.secrets_redact:
        sec = redact_secrets(text, enabled=True, mode=body.secrets_mode, mask=body.secrets_mask)
        text = sec.text
        secrets_hits = sec.hits
    return text, pii_hits, secrets_hits


def _try_drop_duplicate_paragraphs(text: str, body: CleanPreviewRequest) -> tuple[str, int]:
    if not body.drop_duplicate_paragraphs:
        return text, 0
    try:
        para = drop_duplicate_paragraphs(
            text,
            min_occurrences=body.drop_duplicate_paragraphs_min_occurrences,
            min_paragraph_chars=body.drop_duplicate_paragraphs_min_chars,
            max_paragraph_chars=body.drop_duplicate_paragraphs_max_chars,
        )
        return para.text, para.paragraphs_dropped
    except Exception as exc:
        logger.debug(_PIPELINE_FALLBACK_LOG_MESSAGE, exc, exc_info=True)
        return text, 0


def _try_trim_references(text: str, body: CleanPreviewRequest) -> tuple[str, int]:
    if not body.trim_references:
        return text, 0
    try:
        ref = trim_references_section(text)
        return ref.text, ref.removed_lines
    except Exception as exc:
        logger.debug(_PIPELINE_FALLBACK_LOG_MESSAGE, exc, exc_info=True)
        return text, 0


def _try_normalize_urls(text: str, body: CleanPreviewRequest) -> tuple[str, int]:
    if not body.normalize_urls:
        return text, 0
    try:
        url = normalize_urls(text, strip_tracking=body.normalize_urls_strip_tracking)
        return url.text, url.urls_changed
    except Exception as exc:
        logger.debug(_PIPELINE_FALLBACK_LOG_MESSAGE, exc, exc_info=True)
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
            min_content_chars=body.drop_outline_min_content_chars,
            max_heading_ratio=body.drop_outline_max_heading_ratio,
        )
        if decision.dropped:
            return decision.reason or "outline_only"
    if body.drop_low_density:
        decision = drop_if_low_density(text, threshold=body.drop_low_density_threshold)
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
        lang = detect_language(text, min_chars=body.language_min_chars)
        return lang.language, lang.confidence
    except Exception:
        return None, None


def _extract_preview_keywords(text: str, body: CleanPreviewRequest) -> list[str] | None:
    if not body.extract_keywords:
        return None
    try:
        max_chars = body.keywords_max_chars
        snippet = text[:max_chars] if max_chars > 0 else text
        keywords = extract_keywords_preview(
            snippet,
            provider=body.keywords_provider or "auto",
            top_k=body.keywords_top_k,
        )
        return list(keywords) if keywords else None
    except Exception:
        return None


def _line_diff_stats(before: str, after: str) -> tuple[int, int, int]:
    """
    Compute coarse line-level diff stats for governance preview.

    Returns: (added_lines, removed_lines, changed_lines)
    - changed_lines counts "replaced" blocks (approximate: max(len(a), len(b))).
    """
    a = before.splitlines()
    b = after.splitlines()
    sm = SequenceMatcher(a=a, b=b, autojunk=False)
    added = 0
    removed = 0
    changed = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            added += j2 - j1
        elif tag == "delete":
            removed += i2 - i1
        elif tag == "replace":
            # Count replaced region as changed (best-effort).
            changed += max(i2 - i1, j2 - j1)
    return added, removed, changed


def _unified_diff_text(before: str, after: str, *, max_lines: int) -> tuple[str | None, bool]:
    """
    Build a unified diff for UI preview (best-effort).

    Returns: (diff_text_or_none, truncated)
    """
    cap = max(0, max_lines)
    if cap == 0:
        return None, False

    diff_lines = list(
        unified_diff(
            before.splitlines(),
            after.splitlines(),
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
        "Goal: Clean up noise and formatting issues from parsing/copying, but do not change "
        "semantics or fabricate content.\n"
        "Requirements:\n"
        "1) Preserve heading/list/table/code block structure; do not modify code block content.\n"
        "2) Remove obvious headers/footers/page numbers/TOC markers/repeated short lines/control "
        "characters/zero-width characters.\n"
        "3) Normalize whitespace: merge excess blank lines, remove trailing spaces, merge 'soft "
        "line breaks' when necessary.\n"
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

    selection.system_prompt = chosen.content.strip()
    selection.prompt_template_id = str(chosen.id)
    selection.template_key = chosen.template_key
    selection.ab_experiment_key = chosen.ab_experiment_key
    selection.ab_variant = chosen.ab_variant
    chosen.usage_count += 1
    db.commit()
    return selection


def _llm_clean_model_config(body: LLMCleanPreviewRequest) -> dict[str, object]:
    model_config: dict[str, object] = {}
    if body.model:
        model_config["model"] = body.model
    if body.temperature is not None:
        model_config["temperature"] = body.temperature
    return model_config


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
                    role=LLMRole.USER,
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


def build_clean_preview(body: CleanPreviewRequest) -> CleanPreviewResponse:
    input_text = _extract_governance_input_text(body)
    input_text, frontmatter, title, tags = _extract_clean_preview_frontmatter(input_text, body)
    baseline_text = input_text

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
            regex_timeout_ms=int(settings.GOVERNANCE_REGEX_TIMEOUT_MS),
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

    rule_stats = _clean_preview_rule_stats(rules, rule_meta, result.rule_hits)

    text = _apply_preview_format_transforms(result.markdown, body)
    text, pii_hits, secrets_hits = _apply_preview_sensitive_redaction(text, body)
    text, paragraphs_dropped, references_removed_lines, urls_changed = _apply_preview_cleanup_stats(text, body)
    drop_reason = _preview_drop_reason(text, body)
    language = None
    language_confidence = None
    keywords = None
    if drop_reason is not None:
        text = ""
    else:
        title = _extract_preview_title(text, title)
        language, language_confidence = _detect_preview_language(text, body)
        keywords = _extract_preview_keywords(text, body)

    diff_unified, diff_truncated = None, False
    if body.include_diff:
        diff_unified, diff_truncated = _unified_diff_text(baseline_text, text, max_lines=body.diff_max_lines)
    added, removed, changed_lines = _line_diff_stats(baseline_text, text)
    issues, suggested_patch = _analyze_governance_preview(baseline_text, text, body, analysis_opts)
    dropped = drop_reason is not None
    return CleanPreviewResponse(
        markdown=text,
        applied_rules=result.applied_rules,
        changed=dropped or text != baseline_text,
        rule_stats=rule_stats,
        dropped=dropped,
        drop_reason=drop_reason,
        pii_hits=pii_hits,
        secrets_hits=secrets_hits,
        frontmatter=frontmatter,
        title=title,
        tags=tags,
        language=language,
        language_confidence=language_confidence,
        keywords=keywords,
        urls_changed=urls_changed,
        paragraphs_dropped=paragraphs_dropped,
        references_removed_lines=references_removed_lines,
        input_chars=len(baseline_text),
        output_chars=len(text),
        input_lines=len(baseline_text.splitlines()),
        output_lines=len(text.splitlines()),
        added_lines=added,
        removed_lines=removed,
        changed_lines=changed_lines,
        diff_unified=diff_unified,
        diff_truncated=diff_truncated,
        issues=issues,
        suggested_pipeline_patch=suggested_patch,
    )
