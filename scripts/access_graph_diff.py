#!/usr/bin/env python3
"""
Diff two access-graph exports and output a bounded, PII-safe change summary.

Inputs:
- NDJSON from `/api/v1/audit/access-graph/export?export_format=ndjson`
- JSON from `/api/v1/audit/access-graph/export?export_format=json`
- Optional gzip-compressed files (`.gz`)

Defaults are safe:
- Never prints raw `user_id` / `account_id` / `name` fields even if they exist in the input.
- Output is bounded (`--max-examples`) and intended for access reviews.

Examples:
  python scripts/access_graph_diff.py --a runs/access-graph-a.ndjson --b runs/access-graph-b.ndjson
  python scripts/access_graph_diff.py --a a.json.gz --b b.json.gz --compact > diff.json
"""


import argparse
import gzip
import json
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path so `import app` works when invoked as:
#   python scripts/access_graph_diff.py ...
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.services.access_graph_diff_service import diff_access_graph_records  # noqa: E402


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _open_text(path: Path):  # noqa: ANN202
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def _iter_non_empty_lines(path: Path) -> Iterable[str]:
    with _open_text(path) as f:
        for line in f:
            s = (line or "").strip()
            if s:
                yield s


def _read_records_json(path: Path) -> list[dict[str, Any]] | None:
    try:
        with _open_text(path) as f:
            payload = json.load(f)
    except Exception:
        return None

    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return [it for it in items if isinstance(it, dict)]
        # Single-record JSON.
        if payload.get("kind"):
            return [payload]
        return []
    if isinstance(payload, list):
        return [it for it in payload if isinstance(it, dict)]
    return []


def _read_records_ndjson(path: Path, *, max_records: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in _iter_non_empty_lines(path):
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        out.append(obj)
        if len(out) >= max_records:
            break
    return out


def _read_records(path: Path, *, max_records: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Return (records, meta) where meta describes parsing/truncation.
    """
    max_records = max(1, int(max_records or 0))

    # Heuristic: try JSON first (single JSON object/page), fall back to NDJSON.
    records_json = _read_records_json(path)
    if records_json is not None:
        truncated = len(records_json) > max_records
        return records_json[:max_records], {
            "format": "json",
            "returned": int(min(len(records_json), max_records)),
            "truncated": bool(truncated),
        }

    records = _read_records_ndjson(path, max_records=max_records)
    return records, {
        "format": "ndjson",
        "returned": int(len(records)),
        "truncated": bool(len(records) >= max_records),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="PII-safe diff of two access-graph exports.")
    p.add_argument("--a", required=True, help="Access-graph export A (ndjson/json, optionally .gz)")
    p.add_argument("--b", required=True, help="Access-graph export B (ndjson/json, optionally .gz)")
    p.add_argument("--max-records", type=int, default=200_000, help="Max records to read from each input (default: 200000)")
    p.add_argument("--max-examples", type=int, default=20, help="Max example items to include per category (default: 20)")
    p.add_argument("--compact", action="store_true", help="Print compact one-line JSON.")
    args = p.parse_args(argv)

    path_a = Path(str(args.a)).expanduser()
    path_b = Path(str(args.b)).expanduser()
    if not path_a.exists():
        print(f"[access_graph_diff] ERROR: file not found: {path_a}", file=sys.stderr)
        return 2
    if not path_b.exists():
        print(f"[access_graph_diff] ERROR: file not found: {path_b}", file=sys.stderr)
        return 2

    records_a, meta_a = _read_records(path_a, max_records=int(args.max_records or 0))
    records_b, meta_b = _read_records(path_b, max_records=int(args.max_records or 0))

    diff = diff_access_graph_records(records_a, records_b, max_examples=int(args.max_examples or 0))
    payload = {
        "schema": "mimirq.access_graph_diff_cli.v1",
        "generated_at": _now_utc().isoformat(),
        "inputs": {
            "a": {"path": str(path_a), **meta_a},
            "b": {"path": str(path_b), **meta_b},
        },
        "diff": diff,
    }

    if bool(args.compact):
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

