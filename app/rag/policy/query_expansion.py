"""
Deterministic query expansion for policy/manual clause references.

This is a "fast lane" meant to improve recall when users mention clause numbers
directly (e.g. "第十二条", "Section 3.2.1").

Constraints:
- No LLM calls
- Bounded output
- Deterministic and safe for logs/storage
"""


import re

from app.rag.policy.clause_refs import extract_clause_refs

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;]\s*")
_SOFT_SPLIT_RE = re.compile(r"(?:，|,|\s+并且\s+|\s+以及\s+|\s+还有\s+|\s+顺便\s+|\s+另外\s+|\s+同时\s+)")
_ENUM_SPLIT_RE = re.compile(r"[、/／]")
_LEADING_FILLERS_RE = re.compile(
    r"^(?:我想|我准备|请帮我|帮我|麻烦|顺便|另外|以及|还有|同时|后续可能还要|后续|想知道|想查|要|需要)+"
)
_TRAILING_FILLERS_RE = re.compile(r"(?:该怎么处理|怎么处理|怎么办|如何处理|相关事项梳理清楚)$")


def _normalize_lightweight_query_part(value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    text = text.strip(" ，,。；;！？!?：:")
    text = _LEADING_FILLERS_RE.sub("", text).strip(" ，,。；;！？!?：:")
    text = _TRAILING_FILLERS_RE.sub("", text).strip(" ，,。；;！？!?：:")
    return text


def _useful_lightweight_query_part(value: str, *, min_chars: int, max_chars: int) -> str:
    text = _normalize_lightweight_query_part(value)
    if len(text) < min_chars:
        return ""
    if not _CJK_RE.search(text) and len(text.split()) < 2:
        return ""
    return text[:max_chars].strip()


def build_clause_fastlane_queries(query: str, *, max_refs: int = 4) -> list[str]:
    raw = (query or "").strip()
    if not raw:
        return []

    refs = extract_clause_refs(raw)
    if not refs:
        return []

    out: list[str] = []
    for ref in refs:
        v = (ref or "").strip()
        if not v:
            continue
        out.append(v)
        if len(out) >= max_refs:
            break
    return out


def _iter_lightweight_query_candidates(
    *,
    raw: str,
    min_part_chars: int,
    max_part_chars: int,
) -> list[str]:
    candidates: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(raw):
        sentence = _normalize_lightweight_query_part(sentence)
        if not sentence:
            continue
        soft_parts = [_normalize_lightweight_query_part(part) for part in _SOFT_SPLIT_RE.split(sentence)]
        for part in soft_parts:
            useful = _useful_lightweight_query_part(
                part,
                min_chars=min_part_chars,
                max_chars=max_part_chars,
            )
            if useful:
                candidates.append(useful)

            enum_parts = [_normalize_lightweight_query_part(item) for item in _ENUM_SPLIT_RE.split(part)]
            if len(enum_parts) < 2:
                continue
            for item in enum_parts:
                useful_item = _useful_lightweight_query_part(
                    item,
                    min_chars=min_part_chars,
                    max_chars=max_part_chars,
                )
                if useful_item:
                    candidates.append(useful_item)
    return candidates


def build_lightweight_subquery_queries(
    query: str,
    *,
    max_queries: int = 3,
    min_query_chars: int = 28,
    min_part_chars: int = 4,
    max_part_chars: int = 80,
) -> list[str]:
    """Build deterministic subqueries for multi-intent questions.

    This is intentionally not domain-specific and does not call an LLM. It only
    splits obvious sentence/list structures so retrieval can fan out cheaply and
    then let the normal fusion/rerank path decide what survives.
    """

    raw = " ".join(str(query or "").strip().split())
    if len(raw) < int(min_query_chars or 0):
        return []

    max_queries = max(0, min(8, int(max_queries or 0)))
    if max_queries <= 0:
        return []

    min_part_chars_i = int(min_part_chars or 1)
    max_part_chars_i = int(max_part_chars or 80)
    candidates = _iter_lightweight_query_candidates(
        raw=raw,
        min_part_chars=min_part_chars_i,
        max_part_chars=max_part_chars_i,
    )

    out: list[str] = []
    seen = {raw.casefold()}
    for candidate in candidates:
        key = candidate.casefold() if candidate.isascii() else candidate
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
        if len(out) >= max_queries:
            break
    return out
