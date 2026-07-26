"""Shared constants and metadata exact-anchor helpers for the hybrid retriever.

Split out of ``app.rag.retriever`` (see ``app.rag.retrieval.hybrid``). The
retriever module re-exports the private names below for backwards compatibility;
new code should import from here.
"""

import re
import unicodedata
from typing import Any

from app.rag.core.logging import get_logger
from app.rag.pipeline_plugins.contracts import (
    DISPLAY_METADATA_KEY,
    EVALUABLE_METADATA_KEY,
    INDEXED_METADATA_KEY,
    METADATA_SCHEMA_VIEW_KEYS,
    RECORD_IDENTITY_METADATA_KEY,
    RETRIEVAL_TEXT_METADATA_KEY,
)
from app.rag.retrieval.query_phrase_match import query_phrase_match

logger = get_logger("rag.retriever")


def _log_retriever_fallback(context: str, exc: BaseException) -> None:
    logger.debug("retriever fallback failed in %s: %s", context, exc, exc_info=True)


SPARSE_INDEX_DIR_FALLBACK = "./data/sparse_indexes"
COLBERT_INDEX_DIR_FALLBACK = "./data/colbert_indexes"
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
_METADATA_EXACT_ANCHOR_SKIP_FIELD_PARTS = (
    "id",
    "uuid",
    "hash",
    "path",
    "file",
    "url",
    "pipeline",
    "strategy",
    "plugin",
    "index",
    "keyword",
    "keywords",
)
_METADATA_EXACT_ANCHOR_SKIP_FIELD_PREFIXES = (
    "metadata_exact_match",
    "exact_phrase",
    "rerank",
)
_HEXISH_VALUE_RE = re.compile(r"^[a-f0-9]{12,}$", flags=re.IGNORECASE)
_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
_SPACE_RE = re.compile(r"\s+")
_FIELD_PART_RE = re.compile(r"[^a-z0-9]+")
_COMPACT_ANCHOR_DROP_RE = re.compile(r"[\s\"'“”‘’`´＂＇《》〈〉【】\[\]（）(){}]+")


