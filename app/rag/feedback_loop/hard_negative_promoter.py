import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.rag.evaluation.generation.hard_negative_mining import HARD_NEGATIVES_SCHEMA_V1
from app.rag.feedback_loop.candidates import FEEDBACK_LOOP_CANDIDATES_SCHEMA_V1

FEEDBACK_HARD_NEGATIVE_EXPORT_SCHEMA_V1 = "mimirq.feedback_hard_negative_export.v1"
DEFAULT_FEEDBACK_HARD_NEGATIVE_JSONL_PATH = "./runs/feedback_loop/hard_negatives.jsonl"


def _validated_records(candidate_payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if not isinstance(candidate_payload, Mapping):
        raise TypeError("Feedback candidates must be a mapping")
    if candidate_payload.get("schema") != FEEDBACK_LOOP_CANDIDATES_SCHEMA_V1:
        raise ValueError("Invalid feedback candidate schema")
    raw = candidate_payload["hard_negative_records"]
    if not isinstance(raw, list):
        raise TypeError("Hard-negative records must be a list")
    records: list[Mapping[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise TypeError("Hard-negative records must be mappings")
        if item.get("schema") != HARD_NEGATIVES_SCHEMA_V1:
            raise ValueError("Invalid hard-negative record schema")
        query_hash = item["query_hash"]
        if not isinstance(query_hash, str) or not query_hash.strip():
            raise ValueError("Hard-negative query_hash must be a non-empty string")
        negatives = item["hard_negatives"]
        if not isinstance(negatives, list):
            raise TypeError("Hard negatives must be a list")
        for negative in negatives:
            if not isinstance(negative, Mapping):
                raise TypeError("Hard negatives must be mappings")
            chunk_id = negative["chunk_id"]
            if not isinstance(chunk_id, str) or not chunk_id.strip():
                raise ValueError("Hard-negative chunk_id must be a non-empty string")
        records.append(item)
    return records


def _clean_str_list(value: Any, *, max_items: int = 100) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("Feedback lineage identifiers must be a list")
    if max_items == 0:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise TypeError("Feedback lineage identifiers must be strings")
        text = item.strip()[:128]
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= max_items:
            break
    return out


def _export_record(record: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(record)
    out["schema"] = HARD_NEGATIVES_SCHEMA_V1
    out["source"] = "feedback_loop"
    out["source_feedback_ids"] = _clean_str_list(record.get("source_feedback_ids"))
    out["source_conversation_ids"] = _clean_str_list(record.get("source_conversation_ids"))
    out["source_message_ids"] = _clean_str_list(record.get("source_message_ids"))
    dataset_id = record.get("dataset_id")
    if dataset_id is not None:
        if not isinstance(dataset_id, str):
            raise TypeError("Feedback dataset_id must be a string")
        dataset_id = dataset_id.strip()[:128]
        if dataset_id:
            out["dataset_id"] = dataset_id
        else:
            out.pop("dataset_id", None)
    return out


def promote_hard_negatives_to_jsonl(
    candidate_payload: Mapping[str, Any],
    *,
    output_path: str | Path | None = None,
    append: bool = True,
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Export feedback-derived hard negatives to JSONL.

    This is intentionally file-only and reviewable. It does not trigger
    training, model promotion, or rule activation.
    """
    records = [_export_record(item) for item in _validated_records(candidate_payload)]
    lines = [
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        for record in records
    ]
    hard_negative_total = sum(len(item["hard_negatives"]) for item in records)
    if isinstance(output_path, str) and not output_path.strip():
        raise ValueError("Feedback output path must not be blank")
    path = Path(DEFAULT_FEEDBACK_HARD_NEGATIVE_JSONL_PATH if output_path is None else output_path)

    if not dry_run and records:
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with path.open(mode, encoding="utf-8") as fh:
            fh.writelines(f"{line}\n" for line in lines)

    return {
        "schema": FEEDBACK_HARD_NEGATIVE_EXPORT_SCHEMA_V1,
        "output_path": str(path),
        "append": bool(append),
        "dry_run": bool(dry_run),
        "candidate_records": len(records),
        "written_records": 0 if dry_run else len(records),
        "hard_negatives": hard_negative_total,
        "source_feedback_ids": sorted(
            {feedback_id for record in records for feedback_id in record["source_feedback_ids"]}
        ),
        "dataset_ids": sorted({record["dataset_id"] for record in records if record.get("dataset_id")}),
    }


__all__ = [
    "DEFAULT_FEEDBACK_HARD_NEGATIVE_JSONL_PATH",
    "FEEDBACK_HARD_NEGATIVE_EXPORT_SCHEMA_V1",
    "promote_hard_negatives_to_jsonl",
]
