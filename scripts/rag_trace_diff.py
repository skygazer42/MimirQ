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


def _read_latest_matches(path: Path, args: argparse.Namespace, *, request_ids: set[str]) -> dict[str, dict[str, Any]]:
    latest: dict[str, tuple[int, dict[str, Any]]] = {}
    with path.open("r", encoding="utf-8", errors="replace") as records:
        for line in records:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if not isinstance(record, dict) or record.get("event") != "rag_trace":
                continue
            request_id = str(record.get("request_id") or "")
            if request_id not in request_ids:
                continue
            if args.tenant_id and str(record.get("tenant_id") or "") != args.tenant_id:
                continue
            if args.conversation_id and str(record.get("conversation_id") or "") != args.conversation_id:
                continue
            try:
                timestamp = int(record.get("ts_ms", 0))
            except (TypeError, ValueError, OverflowError):
                timestamp = 0
            previous = latest.get(request_id)
            if timestamp >= (previous[0] if previous is not None else -1):
                latest[request_id] = timestamp, record
    return {request_id: record for request_id, (_, record) in latest.items()}


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

    path = Path(args.path).expanduser()
    if not path.exists():
        print(f"[rag_trace_diff] ERROR: file not found: {path}", file=sys.stderr)
        return 2

    req_a = args.request_id_a.strip()
    req_b = args.request_id_b.strip()
    if not req_a or not req_b:
        print("[rag_trace_diff] ERROR: request ids are required", file=sys.stderr)
        return 2
    if req_a == req_b:
        print("[rag_trace_diff] ERROR: request ids must be different", file=sys.stderr)
        return 2

    matches = _read_latest_matches(path, args, request_ids={req_a, req_b})
    if req_a not in matches:
        print(f"[rag_trace_diff] ERROR: request_id_a not found: {req_a}", file=sys.stderr)
        return 3
    if req_b not in matches:
        print(f"[rag_trace_diff] ERROR: request_id_b not found: {req_b}", file=sys.stderr)
        return 3

    # Normalize to the PII-safe RagTrace shape used by the UI.
    from app.services.observability.rag_trace_diff import diff_rag_traces  # noqa: WPS433
    from app.services.observability.rag_traces import normalize_rag_trace_record  # noqa: WPS433

    trace_a = normalize_rag_trace_record(matches[req_a])
    trace_b = normalize_rag_trace_record(matches[req_b])
    diff = diff_rag_traces(trace_a, trace_b)

    if args.compact:
        print(json.dumps(diff, ensure_ascii=False))
    else:
        print(json.dumps(diff, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
