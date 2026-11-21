"""Detect freshness intent and apply deterministic recency boosts to retrieved documents."""

import math
import re
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.documents import Document

# Broad, multilingual temporal/freshness hints.
#
# Note: these are *hints*, not guarantees. We keep the detector conservative
# and gate any behavior change behind a feature flag.
_TEMPORAL_HINT_RE = re.compile(
    r"("
    r"最新|最近|当前|目前|现在|截至|到目前为止|"
    r"latest|newest|recent|currently|current|as of|up[- ]to[- ]date|today|updated"
    r")",
    flags=re.IGNORECASE,
)


# Explicit years (e.g. 2024/2025) are a strong temporal signal.
_YEAR_RE = re.compile(r"\b(20\d{2})\b")


# Relative time ranges (rough heuristics).
_RELATIVE_HINT_RE = re.compile(
    r"("
    r"近(?:一|两|三|四|五|六|七|八|九|十)?(?:天|周|个月|月|年)|"
    r"过去(?:一|两|三|四|五|六|七|八|九|十)?(?:天|周|个月|月|年)|"
    r"last\s+(?:day|week|month|year)|"
    r"past\s+(?:day|week|month|year)"
    r")",
    flags=re.IGNORECASE,
)


def detect_temporal_intent(query: str) -> dict[str, Any]:
    """
    Best-effort temporal intent detector.

    Returns a compact, PII-safe payload:
      {
        "detected": bool,
        "reason_codes": list[str],
      }
    """
    q = (query).strip()
    if not q:
        return {"detected": False, "reason_codes": []}

    reasons: list[str] = []
    if _TEMPORAL_HINT_RE.search(q):
        reasons.append("keyword")
    if _RELATIVE_HINT_RE.search(q):
        reasons.append("relative")
    if _YEAR_RE.search(q):
        reasons.append("year")

    # Keep this low-cardinality for metrics.
    reasons = sorted(set(reasons))
    return {"detected": bool(reasons), "reason_codes": reasons[:8]}


def _doc_base_score(meta: dict[str, Any]) -> float:
    for key in ("relevance_score", "query_expansion_base_score", "retrieval_score", "score"):
        score = meta.get(key)
        if score is not None:
            base = float(score)
            if not math.isfinite(base):
                raise ValueError("Recency ranking requires a finite base score")
            return base
    return 0.0


def apply_recency_boost(
    docs: list["Document"],
    *,
    updated_ts_by_document_id: dict[str, float],
    boost_max: float,
    window_days: int,
    now_ts: float | None = None,
) -> tuple[list["Document"], dict[str, Any]]:
    """
    Re-rank retrieved docs by adding a small recency boost.

    - The boost is additive: composite = base_score + boost
    - boost is linearly decayed from 1 -> 0 over `window_days`
    - docs without timestamps are left unboosted
    """
    boost_max = max(0.0, boost_max)
    window_days = max(1, window_days)
    if not docs:
        return [], {"enabled": True, "used": False, "reason": "empty_docs"}
    if boost_max <= 0.0:
        return list(docs), {"enabled": True, "used": False, "reason": "boost_max_le_0"}
    if not updated_ts_by_document_id:
        return list(docs), {"enabled": True, "used": False, "reason": "no_timestamps"}

    now_ts = float(now_ts) if now_ts is not None else time.time()

    boosts: list[float] = []
    scored: list[tuple[float, int, Document]] = []
    docs_with_ts = 0

    for i, doc in enumerate(docs):
        meta = doc.metadata

        doc_id_raw = meta.get("document_id")
        doc_id = str(doc_id_raw).strip() if doc_id_raw is not None else ""
        ts = updated_ts_by_document_id.get(doc_id) if doc_id else None
        if ts is not None:
            timestamp = float(ts)
            if not math.isfinite(timestamp):
                raise ValueError("Recency ranking requires a finite document timestamp")
            docs_with_ts += 1
            age_days = max(0.0, (now_ts - timestamp) / 86400.0)
            recency = max(0.0, 1.0 - (age_days / float(window_days)))
            boost = recency * boost_max
        else:
            boost = 0.0

        base = _doc_base_score(meta)
        comp = base + boost
        boosts.append(boost)
        scored.append((comp, i, doc))

    scored_sorted = sorted(scored, key=lambda x: (-x[0], x[1]))
    out = [d for _score, _i, d in scored_sorted]

    avg_boost = sum(boosts) / len(boosts)
    max_boost = max(boosts)

    return out, {
        "enabled": True,
        "used": True,
        "docs": len(docs),
        "docs_with_ts": docs_with_ts,
        "window_days": window_days,
        "boost_max": boost_max,
        "avg_boost": round(avg_boost, 6),
        "max_boost": round(max_boost, 6),
        "reordered": bool(out != list(docs)),
    }


__all__ = ["apply_recency_boost", "detect_temporal_intent"]
