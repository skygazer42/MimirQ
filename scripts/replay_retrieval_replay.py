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


def _build_parser() -> argparse.ArgumentParser:
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
    return p


def _capture_context(line: str, case_lookup: dict[str, str]) -> tuple[dict[str, Any], str, str] | None:
    try:
        record = json.loads(line)
    except Exception:
        return None
    if not isinstance(record, dict) or str(record.get("schema") or "") != RETRIEVAL_REPLAY_CAPTURE_SCHEMA_V1:
        return None
    query_hash = str(record.get("query_hash") or "").strip()
    query = case_lookup.get(query_hash)
    if not query_hash or not query:
        return None
    return record, query_hash, query


def _seed_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except Exception:
        return None


def _request_body(record: dict[str, Any], *, dataset_id: str, query: str) -> dict[str, Any]:
    rag_config = record.get("rag_config") if isinstance(record.get("rag_config"), dict) else {}
    return {
        "query": query,
        "history": [],
        "dataset_id": dataset_id,
        "document_ids": [],
        "rag_config": dict(rag_config),
        "seed": _seed_int(record.get("seed")),
    }


def _post_retrieval(
    client: httpx.Client,
    *,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    query_hash: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        response = client.post(url, headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        return None, {"query_hash": query_hash, "kind": "http_error", "error": str(exc)[:200]}
    if not isinstance(payload, dict):
        return None, {"query_hash": query_hash, "kind": "bad_payload"}
    return payload, None


def _compare_capture(
    record: dict[str, Any],
    payload: dict[str, Any],
    *,
    query_hash: str,
) -> tuple[bool, dict[str, Any]]:
    fingerprint_expected = str(record.get("citations_fingerprint") or "").strip()
    fingerprint_actual = fingerprint_citations(payload.get("citations"))
    config_expected = str(record.get("retrieval_config_hash") or "").strip() or None
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    config_actual = str(metrics.get("retrieval_config_hash") or "").strip() or None
    matched = bool(fingerprint_expected) and fingerprint_actual == fingerprint_expected
    matched = matched and (config_expected is None or config_actual == config_expected)
    mismatch = {
        "query_hash": query_hash,
        "retrieval_config_hash_expected": config_expected,
        "retrieval_config_hash_actual": config_actual,
        "fingerprint_expected": fingerprint_expected,
        "fingerprint_actual": fingerprint_actual,
    }
    return matched, mismatch


def _replay_line(
    line: str,
    *,
    case_lookup: dict[str, str],
    dataset_id: str,
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
) -> tuple[str, dict[str, Any] | None]:
    context = _capture_context(line, case_lookup)
    if context is None:
        return "skipped", None
    record, query_hash, query = context
    payload, error = _post_retrieval(
        client,
        url=url,
        headers=headers,
        body=_request_body(record, dataset_id=dataset_id, query=query),
        query_hash=query_hash,
    )
    if error is not None or payload is None:
        return "errors", error
    matched, mismatch = _compare_capture(record, payload, query_hash=query_hash)
    return ("matched", None) if matched else ("mismatched", mismatch)


def _process_captures(
    captures_path: Path,
    *,
    max_items: int,
    case_lookup: dict[str, str],
    dataset_id: str,
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    totals = {"records": 0, "matched": 0, "mismatched": 0, "skipped": 0, "errors": 0}
    mismatches: list[dict[str, Any]] = []
    with captures_path.open("r", encoding="utf-8", errors="replace") as capture_file:
        for line in capture_file:
            if max_items and totals["records"] >= max_items:
                break
            line = (line or "").strip()
            if not line:
                continue
            totals["records"] += 1
            outcome, mismatch = _replay_line(
                line,
                case_lookup=case_lookup,
                dataset_id=dataset_id,
                client=client,
                url=url,
                headers=headers,
            )
            totals[outcome] += 1
            if mismatch is not None:
                mismatches.append(mismatch)
    return totals, mismatches


def _print_summary(totals: dict[str, int], *, elapsed: float) -> None:
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


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

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
    t0 = time.monotonic()
    with httpx.Client(timeout=timeout) as client:
        totals, mismatches = _process_captures(
            captures_path,
            max_items=int(args.max_items or 0),
            case_lookup=case_lookup,
            dataset_id=str(dataset_id),
            client=client,
            url=url,
            headers=_headers(args),
        )

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

    _print_summary(totals, elapsed=elapsed)

    # CI-friendly: non-zero exit when mismatches or errors exist.
    if totals["mismatched"] or totals["errors"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
