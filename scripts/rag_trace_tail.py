#!/usr/bin/env python3
"""
Tail and pretty-print RAG trace records from the metrics JSONL log.

Defaults are PII-safe:
- hides raw question/query text
- hides chunk snippets (chunk_content)

Use --include-text if you explicitly want to print raw text fields.
"""


import argparse
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any


def _strip_text_fields(record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    out.pop("question", None)
    out.pop("query_for_retrieval", None)

    citations = out.get("citations")
    if isinstance(citations, list):
        safe: list[dict[str, Any]] = []
        for c in citations:
            if not isinstance(c, dict):
                continue
            d = dict(c)
            d.pop("chunk_content", None)
            safe.append(d)
        out["citations"] = safe

    return out


def _matches(record: dict[str, Any], args: argparse.Namespace) -> bool:
    if str(record.get("event") or "") != "rag_trace":
        return False
    if args.tenant_id and str(record.get("tenant_id") or "") != args.tenant_id:
        return False
    if args.conversation_id and str(record.get("conversation_id") or "") != args.conversation_id:
        return False
    if args.request_id and str(record.get("request_id") or "") != args.request_id:
        return False
    return True


def main() -> int:
    p = argparse.ArgumentParser(description="Tail RAG trace records from metrics JSONL.")
    p.add_argument(
        "--path",
        default="./logs/rag_metrics.jsonl",
        help="Metrics JSONL path (default: %(default)s)",
    )
    p.add_argument("--tenant-id", default="", help="Filter by tenant_id (optional)")
    p.add_argument("--conversation-id", default="", help="Filter by conversation_id (optional)")
    p.add_argument("--request-id", default="", help="Filter by request_id (optional)")
    p.add_argument("--limit", type=int, default=5, help="Max records to print (default: %(default)s)")
    p.add_argument("--include-text", action="store_true", help="Print raw question/query/chunk snippets (PII risk).")
    p.add_argument("--compact", action="store_true", help="Print compact one-line JSON per record.")
    args = p.parse_args()

    limit = max(1, min(int(args.limit or 0), 200))
    path = Path(str(args.path)).expanduser()
    if not path.exists():
        print(f"[rag_trace_tail] ERROR: file not found: {path}", file=sys.stderr)
        return 2

    out = deque(maxlen=limit)

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
            if _matches(obj, args):
                out.append(obj)

    for rec in out:
        payload = rec if bool(args.include_text) else _strip_text_fields(rec)
        if args.compact:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

