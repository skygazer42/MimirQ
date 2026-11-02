"""Dify service-anchor query rules shared by scope and metadata retrieval."""

from app.services.dify_integration.common import (
    _CJK_RE,
    _MIN_SPECIFIC_INTENT_CHARS,
    _QUOTED_ANCHOR_RE,
    _SERVICE_ANCHOR_QUERY_TRAILING_CHARS,
    _normalize_match_term,
)
from app.services.dify_integration.policy_helpers import (
    service_anchor_admin_aliases_for_policy_refs as _service_anchor_admin_aliases_for_policy_refs,
)
from app.services.dify_integration.policy_helpers import (
    service_anchor_cutoff_terms_for_policy_refs as _service_anchor_cutoff_terms_for_policy_refs,
)
from app.services.dify_integration.policy_helpers import (
    service_anchor_entity_terms_for_policy_refs as _service_anchor_entity_terms_for_policy_refs,
)
from app.services.dify_integration.policy_helpers import (
    service_anchor_leading_noise_terms_for_policy_refs as _service_anchor_leading_noise_terms_for_policy_refs,
)
from app.services.dify_integration.policy_helpers import (
    service_anchor_noise_terms_for_policy_refs as _service_anchor_noise_terms_for_policy_refs,
)
from app.services.dify_integration.policy_helpers import (
    service_anchor_query_rewrite_terms_for_policy_refs as _service_anchor_query_rewrite_terms_for_policy_refs,
)
from app.services.dify_integration.scoring import (
    _contains_cjk,
    _iter_anchor_word_segments,
    _quoted_anchor_match_text,
    _quoted_query_anchor_terms,
    _rstrip_service_anchor_query_noise,
    _strip_trailing_service_anchor_admin,
)

_METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS = 8


def _strip_service_anchor_query_noise(
    query: str,
    *,
    noise_terms: tuple[str, ...] = (),
    leading_noise_terms: tuple[str, ...] = (),
    cutoff_terms: tuple[str, ...] = (),
    admin_aliases: tuple[str, ...] = (),
) -> str:
    text = str(query or "").strip()
    if not text:
        return ""
    text = _strip_service_anchor_leading_noise(text, leading_noise_terms=leading_noise_terms)
    declared_admin_aliases = _sorted_anchor_query_terms(admin_aliases)
    text = _strip_service_anchor_admin_prefixes(text, declared_admin_aliases)
    cutoff_indexes = [index for marker in _sorted_anchor_query_terms(cutoff_terms) if (index := text.find(marker)) > 0]
    if cutoff_indexes:
        text = text[: min(cutoff_indexes)].strip()
    for phrase in _sorted_anchor_query_terms(noise_terms):
        if not phrase:
            continue
        text = text.replace(phrase, "")
    text = _rstrip_service_anchor_query_noise(text)
    previous = None
    while previous != text:
        previous = text
        text = _strip_trailing_service_anchor_admin(
            text,
            admin_aliases=declared_admin_aliases,
        )
        text = _rstrip_service_anchor_query_noise(text)
    return text


def _sorted_anchor_query_terms(terms: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {str(term or "").strip() for term in terms if str(term or "").strip()},
            key=len,
            reverse=True,
        )
    )


def _strip_service_anchor_leading_noise(
    text: str,
    *,
    leading_noise_terms: tuple[str, ...] = (),
) -> str:
    for phrase in _sorted_anchor_query_terms(leading_noise_terms):
        if text.startswith(phrase):
            return text[len(phrase) :].strip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS)
    return text


def _strip_service_anchor_admin_prefixes(
    text: str,
    admin_aliases: tuple[str, ...],
) -> str:
    for _ in range(2):
        prefix = next((alias for alias in admin_aliases if text.startswith(alias)), None)
        if prefix is None:
            break
        text = text[len(prefix) :].strip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS)
    return text


