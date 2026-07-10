#!/usr/bin/env python3
"""
Mine PII-safe hard negatives (near-miss citations above first positive) from rag_trace bundles.

Inputs:
- Regression cases bundle (mimirq.regression_cases.v1 or legacy shapes) provides:
  - question (raw, kept only in-memory)
  - reference_sources.chunk_id (ground truth)
- Trace bundle (metrics JSONL, rag_trace events) provides:
  - question_hash/query_hash
  - retrieval.retrieval_config_hash
  - citations[] with identifiers + scores (PII-safe by default)

Output:
- JSONL with schema mimirq.hard_negatives.v1
- PII-safe by construction: NO raw query text is written.
"""


import argparse
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.rag.core.hashing import stable_hash
from app.rag.evaluation.hard_negative_mining import (
    merge_hard_negative_records,
    mine_hard_negatives_for_case_from_trace,
)


def _load_json(path: Path) -> Any:
    # PowerShell commonly writes UTF-8 JSON with BOM; `utf-8-sig` handles both BOM/no-BOM.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def coerce_case_bundle(obj: Any) -> tuple[str, list[dict[str, Any]]]:
    """
    Normalize case bundle payloads into: (dataset_id, items[]).

    Supported shapes:
    - Export bundle v1: {"schema":"mimirq.regression_cases.v1","dataset_id":"...","items":[...]}
    - Minimal bundle: {"dataset_id":"...","items":[...]}
    - Legacy: [{"dataset_id":"...","question":"...","reference_sources":[...], ...}, ...]
    """
    if isinstance(obj, dict) and isinstance(obj.get("items"), list):
        ds = str(obj.get("dataset_id") or "").strip()
        if ds:
            items = [x for x in obj.get("items") if isinstance(x, dict)]
            cleaned = [{k: v for k, v in it.items() if k != "dataset_id"} for it in items]
            return ds, cleaned
        return coerce_case_bundle(list(obj.get("items") or []))

    if isinstance(obj, list):
        items = [x for x in obj if isinstance(x, dict)]
        dsids: list[str] = []
        for it in items:
            ds = str(it.get("dataset_id") or "").strip()
            if ds and ds not in dsids:
                dsids.append(ds)
        if not dsids:
            raise ValueError("dataset_id is required in cases bundle")
        if len(dsids) > 1:
            raise ValueError("mixed dataset_id in cases bundle")
        dsid = dsids[0]
        cleaned = [{k: v for k, v in it.items() if k != "dataset_id"} for it in items]
        return dsid, cleaned

    raise ValueError("cases file must be a JSON array, or an object with { dataset_id, items: [...] }")


def _iter_trace_records(path: Path, *, max_records: int = 0) -> Iterator[dict[str, Any]]:
    """
    Yield parsed rag_trace JSON objects (best-effort).

    Note: This keeps memory bounded (streams the file) and supports max_records.
    """
    with path.open("r", encoding="utf-8", errors="replace") as f:
        emitted = 0
        for line in f:
            if max_records and emitted >= int(max_records):
                break
            line = (line or "").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            if str(obj.get("event") or "") != "rag_trace":
                continue
            yield obj
            emitted += 1


def _iter_feedback_event_rows(path: Path, *, max_records: int = 0) -> Iterator[dict[str, Any]]:
    """
    Yield parsed feedback/training export rows from JSONL (best-effort).

    Supported row shapes:
    - mimirq.training_export_row.v1 (feedback source rows)
    - lightweight custom rows containing {question, reference_sources, trace_snapshot}
    """
    with path.open("r", encoding="utf-8", errors="replace") as f:
        emitted = 0
        for line in f:
            if max_records and emitted >= int(max_records):
                break
            line = (line or "").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            yield obj
            emitted += 1


