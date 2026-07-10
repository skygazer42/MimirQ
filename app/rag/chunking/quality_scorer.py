"""
Chunk semantic-ish quality scoring (best-effort).

This is intentionally lightweight and heuristic-driven:
- No LLM calls (preview must stay fast).
- PII-safe outputs: only numeric scores + coarse reason codes.

Used initially by chunk preview to surface "needs_review" signals for data governance.
"""


import re
from typing import Any

from app.rag.preprocessing.tokenization import tokenize_for_bm25

# P0 Optimization: Chunk size bounds based on Vectara NAACL 2025 research
MIN_CHUNK_SIZE_TOKENS = 100  # Minimum for effective retrieval
MAX_CHUNK_SIZE_TOKENS = 1000  # Before quality degradation
OPTIMAL_CHUNK_RANGE = (200, 512)  # Sweet spot for recall

# P0 Optimization: Context Cliff detection based on Anthropic research
CONTEXT_CLIFF_WARNING = 2000  # Recall starts to decline
CONTEXT_CLIFF_DANGER = 2500   # Steep drop in recall quality (92% -> 55%)

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


def validate_chunk_size_bounds(tokens_est: int) -> dict[str, Any]:
    """
    P0 Optimization: Validate chunk size against research-backed bounds.

    Based on:
    - Vectara NAACL 2025: Chunks < 100 tokens have significantly lower recall
    - Optimal range: 200-512 tokens for best retrieval quality

    Args:
        tokens_est: Estimated token count for the chunk

    Returns:
        Dictionary with validation results:
        - is_valid: Whether chunk meets minimum requirements
        - tokens: The token count
        - size_category: Classification (too_small/below_optimal/optimal/above_optimal/too_large)
        - warning: Warning message if any
        - recommendation: Suggested action
        - severity: Issue severity (critical/warning/info/none)
    """
    result = {
        "is_valid": True,
        "tokens": tokens_est,
        "size_category": "optimal",
        "warning": None,
        "recommendation": None,
        "severity": "none"
    }

    if tokens_est < MIN_CHUNK_SIZE_TOKENS:
        result["is_valid"] = False
        result["size_category"] = "too_small"
        result["warning"] = f"Chunk too small ({tokens_est} < {MIN_CHUNK_SIZE_TOKENS} tokens)"
        result["recommendation"] = f"merge_to_{MIN_CHUNK_SIZE_TOKENS}"
        result["severity"] = "critical"
    elif tokens_est > MAX_CHUNK_SIZE_TOKENS:
        result["is_valid"] = False
        result["size_category"] = "too_large"
        result["warning"] = f"Chunk too large ({tokens_est} > {MAX_CHUNK_SIZE_TOKENS} tokens)"
        result["recommendation"] = f"split_to_{OPTIMAL_CHUNK_RANGE[1]}"
        result["severity"] = "critical"
    elif tokens_est < OPTIMAL_CHUNK_RANGE[0]:
        result["size_category"] = "below_optimal"
        result["warning"] = f"Below optimal range ({tokens_est} < {OPTIMAL_CHUNK_RANGE[0]})"
        result["recommendation"] = "consider_merge"
        result["severity"] = "warning"
    elif tokens_est > OPTIMAL_CHUNK_RANGE[1]:
        result["size_category"] = "above_optimal"
        result["warning"] = f"Above optimal range ({tokens_est} > {OPTIMAL_CHUNK_RANGE[1]})"
        result["recommendation"] = "consider_split"
        result["severity"] = "info"

    return result


def detect_context_cliff(tokens_est: int) -> dict[str, Any]:
    """
    P0 Optimization: Detect Context Cliff risk based on Anthropic research.

    Context Cliff phenomenon: Retrieval quality drops dramatically when chunks
    exceed ~2500 tokens. Recall drops from 92% to 55% at this threshold.

    Args:
        tokens_est: Estimated token count for the chunk

    Returns:
        Dictionary with cliff detection results:
        - cliff_risk: Risk level (none/low/medium/high)
        - severity: Issue severity (critical/warning/info/none)
        - action: Recommended action
        - target_sizes: Suggested split sizes
        - explanation: Human-readable explanation
        - estimated_recall: Expected recall percentage
    """
    if tokens_est >= CONTEXT_CLIFF_DANGER:
        return {
            "cliff_risk": "high",
            "severity": "critical",
            "action": "split_required",
            "target_sizes": [600, 800, 1000],
            "explanation": f"Exceeds Context Cliff threshold ({tokens_est} >= {CONTEXT_CLIFF_DANGER} tokens). Recall drops to ~55%.",
            "estimated_recall": 0.55
        }
    elif tokens_est >= CONTEXT_CLIFF_WARNING:
        return {
            "cliff_risk": "medium",
            "severity": "warning",
            "action": "consider_split",
            "target_sizes": [1000, 1200],
            "explanation": f"Approaching Context Cliff ({tokens_est} >= {CONTEXT_CLIFF_WARNING} tokens). Consider splitting.",
            "estimated_recall": 0.75
        }
    elif tokens_est >= OPTIMAL_CHUNK_RANGE[1]:
        return {
            "cliff_risk": "low",
            "severity": "info",
            "action": "monitor",
            "target_sizes": None,
            "explanation": f"Within safe range ({tokens_est} tokens). Monitor for growth.",
            "estimated_recall": 0.88
        }
    else:
        return {
            "cliff_risk": "none",
            "severity": "none",
            "action": "none",
            "target_sizes": None,
            "explanation": f"In optimal range ({tokens_est} tokens).",
            "estimated_recall": 0.92
        }


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

    # P0 Optimization: Validate chunk size bounds
    size_validation = validate_chunk_size_bounds(denom_tokens)

    # P0 Optimization: Detect Context Cliff risk
    cliff_detection = detect_context_cliff(denom_tokens)

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

    # P0 Optimization: Add size and cliff warnings
    if not size_validation["is_valid"]:
        reasons.append(size_validation["size_category"])
    if cliff_detection["cliff_risk"] in ("high", "medium"):
        reasons.append(f"cliff_risk_{cliff_detection['cliff_risk']}")

    scores: dict[str, Any] = {
        "information_density": round(_clamp01(information_density), 4),
        "semantic_completeness": round(_clamp01(semantic_completeness), 4),
        "self_containedness": round(_clamp01(self_containedness), 4),
        "pronoun_ratio": round(_clamp01(pronoun_ratio), 4),
        "dedup_risk_prev_jaccard": (round(float(dedup_prev), 4) if dedup_prev is not None else None),
        "needs_review": bool(reasons),
        "reasons": reasons[:6],  # Increased from 4 to 6 to accommodate new checks
        # P0 Optimization: Include size validation and cliff detection
        "size_validation": size_validation,
        "context_cliff": cliff_detection,
        "token_count": denom_tokens,
    }

    return scores, token_set


__all__ = [
    "score_chunk_semantic_quality",
    "validate_chunk_size_bounds",
    "detect_context_cliff",
    "MIN_CHUNK_SIZE_TOKENS",
    "MAX_CHUNK_SIZE_TOKENS",
    "OPTIMAL_CHUNK_RANGE",
    "CONTEXT_CLIFF_WARNING",
    "CONTEXT_CLIFF_DANGER",
]
