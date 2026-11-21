"""Candidate metadata views, exact-text signals and recall diagnostics."""

import logging
import re
from typing import Any

from app.rag.retrieval.planning.phrases import query_phrase_match
from app.rag.retrieval.ranking.metadata import (
    looks_like_metadata_anchor,
    match_metadata_anchors,
    normalize_exact_anchor,
)
from app.types.indexing import (
    DISPLAY_METADATA_KEY,
    EVALUABLE_METADATA_KEY,
    INDEXED_METADATA_KEY,
    METADATA_SCHEMA_VIEW_KEYS,
    RECORD_IDENTITY_METADATA_KEY,
    RETRIEVAL_TEXT_METADATA_KEY,
)

logger = logging.getLogger("rag.retriever")


def _log_retriever_fallback(context: str, exc: BaseException) -> None:
    logger.debug("retriever fallback failed in %s: %s", context, exc, exc_info=True)


LEXICAL_DB_SEARCH_FAILED_LOG = "Lexical DB search failed: %s"
NON_CRITICAL_RETRIEVER_FALLBACK_LOG = "Ignoring non-critical retriever fallback failure: %s"
_RETRIEVAL_DISPLAY_CONTENT_KEY = "_retrieval_display_content"
_RETRIEVAL_TEXT_KEY = RETRIEVAL_TEXT_METADATA_KEY
_RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY = "_retrieval_expected_embedding_space_hash"
_RETRIEVAL_QUESTIONS_CHANNEL_KEY = "_retrieval_questions_channel_applied"
_PIPELINE_PLUGIN_METADATA_KEYS = ("chunk_python_plugin", "governance_python_plugin", "kg_python_plugin")
_INDEXED_METADATA_KEY = INDEXED_METADATA_KEY
_DISPLAY_METADATA_KEY = DISPLAY_METADATA_KEY
_EVALUABLE_METADATA_KEY = EVALUABLE_METADATA_KEY
_RECORD_IDENTITY_METADATA_KEY = RECORD_IDENTITY_METADATA_KEY
_PLATFORM_METADATA_VIEW_KEYS = METADATA_SCHEMA_VIEW_KEYS
_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


def _append_metadata_anchor_values(
    out: list[tuple[str, str]],
    seen: set[tuple[str, str]],
    *,
    field: str,
    value: Any,
) -> None:
    field_s = (field).strip()
    if not field_s:
        return
    values = list(value) if isinstance(value, (list, tuple)) else [value]
    for item in values:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text:
            continue
        key = (field_s, text)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)


def _iter_metadata_exact_anchor_values(meta: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for view_key in (_EVALUABLE_METADATA_KEY, _DISPLAY_METADATA_KEY, _INDEXED_METADATA_KEY):
        view = meta.get(view_key)
        if isinstance(view, dict):
            for field, value in view.items():
                _append_metadata_anchor_values(out, seen, field=str(field), value=value)

    for field, value in meta.items():
        field_s = field.strip()
        if not field_s or field_s.startswith("_"):
            continue
        _append_metadata_anchor_values(out, seen, field=field_s, value=value)

    return out


def _looks_like_metadata_exact_anchor(field: str, text: str) -> bool:
    return looks_like_metadata_anchor(field, text, normalize=normalize_exact_anchor)


def _metadata_exact_anchor_match(query: str, meta: dict[str, Any]) -> dict[str, Any]:
    query_norm = normalize_exact_anchor(query, compact=True)
    if not query_norm:
        return {}
    return match_metadata_anchors(
        query_norm, _iter_metadata_exact_anchor_values(meta), normalize=normalize_exact_anchor
    )


def _query_looks_like_cjk_metadata_anchor(query: str) -> bool:
    normalized = normalize_exact_anchor(query)
    if not normalized:
        return False
    # Chinese FAQ/title questions often need exact metadata recall. Keep this
    # CJK-scoped so generic English hybrid queries do not always pay the DB cost.
    if len(_CJK_CHAR_RE.findall(normalized)) < 4:
        return False
    return _looks_like_metadata_exact_anchor("question", normalized)


def _results_contain_metadata_exact_anchor(
    query: str, results: list[dict[str, Any]], *, limit: int | None = None
) -> bool:
    candidates = results
    if limit is not None and limit > 0:
        candidates = sorted(
            candidates,
            key=lambda item: (
                -_float_or_default(item.get("score"), 0.0),
                str(item.get("chunk_id")),
            ),
        )[:limit]
    for result in candidates:
        meta = result.get("metadata")
        if not isinstance(meta, dict):
            continue
        if _metadata_exact_anchor_match(query, meta):
            return True
    return False


def _float_or_default(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _apply_metadata_exact_anchor_to_result(
    *,
    query: str,
    result: dict[str, Any],
    phrase_boost_weight: float,
    promote_score: bool = False,
) -> bool:
    meta_for_anchor = dict(result.get("metadata") or {})
    metadata_match = _metadata_exact_anchor_match(query, meta_for_anchor)
    if not metadata_match:
        return False

    match_score = float(metadata_match.get("score") or 0.0)
    metadata_boost = match_score * max(0.0, float(phrase_boost_weight or 0.0))
    result["metadata_exact_match_score"] = match_score
    result["metadata_exact_match_primary_score"] = float(metadata_match.get("primary_score") or 0.0)
    result["metadata_exact_match_boost"] = float(metadata_boost)
    result["metadata_exact_match_field"] = metadata_match["field"]
    result["metadata_exact_match_value"] = metadata_match["value"]
    result["metadata_exact_match_fields"] = list(metadata_match.get("fields") or [])
    result["metadata_exact_match_values"] = list(metadata_match.get("values") or [])

    if promote_score:
        current_score = _float_or_default(result.get("score"), 0.0)
        promoted_score = max(current_score, match_score)
        if promoted_score > current_score:
            result["score"] = round(float(promoted_score), 6)
            result["metadata_exact_match_promoted_score"] = round(float(promoted_score), 6)
    return True


def _apply_exact_content_bonus_to_result(
    *,
    query: str,
    result: dict[str, Any],
    phrase_boost_weight: float,
) -> bool:
    """Add a bounded exact-text signal without expanding the candidate set."""
    if result.get("exact_phrase_score") is not None:
        return False

    metadata = result.get("metadata") if isinstance(result, dict) else None
    indexed_content = metadata.get(_RETRIEVAL_TEXT_KEY) if isinstance(metadata, dict) else None
    content = (
        str(indexed_content) if isinstance(indexed_content, str) and indexed_content.strip() else result["content"]
    )
    query_norm = normalize_exact_anchor(query)
    content_norm = normalize_exact_anchor(content)
    phrase = query_phrase_match(query, content)
    phrase_score = float(phrase.get("score", 0.0) or 0.0)
    full_query_match = bool(len(query_norm) >= 2 and query_norm in content_norm)
    exact_score = max(1.0 if full_query_match else 0.0, phrase_score)
    if exact_score <= 0.0:
        return False

    boost = exact_score * max(0.0, float(phrase_boost_weight or 0.0))
    current_score = _float_or_default(result.get("score"), 0.0)
    result["exact_phrase_score"] = round(float(exact_score), 6)
    result["exact_phrase_boost"] = round(float(boost), 6)
    matches = list(phrase.get("matched_phrases") or [])
    if full_query_match and query_norm not in matches:
        matches.insert(0, query_norm)
    if matches:
        result["exact_phrase_matches"] = matches[:4]
    result["score"] = min(1.0, current_score + boost)
    return True