def _feedback_row_to_trace_record(row: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(row, dict):
        return None
    question = str(row.get("question") or row.get("query") or "").strip()
    if not question:
        return None
    trace = row.get("trace_snapshot")
    if not isinstance(trace, dict):
        extra = row.get("extra")
        if isinstance(extra, dict):
            trace = extra.get("retrieval_trace")
    if not isinstance(trace, dict):
        return None

    record = dict(trace)
    qh = str(record.get("question_hash") or record.get("query_hash") or row.get("question_hash") or "").strip()
    if not qh:
        qh = stable_hash(question, length=16)
    record.setdefault("question_hash", qh)
    record.setdefault("event", "rag_trace")

    if not isinstance(record.get("citations"), list):
        citations = row.get("citations")
        if isinstance(citations, list):
            record["citations"] = citations

    return qh, record


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Mine PII-safe hard negatives from rag_trace bundles.")
    p.add_argument("--cases", required=True, help="Path to regression cases JSON (bundle v1 or legacy array)")
    p.add_argument("--traces", required=True, help="Path to metrics JSONL containing rag_trace events")
    p.add_argument(
        "--feedback-events",
        default="",
        help=(
            "Optional JSONL with feedback/training rows (e.g. mimirq.training_export_row.v1) "
            "that include trace_snapshot citations; mined negatives are merged with trace JSONL results."
        ),
    )
    p.add_argument("--out", required=True, help="Write mined hard negatives JSONL to this path")

    p.add_argument("--retrieval-config-hash", default="", help="Only use trace records matching this retrieval_config_hash (optional)")
    p.add_argument("--tenant-id", default="", help="Only use trace records matching this tenant_id (optional)")
    p.add_argument("--max-cases", type=int, default=0, help="Limit cases processed (default: all)")
    p.add_argument("--max-traces", type=int, default=0, help="Limit trace records read (default: all)")
    p.add_argument("--max-hard-negatives", type=int, default=10, help="Hard negatives per case (default: %(default)s)")
    p.add_argument("--max-negatives-per-document", type=int, default=2, help="Cap negatives per document_id (default: %(default)s)")

    args = p.parse_args(argv)

    cases_path = Path(args.cases)
    traces_path = Path(args.traces)
    feedback_events_path = Path(str(args.feedback_events)) if str(args.feedback_events or "").strip() else None
    out_path = Path(args.out)

    if not cases_path.exists():
        print(f"[hard-negatives] ERROR: cases file not found: {cases_path}", file=sys.stderr)
        return 2
    if not traces_path.exists():
        print(f"[hard-negatives] ERROR: traces file not found: {traces_path}", file=sys.stderr)
        return 2
    if feedback_events_path is not None and not feedback_events_path.exists():
        print(f"[hard-negatives] ERROR: feedback events file not found: {feedback_events_path}", file=sys.stderr)
        return 2

    try:
        raw_cases = _load_json(cases_path)
        _dataset_id, items = coerce_case_bundle(raw_cases)
    except Exception as exc:  # noqa: BLE001
        print(f"[hard-negatives] ERROR: failed to parse cases: {str(exc)[:200]}", file=sys.stderr)
        return 2

    if args.max_cases and int(args.max_cases) > 0:
        items = list(items)[: int(args.max_cases)]

    target_hashes: dict[str, dict[str, Any]] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        q = str(it.get("question") or it.get("query") or "").strip()
        if not q:
            continue
        target_hashes[stable_hash(q, length=16)] = it

    if not target_hashes:
        print("[hard-negatives] ERROR: produced zero case hashes (missing questions?)", file=sys.stderr)
        return 2

    # Index traces by question_hash (preferred) or query_hash.
    want_cfg = str(args.retrieval_config_hash or "").strip() or None
    want_tenant = str(args.tenant_id or "").strip() or None
    traces_by_hash: dict[str, list[dict[str, Any]]] = {}
    matched_traces = 0
    traces_total = 0
    for rec in _iter_trace_records(traces_path, max_records=int(args.max_traces or 0)):
        traces_total += 1

        if want_tenant:
            tid = str(rec.get("tenant_id") or "").strip()
            if not tid or tid != want_tenant:
                continue

        qh = str(rec.get("question_hash") or rec.get("query_hash") or "").strip()
        if not qh or qh not in target_hashes:
            continue

        if want_cfg:
            cfg = ""
            retrieval = rec.get("retrieval")
            if isinstance(retrieval, dict):
                cfg = str(retrieval.get("retrieval_config_hash") or "").strip()
            if cfg != want_cfg:
                continue

        traces_by_hash.setdefault(qh, []).append(rec)
        matched_traces += 1

    feedback_total = 0
    feedback_matched = 0
    if feedback_events_path is not None:
        for row in _iter_feedback_event_rows(feedback_events_path, max_records=int(args.max_traces or 0)):
            feedback_total += 1
            transformed = _feedback_row_to_trace_record(row)
            if transformed is None:
                continue
            qh, rec = transformed
            if not qh or qh not in target_hashes:
                continue

            if want_tenant:
                tenant_candidates = [
                    rec.get("tenant_id"),
                    row.get("tenant_id"),
                    (row.get("source_metadata") or {}).get("tenant_id") if isinstance(row.get("source_metadata"), dict) else None,
                ]
                tenant_hit = False
                for raw_tenant in tenant_candidates:
                    if str(raw_tenant or "").strip() == want_tenant:
                        tenant_hit = True
                        break
                if not tenant_hit:
                    continue

            if want_cfg:
                cfg = ""
                retrieval = rec.get("retrieval")
                if isinstance(retrieval, dict):
                    cfg = str(retrieval.get("retrieval_config_hash") or "").strip()
                if not cfg:
                    cfg = str(rec.get("retrieval_config_hash") or "").strip()
                if cfg != want_cfg:
                    continue

            traces_by_hash.setdefault(qh, []).append(rec)
            feedback_matched += 1

    rows: list[dict[str, Any]] = []
    used = 0
    skipped = 0
    for qh, case in target_hashes.items():
        trace_records = traces_by_hash.get(qh) or []
        if not trace_records:
            skipped += 1
            continue

        mined_rows: list[dict[str, Any]] = []
        for trace in trace_records:
            rec = mine_hard_negatives_for_case_from_trace(
                case=case,
                trace_record=trace,
                query_hash=qh,
                max_hard_negatives=int(args.max_hard_negatives or 0),
                max_negatives_per_document=int(args.max_negatives_per_document or 0),
            )
            hard = rec.get("hard_negatives") or []
            if isinstance(hard, list) and hard:
                mined_rows.append(rec)

        if not mined_rows:
            skipped += 1
            continue

        rows.append(
            merge_hard_negative_records(
                records=mined_rows,
                max_hard_negatives=int(args.max_hard_negatives or 0),
            )
        )
        used += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(
        "[hard-negatives] OK"
        f" cases_total={len(target_hashes)}"
        f" cases_used={used}"
        f" cases_skipped={skipped}"
        f" traces_total={traces_total}"
        f" traces_matched={matched_traces}"
        f" feedback_events_total={feedback_total}"
        f" feedback_events_matched={feedback_matched}"
        f" out={out_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
