
import json
from pathlib import Path
from typing import Any

from app.rag.evaluation.hard_negative_mining import HARD_NEGATIVES_SCHEMA_V1

FEEDBACK_HARD_NEGATIVE_EXPORT_SCHEMA_V1 = "mimirq.feedback_hard_negative_export.v1"
DEFAULT_FEEDBACK_HARD_NEGATIVE_JSONL_PATH = "./runs/feedback_loop/hard_negatives.jsonl"


def _safe_records(candidate_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(candidate_payload, dict):
        return []
    raw = candidate_payload.get("hard_negative_records") or []
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict) and item.get("schema") == HARD_NEGATIVES_SCHEMA_V1]


def _clean_str_list(value: Any, *, max_items: int = 100) -> list[str]:
    raw = value if isinstance(value, list) else []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text[:128])
        if len(out) >= max_items:
            break
    return out


def _export_record(record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    out["schema"] = HARD_NEGATIVES_SCHEMA_V1
    out["source"] = "feedback_loop"
    out["source_feedback_ids"] = _clean_str_list(record.get("source_feedback_ids"))
    out["source_conversation_ids"] = _clean_str_list(record.get("source_conversation_ids"))
    out["source_message_ids"] = _clean_str_list(record.get("source_message_ids"))
    dataset_id = str(record.get("dataset_id") or "").strip()
    if dataset_id:
        out["dataset_id"] = dataset_id[:128]
    return out


def promote_hard_negatives_to_jsonl(
    candidate_payload: dict[str, Any] | None,
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
    records = [_export_record(item) for item in _safe_records(candidate_payload)]
    hard_negative_total = sum(
        len(item.get("hard_negatives") or []) for item in records if isinstance(item.get("hard_negatives"), list)
    )
    path = Path(output_path or DEFAULT_FEEDBACK_HARD_NEGATIVE_JSONL_PATH)

    if not dry_run and records:
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with path.open(mode, encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                fh.write("\n")

    return {
        "schema": FEEDBACK_HARD_NEGATIVE_EXPORT_SCHEMA_V1,
        "output_path": str(path),
        "append": bool(append),
        "dry_run": bool(dry_run),
        "candidate_records": int(len(records)),
        "written_records": 0 if dry_run else int(len(records)),
        "hard_negatives": int(hard_negative_total),
        "source_feedback_ids": sorted({fid for record in records for fid in _clean_str_list(record.get("source_feedback_ids"))}),
        "dataset_ids": sorted({str(record.get("dataset_id")) for record in records if record.get("dataset_id")}),
    }


__all__ = [
    "DEFAULT_FEEDBACK_HARD_NEGATIVE_JSONL_PATH",
    "FEEDBACK_HARD_NEGATIVE_EXPORT_SCHEMA_V1",
    "promote_hard_negatives_to_jsonl",
]
