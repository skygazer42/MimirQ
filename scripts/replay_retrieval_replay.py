#!/usr/bin/env python3
"""
Deterministic offline replay runner for retrieval-only Evidence API requests.

Inputs:
- `--captures`: JSONL produced by scripts/capture_retrieval_replay.py (PII-safe)
- `--cases`: regression cases bundle providing raw queries (kept local / CI fixture)

Outputs:
- Summary to stderr
- Optional JSON report for CI artifacts
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from app.rag.core.hashing import stable_hash
from app.rag.evaluation.replay_capture import (
    RETRIEVAL_REPLAY_CAPTURE_SCHEMA_V1,
    fingerprint_citations,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _headers(args: argparse.Namespace) -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if args.tenant_id:
        h["X-Tenant-ID"] = str(args.tenant_id)
    if args.user_id:
        h["X-User-ID"] = str(args.user_id)
    if args.bearer:
        h["Authorization"] = f"Bearer {args.bearer}"
    return h


def coerce_case_bundle(obj: Any) -> tuple[str, list[dict[str, Any]]]:
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


def _build_case_lookup(items: list[dict[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        q = str(it.get("question") or it.get("query") or "").strip()
        if not q:
            continue
        lookup.setdefault(stable_hash(q, length=16), q)
    return lookup


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay Evidence API captures deterministically.")
    p.add_argument("--captures", required=True, help="Path to capture JSONL (mimirq.retrieval_replay_capture.v1)")
    p.add_argument("--cases", required=True, help="Path to regression cases bundle (provides raw queries)")
    p.add_argument("--out-json", default="", help="Optional: write replay report JSON to this path")

    p.add_argument("--base-url", default="http://localhost:8000/api/v1", help="API base URL (default: %(default)s)")
    p.add_argument("--tenant-id", default="", help="Tenant id (X-Tenant-ID header)")
    p.add_argument("--user-id", default="", help="User id (X-User-ID header, for AUTH_MODE=header)")
    p.add_argument("--bearer", default="", help="Bearer token (Authorization: Bearer ...)")
    p.add_argument("--timeout-sec", type=float, default=30.0, help="HTTP timeout seconds (default: %(default)s)")
    p.add_argument("--max-items", type=int, default=0, help="Limit records replayed (default: all)")
    args = p.parse_args(argv)

    captures_path = Path(args.captures)
    cases_path = Path(args.cases)
    if not captures_path.exists():
        print(f"[replay-runner] ERROR: captures file not found: {captures_path}", file=sys.stderr)
        return 2
    if not cases_path.exists():
        print(f"[replay-runner] ERROR: cases file not found: {cases_path}", file=sys.stderr)
        return 2

    try:
        raw = _load_json(cases_path)
        dataset_id, items = coerce_case_bundle(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"[replay-runner] ERROR: failed to parse cases: {str(exc)[:200]}", file=sys.stderr)
        return 2

    case_lookup = _build_case_lookup(items)
    if not case_lookup:
        print("[replay-runner] ERROR: produced zero case questions (missing questions?)", file=sys.stderr)
        return 2

    url = str(args.base_url).rstrip("/") + "/rag/retrieve"
    timeout = httpx.Timeout(float(args.timeout_sec or 30.0))

    totals = {"records": 0, "matched": 0, "mismatched": 0, "skipped": 0, "errors": 0}
    mismatches: list[dict[str, Any]] = []

    t0 = time.monotonic()
    with httpx.Client(timeout=timeout) as client, captures_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if args.max_items and totals["records"] >= int(args.max_items):
                break
            line = (line or "").strip()
            if not line:
                continue
            totals["records"] += 1
            try:
                rec = json.loads(line)
            except Exception:
                totals["skipped"] += 1
                continue
            if not isinstance(rec, dict) or str(rec.get("schema") or "") != RETRIEVAL_REPLAY_CAPTURE_SCHEMA_V1:
                totals["skipped"] += 1
                continue

            qh = str(rec.get("query_hash") or "").strip()
            if not qh:
                totals["skipped"] += 1
                continue
            query = case_lookup.get(qh)
            if not query:
                totals["skipped"] += 1
                continue

            rag_config = rec.get("rag_config") if isinstance(rec.get("rag_config"), dict) else {}
            seed = rec.get("seed")
            try:
                seed_int = int(seed) if seed is not None else None
            except Exception:
                seed_int = None

            body = {
                "query": query,
                "history": [],
                "dataset_id": str(dataset_id),
                "document_ids": [],
                "rag_config": dict(rag_config),
                "seed": seed_int,
            }

            try:
                resp = client.post(url, headers=_headers(args), json=body)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001
                totals["errors"] += 1
                mismatches.append({"query_hash": qh, "kind": "http_error", "error": str(exc)[:200]})
                continue

            if not isinstance(payload, dict):
                totals["errors"] += 1
                mismatches.append({"query_hash": qh, "kind": "bad_payload"})
                continue

            fp_expected = str(rec.get("citations_fingerprint") or "").strip()
            fp_actual = fingerprint_citations(payload.get("citations"))
            cfg_expected = str(rec.get("retrieval_config_hash") or "").strip() or None
            cfg_actual = None
            metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
            if isinstance(metrics, dict):
                cfg_actual = str(metrics.get("retrieval_config_hash") or "").strip() or None

            ok = bool(fp_expected) and fp_actual == fp_expected and (cfg_expected is None or cfg_actual == cfg_expected)
            if ok:
                totals["matched"] += 1
                continue

            totals["mismatched"] += 1
            mismatch = {
                "query_hash": qh,
                "retrieval_config_hash_expected": cfg_expected,
                "retrieval_config_hash_actual": cfg_actual,
                "fingerprint_expected": fp_expected,
                "fingerprint_actual": fp_actual,
            }
            mismatches.append(mismatch)

    elapsed = round(float(time.monotonic() - t0), 3)
    report = {
        "schema": "mimirq.retrieval_replay_report.v1",
        "dataset_id": str(dataset_id),
        "totals": totals,
        "elapsed_sec": elapsed,
        "mismatches": mismatches[:50],
    }

    if args.out_json:
        Path(args.out_json).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        "[replay-runner] OK"
        f" records={totals['records']}"
        f" matched={totals['matched']}"
        f" mismatched={totals['mismatched']}"
        f" skipped={totals['skipped']}"
        f" errors={totals['errors']}"
        f" elapsed_sec={elapsed}",
        file=sys.stderr,
    )

    # CI-friendly: non-zero exit when mismatches or errors exist.
    if totals["mismatched"] or totals["errors"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
