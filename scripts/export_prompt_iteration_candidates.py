
import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _group_key(row: dict[str, Any]) -> str:
    tags = [str(tag or "").strip() for tag in (row.get("tags") or []) if str(tag or "").strip()]
    if tags:
        return tags[0]
    reason = str(row.get("reason") or "").strip()
    if "知识库" in reason or "型号" in reason or "未收录" in reason:
        return "out_of_scope"
    return "answer_wrong"


def _suggested_action(group_key: str) -> str:
    if group_key == "out_of_scope":
        return "strengthen_out_of_scope_refusal_language"
    return "tighten_stepwise_grounded_answering"


def export_prompt_iteration_candidates(*, feedback_rows: list[dict[str, Any]]) -> dict[str, Any]:
    negative_rows = [
        row for row in (feedback_rows or [])
        if isinstance(row, dict) and int(row.get("rating") or 0) <= 2
    ]
    counts: Counter[str] = Counter(_group_key(row) for row in negative_rows)
    groups: list[dict[str, Any]] = []
    for group_key, count in counts.most_common():
        samples = []
        for row in negative_rows:
            if _group_key(row) != group_key:
                continue
            message = row.get("message") if isinstance(row.get("message"), dict) else {}
            metadata = message.get("message_metadata") if isinstance(message.get("message_metadata"), dict) else {}
            rag_snapshot = row.get("extra") if isinstance(row.get("extra"), dict) else {}
            samples.append(
                {
                    "reason": str(row.get("reason") or "").strip(),
                    "rewritten_query": str(metadata.get("rewritten_query") or "").strip() or None,
                    "retrieval_mode": (
                        str((rag_snapshot.get("rag_config_snapshot") or {}).get("retrieval_mode") or "").strip() or None
                        if isinstance(rag_snapshot.get("rag_config_snapshot"), dict)
                        else None
                    ),
                }
            )
            if len(samples) >= 3:
                break
        groups.append(
            {
                "group_key": group_key,
                "count": int(count),
                "suggested_prompt_action": _suggested_action(group_key),
                "samples": samples,
            }
        )

    return {
        "schema": "mimirq.prompt_iteration_candidates.v1",
        "summary": {
            "negative_feedback_count": int(len(negative_rows)),
            "groups_count": int(len(groups)),
        },
        "groups": groups,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export feedback-driven prompt iteration candidates.")
    parser.add_argument("--feedback-json", required=True, help="Path to feedback JSON list.")
    parser.add_argument("--out", required=True, help="Output JSON path.")
    args = parser.parse_args(argv)

    rows = _read_json(Path(args.feedback_json))
    payload = export_prompt_iteration_candidates(feedback_rows=rows)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
