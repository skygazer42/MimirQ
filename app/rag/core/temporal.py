"""
Temporal intent detection + lightweight recency-aware reranking (optional).

This module is intentionally:
- deterministic (no LLM calls)
- dependency-light
- fail-open (must never break retrieval)
"""


import re
import time
from typing import Any
from uuid import UUID

from app.rag.core.logging import get_logger

logger = get_logger(__name__)

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
    r"last\\s+(?:day|week|month|year)|"
    r"past\\s+(?:day|week|month|year)"
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
    q = (query or "").strip()
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
    for k in ("relevance_score", "query_expansion_base_score", "retrieval_score", "score"):
        v = meta.get(k)
        if v is None:
            continue
        try:
            return float(v or 0.0)
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
    return 0.0


def apply_recency_boost(
    docs: list[Any],
    *,
    updated_ts_by_document_id: dict[str, float],
    boost_max: float,
    window_days: int,
    now_ts: float | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """
    Re-rank retrieved docs by adding a small recency boost.

    - The boost is additive: composite = base_score + boost
    - boost is linearly decayed from 1 -> 0 over `window_days`
    - docs without timestamps are left unboosted
    """
    boost_max = max(0.0, float(boost_max or 0.0))
    window_days = max(1, int(window_days or 0))
    if not docs:
        return [], {"enabled": True, "used": False, "reason": "empty_docs"}
    if boost_max <= 0.0:
        return list(docs), {"enabled": True, "used": False, "reason": "boost_max_le_0"}
    if not updated_ts_by_document_id:
        return list(docs), {"enabled": True, "used": False, "reason": "no_timestamps"}

    now_ts = float(now_ts) if now_ts is not None else time.time()

    boosts: list[float] = []
    scored: list[tuple[float, int, Any]] = []
    docs_with_ts = 0

    for i, d in enumerate(docs):
        meta = getattr(d, "metadata", None)
        meta = meta if isinstance(meta, dict) else {}

        doc_id_raw = meta.get("document_id")
        doc_id = str(doc_id_raw).strip() if doc_id_raw is not None else ""
        ts = updated_ts_by_document_id.get(doc_id) if doc_id else None
        if ts is not None:
            docs_with_ts += 1
            try:
                age_days = max(0.0, (now_ts - float(ts)) / 86400.0)
            except Exception:
                age_days = 0.0
            recency = max(0.0, 1.0 - (age_days / float(window_days)))
            boost = float(recency) * float(boost_max)
        else:
            boost = 0.0

        base = _doc_base_score(meta)
        comp = float(base) + float(boost)
        boosts.append(float(boost))
        scored.append((comp, i, d))

    scored_sorted = sorted(scored, key=lambda x: (-x[0], x[1]))
    out = [d for _score, _i, d in scored_sorted]

    try:
        avg_boost = float(sum(boosts)) / float(len(boosts))
    except Exception:
        avg_boost = 0.0
    try:
        max_boost = float(max(boosts)) if boosts else 0.0
    except Exception:
        max_boost = 0.0

    return out, {
        "enabled": True,
        "used": True,
        "docs": int(len(docs)),
        "docs_with_ts": int(docs_with_ts),
        "window_days": int(window_days),
        "boost_max": float(boost_max),
        "avg_boost": round(float(avg_boost), 6),
        "max_boost": round(float(max_boost), 6),
        "reordered": bool(out != list(docs)),
    }


def _parse_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except Exception:
        return None


def _normalize_document_uuid_list(document_ids: list[str], *, max_docs: int) -> list[UUID]:
    doc_uuid_list: list[UUID] = []
    seen: set[str] = set()
    for did in document_ids:
        s = str(did or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        parsed = _parse_uuid(s)
        if parsed is None:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        doc_uuid_list.append(parsed)
        if len(doc_uuid_list) >= max_docs:
            break
    return doc_uuid_list


def _rows_to_updated_timestamps(rows: list[tuple[Any, Any, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for did, updated_at, created_at in rows:
        ts = updated_at or created_at
        try:
            ts_sec = float(ts.timestamp()) if ts is not None else None
        except Exception:
            ts_sec = None
        if ts_sec is None:
            continue
        out[str(did)] = float(ts_sec)
    return out


def _query_document_timestamp_rows(
    *,
    tenant_uuid: UUID,
    dataset_uuid: UUID | None,
    doc_uuid_list: list[UUID],
) -> list[tuple[Any, Any, Any]]:
    from app.core.database import SessionLocal  # noqa: WPS433
    from app.models.document import Document as DBDocument  # noqa: WPS433

    db = SessionLocal()
    try:
        q = (
            db.query(DBDocument.id, DBDocument.updated_at, DBDocument.created_at)
            .filter(DBDocument.tenant_id == tenant_uuid)
            .filter(DBDocument.id.in_(sorted(doc_uuid_list)))
        )
        if dataset_uuid is not None:
            q = q.filter(DBDocument.dataset_id == dataset_uuid)
        return q.all()
    finally:
        try:
            db.close()
        except Exception as exc:
            logger.debug("Ignoring temporal metadata session close failure: %s", exc)


def fetch_document_updated_ts(
    document_ids: list[str],
    *,
    tenant_id: Any,
    dataset_id: Any | None = None,
    max_docs: int = 200,
) -> dict[str, float]:
    """
    Query DB for document updated timestamps.

    Returns:
      { "<document_uuid>": <ts_seconds> }
    """
    max_docs = max(0, int(max_docs or 0))
    if max_docs <= 0:
        return {}

    if not tenant_id or not document_ids:
        return {}

    # Parse IDs early to avoid wasting DB calls.
    doc_uuid_list = _normalize_document_uuid_list(document_ids, max_docs=max_docs)
    if not doc_uuid_list:
        return {}

    tenant_uuid = _parse_uuid(tenant_id)
    if tenant_uuid is None:
        return {}

    dataset_uuid = _parse_uuid(dataset_id) if dataset_id is not None else None
    try:
        rows = _query_document_timestamp_rows(
            tenant_uuid=tenant_uuid,
            dataset_uuid=dataset_uuid,
            doc_uuid_list=doc_uuid_list,
        )
        return _rows_to_updated_timestamps(rows)
    except Exception:
        return {}


__all__ = [
    "apply_recency_boost",
    "detect_temporal_intent",
    "fetch_document_updated_ts",
]
