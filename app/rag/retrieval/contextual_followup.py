"""
Deterministic contextual follow-up query builder.

Goal:
- Use already retrieved document context to derive one bounded second-pass query.
- No LLM calls.
- Keep output auditable and low variance.
"""

import re
from collections.abc import Iterable
from typing import Any

from langchain_core.documents import Document

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_./:-]{2,63}|[\u4e00-\u9fff]{2,16}")

# Small, deterministic stop-word set for keyword-like extraction.
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "onto",
    "your",
    "you",
    "are",
    "was",
    "were",
    "have",
    "has",
    "had",
    "will",
    "would",
    "can",
    "could",
    "should",
    "about",
    "what",
    "when",
    "where",
    "which",
    "why",
    "how",
    "issue",
    "error",
    "errors",
    "debug",
    "help",
    "please",
    "query",
    "docs",
    "doc",
}

_META_FIELDS = (
    ("keywords", 1.8),
    ("tags", 1.6),
    ("title", 1.4),
    ("heading", 1.3),
    ("section", 1.3),
    ("table_id", 1.2),
    ("source_key", 1.2),
    ("source", 1.0),
)


def _sig(value: str) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    return s.casefold() if s.isascii() else s


def _extract_terms(text: str, *, min_chars: int, max_chars: int) -> list[str]:
    out: list[str] = []
    for m in _TOKEN_RE.finditer(str(text or "")):
        tok = str(m.group(0) or "").strip()
        if not tok:
            continue
        if len(tok) < int(min_chars):
            continue
        if int(max_chars) > 0 and len(tok) > int(max_chars):
            continue
        sig = _sig(tok)
        if not sig:
            continue
        if sig in _STOPWORDS:
            continue
        out.append(tok)
    return out


def _iter_meta_values(raw: Any) -> Iterable[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, (list, tuple, set)):
        out: list[str] = []
        for v in raw:
            s = str(v or "").strip()
            if not s:
                continue
            out.append(s)
            if len(out) >= 16:
                break
        return out
    return []


