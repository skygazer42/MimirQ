#!/usr/bin/env python3
"""
Build a deterministic parse-repair schedule from parse-risk artifacts.
"""

import argparse
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _normalize_doc_id(raw: Any) -> str:
    return str(raw or "").strip()


def _risk_from_parse_quality_score(raw_score: Any) -> float:
    score = _coerce_float(raw_score, default=1.0)
    if score < 0.0:
        score = 0.0
    if score > 1.0:
        score = 1.0
    return round(1.0 - float(score), 6)


@dataclass
class Candidate:
    document_id: str
    risk_score: float = 0.0
    reasons: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)

    def merge(self, *, risk_score: float, reason: str, source: str) -> None:
        self.risk_score = max(float(self.risk_score), float(risk_score))
        if reason:
            self.reasons.add(str(reason))
        if source:
            self.sources.add(str(source))


def _record_candidate(
    bucket: dict[str, Candidate],
    *,
    document_id: Any,
    risk_score: float,
    reason: str,
    source: str,
) -> None:
    doc_id = _normalize_doc_id(document_id)
    if not doc_id:
        return
    row = bucket.get(doc_id)
    if row is None:
        row = Candidate(document_id=doc_id)
        bucket[doc_id] = row
    row.merge(risk_score=float(max(0.0, min(1.0, risk_score))), reason=reason, source=source)


def _collect_quality_documents(
    items: Any,
    *,
    reason: str,
    source_name: str,
    bucket: dict[str, Candidate],
) -> None:
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        _record_candidate(
            bucket,
            document_id=item.get("document_id"),
            risk_score=_risk_from_parse_quality_score(item.get("score")),
            reason=reason,
            source=source_name,
        )


def _collect_parse_risk_summary(
    value: Any,
    *,
    source_name: str,
    bucket: dict[str, Candidate],
) -> None:
    if not isinstance(value, dict):
        return
    _collect_quality_documents(
        value.get("top_low_quality_documents"),
        reason="parse_risk_summary_low_quality",
        source_name=source_name,
        bucket=bucket,
    )
    _collect_quality_documents(
        value.get("parse_risk_tail"),
        reason="parse_risk_tail",
        source_name=source_name,
        bucket=bucket,
    )


def _collect_tail_drift(
    value: Any,
    *,
    source_name: str,
    bucket: dict[str, Candidate],
) -> None:
    if not isinstance(value, dict):
        return
    added = value.get("added_document_ids")
    if not isinstance(added, list):
        return
    for document_id in added:
        _record_candidate(
            bucket,
            document_id=document_id,
            risk_score=1.0,
            reason="parse_risk_tail_added",
            source=source_name,
        )


def _collect_explicit_candidates(
    value: Any,
    *,
    source_name: str,
    bucket: dict[str, Candidate],
) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        if not isinstance(item, dict):
            continue
        risk = item.get("risk_score")
        if risk is None:
            risk = _risk_from_parse_quality_score(item.get("score"))
        _record_candidate(
            bucket,
            document_id=item.get("document_id"),
            risk_score=float(_coerce_float(risk, default=0.0)),
            reason=str(item.get("reason") or "candidate"),
            source=source_name,
        )


def _collect_from_object(
    obj: Any,
    *,
    source_name: str,
    bucket: dict[str, Candidate],
) -> None:
    if isinstance(obj, list):
        for item in obj:
            _collect_from_object(item, source_name=source_name, bucket=bucket)
        return
    if not isinstance(obj, dict):
        return

    _collect_parse_risk_summary(obj.get("parse_risk_summary"), source_name=source_name, bucket=bucket)
    _collect_tail_drift(obj.get("parse_risk_tail_drift"), source_name=source_name, bucket=bucket)
    _collect_explicit_candidates(obj.get("candidates"), source_name=source_name, bucket=bucket)


def build_parse_repair_schedule(
    *,
    inputs: list[Path],
    max_docs: int,
    min_risk_score: float,
) -> dict[str, Any]:
    max_docs = max(1, int(max_docs or 1))
    min_risk_score = max(0.0, min(1.0, float(min_risk_score)))

    bucket: dict[str, Candidate] = {}
    loaded_inputs: list[str] = []

    for path in inputs:
        raw = json.loads(path.read_text(encoding="utf-8"))
        loaded_inputs.append(str(path))
        _collect_from_object(raw, source_name=path.name, bucket=bucket)

    rows: list[Candidate] = [r for r in bucket.values() if float(r.risk_score) >= min_risk_score]
    rows.sort(key=lambda r: (-float(r.risk_score), r.document_id))
    rows = rows[:max_docs]

    actions: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        actions.append(
            {
                "rank": int(idx),
                "document_id": row.document_id,
                "risk_score": round(float(row.risk_score), 4),
                "priority": ("high" if row.risk_score >= 0.8 else "medium" if row.risk_score >= 0.5 else "low"),
                "reasons": sorted(row.reasons),
                "sources": sorted(row.sources),
                "action": "reparse_document",
            }
        )

    return {
        "schema": "mimirq.parse_repair_schedule.v1",
        "generated_at": _now_utc_iso(),
        "inputs": loaded_inputs,
        "policy": {
            "max_docs": int(max_docs),
            "min_risk_score": round(float(min_risk_score), 4),
        },
        "summary": {
            "candidates_seen": int(len(bucket)),
            "scheduled_documents": int(len(actions)),
        },
        "actions": actions,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Schedule parse-repair actions from risk artifacts.")
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="Input JSON artifact path. Can be set multiple times.",
    )
    parser.add_argument("--max-docs", type=int, default=100)
    parser.add_argument("--min-risk-score", type=float, default=0.0)
    parser.add_argument("--out", default="artifacts/parse_repair.schedule.json")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args(argv)

    inputs = [Path(p).expanduser().resolve() for p in (args.input or []) if str(p or "").strip()]
    if not inputs:
        raise SystemExit("--input is required at least once")
    missing = [str(p) for p in inputs if not p.exists()]
    if missing:
        raise SystemExit(f"input_not_found:{','.join(missing)}")

    payload = build_parse_repair_schedule(
        inputs=inputs,
        max_docs=max(1, int(args.max_docs or 1)),
        min_risk_score=float(args.min_risk_score),
    )

    out = Path(str(args.out)).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if bool(args.compact):
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
