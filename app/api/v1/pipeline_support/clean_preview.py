"""Governance clean-preview and LLM clean-preview helpers for the pipeline API.

Extracted verbatim from ``app/api/v1/pipeline.py``. Submodules must not import
``app.api.v1.pipeline`` (circular import).
"""
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher, unified_diff
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.pipeline import (
    CleanPreviewRequest,
    CleanPreviewResponse,
    GovernanceAnalyzeRequest,
    GovernanceIssue,
    LLMCleanPreviewRequest,
)
from app.core.regex_safety import RegexRulesValidationError, validate_regex_rules
from app.rag.core.errors import ConfigError
from app.rag.core.logging import get_logger
from app.rag.llm.factory import create_llm_client
from app.rag.llm.models import LLMMessage, LLMRole
from app.rag.preprocessing.boilerplate import remove_markdown_boilerplate
from app.rag.preprocessing.cleaning import RegexRule
from app.rag.preprocessing.code_blocks import strip_fenced_code_line_numbers
from app.rag.preprocessing.diagnostics import analyze_governance
from app.rag.preprocessing.frontmatter import extract_markdown_frontmatter, extract_markdown_title
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

REDACTED_MASK = "[REDACTED]"
# Redaction placeholder, not a credential.
SECRET_MASK = "[SECRET]"  # noqa: S105
_PIPELINE_FALLBACK_LOG_MESSAGE = "Ignoring non-critical pipeline fallback failure: %s"
_FRONTMATTER_TAG_KEYS = ("tags", "tag", "categories", "category", "keywords")


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
