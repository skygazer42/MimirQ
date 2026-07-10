
import re
import unicodedata
from typing import Any

from app.rag.core.logging import get_logger
from app.rag.preprocessing.stopwords import STOPWORDS

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+./:-]{1,64}|[\u4e00-\u9fff]{2,32}", flags=re.UNICODE)
_SPACE_RE = re.compile(r"\s+")
_SEPARATOR_RE = re.compile(r"[-_/]+")

_QUERY_BOILERPLATE = {
    "article",
    "articles",
    "document",
    "documents",
    "find",
    "identify",
    "include",
    "including",
    "introduce",
    "introduced",
    "introduces",
    "method",
    "methods",
    "model",
    "models",
    "paper",
    "papers",
    "propose",
    "proposed",
    "review",
    "reviews",
    "survey",
    "surveys",
    "use",
    "used",
    "uses",
    "work",
    "works",
}


def _normalize_text(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        raw = unicodedata.normalize("NFKC", raw)
    except Exception as exc:
        logger.debug("Ignoring query phrase unicode normalization failure: %s", exc)
    raw = _SEPARATOR_RE.sub(" ", raw)
    return _SPACE_RE.sub(" ", raw.casefold()).strip()


def _query_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(str(query or "")):
        tok = _normalize_text(raw)
        if not tok:
            continue
        if tok in STOPWORDS or tok in _QUERY_BOILERPLATE:
            continue
        if len(tok) < 2:
            continue
        tokens.append(tok)
    return tokens


def extract_informative_query_phrases(
    query: str,
    *,
    max_phrases: int = 24,
    max_ngram: int = 4,
    include_unigrams: bool = False,
) -> list[str]:
    tokens = _query_tokens(query)
    if not tokens:
        return []

    phrases: list[str] = []
    seen: set[str] = set()

    def add(phrase: str) -> None:
        normalized = _normalize_text(phrase)
        if not normalized or normalized in seen:
            return
        if len(normalized) > 160:
            return
        seen.add(normalized)
        phrases.append(normalized)

    upper = max(1, min(int(max_ngram or 1), len(tokens)))
    lower = 1 if include_unigrams else 2
    for n in range(upper, lower - 1, -1):
        for start in range(0, len(tokens) - n + 1):
            add(" ".join(tokens[start : start + n]))
            if len(phrases) >= max(1, int(max_phrases or 1)):
                return phrases
    return phrases


def query_phrase_match(
    query: str,
    text: str,
    *,
    max_phrases: int = 24,
    max_ngram: int = 4,
) -> dict[str, Any]:
    haystack = _normalize_text(text)
    if not haystack:
        return {"score": 0.0, "matched_phrases": [], "longest_match_tokens": 0, "token_coverage": 0.0}

    phrases = extract_informative_query_phrases(query, max_phrases=max_phrases, max_ngram=max_ngram)
    if not phrases:
        return {"score": 0.0, "matched_phrases": [], "longest_match_tokens": 0, "token_coverage": 0.0}

    matched: list[str] = []
    longest = 0
    for phrase in phrases:
        if phrase and phrase in haystack:
            matched.append(phrase)
            longest = max(longest, len(phrase.split()))

    tokens = _query_tokens(query)
    token_total = len(set(tokens))
    token_hits = sum(1 for tok in set(tokens) if tok in haystack) if token_total else 0
    coverage = float(token_hits) / float(token_total) if token_total else 0.0

    if longest >= 3:
        exact_component = min(0.9, float(longest) / 4.0)
        repeat_component = min(0.12, max(0, len(matched) - 1) * 0.04)
        coverage_component = min(0.18, coverage * 0.18)
    else:
        # Two-token overlaps such as "neural networks" are useful but too generic
        # to outweigh an exact paper-title phrase on their own.
        exact_component = float(longest) * 0.12 if longest else 0.0
        repeat_component = min(0.06, max(0, len(matched) - 1) * 0.02)
        coverage_component = min(0.06, coverage * 0.06)
    score = min(1.0, exact_component + repeat_component + coverage_component)

    return {
        "score": round(float(score), 6),
        "matched_phrases": matched[:8],
        "longest_match_tokens": int(longest),
        "token_coverage": round(float(coverage), 6),
    }


__all__ = ["extract_informative_query_phrases", "query_phrase_match"]