def _dedupe_terms(values: list[str], *, max_items: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        term = str(raw or "").strip()
        if not term:
            continue
        sig = _sig(term)
        if not sig or sig in seen:
            continue
        seen.add(sig)
        out.append(term)
        if len(out) >= max(1, int(max_items or 1)):
            break
    return out


def _unused_followup_result(
    *,
    query: str,
    reason_code: str,
    selected_terms: list[str] | None = None,
    terms_considered: int = 0,
    docs_considered: int = 0,
) -> dict[str, Any]:
    return {
        "query": query,
        "used": False,
        "reason_codes": [reason_code],
        "selected_terms": list(selected_terms or []),
        "terms_considered": int(terms_considered),
        "docs_considered": int(docs_considered),
    }


def _extract_query_terms(base: str, *, min_chars: int, max_chars: int) -> set[str]:
    return {_sig(term) for term in _extract_terms(base, min_chars=min_chars, max_chars=max_chars)}


def _extract_gap_terms(
    *,
    evidence_gap: dict[str, Any] | None,
    query_terms: set[str],
    min_chars: int,
    max_chars: int,
    max_terms: int,
) -> tuple[list[str], list[str]]:
    if not isinstance(evidence_gap, dict):
        return [], []
    gap_reason_codes: list[str] = []
    gap_terms_raw: list[str] = []
    missing_source_keys = [str(v) for v in (evidence_gap.get("missing_source_keys") or []) if str(v).strip()][:20]
    if missing_source_keys:
        for key in missing_source_keys:
            gap_terms_raw.extend(_extract_terms(key, min_chars=min_chars, max_chars=max_chars))
        gap_reason_codes.append("gap_missing_source_keys")
    if int(evidence_gap.get("anchor_missing_any") or 0) > 0:
        gap_reason_codes.append("gap_missing_anchor_fields")
    gap_terms = _dedupe_terms(
        [term for term in gap_terms_raw if _sig(term) not in query_terms],
        max_items=max_terms,
    )
    return gap_terms, gap_reason_codes


def _score_terms_from_docs(
    *,
    docs: list[Document],
    query_terms: set[str],
    min_chars: int,
    max_chars: int,
) -> tuple[dict[str, float], dict[str, str], int]:
    score_by_sig: dict[str, float] = {}
    term_by_sig: dict[str, str] = {}
    considered = 0
    for doc in docs:
        meta = dict(getattr(doc, "metadata", None) or {})
        for field, weight in _META_FIELDS:
            for raw in _iter_meta_values(meta.get(field)):
                for token in _extract_terms(raw, min_chars=min_chars, max_chars=max_chars):
                    sig = _sig(token)
                    if not sig or sig in query_terms:
                        continue
                    considered += 1
                    score_by_sig[sig] = float(score_by_sig.get(sig, 0.0) or 0.0) + float(weight)
                    term_by_sig.setdefault(sig, token)
        content = str(getattr(doc, "page_content", "") or "")
        if not content:
            continue
        for token in _extract_terms(content[:2000], min_chars=min_chars, max_chars=max_chars):
            sig = _sig(token)
            if not sig or sig in query_terms:
                continue
            considered += 1
            score_by_sig[sig] = float(score_by_sig.get(sig, 0.0) or 0.0) + 1.0
            term_by_sig.setdefault(sig, token)
    return score_by_sig, term_by_sig, considered


def _rank_scored_terms(score_by_sig: dict[str, float], term_by_sig: dict[str, str]) -> list[tuple[str, float, str]]:
    return sorted(
        (
            (
                sig,
                float(score_by_sig.get(sig, 0.0) or 0.0),
                str(term_by_sig.get(sig) or sig),
            )
            for sig in score_by_sig
        ),
        key=lambda item: (-item[1], item[2]),
    )


def _select_followup_terms(
    *,
    gap_terms: list[str],
    ranked_terms: list[tuple[str, float, str]],
    max_terms: int,
) -> list[str]:
    selected_terms = list(gap_terms)
    selected_sigs = {_sig(value) for value in selected_terms if _sig(value)}
    for _rank_sig, _rank_score, term in ranked_terms:
        sig = _sig(term)
        if sig in selected_sigs:
            continue
        selected_terms.append(term)
        if sig:
            selected_sigs.add(sig)
        if len(selected_terms) >= max_terms:
            break
    return selected_terms


def build_contextual_followup_query(
    *,
    query: str,
    docs: list[Document] | None,
    evidence_gap: dict[str, Any] | None = None,
    max_docs: int = 4,
    max_terms: int = 4,
    min_term_chars: int = 4,
    max_term_chars: int = 40,
    max_query_chars: int = 500,
) -> dict[str, Any]:
    base = " ".join(str(query or "").strip().split())
    if not base:
        return _unused_followup_result(query="", reason_code="empty_query")

    docs_list = [d for d in (docs or []) if d is not None]
    max_docs_n = max(0, int(max_docs or 0))
    max_terms_n = max(0, int(max_terms or 0))
    min_chars = max(2, int(min_term_chars or 0))
    max_chars = max(0, int(max_term_chars or 0))
    max_query_chars_n = max(0, int(max_query_chars or 0))

    if not docs_list:
        return _unused_followup_result(query=base, reason_code="no_docs")
    if max_docs_n <= 0:
        return _unused_followup_result(query=base, reason_code="max_docs_le_0")
    if max_terms_n <= 0:
        return _unused_followup_result(
            query=base,
            reason_code="max_terms_le_0",
            docs_considered=min(len(docs_list), max_docs_n),
        )

    query_terms = _extract_query_terms(base, min_chars=min_chars, max_chars=max_chars or 64)
    gap_terms, gap_reason_codes = _extract_gap_terms(
        evidence_gap=evidence_gap,
        query_terms=query_terms,
        min_chars=min_chars,
        max_chars=max_chars or 64,
        max_terms=max_terms_n,
    )
    score_by_sig, term_by_sig, considered = _score_terms_from_docs(
        docs=docs_list[:max_docs_n],
        query_terms=query_terms,
        min_chars=min_chars,
        max_chars=max_chars,
    )

    if not score_by_sig:
        return _unused_followup_result(
            query=base,
            reason_code="no_new_terms",
            terms_considered=considered,
            docs_considered=min(len(docs_list), max_docs_n),
        )

    selected_terms = _select_followup_terms(
        gap_terms=gap_terms,
        ranked_terms=_rank_scored_terms(score_by_sig, term_by_sig),
        max_terms=max_terms_n,
    )

    followup = f"{base} {' '.join(selected_terms)}".strip()
    if max_query_chars_n > 0 and len(followup) > max_query_chars_n:
        followup = followup[:max_query_chars_n].rstrip()

    used = bool(followup and followup != base and selected_terms)
    reason_codes = list(gap_reason_codes)
    reason_codes.append("selected_terms" if used else "followup_equals_base")
    reason_codes = _dedupe_terms(reason_codes, max_items=8)

    return {
        "query": followup if followup else base,
        "used": used,
        "reason_codes": reason_codes,
        "selected_terms": selected_terms[:max_terms_n],
        "terms_considered": int(considered),
        "docs_considered": min(len(docs_list), max_docs_n),
    }


__all__ = ["build_contextual_followup_query"]