def _normalize_exact_anchor(value: Any, *, compact: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        text = unicodedata.normalize("NFKC", text)
    except Exception as exc:
        logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
    text = _SPACE_RE.sub(" ", text.casefold()).strip()
    return _COMPACT_ANCHOR_DROP_RE.sub("", text) if compact else text


def _iter_metadata_exact_anchor_values(meta: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(field: str, value: Any) -> None:
        field_s = str(field or "").strip()
        if not field_s:
            return
        values: list[Any]
        if isinstance(value, (list, tuple)):
            values = list(value)
        else:
            values = [value]
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

    for view_key in (_EVALUABLE_METADATA_KEY, _DISPLAY_METADATA_KEY, _INDEXED_METADATA_KEY):
        view = meta.get(view_key)
        if isinstance(view, dict):
            for field, value in view.items():
                add(str(field), value)

    for field, value in meta.items():
        field_s = str(field or "").strip()
        if not field_s or field_s.startswith("_"):
            continue
        add(field_s, value)

    return out


def _looks_like_metadata_exact_anchor(field: str, text: str) -> bool:
    field_norm = str(field or "").strip().lower()
    if any(field_norm.startswith(prefix) for prefix in _METADATA_EXACT_ANCHOR_SKIP_FIELD_PREFIXES):
        return False
    field_parts = {p for p in _FIELD_PART_RE.split(field_norm) if p}
    if field_parts.intersection(_METADATA_EXACT_ANCHOR_SKIP_FIELD_PARTS):
        return False
    if field_norm.endswith(("_id", "_ids", "-id", ".id")):
        return False

    normalized = _normalize_exact_anchor(text)
    if len(normalized) < 4 or len(normalized) > 160:
        return False
    if "://" in normalized or "/" in normalized or "\\" in normalized:
        return False
    if _HEXISH_VALUE_RE.fullmatch(normalized.replace("-", "")):
        return False
    if normalized.isdigit():
        return False

    cjk_count = len(_CJK_CHAR_RE.findall(normalized))
    if cjk_count:
        return cjk_count >= 4
    if "_" in normalized and " " not in normalized:
        return False
    return len(normalized) >= 8


def _metadata_exact_anchor_match(query: str, meta: dict[str, Any]) -> dict[str, Any]:
    query_norm = _normalize_exact_anchor(query, compact=True)
    if not query_norm:
        return {}

    matches: list[dict[str, Any]] = []
    for field, anchor_text in _iter_metadata_exact_anchor_values(meta):
        if not _looks_like_metadata_exact_anchor(field, anchor_text):
            continue
        anchor_norm = _normalize_exact_anchor(anchor_text, compact=True)
        if not anchor_norm or anchor_norm not in query_norm:
            continue
        score = min(1.0, max(0.45, float(len(anchor_norm)) / float(max(1, len(query_norm)))))
        matches.append(
            {
                "field": str(field),
                "value": str(anchor_text),
                "score": round(float(score), 6),
                "norm": anchor_norm,
            }
        )

    if not matches:
        return {}

    # Same metadata field can expose nested aliases, e.g. "注意事项" and
    # "办理注意事项". Keep the longest per field to avoid double-counting a
    # single business intent, while still allowing title + intent to combine.
    filtered: list[dict[str, Any]] = []
    seen_norms: set[str] = set()
    for item in sorted(matches, key=lambda x: (-len(str(x.get("norm") or "")), -float(x.get("score") or 0.0))):
        field = str(item.get("field") or "")
        norm = str(item.get("norm") or "")
        if any(str(kept.get("field") or "") == field and norm in str(kept.get("norm") or "") for kept in filtered):
            continue
        if norm in seen_norms:
            continue
        seen_norms.add(norm)
        filtered.append(item)

    ranked = sorted(
        filtered,
        key=lambda x: (-float(x.get("score") or 0.0), -len(str(x.get("norm") or "")), str(x.get("field") or "")),
    )
    primary = ranked[0]
    aggregate = float(primary.get("score") or 0.0)
    aggregate += 0.5 * sum(float(item.get("score") or 0.0) for item in ranked[1:])
    aggregate = min(1.0, aggregate)

    fields = list(dict.fromkeys(str(item.get("field") or "") for item in ranked if str(item.get("field") or "")))
    values = [str(item.get("value") or "") for item in ranked if str(item.get("value") or "")]
    return {
        "field": str(primary.get("field") or ""),
        "value": str(primary.get("value") or ""),
        "score": round(float(aggregate), 6),
        "primary_score": round(float(primary.get("score") or 0.0), 6),
        "fields": fields[:8],
        "values": values[:8],
    }


def _query_looks_like_cjk_metadata_anchor(query: str) -> bool:
    normalized = _normalize_exact_anchor(query)
    if not normalized:
        return False
    # Chinese FAQ/title questions often need exact metadata recall. Keep this
    # CJK-scoped so generic English hybrid queries do not always pay the DB cost.
    if len(_CJK_CHAR_RE.findall(normalized)) < 4:
        return False
    return _looks_like_metadata_exact_anchor("question", normalized)


def _results_contain_metadata_exact_anchor(query: str, results: list[dict[str, Any]], *, limit: int | None = None) -> bool:
    candidates = list(results or [])
    if limit is not None and int(limit or 0) > 0:
        candidates = sorted(
            candidates,
            key=lambda item: (
                -_float_or_default(item.get("score") if isinstance(item, dict) else None, 0.0),
                str(item.get("chunk_id") if isinstance(item, dict) else ""),
            ),
        )[: int(limit)]
    for result in candidates:
        if not isinstance(result, dict):
            continue
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
    result["metadata_exact_match_field"] = str(metadata_match.get("field") or "")
    result["metadata_exact_match_value"] = str(metadata_match.get("value") or "")
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
        str(indexed_content)
        if isinstance(indexed_content, str) and indexed_content.strip()
        else str(result.get("content") or "")
    )
    query_norm = _normalize_exact_anchor(query)
    content_norm = _normalize_exact_anchor(content)
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
