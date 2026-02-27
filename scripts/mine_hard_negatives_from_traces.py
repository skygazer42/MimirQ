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

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.rag.core.hashing import stable_hash
from app.rag.evaluation.hard_negative_mining import mine_hard_negatives_for_case_from_trace


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


def _iter_trace_records(path: Path, *, max_records: int = 0) -> list[dict[str, Any]]:
    """
    Return a list of parsed rag_trace JSON objects (best-effort).

    Note: This keeps memory bounded via max_records (0=unbounded, but not recommended).
    """
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if max_records and len(out) >= int(max_records):
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
            out.append(obj)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Mine PII-safe hard negatives from rag_trace bundles.")
    p.add_argument("--cases", required=True, help="Path to regression cases JSON (bundle v1 or legacy array)")
    p.add_argument("--traces", required=True, help="Path to metrics JSONL containing rag_trace events")
    p.add_argument("--out", required=True, help="Write mined hard negatives JSONL to this path")

    p.add_argument("--retrieval-config-hash", default="", help="Only use trace records matching this retrieval_config_hash (optional)")
    p.add_argument("--max-cases", type=int, default=0, help="Limit cases processed (default: all)")
    p.add_argument("--max-traces", type=int, default=0, help="Limit trace records read (default: all)")
    p.add_argument("--max-hard-negatives", type=int, default=10, help="Hard negatives per case (default: %(default)s)")
    p.add_argument("--max-negatives-per-document", type=int, default=2, help="Cap negatives per document_id (default: %(default)s)")

    args = p.parse_args(argv)

    cases_path = Path(args.cases)
    traces_path = Path(args.traces)
    out_path = Path(args.out)

    if not cases_path.exists():
        print(f"[hard-negatives] ERROR: cases file not found: {cases_path}", file=sys.stderr)
        return 2
    if not traces_path.exists():
        print(f"[hard-negatives] ERROR: traces file not found: {traces_path}", file=sys.stderr)
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

    traces = _iter_trace_records(traces_path, max_records=int(args.max_traces or 0))

    # Index traces by question_hash (preferred) or query_hash.
    want_cfg = str(args.retrieval_config_hash or "").strip() or None
    trace_by_hash: dict[str, dict[str, Any]] = {}
    matched_traces = 0
    for rec in traces:
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

        # Prefer the latest record (keep overwriting).
        trace_by_hash[qh] = rec
        matched_traces += 1

    rows: list[dict[str, Any]] = []
    used = 0
    skipped = 0
    for qh, case in target_hashes.items():
        trace = trace_by_hash.get(qh)
        if trace is None:
            skipped += 1
            continue
        rec = mine_hard_negatives_for_case_from_trace(
            case=case,
            trace_record=trace,
            query_hash=qh,
            max_hard_negatives=int(args.max_hard_negatives or 0),
            max_negatives_per_document=int(args.max_negatives_per_document or 0),
        )
        hard = rec.get("hard_negatives") or []
        if not isinstance(hard, list) or not hard:
            skipped += 1
            continue
        rows.append(rec)
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
        f" traces_total={len(traces)}"
        f" traces_matched={matched_traces}"
        f" out={out_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

