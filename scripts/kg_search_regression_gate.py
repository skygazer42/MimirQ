#!/usr/bin/env python3
"""
KG search regression gate for CI.

This is intentionally lightweight:
- Uses the existing regression case import/list APIs
- Runs KG search diagnostics and gates on Hit/MRR/Recall @K

Expected CI env:
- KG_ENABLED=true (backend)
- KG_SEARCH_VECTOR_RECALL_ENABLED=false (so Milvus/embeddings are not required)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx


def _load_json(path: Path) -> Any:
    # PowerShell commonly writes UTF-8 JSON with BOM; `utf-8-sig` handles both BOM/no-BOM.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_file(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _require(ok: bool, msg: str) -> None:
    if ok:
        return
    raise SystemExit(msg)


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
            items = [x for x in obj.get("items") if isinstance(x, dict)]  # type: ignore[union-attr]
            cleaned = [{k: v for k, v in it.items() if k != "dataset_id"} for it in items]
            return ds, cleaned
        return coerce_case_bundle(list(obj.get("items") or []))

    if isinstance(obj, list):
        items = [x for x in obj if isinstance(x, dict)]
        dsids = []
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
    - {"baseline_hit_rate": 1.0} -> {"baseline_hit_rate": {"min": 1.0}}

    New format:
    - {"baseline_recall": {"min": 0.8}}
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


def parse_thresholds_config(raw: Any) -> dict[str, dict[str, float]]:
    """
    Parse a thresholds JSON payload.

    Supported formats:
    - Legacy: {"baseline_hit_rate": 1.0, "baseline_mrr": {"min": 0.9}}
    - Structured: {"metrics": { ...legacy... }}
    """
    if not isinstance(raw, dict):
        return {}
    if "metrics" in raw:
        return normalize_thresholds(raw.get("metrics") or {})
    return normalize_thresholds(raw)


def _check_thresholds(*, summary: dict[str, Any], thresholds: dict[str, dict[str, float]]) -> list[str]:
    failures: list[str] = []
    for metric, bounds in (thresholds or {}).items():
        if metric not in summary:
            failures.append(f"missing metric in summary: {metric}")
            continue
        val_raw = summary.get(metric)
        try:
            val = float(val_raw)
        except Exception:
            failures.append(f"non-numeric metric {metric}: {val_raw!r}")
            continue

        mn = bounds.get("min")
        mx = bounds.get("max")
        if mn is not None and val < float(mn):
            failures.append(f"{metric}={val:.4f} < min {float(mn):.4f}")
        if mx is not None and val > float(mx):
            failures.append(f"{metric}={val:.4f} > max {float(mx):.4f}")
    return failures


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="KG search regression gate (diagnostics-based).")
    p.add_argument("--base-url", required=True, help="API base URL, e.g. http://localhost:8000/api/v1")
    p.add_argument("--tenant-id", default="", help="Tenant UUID (X-Tenant-ID)")
    p.add_argument("--user-id", default="", help="User id (X-User-ID) when AUTH_MODE=header")
    p.add_argument("--bearer", default="", help="JWT bearer token (Authorization: Bearer ...)")
    p.add_argument("--cases", required=True, help="Regression cases bundle JSON path")
    p.add_argument("--thresholds", required=True, help="Thresholds JSON path (baseline_hit_rate/mrr/recall)")
    p.add_argument("--k", type=int, default=10, help="Hit@K / metrics cutoff (default: 10)")
    p.add_argument("--auto-extract-kg", action="store_true", help="Enable KG extraction preflight (default: off)")
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing cases during import")
    p.add_argument("--skip-import", action="store_true", help="Skip importing cases (assumes they already exist)")
    p.add_argument("--out-run-json", default="", help="Write diagnostics response JSON to this path (optional)")
    return p


def _load_gate_inputs(args: argparse.Namespace) -> tuple[str, list[dict[str, Any]], dict[str, dict[str, float]]]:
    cases_path = Path(args.cases)
    _require(cases_path.exists(), f"cases file not found: {cases_path}")
    dataset_id, items = coerce_case_bundle(_load_json(cases_path))
    _require(bool(dataset_id), "missing dataset_id in cases bundle")
    _require(bool(items), "cases bundle contains zero items")

    thresholds_path = Path(args.thresholds)
    _require(thresholds_path.exists(), f"thresholds file not found: {thresholds_path}")
    raw_thresholds = _load_json(thresholds_path)
    thresholds = parse_thresholds_config(raw_thresholds)
    _require(bool(thresholds), "thresholds is empty")
    configured_dataset = str(raw_thresholds.get("dataset_id") or "").strip() if isinstance(raw_thresholds, dict) else ""
    if configured_dataset and configured_dataset != dataset_id:
        _require(False, f"thresholds dataset_id mismatch (expected {dataset_id}, got {configured_dataset})")
    return dataset_id, items, thresholds


def _import_cases(
    client: httpx.Client,
    *,
    base_url: str,
    dataset_id: str,
    items: list[dict[str, Any]],
    overwrite: bool,
) -> None:
    response = client.post(
        f"{base_url}/evaluations/ragas/regression/cases/import",
        json={
            "dataset_id": dataset_id,
            "overwrite": overwrite,
            "max_items": min(2000, len(items)),
            "items": items,
        },
    )
    response.raise_for_status()
    result = response.json() or {}
    print(
        f"[kg_search_regression_gate] import: created={result.get('created')} "
        f"updated={result.get('updated')} skipped={result.get('skipped')}"
    )
    if result.get("errors"):
        print(f"[kg_search_regression_gate] import warnings: {len(result.get('errors') or [])} errors")


def _wanted_case_keys(items: list[dict[str, Any]], *, dataset_id: str) -> set[str]:
    return {f"{question}\n{dataset_id}" for item in items if (question := str(item.get("question") or "").strip())}


def _matched_case_ids(
    client: httpx.Client,
    *,
    base_url: str,
    dataset_id: str,
    wanted_keys: set[str],
) -> list[str]:
    matched_ids: list[str] = []
    skip = 0
    while True:
        response = client.get(
            f"{base_url}/evaluations/ragas/regression/cases",
            params={"skip": skip, "limit": 200, "dataset_id": dataset_id},
        )
        response.raise_for_status()
        data = response.json() or {}
        rows = data.get("items") or []
        if not rows:
            break
        for row in rows:
            question = str(row.get("question") or "").strip()
            key = f"{question}\n{row.get('dataset_id') or ''}"
            if key in wanted_keys and row.get("id"):
                matched_ids.append(str(row["id"]))
        skip += len(rows)
        if skip >= int(data.get("total") or 0):
            break
    return matched_ids


def _run_diagnostics(
    client: httpx.Client,
    *,
    base_url: str,
    dataset_id: str,
    case_ids: list[str],
    k: int,
    auto_extract_kg: bool,
) -> dict[str, Any]:
    payload = {
        "dataset_id": dataset_id,
        "case_ids": case_ids,
        "max_cases": min(200, len(case_ids)),
        "k": max(1, min(k, 50)),
        "auto_extract_kg": auto_extract_kg,
        "hardcase_mode": "off",
        "hardcases_per_failed_case": 0,
        "max_failed_cases_for_hardcase": 0,
        "persist_run": False,
    }
    response = client.post(f"{base_url}/evaluations/kg/search/diagnostics", json=payload)
    response.raise_for_status()
    result = response.json() or {}
    return result if isinstance(result, dict) else {}


def _write_diagnostics(path_value: str, response: dict[str, Any]) -> None:
    if not path_value:
        return
    path = Path(path_value.strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_file(path, response)
    print(f"[kg_search_regression_gate] wrote diagnostics response: {path}")


def _report_failures(failures: list[str], summary: dict[str, Any]) -> None:
    print("[kg_search_regression_gate] FAIL", file=sys.stderr)
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    print(
        f"[kg_search_regression_gate] summary={json.dumps(summary, ensure_ascii=False, sort_keys=True)}",
        file=sys.stderr,
    )


def main() -> int:
    args = _build_parser().parse_args()

    dataset_id, items, thresholds = _load_gate_inputs(args)
    headers = _headers(args)
    _require(
        bool(headers.get("X-User-ID") or headers.get("Authorization")),
        "missing auth headers (use --user-id or --bearer)",
    )

    base = str(args.base_url).rstrip("/")
    timeout = httpx.Timeout(30.0)

    with httpx.Client(headers=headers, timeout=timeout, trust_env=False) as client:
        if not args.skip_import:
            _import_cases(
                client,
                base_url=base,
                dataset_id=dataset_id,
                items=items,
                overwrite=bool(args.overwrite),
            )
        wanted_keys = _wanted_case_keys(items, dataset_id=dataset_id)
        matched_ids = _matched_case_ids(
            client,
            base_url=base,
            dataset_id=dataset_id,
            wanted_keys=wanted_keys,
        )

        _require(len(matched_ids) > 0, "no matching cases found after import/list")
        print(f"[kg_search_regression_gate] matched cases: {len(matched_ids)}/{len(wanted_keys)}")
        response = _run_diagnostics(
            client,
            base_url=base,
            dataset_id=dataset_id,
            case_ids=matched_ids,
            k=int(args.k),
            auto_extract_kg=bool(args.auto_extract_kg),
        )
        summary = response.get("summary") or {}
        if not isinstance(summary, dict):
            summary = {}

        _write_diagnostics(str(args.out_run_json or ""), response)
        failures = _check_thresholds(summary=summary, thresholds=thresholds)
        if failures:
            _report_failures(failures, summary)
            return 1

        print("[kg_search_regression_gate] PASS")
        print(f"[kg_search_regression_gate] summary={json.dumps(summary, ensure_ascii=False, sort_keys=True)}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
