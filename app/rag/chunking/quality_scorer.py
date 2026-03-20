"""
Chunk semantic-ish quality scoring (best-effort).

This is intentionally lightweight and heuristic-driven:
- No LLM calls (preview must stay fast).
- PII-safe outputs: only numeric scores + coarse reason codes.

Used initially by chunk preview to surface "needs_review" signals for data governance.
"""

from __future__ import annotations

import re
from typing import Any

from app.rag.preprocessing.tokenization import tokenize_for_bm25

_TERMINAL_PUNCT = set(".!?。！？;；:：")
_SOFT_TERMINAL_PUNCT = set(",，")

_CLOSING_PUNCT = set(")]}”’\"」】》")
_OPENING_TO_CLOSING = {
    "(": ")",
    "[": "]",
    "{": "}",
    "“": "”",
    "‘": "’",
    "「": "」",
    "【": "】",
    "《": "》",
}

# Coarse context-dependent indicators (best-effort).
_PRONOUN_EN_RE = re.compile(
    r"(?i)\b(it|this|that|these|those|they|them|their|its|here|there|above|below)\b"
)
_PRONOUN_ZH_RE = re.compile(r"(?:上述|下文|本节|本段|此处|这里|那里|这个|这些|那个|那些|其|该[文段节项]?)")


def _clamp01(value: float) -> float:
    try:
        v = float(value)
    except Exception:
        return 0.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return float(len(a & b) / len(union))


def _pronoun_count(text: str) -> int:
    if not text:
        return 0
    try:
        en = len(_PRONOUN_EN_RE.findall(text))
    except Exception:
        en = 0
    try:
        zh = sum(1 for _ in _PRONOUN_ZH_RE.finditer(text))
    except Exception:
        zh = 0
    return int(en + zh)


def _semantic_completeness_score(text: str) -> float:
    """
    Best-effort completeness score in [0, 1].

    Signals:
    - ends with terminal punctuation -> higher
    - starts with obvious mid-sentence tokens -> lower
    - unbalanced brackets/quotes -> lower
    """
    raw = (text or "").strip()
    if not raw:
        return 0.0

    last = raw[-1]
    if last in _TERMINAL_PUNCT or last in _CLOSING_PUNCT:
        end_score = 1.0
    elif last in _SOFT_TERMINAL_PUNCT:
        end_score = 0.55
    else:
        end_score = 0.25

    first = raw[0]
    if first.islower() or first in _SOFT_TERMINAL_PUNCT:
        start_score = 0.65
    else:
        start_score = 1.0

    balance_penalty = 1.0
    try:
        for op, cl in _OPENING_TO_CLOSING.items():
            if raw.count(op) != raw.count(cl):
                balance_penalty *= 0.85
    except Exception:
        balance_penalty = 0.9

    return _clamp01(end_score * start_score * balance_penalty)


def score_chunk_semantic_quality(
    content: str,
    *,
    tokens_est: int | None = None,
    prev_token_set: set[str] | None = None,
    max_tokenize_chars: int = 4000,
) -> tuple[dict[str, Any], set[str]]:
    """
    Return (scores, token_set) for a chunk.

    `scores` is safe to embed into chunk metadata.
    """
    text = str(content or "")
    trimmed = text.strip()
    if not trimmed:
        return (
            {
                "information_density": 0.0,
                "semantic_completeness": 0.0,
                "self_containedness": 0.0,
                "pronoun_ratio": 0.0,
                "dedup_risk_prev_jaccard": None,
                "needs_review": True,
                "reasons": ["empty"],
            },
            set(),
        )

    sample = trimmed[: max(0, int(max_tokenize_chars or 0))] if max_tokenize_chars else trimmed
    tokens = tokenize_for_bm25(sample)
    token_set = set(tokens or [])
    keyword_count = int(len(token_set))

    denom_tokens = int(tokens_est or 0)
    if denom_tokens <= 0:
        denom_tokens = max(1, int(len(tokens or [])))

    information_density = float(keyword_count / max(1, denom_tokens))

    pronouns = _pronoun_count(trimmed)
    pronoun_ratio = float(pronouns / max(1, denom_tokens))
    # Map pronoun ratio to a "self-containedness" score (lower pronoun ratio => higher score).
    self_containedness = _clamp01(1.0 - (pronoun_ratio / 0.06))

    semantic_completeness = _semantic_completeness_score(trimmed)

    dedup_prev = None
    if prev_token_set is not None and token_set:
        dedup_prev = _jaccard(prev_token_set, token_set)

    reasons: list[str] = []
    if denom_tokens >= 80 and information_density < 0.12:
        reasons.append("low_density")
    if semantic_completeness < 0.35:
        reasons.append("incomplete")
    if denom_tokens >= 50 and self_containedness < 0.35:
        reasons.append("context_dependent")
    if dedup_prev is not None and dedup_prev > 0.9:
        reasons.append("near_duplicate")

    scores: dict[str, Any] = {
        "information_density": round(_clamp01(information_density), 4),
        "semantic_completeness": round(_clamp01(semantic_completeness), 4),
        "self_containedness": round(_clamp01(self_containedness), 4),
        "pronoun_ratio": round(_clamp01(pronoun_ratio), 4),
        "dedup_risk_prev_jaccard": (round(float(dedup_prev), 4) if dedup_prev is not None else None),
        "needs_review": bool(reasons),
        "reasons": reasons[:4],
    }

    return scores, token_set


__all__ = ["score_chunk_semantic_quality"]
