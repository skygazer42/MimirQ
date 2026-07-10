
import hashlib
from typing import Any

from app.rag.core.logging import get_logger
from app.rag.evaluation.hard_negative_mining import mine_hard_negatives_for_case_from_trace
from app.rag.industry_rules.mining.auto_rules import build_ruleset_suggestions
from app.rag.industry_rules.schema import IndustryRuleset

FEEDBACK_LOOP_CANDIDATES_SCHEMA_V1 = "mimirq.feedback_loop_candidates.v1"
FEEDBACK_TRAINING_TRIPLE_SCHEMA_V1 = "mimirq.feedback_training_triple.v1"


def _as_mapping(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    out: dict[str, Any] = {}
    for key in dir(row):
        if key.startswith("_"):
            continue
        try:
            value = getattr(row, key)
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if callable(value):
            continue
        out[key] = value
    return out


def _safe_str(value: Any, *, max_len: int = 512) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[: max(0, int(max_len or 0))] if max_len else text


def _stable_query_hash(query: str) -> str:
    return hashlib.sha256(str(query or "").encode("utf-8", errors="ignore")).hexdigest()


def _rating(row: dict[str, Any]) -> int | None:
    try:
        return int(row.get("rating")) if row.get("rating") is not None else None
    except Exception:
        return None


def _extra(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("extra")
    return dict(value) if isinstance(value, dict) else {}


def _query(row: dict[str, Any]) -> str:
    extra = _extra(row)
    for key in ("original_query", "query", "question", "user_query"):
        text = _safe_str(row.get(key), max_len=4000)
        if text:
            return text
    for key in ("original_query", "query", "question", "user_query"):
        text = _safe_str(extra.get(key), max_len=4000)
        if text:
            return text
    return ""


def _reference_sources(row: dict[str, Any]) -> list[dict[str, Any]]:
    extra = _extra(row)
    refs = row.get("reference_sources")
    if not isinstance(refs, list):
        refs = extra.get("reference_sources")
    if not isinstance(refs, list):
        refs = []
    return [dict(item) for item in refs if isinstance(item, dict)]


def _retrieval_trace(row: dict[str, Any]) -> dict[str, Any]:
    extra = _extra(row)
    for key in ("retrieval_trace", "trace", "trace_record"):
        value = row.get(key)
        if isinstance(value, dict):
            return dict(value)
    value = extra.get("retrieval_trace")
    return dict(value) if isinstance(value, dict) else {}


def _feedback_id(row: dict[str, Any]) -> str:
    return _safe_str(row.get("feedback_id") or row.get("id") or _extra(row).get("feedback_id"), max_len=128)


def _dataset_id(row: dict[str, Any]) -> str | None:
    text = _safe_str(row.get("dataset_id") or _extra(row).get("dataset_id"), max_len=128)
    return text or None


def _lineage_id(row: dict[str, Any], key: str) -> str | None:
    text = _safe_str(row.get(key) or _extra(row).get(key), max_len=128)
    return text or None


def _positive_chunk_ids(reference_sources: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in reference_sources:
        cid = _safe_str(item.get("chunk_id"), max_len=200)
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
        if len(out) >= 20:
            break
    return out


def _build_training_triple(
    *,
    row: dict[str, Any],
    mined: dict[str, Any],
    reference_sources: list[dict[str, Any]],
) -> dict[str, Any] | None:
    positives = _positive_chunk_ids(reference_sources)
    negatives = [
        _safe_str(item.get("chunk_id"), max_len=200)
        for item in (mined.get("hard_negatives") or [])
        if isinstance(item, dict) and _safe_str(item.get("chunk_id"), max_len=200)
    ]
    if not positives or not negatives:
        return None
    return {
        "schema": FEEDBACK_TRAINING_TRIPLE_SCHEMA_V1,
        "query_hash": mined.get("query_hash") or "",
        "positive_chunk_ids": positives,
        "negative_chunk_ids": negatives[:20],
        "source_feedback_id": _feedback_id(row) or None,
        "dataset_id": _dataset_id(row),
    }


def _rules_row(row: dict[str, Any]) -> dict[str, Any]:
    trace = _retrieval_trace(row)
    citations = trace.get("citations") if isinstance(trace, dict) else []
    filenames: list[str] = []
    if isinstance(citations, list):
        for item in citations:
            if not isinstance(item, dict):
                continue
            name = _safe_str(item.get("filename") or item.get("document_name") or item.get("document_id"), max_len=200)
            if name:
                filenames.append(name)
    return {
        "interaction_id": _feedback_id(row),
        "original_query": _query(row),
        "final_context_filenames": filenames[:20],
    }


def build_feedback_loop_candidates(
    rows: list[Any],
    *,
    ruleset: IndustryRuleset | None = None,
    max_rating: int = 2,
    top_k: int = 10,
    max_hard_negatives: int = 10,
) -> dict[str, Any]:
    normalized_rows = [_as_mapping(row) for row in (rows or [])]
    negative_rows = [row for row in normalized_rows if (_rating(row) is not None and int(_rating(row) or 0) <= int(max_rating))]

    hard_negative_records: list[dict[str, Any]] = []
    training_triples: list[dict[str, Any]] = []

    for row in negative_rows:
        query = _query(row)
        refs = _reference_sources(row)
        trace = _retrieval_trace(row)
        if not query or not refs or not trace:
            continue
        mined = mine_hard_negatives_for_case_from_trace(
            case={"reference_sources": refs},
            trace_record=trace,
            query_hash=_stable_query_hash(query),
            max_hard_negatives=max_hard_negatives,
        )
        if not mined.get("hard_negatives"):
            continue
        fid = _feedback_id(row)
        if fid:
            mined["source_feedback_ids"] = [fid]
        ds = _dataset_id(row)
        if ds:
            mined["dataset_id"] = ds
        conv_id = _lineage_id(row, "conversation_id")
        if conv_id:
            mined["source_conversation_ids"] = [conv_id]
        msg_id = _lineage_id(row, "message_id")
        if msg_id:
            mined["source_message_ids"] = [msg_id]
        hard_negative_records.append(mined)

        triple = _build_training_triple(row=row, mined=mined, reference_sources=refs)
        if triple is not None:
            training_triples.append(triple)

    rules_rows = [_rules_row(row) for row in negative_rows if _query(row)]
    rules_suggestions = build_ruleset_suggestions(rules_rows, ruleset=ruleset, top_k=top_k)

    return {
        "schema": FEEDBACK_LOOP_CANDIDATES_SCHEMA_V1,
        "summary": {
            "feedback_total": int(len(normalized_rows)),
            "negative_feedback_total": int(len(negative_rows)),
            "hard_negative_records": int(len(hard_negative_records)),
            "training_triples": int(len(training_triples)),
            "rules_glossary_candidates": int(len(rules_suggestions.get("glossary_suggestions") or [])),
            "rules_pattern_candidates": int(len(rules_suggestions.get("pattern_suggestions") or [])),
            "rules_intent_candidates": int(len(rules_suggestions.get("intent_suggestions") or [])),
        },
        "hard_negative_records": hard_negative_records,
        "training_triples": training_triples,
        "rules_suggestions": rules_suggestions,
    }


__all__ = [
    "FEEDBACK_LOOP_CANDIDATES_SCHEMA_V1",
    "FEEDBACK_TRAINING_TRIPLE_SCHEMA_V1",
    "build_feedback_loop_candidates",
]
