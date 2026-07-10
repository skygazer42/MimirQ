#!/usr/bin/env python3
"""
Diff two RAG trace records from the metrics JSONL log.

Defaults are PII-safe:
- Uses `normalize_rag_trace_record` to drop any raw question/query/chunk snippets.
- Outputs only stable counters, modes, and config fingerprints.

Example:
  python scripts/rag_trace_diff.py --request-id-a <reqA> --request-id-b <reqB>
"""


import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _matches(record: dict[str, Any], args: argparse.Namespace, *, request_id: str) -> bool:
    if str(record.get("event") or "") != "rag_trace":
        return False
    if args.tenant_id and str(record.get("tenant_id") or "") != args.tenant_id:
        return False
    if args.conversation_id and str(record.get("conversation_id") or "") != args.conversation_id:
        return False
    if str(record.get("request_id") or "") != request_id:
        return False
    return True


def _read_latest_match(path: Path, args: argparse.Namespace, *, request_id: str) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_ts = -1
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = (line or "").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            if not _matches(obj, args, request_id=request_id):
                continue
            try:
                ts = int(obj.get("ts_ms") or 0)
            except Exception:
                ts = 0
            if ts >= best_ts:
                best_ts = ts
                best = obj
    return best


def main() -> int:
    p = argparse.ArgumentParser(description="Diff two rag_trace records from metrics JSONL.")
    p.add_argument(
        "--path",
        default="./logs/rag_metrics.jsonl",
        help="Metrics JSONL path (default: %(default)s)",
    )
    p.add_argument("--tenant-id", dest="tenant_id", default="", help="Filter by tenant_id (optional)")
    p.add_argument("--conversation-id", dest="conversation_id", default="", help="Filter by conversation_id (optional)")
    p.add_argument("--request-id-a", required=True, help="Request id A (required)")
    p.add_argument("--request-id-b", required=True, help="Request id B (required)")
    p.add_argument("--compact", action="store_true", help="Print compact one-line JSON.")
    args = p.parse_args()

    path = Path(str(args.path)).expanduser()
    if not path.exists():
        print(f"[rag_trace_diff] ERROR: file not found: {path}", file=sys.stderr)
        return 2

    req_a = str(args.request_id_a or "").strip()
    req_b = str(args.request_id_b or "").strip()
    if not req_a or not req_b:
        print("[rag_trace_diff] ERROR: request ids are required", file=sys.stderr)
        return 2
    if req_a == req_b:
        print("[rag_trace_diff] ERROR: request ids must be different", file=sys.stderr)
        return 2

    rec_a = _read_latest_match(path, args, request_id=req_a)
    rec_b = _read_latest_match(path, args, request_id=req_b)
    if not rec_a:
        print(f"[rag_trace_diff] ERROR: request_id_a not found: {req_a}", file=sys.stderr)
        return 3
    if not rec_b:
        print(f"[rag_trace_diff] ERROR: request_id_b not found: {req_b}", file=sys.stderr)
        return 3

    # Normalize to the PII-safe RagTrace shape used by the UI.
    from app.services.rag_trace_diff_service import diff_rag_traces  # noqa: WPS433
    from app.services.rag_trace_service import normalize_rag_trace_record  # noqa: WPS433

    trace_a = normalize_rag_trace_record(rec_a)
    trace_b = normalize_rag_trace_record(rec_b)
    diff = diff_rag_traces(trace_a, trace_b)

    if bool(args.compact):
        print(json.dumps(diff, ensure_ascii=False))
    else:
        print(json.dumps(diff, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

