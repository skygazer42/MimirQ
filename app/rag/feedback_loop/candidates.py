import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from app.rag.evaluation.generation.hard_negative_mining import mine_hard_negatives_for_case_from_trace
from app.rag.industry_rules.mining.auto_rules import build_ruleset_suggestions
from app.rag.industry_rules.schema import IndustryRuleset

FEEDBACK_LOOP_CANDIDATES_SCHEMA_V1 = "mimirq.feedback_loop_candidates.v1"
FEEDBACK_TRAINING_TRIPLE_SCHEMA_V1 = "mimirq.feedback_training_triple.v1"
FEEDBACK_EVAL_CASE_SCHEMA_V1 = "mimirq.feedback_eval_case.v1"


def _optional_text(value: str | None, *, max_len: int = 512) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("Feedback text fields must be strings")
    text = value.strip()
    return text[:max_len] if max_len else text


def _stable_query_hash(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8", errors="ignore")).hexdigest()


def _bounded_optional_text(value: str | None, *, max_len: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("Feedback text fields must be strings")
    return value[:max_len]


def _rating(row: dict[str, Any]) -> int | None:
    value = row.get("rating")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("Feedback rating must be an integer")
    if not 1 <= value <= 5:
        raise ValueError("Feedback rating must be between 1 and 5")
    return value


def _extra(row: dict[str, Any]) -> Mapping[str, Any]:
    value = row.get("extra")
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("Feedback extra must be a mapping")
    return value


def _query(row: dict[str, Any]) -> str:
    extra = _extra(row)
    for key in ("original_query", "query", "question", "user_query"):
        text = _optional_text(row.get(key), max_len=4000)
        if text:
            return text
    for key in ("original_query", "query", "question", "user_query"):
        text = _optional_text(extra.get(key), max_len=4000)
        if text:
            return text
    return ""


def _reference_sources(row: dict[str, Any]) -> list[dict[str, Any]]:
    extra = _extra(row)
    refs = row.get("reference_sources")
    if refs is None:
        refs = extra.get("reference_sources")
    if refs is None:
        return []
    if not isinstance(refs, list) or any(not isinstance(item, Mapping) for item in refs):
        raise TypeError("Feedback reference sources must be a list of mappings")
    return [dict(item) for item in refs]


def _retrieval_trace(row: dict[str, Any]) -> dict[str, Any]:
    extra = _extra(row)
    for key in ("retrieval_trace", "trace", "trace_record"):
        value = row.get(key)
        if value is not None:
            if not isinstance(value, Mapping):
                raise TypeError("Feedback retrieval trace must be a mapping")
            return dict(value)
    value = extra.get("retrieval_trace")
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("Feedback retrieval trace must be a mapping")
    return dict(value)


def _feedback_id(row: dict[str, Any]) -> str | None:
    value = row.get("feedback_id", row.get("id", _extra(row).get("feedback_id")))
    return _bounded_optional_text(value, max_len=128)


def _lineage_id(row: dict[str, Any], key: str) -> str | None:
    value = row.get(key, _extra(row).get(key))
    return _bounded_optional_text(value, max_len=128)


def _positive_chunk_ids(reference_sources: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in reference_sources:
        cid = _optional_text(item.get("chunk_id"), max_len=200)
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
    negatives: list[str] = []
    for item in mined["hard_negatives"]:
        chunk_id = _optional_text(item["chunk_id"], max_len=200)
        if chunk_id:
            negatives.append(chunk_id)
    if not positives or not negatives:
        return None
    return {
        "schema": FEEDBACK_TRAINING_TRIPLE_SCHEMA_V1,
        "query_hash": mined["query_hash"],
        "positive_chunk_ids": positives,
        "negative_chunk_ids": negatives[:20],
        "source_feedback_id": _feedback_id(row),
        "dataset_id": _lineage_id(row, "dataset_id"),
    }


def _build_eval_case_candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    extra = _extra(row)
    status = _optional_text(row.get("eval_case_status", extra.get("eval_case_status")), max_len=32)
    if status is not None:
        status = status.lower()
    archived = row.get("archived", extra.get("archived", False))
    if archived is not None and not isinstance(archived, bool):
        raise TypeError("Feedback archived flag must be a boolean")
    if status in {"promoted", "rejected"} or archived:
        return None
    question = _query(row)
    if not question:
        return None
    category = _bounded_optional_text(row.get("category"), max_len=32)
    raw_tags = row.get("tags")
    if raw_tags is None:
        raw_tags = []
    if not isinstance(raw_tags, list):
        raise TypeError("Feedback tags must be a list")
    tags = [_optional_text(item, max_len=64) for item in raw_tags]
    tags = [item for item in tags if item]
    if category and category not in tags:
        tags.append(category)
    trace = _retrieval_trace(row)
    reference_sources = _reference_sources(row)
    if not reference_sources and isinstance(trace.get("citations"), list):
        reference_sources = [dict(item) for item in trace["citations"] if isinstance(item, dict)]
    retrieval = trace.get("retrieval") if isinstance(trace.get("retrieval"), dict) else {}
    return {
        "schema": FEEDBACK_EVAL_CASE_SCHEMA_V1,
        "status": "pending_review",
        "question": question,
        "expected_answer": _bounded_optional_text(row.get("expected_answer"), max_len=16_000),
        "reference_sources": reference_sources,
        "tags": tags[:30],
        "category": category,
        "category_source": _bounded_optional_text(row.get("category_source"), max_len=32),
        "query_hash": _optional_text(row.get("query_hash"), max_len=64) or _stable_query_hash(question),
        "retrieval_trace_ref": _bounded_optional_text(row.get("retrieval_trace_ref"), max_len=255),
        "retrieval_config_hash": _bounded_optional_text(retrieval.get("retrieval_config_hash"), max_len=128),
        "profile": _bounded_optional_text(row.get("profile"), max_len=64),
        "judge_score_ref": _bounded_optional_text(row.get("judge_score_ref"), max_len=255),
        "source_feedback_id": _feedback_id(row),
        "source_conversation_id": _lineage_id(row, "conversation_id"),
        "source_message_id": _lineage_id(row, "message_id"),
        "dataset_id": _lineage_id(row, "dataset_id"),
    }


def _rules_row(row: dict[str, Any], *, query: str) -> dict[str, Any]:
    trace = _retrieval_trace(row)
    citations = trace.get("citations")
    filenames: list[str] = []
    if isinstance(citations, list):
        for item in citations:
            if not isinstance(item, dict):
                continue
            name = _optional_text(
                item.get("filename") or item.get("document_name") or item.get("document_id"), max_len=200
            )
            if name:
                filenames.append(name)
    return {
        "interaction_id": _feedback_id(row),
        "original_query": query,
        "final_context_filenames": filenames[:20],
    }


def build_feedback_loop_candidates(
    rows: Sequence[Mapping[str, Any]],
    *,
    ruleset: IndustryRuleset | None = None,
    max_rating: int = 2,
    top_k: int = 10,
    max_hard_negatives: int = 10,
) -> dict[str, Any]:
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("Feedback rows must be mappings")
        normalized_rows.append(dict(row))
    negative_rows: list[dict[str, Any]] = []
    for row in normalized_rows:
        rating = _rating(row)
        if rating is not None and rating <= max_rating:
            negative_rows.append(row)

    hard_negative_records: list[dict[str, Any]] = []
    training_triples: list[dict[str, Any]] = []
    eval_case_candidates: list[dict[str, Any]] = []

    for row in negative_rows:
        eval_case = _build_eval_case_candidate(row)
        if eval_case is not None:
            eval_case_candidates.append(eval_case)
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
        if not mined["hard_negatives"]:
            continue
        fid = _feedback_id(row)
        if fid:
            mined["source_feedback_ids"] = [fid]
        ds = _lineage_id(row, "dataset_id")
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

    rules_rows = [_rules_row(row, query=query) for row in negative_rows if (query := _query(row))]
    rules_suggestions = build_ruleset_suggestions(rules_rows, ruleset=ruleset, top_k=top_k)

    return {
        "schema": FEEDBACK_LOOP_CANDIDATES_SCHEMA_V1,
        "summary": {
            "feedback_total": len(normalized_rows),
            "negative_feedback_total": len(negative_rows),
            "hard_negative_records": len(hard_negative_records),
            "training_triples": len(training_triples),
            "eval_case_candidates": len(eval_case_candidates),
            "rules_glossary_candidates": len(rules_suggestions["glossary_suggestions"]),
            "rules_pattern_candidates": len(rules_suggestions["pattern_suggestions"]),
            "rules_intent_candidates": len(rules_suggestions["intent_suggestions"]),
        },
        "hard_negative_records": hard_negative_records,
        "training_triples": training_triples,
        "eval_case_candidates": eval_case_candidates,
        "rules_suggestions": rules_suggestions,
    }


__all__ = [
    "FEEDBACK_LOOP_CANDIDATES_SCHEMA_V1",
    "FEEDBACK_TRAINING_TRIPLE_SCHEMA_V1",
    "FEEDBACK_EVAL_CASE_SCHEMA_V1",
    "build_feedback_loop_candidates",
]
