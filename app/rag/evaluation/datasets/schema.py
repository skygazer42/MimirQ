
from typing import Any

EVAL_DATASET_SCHEMA_V1 = "mimirq.eval.dataset.sample.v1"
_QUERY_TYPES = {"factual", "multi_hop", "structured", "unanswerable"}
_SOURCE_TYPES = {"real_log", "manual_seed", "adversarial", "synthetic"}
_ROUTES = {"retrieval", "kg", "hybrid", "agentic"}
_ANNOTATION_STATUS = {"todo", "labeled", "reviewed"}
_REVIEW_STATUS = {"pending", "reviewed", "approved"}


def _safe_str(value: Any, *, max_len: int = 10_000) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[: max(1, int(max_len or 1))]


def normalize_eval_dataset_sample(sample: dict[str, Any]) -> dict[str, Any]:
    payload = dict(sample or {})
    query_type = _safe_str(payload.get("query_type"), max_len=64) or "factual"
    source_type = _safe_str(payload.get("source_type"), max_len=64) or "real_log"
    expected_route = _safe_str(payload.get("expected_route"), max_len=64)
    if expected_route is not None and expected_route not in _ROUTES:
        expected_route = None
    gold_chunk_ids = [
        str(item).strip()
        for item in (payload.get("gold_chunk_ids") or [])
        if str(item or "").strip()
    ]

    return {
        "schema_version": EVAL_DATASET_SCHEMA_V1,
        "sample_id": _safe_str(payload.get("sample_id"), max_len=255) or "",
        "query": _safe_str(payload.get("query")) or "",
        "query_type": query_type,
        "source_type": source_type,
        "gold_answer": _safe_str(payload.get("gold_answer")) or "",
        "gold_chunk_ids": gold_chunk_ids,
        "gold_evidence": list(payload.get("gold_evidence") or []),
        "is_unanswerable": bool(payload.get("is_unanswerable") or False),
        "expected_route": expected_route,
        "annotation_status": _safe_str(payload.get("annotation_status"), max_len=64) or "todo",
        "review_status": _safe_str(payload.get("review_status"), max_len=64) or "pending",
        "construction_method": _safe_str(payload.get("construction_method"), max_len=128),
        "parent_sample_ids": [
            str(item).strip()
            for item in (payload.get("parent_sample_ids") or [])
            if str(item or "").strip()
        ],
        "critique": dict(payload.get("critique") or {}),
        "notes": _safe_str(payload.get("notes")),
        "tags": [str(item).strip() for item in (payload.get("tags") or []) if str(item or "").strip()],
    }


__all__ = [
    "EVAL_DATASET_SCHEMA_V1",
    "normalize_eval_dataset_sample",
]
