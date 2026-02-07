#!/usr/bin/env python3
"""
Offline regression gate for CI.

Workflow:
1) (Optional) import a regression case bundle (JSON) via API
2) run a regression evaluation run
3) wait for completion and compare summary metrics to thresholds

Auth:
- AUTH_MODE=header: provide --user-id (X-User-ID)
- AUTH_MODE=jwt: provide --bearer (Authorization: Bearer ...)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _coerce_cases(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict) and isinstance(obj.get("items"), list):
        return [x for x in obj["items"] if isinstance(x, dict)]
    raise ValueError("cases file must be a JSON array, or an object with { items: [...] }")


def _headers(args: argparse.Namespace) -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if args.tenant_id:
        h["X-Tenant-ID"] = str(args.tenant_id)
    if args.user_id:
        h["X-User-ID"] = str(args.user_id)
    if args.bearer:
        h["Authorization"] = f"Bearer {args.bearer}"
    return h


def normalize_thresholds(raw: Any) -> dict[str, dict[str, float]]:
    """
    Normalize thresholds into a { metric: { min?: float, max?: float } } mapping.

    Back-compat:
    - {"faithfulness": 0.7} -> {"faithfulness": {"min": 0.7}}

    New format:
    - {"abstain_rate": {"max": 0.02}}
    - {"retrieval_recall": {"min": 0.3, "max": 0.9}}
    """
    if not isinstance(raw, dict):
        return {}

    out: dict[str, dict[str, float]] = {}
    for k, v in raw.items():
        metric = str(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[metric] = {"min": float(v)}
            continue

        if isinstance(v, dict):
            entry: dict[str, float] = {}
            if "min" in v:
                try:
                    entry["min"] = float(v.get("min"))  # type: ignore[arg-type]
                except Exception:
                    pass
            if "max" in v:
                try:
                    entry["max"] = float(v.get("max"))  # type: ignore[arg-type]
                except Exception:
                    pass
            if entry:
                out[metric] = entry
            continue

    return out


def check_thresholds(
    *,
    summary: dict[str, Any],
    thresholds: dict[str, dict[str, float]],
) -> tuple[bool, list[str]]:
    """
    Evaluate thresholds against a run summary.

    Returns:
      (ok, failures)
    """
    failures: list[str] = []
    for metric, bounds in (thresholds or {}).items():
        raw_val = summary.get(metric)
        try:
            val = float(raw_val)
        except Exception:
            failures.append(f"missing metric '{metric}'")
            continue

        if "min" in bounds:
            min_v = bounds.get("min")
            if min_v is not None and val < float(min_v):
                failures.append(f"{metric}={val:.4f} < min {float(min_v):.4f}")
        if "max" in bounds:
            max_v = bounds.get("max")
            if max_v is not None and val > float(max_v):
                failures.append(f"{metric}={val:.4f} > max {float(max_v):.4f}")

    return (len(failures) == 0), failures


def _require(cond: bool, msg: str) -> None:
    if cond:
        return
    print(f"[regression_gate] ERROR: {msg}", file=sys.stderr)
    sys.exit(2)


def main() -> int:
    p = argparse.ArgumentParser(description="Run regression suite and gate on thresholds.")
    p.add_argument("--base-url", default="http://localhost:8000/api/v1", help="API base url (default: %(default)s)")
    p.add_argument("--tenant-id", default="", help="X-Tenant-ID header (optional in non-prod)")
    p.add_argument("--user-id", default="", help="X-User-ID header (AUTH_MODE=header)")
    p.add_argument("--bearer", default="", help="Bearer token (AUTH_MODE=jwt)")

    p.add_argument("--cases", type=str, required=True, help="Path to regression cases JSON (export bundle or items array)")
    p.add_argument("--skip-import", action="store_true", help="Skip importing the cases file (assumes cases already exist)")
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing cases matched by (question + dataset_id)")

    p.add_argument("--metrics", default="faithfulness,response_relevancy", help="Comma-separated metrics (default: %(default)s)")
    p.add_argument("--poll-sec", type=float, default=2.0, help="Polling interval seconds (default: %(default)s)")
    p.add_argument("--timeout-sec", type=float, default=600.0, help="Timeout seconds (default: %(default)s)")

    p.add_argument(
        "--thresholds",
        type=str,
        default="",
        help="JSON file mapping metric->number (min) or metric->{min,max} (optional)",
    )

    args = p.parse_args()

    cases_path = Path(args.cases)
    _require(cases_path.exists(), f"cases file not found: {cases_path}")
    items = _coerce_cases(_load_json(cases_path))
    _require(len(items) > 0, "cases file contains no items")

    metrics = [m.strip() for m in str(args.metrics or "").split(",") if m.strip()]
    _require(len(metrics) > 0, "metrics list is empty")

    thresholds: dict[str, dict[str, float]] = {}
    if args.thresholds:
        th_path = Path(args.thresholds)
        _require(th_path.exists(), f"thresholds file not found: {th_path}")
        raw_th = _load_json(th_path)
        if not isinstance(raw_th, dict):
            _require(False, "thresholds must be a JSON object { metric: number | {min,max} }")
        thresholds = normalize_thresholds(raw_th)

    headers = _headers(args)
    _require(bool(headers.get("X-User-ID") or headers.get("Authorization")), "missing auth headers (use --user-id or --bearer)")

    base = str(args.base_url).rstrip("/")
    timeout = httpx.Timeout(30.0)

    with httpx.Client(headers=headers, timeout=timeout) as client:
        if not args.skip_import:
            r = client.post(
                f"{base}/evaluations/ragas/regression/cases/import",
                json={
                    "overwrite": bool(args.overwrite),
                    "max_items": min(2000, len(items)),
                    "items": items,
                },
            )
            r.raise_for_status()
            imp = r.json()
            print(f"[regression_gate] import: created={imp.get('created')} updated={imp.get('updated')} skipped={imp.get('skipped')}")
            if imp.get("errors"):
                print(f"[regression_gate] import warnings: {len(imp.get('errors') or [])} errors")

        # Resolve case ids by listing and matching (question + dataset_id).
        want_keys = set()
        for it in items:
            q = (str(it.get("question") or "")).strip()
            dsid = it.get("dataset_id") or ""
            if q:
                want_keys.add(f"{q}\n{dsid}")

        matched_ids: list[str] = []
        skip = 0
        while True:
            r = client.get(f"{base}/evaluations/ragas/regression/cases", params={"skip": skip, "limit": 200})
            r.raise_for_status()
            data = r.json() or {}
            rows = data.get("items") or []
            if not rows:
                break
            for row in rows:
                q = (str(row.get("question") or "")).strip()
                dsid = row.get("dataset_id") or ""
                key = f"{q}\n{dsid}"
                if key in want_keys and row.get("id"):
                    matched_ids.append(str(row["id"]))
            skip += len(rows)
            if skip >= int(data.get("total") or 0):
                break

        _require(len(matched_ids) > 0, "no matching cases found after import/list")
        print(f"[regression_gate] matched cases: {len(matched_ids)}/{len(want_keys)}")

        # Start regression run (defaults follow system settings unless explicitly overridden).
        r = client.post(
            f"{base}/evaluations/ragas/regression/runs",
            json={
                "case_ids": matched_ids,
                "metrics": metrics,
                "skip_empty_contexts": True,
                "max_cases": min(500, len(matched_ids)),
            },
        )
        r.raise_for_status()
        run = r.json() or {}
        run_id = run.get("id")
        _require(bool(run_id), "failed to create regression run (missing run.id)")
        print(f"[regression_gate] run started: {run_id}")

        # Poll until done.
        deadline = time.time() + float(args.timeout_sec)
        status = ""
        summary: dict[str, Any] = {}
        while time.time() < deadline:
            r = client.get(f"{base}/evaluations/ragas/regression/runs/{run_id}", params={"include_items": False})
            r.raise_for_status()
            detail = r.json() or {}
            status = str((detail.get("run") or {}).get("status") or "")
            summary = dict((detail.get("run") or {}).get("summary") or {})
            if status in {"completed", "failed"}:
                break
            time.sleep(float(args.poll_sec))

        if status != "completed":
            err = (detail.get("run") or {}).get("error_message") if isinstance(detail, dict) else None
            print(f"[regression_gate] ERROR: run status={status} error={err}", file=sys.stderr)
            return 1

        print(f"[regression_gate] run completed. summary keys={list(summary.keys())}")

        if not thresholds:
            print("[regression_gate] no thresholds set; PASS")
            return 0

        failed = False
        for metric, bounds in thresholds.items():
            try:
                val = float(summary.get(metric))
            except Exception:
                val = None
            if val is None:
                print(f"[regression_gate] FAIL: missing metric '{metric}'", file=sys.stderr)
                failed = True
                continue

            min_v = bounds.get("min")
            max_v = bounds.get("max")

            if min_v is not None and val < float(min_v):
                print(f"[regression_gate] FAIL: {metric}={val:.4f} < min {float(min_v):.4f}", file=sys.stderr)
                failed = True
                continue
            if max_v is not None and val > float(max_v):
                print(f"[regression_gate] FAIL: {metric}={val:.4f} > max {float(max_v):.4f}", file=sys.stderr)
                failed = True
                continue

            if min_v is not None and max_v is not None:
                print(f"[regression_gate] OK: {metric}={val:.4f} in [{float(min_v):.4f}, {float(max_v):.4f}]")
            elif min_v is not None:
                print(f"[regression_gate] OK: {metric}={val:.4f} >= {float(min_v):.4f}")
            elif max_v is not None:
                print(f"[regression_gate] OK: {metric}={val:.4f} <= {float(max_v):.4f}")
            else:
                # Should not happen (normalize_thresholds drops empty bounds), but keep it safe.
                print(f"[regression_gate] OK: {metric}={val:.4f}")

        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