def _service_anchor_query_noise_variants(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    common_kwargs = {
        "noise_terms": _service_anchor_noise_terms_for_policy_refs(policy_plugin_refs),
        "leading_noise_terms": _service_anchor_leading_noise_terms_for_policy_refs(policy_plugin_refs),
        "cutoff_terms": _service_anchor_cutoff_terms_for_policy_refs(policy_plugin_refs),
    }
    candidates = (
        _strip_service_anchor_query_noise(query, **common_kwargs),
        _strip_service_anchor_query_noise(
            query,
            **common_kwargs,
            admin_aliases=_service_anchor_admin_aliases_for_policy_refs(policy_plugin_refs),
        ),
    )
    variants: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalize_match_term(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        variants.append(candidate)
    return tuple(variants)


def _metadata_anchor_service_name_query_terms(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[str]:
    cleaned_variants = _service_anchor_query_noise_variants(
        query,
        policy_plugin_refs=policy_plugin_refs,
    )
    if not cleaned_variants:
        return []

    terms: list[str] = []
    seen: set[str] = set()
    seen_text: set[str] = set()

    for match in _QUOTED_ANCHOR_RE.finditer(str(query or "")):
        literal = _quoted_anchor_match_text(match)
        _append_literal_metadata_anchor_term(terms, literal, min_chars=4, seen_text=seen_text)
    for quoted_anchor in _quoted_query_anchor_terms(query):
        _append_metadata_anchor_term(terms, seen, quoted_anchor, min_chars=4, seen_text=seen_text)
    for cleaned in cleaned_variants:
        _append_metadata_anchor_term(terms, seen, cleaned, min_chars=4, seen_text=seen_text)
    for rewritten in _service_anchor_query_rewrite_terms_for_policy_refs(query, policy_plugin_refs):
        _append_metadata_anchor_term(terms, seen, rewritten, min_chars=4, seen_text=seen_text)
    _append_metadata_anchor_segment_terms(
        terms,
        seen=seen,
        cleaned_variants=cleaned_variants,
        sizes=(12, 10, 8, 6, 4),
        limit=_METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS,
        seen_text=seen_text,
    )
    return terms[:_METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS]


def _query_has_specific_service_anchor_candidate(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    for term in _metadata_anchor_service_name_query_terms(query, policy_plugin_refs=policy_plugin_refs)[:3]:
        normalized = _normalize_match_term(term)
        if not _CJK_RE.search(normalized):
            continue
        if len(normalized) < _MIN_SPECIFIC_INTENT_CHARS or len(normalized) > 30:
            continue
        entity_terms = tuple(
            _normalize_match_term(term)
            for term in _service_anchor_entity_terms_for_policy_refs(policy_plugin_refs)
            if _normalize_match_term(term)
        )
        if entity_terms and any(marker in normalized for marker in entity_terms):
            return True
    return False


def _append_literal_metadata_anchor_term(
    terms: list[str],
    raw: str,
    *,
    min_chars: int,
    seen_text: set[str],
) -> None:
    term = str(raw or "").strip()
    normalized = _normalize_match_term(term)
    text_key = term.casefold()
    if len(normalized) < min_chars or text_key in seen_text:
        return
    seen_text.add(text_key)
    terms.append(term)


def _append_metadata_anchor_term(
    terms: list[str],
    seen: set[str],
    raw: str,
    *,
    min_chars: int,
    cjk_min_chars: int | None = None,
    seen_text: set[str] | None = None,
) -> None:
    term = str(raw or "").strip()
    normalized = _normalize_match_term(term)
    text_key = term.casefold()
    effective_min_chars = cjk_min_chars if cjk_min_chars is not None and _contains_cjk(normalized) else min_chars
    if len(normalized) < effective_min_chars or normalized in seen:
        return
    if seen_text is not None and text_key in seen_text:
        return
    seen.add(normalized)
    if seen_text is not None:
        seen_text.add(text_key)
    terms.append(term)


def _append_metadata_anchor_segment_terms(
    terms: list[str],
    *,
    seen: set[str],
    cleaned_variants: tuple[str, ...],
    sizes: tuple[int, ...],
    limit: int,
    min_chars: int = 4,
    cjk_min_chars: int | None = None,
    seen_text: set[str] | None = None,
) -> None:
    for cleaned in cleaned_variants:
        for segment in _iter_anchor_word_segments(cleaned):
            _append_metadata_anchor_term(
                terms,
                seen,
                segment,
                min_chars=min_chars,
                cjk_min_chars=cjk_min_chars,
                seen_text=seen_text,
            )
            if not _contains_cjk(segment):
                continue
            for size in sizes:
                if len(segment) < size:
                    continue
                for start in range(0, len(segment) - size + 1):
                    _append_metadata_anchor_term(
                        terms,
                        seen,
                        segment[start : start + size],
                        min_chars=min_chars,
                        cjk_min_chars=cjk_min_chars,
                        seen_text=seen_text,
                    )
                    if len(terms) >= limit:
                        return


query_has_specific_service_anchor_candidate = _query_has_specific_service_anchor_candidate
