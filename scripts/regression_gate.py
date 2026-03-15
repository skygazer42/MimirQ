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
import difflib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import httpx


def _load_json(path: Path) -> Any:
    # PowerShell commonly writes UTF-8 JSON with BOM; `utf-8-sig` handles both BOM/no-BOM.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_file(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text_file(path: Path, content: str) -> None:
    path.write_text(str(content or ""), encoding="utf-8")


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
            # Defensive: strip accidental dataset_id field inside each item (API expects dataset_id only at top-level).
            cleaned = [{k: v for k, v in it.items() if k != "dataset_id"} for it in items]
            return ds, cleaned
        # Fall back: accept bundles that forgot top-level dataset_id but include it per item.
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


_RUN_OVERRIDE_KEYS: tuple[str, ...] = (
    # Aligned with app/api/schemas/regression.py:RagasRegressionRunCreateRequest
    "retrieval_profile",
    "enable_query_alias_expansion",
    "query_alias_max_queries",
    "enable_multi_query",
    "multi_query_count",
    "multi_query_temperature",
    "multi_query_max_chars",
    "enable_query_rewrite",
    "query_rewrite_strategy",
    "query_rewrite_temperature",
    "query_rewrite_max_chars",
    "sparse_retrieval_enabled",
    "sparse_retrieval_provider",
    "top_k",
    "score_threshold",
    "retrieval_mode",
    "alpha",
    "fusion_strategy",
    "fusion_budgets",
    "fusion_min_scores",
    "fusion_weights",
    "enable_weight_rerank",
    "vector_weight",
    "keyword_weight",
    "mmr_lambda",
    "enable_reranker",
    "reranker_provider",
    "reranker_top_n",
    "prompt_template_id",
    "prompt_template_key",
    "prompt_ab_experiment_key",
)


def build_run_create_request_payload(
    *,
    case_ids: list[str],
    dataset_id: str,
    metrics: list[str],
    max_cases: int,
    retrieval_overrides: dict[str, Any] | None = None,
    skip_empty_contexts: bool = True,
) -> dict[str, Any]:
    """
    Build a request body for POST /evaluations/ragas/regression/runs.

    Keeps behavior stable and testable, and avoids sprinkling run-param wiring across call sites.
    """
    payload: dict[str, Any] = {
        "case_ids": list(case_ids or []),
        "dataset_id": dataset_id,
        "metrics": list(metrics or []),
        "skip_empty_contexts": bool(skip_empty_contexts),
        "max_cases": int(max_cases),
    }

    overrides = retrieval_overrides if isinstance(retrieval_overrides, dict) else {}
    for key in _RUN_OVERRIDE_KEYS:
        if key in overrides and overrides.get(key) is not None:
            payload[key] = overrides.get(key)

    return payload


def parse_metrics_list(raw: Any) -> list[str]:
    return [m.strip() for m in str(raw or "").split(",") if m.strip()]


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


def normalize_slice_thresholds(raw: Any) -> dict[str, dict[str, dict[str, dict[str, float]]]]:
    """
    Normalize per-slice thresholds into a mapping:
      { dim: { bucket_key: { metric: {min?: float, max?: float} } } }

    Expected input shape:
      {
        "file_type": {
          "pdf": {"retrieval_recall": {"min": 0.3}},
          "md": {"abstain_rate": {"max": 0.02}}
        },
        "language": { ... }
      }
    """
    if not isinstance(raw, dict):
        return {}

    out: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    for dim_raw, buckets_raw in raw.items():
        dim = str(dim_raw or "").strip()
        if not dim:
            continue
        if not isinstance(buckets_raw, dict):
            continue

        dim_out: dict[str, dict[str, dict[str, float]]] = {}
        for bucket_raw, th_raw in buckets_raw.items():
            bucket = str(bucket_raw or "").strip().lower()
            if not bucket:
                continue
            th = normalize_thresholds(th_raw)
            if th:
                dim_out[bucket] = th

        if dim_out:
            out[dim] = dim_out

    return out


def parse_thresholds_config(
    raw: Any,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, dict[str, dict[str, float]]]]]:
    """
    Parse a thresholds JSON payload into:
      (top_level_thresholds, per_slice_thresholds).

    Supported formats:
      - Legacy (v1): {"retrieval_recall": 0.3, "abstain_rate": {"max": 0.02}}
      - Structured (v2):
        {
          "schema": "mimirq.thresholds.v2",
          "dataset_id": "...",
          "metrics": { ... legacy thresholds ... },
          "slices": { ... per-slice thresholds ... }
        }
    """
    if not isinstance(raw, dict):
        return {}, {}

    if "metrics" in raw or "slices" in raw:
        metrics = normalize_thresholds(raw.get("metrics") or {})
        slices = normalize_slice_thresholds(raw.get("slices") or {})
        return metrics, slices

    return normalize_thresholds(raw), {}


def is_empty_metrics_allowed(
    *,
    metrics: list[str],
    thresholds: dict[str, dict[str, float]] | None,
    slice_thresholds: dict[str, dict[str, dict[str, dict[str, float]]]] | None,
    thresholds_file_provided: bool,
    generate_thresholds_out: str,
) -> bool:
    """
    The API supports a retrieval-only regression run by sending an empty metrics list.

    Empty metrics are allowed when:
    - we are gating (thresholds are provided), OR
    - we are generating thresholds from this run (baseline workflow).
    """
    if metrics:
        return True
    if str(generate_thresholds_out or "").strip():
        return True
    if bool(thresholds_file_provided) and (bool(thresholds) or bool(slice_thresholds)):
        return True
    return False


def format_unified_diff(old_text: str, new_text: str, *, fromfile: str, tofile: str) -> str:
    """
    Return a unified diff string (empty when identical).

    Kept as a tiny helper so it can be unit-tested without invoking the CLI/network.
    """
    old_lines = str(old_text or "").splitlines(keepends=True)
    new_lines = str(new_text or "").splitlines(keepends=True)
    return "".join(difflib.unified_diff(old_lines, new_lines, fromfile=str(fromfile), tofile=str(tofile)))


def summarize_channel_attribution(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    totals = {
        "vector": 0,
        "bm25": 0,
        "lexical": 0,
        "sparse": 0,
        "multi": 0,
        "citations_with_scores": 0,
        "total_citations": 0,
    }
    cases_with_citations = 0
    for item in (items or []):
        if not isinstance(item, dict):
            continue
        citations = item.get("citations")
        if not isinstance(citations, list):
            continue
        if citations:
            cases_with_citations += 1
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            totals["total_citations"] += 1
            has_vector = _coerce_float(citation.get("vector_score")) not in (None, 0.0)
            has_bm25 = _coerce_float(citation.get("bm25_score")) not in (None, 0.0)
            has_lexical = _coerce_float(citation.get("lexical_score")) not in (None, 0.0)
            has_sparse = _coerce_float(citation.get("sparse_score")) not in (None, 0.0)
            hit_count = sum((has_vector, has_bm25, has_lexical, has_sparse))
            if hit_count > 0:
                totals["citations_with_scores"] += 1
            if has_vector:
                totals["vector"] += 1
            if has_bm25:
                totals["bm25"] += 1
            if has_lexical:
                totals["lexical"] += 1
            if has_sparse:
                totals["sparse"] += 1
            if hit_count > 1:
                totals["multi"] += 1

    return {
        "cases_with_citations": cases_with_citations,
        "totals": totals,
    }


def summarize_multihop_diagnostics(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    path_scores: list[float] = []
    order_scores: list[float] = []
    hit_flags: list[float] = []
    cases_with_expectation = 0
    for item in (items or []):
        if not isinstance(item, dict):
            continue
        meta = item.get("meta")
        meta = meta if isinstance(meta, dict) else {}

        evidence_steps = meta.get("evidence_chain_steps")
        try:
            evidence_steps_n = int(evidence_steps or 0)
        except Exception:
            evidence_steps_n = 0
        if evidence_steps_n <= 0:
            continue

        cases_with_expectation += 1

        try:
            p = float(meta.get("multihop_path_completeness"))
            path_scores.append(p)
        except Exception:
            pass
        try:
            o = float(meta.get("multihop_order_consistency"))
            order_scores.append(o)
        except Exception:
            pass
        if meta.get("multihop_chain_hit") is not None:
            hit_flags.append(1.0 if bool(meta.get("multihop_chain_hit")) else 0.0)

    def _mean(values: list[float]) -> float | None:
        if not values:
            return None
        return round(float(sum(values)) / float(len(values)), 4)

    return {
        "cases_with_expectation": int(cases_with_expectation),
        "path_completeness": _mean(path_scores),
        "order_consistency": _mean(order_scores),
        "chain_hit_rate": _mean(hit_flags),
    }


def build_regression_gate_report(
    *,
    dataset_id: str,
    run_id: str,
    matched_case_count: int,
    metrics: list[str],
    thresholds_enabled: bool,
    ok: bool,
    failures: list[str],
    detail: dict[str, Any],
    run_payload: dict[str, Any],
) -> dict[str, Any]:
    run = detail.get("run") if isinstance(detail, dict) else {}
    run = run if isinstance(run, dict) else {}
    items = detail.get("items") if isinstance(detail, dict) else []
    items = items if isinstance(items, list) else []
    summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}

    if str(run.get("status") or "") != "completed":
        gate_status = "error"
    elif ok:
        gate_status = "pass"
    else:
        gate_status = "fail"

    return {
        "schema": "mimirq.regression_gate_report.v1",
        "dataset_id": str(dataset_id or ""),
        "run_id": str(run_id or ""),
        "gate_status": gate_status,
        "thresholds_enabled": bool(thresholds_enabled),
        "matched_case_count": int(matched_case_count or 0),
        "metrics": list(metrics or []),
        "summary": dict(summary or {}),
        "retrieval_slices": dict(summary.get("retrieval_slices") or {}) if isinstance(summary, dict) else {},
        "failures": [str(msg) for msg in (failures or []) if str(msg or "").strip()],
        "run_status": str(run.get("status") or ""),
        "error_message": str(run.get("error_message") or "") or None,
        "channel_attribution": summarize_channel_attribution(items),
        "multihop": summarize_multihop_diagnostics(items),
        "run_params": dict(run_payload or {}),
    }


def render_regression_gate_markdown(report: dict[str, Any]) -> str:
    payload = report if isinstance(report, dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    attribution = payload.get("channel_attribution") if isinstance(payload.get("channel_attribution"), dict) else {}
    totals = attribution.get("totals") if isinstance(attribution.get("totals"), dict) else {}
    multihop = payload.get("multihop") if isinstance(payload.get("multihop"), dict) else {}
    failures = [str(x) for x in (payload.get("failures") or []) if str(x or "").strip()]

    lines = [
        "# Retrieval Regression Gate Report",
        "",
        f"- Gate status: `{payload.get('gate_status') or 'unknown'}`",
        f"- Run status: `{payload.get('run_status') or 'unknown'}`",
        f"- Dataset ID: `{payload.get('dataset_id') or ''}`",
        f"- Run ID: `{payload.get('run_id') or ''}`",
        f"- Matched cases: `{int(payload.get('matched_case_count') or 0)}`",
        f"- Thresholds enabled: `{bool(payload.get('thresholds_enabled'))}`",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]

    rendered_metric = False
    for key, value in sorted((summary or {}).items()):
        if key == "retrieval_slices":
            continue
        numeric = _coerce_float(value)
        if numeric is None and isinstance(value, (dict, list)):
            continue
        rendered_metric = True
        value_text = f"{numeric:.4f}" if numeric is not None else str(value)
        lines.append(f"| {key} | {value_text} |")
    if not rendered_metric:
        lines.append("| _none_ | - |")

    lines.extend(
        [
            "",
            "## Channel Attribution",
            "",
            "| Channel | Citations |",
            "| --- | ---: |",
            f"| vector | {int(totals.get('vector') or 0)} |",
            f"| bm25 | {int(totals.get('bm25') or 0)} |",
            f"| lexical | {int(totals.get('lexical') or 0)} |",
            f"| sparse | {int(totals.get('sparse') or 0)} |",
            f"| multi-channel | {int(totals.get('multi') or 0)} |",
            "",
        ]
    )

    if int(multihop.get("cases_with_expectation") or 0) > 0:
        lines.extend(
            [
                "## Multi-hop Diagnostics",
                "",
                f"- Cases with expectation: `{int(multihop.get('cases_with_expectation') or 0)}`",
                f"- Path completeness: `{multihop.get('path_completeness')}`",
                f"- Order consistency: `{multihop.get('order_consistency')}`",
                f"- Chain hit rate: `{multihop.get('chain_hit_rate')}`",
                "",
            ]
        )

    if failures:
        lines.extend(["## Failures", ""])
        for msg in failures:
            lines.append(f"- {msg}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def check_thresholds(
    *,
    summary: dict[str, Any],
    thresholds: dict[str, dict[str, float]],
    slice_thresholds: dict[str, dict[str, dict[str, dict[str, float]]]] | None = None,
) -> tuple[bool, list[str]]:
    """
    Evaluate thresholds against a run summary.

    Returns:
      (ok, failures)
    """
    failures: list[str] = []

    def _check_one(*, name: str, raw_val: Any, bounds: dict[str, float]) -> None:
        try:
            val = float(raw_val)
        except Exception:
            failures.append(f"missing metric '{name}'")
            return

        if "min" in bounds:
            min_v = bounds.get("min")
            if min_v is not None and val < float(min_v):
                failures.append(f"{name}={val:.4f} < min {float(min_v):.4f}")
        if "max" in bounds:
            max_v = bounds.get("max")
            if max_v is not None and val > float(max_v):
                failures.append(f"{name}={val:.4f} > max {float(max_v):.4f}")

    for metric, bounds in (thresholds or {}).items():
        _check_one(name=metric, raw_val=summary.get(metric), bounds=bounds)

    # Optional: enforce per-slice thresholds against summary["retrieval_slices"][dim].buckets[].{metric}.
    rs = summary.get("retrieval_slices") if isinstance(summary, dict) else None
    rs_dict = rs if isinstance(rs, dict) else {}
    for dim, bucket_map in (slice_thresholds or {}).items():
        dim_key = str(dim or "").strip()
        if not dim_key:
            continue

        dim_obj = rs_dict.get(dim_key)
        if not isinstance(dim_obj, dict):
            failures.append(f"missing slice dim '{dim_key}'")
            continue

        buckets = dim_obj.get("buckets")
        if not isinstance(buckets, list):
            failures.append(f"missing slice buckets '{dim_key}.buckets'")
            continue

        by_key: dict[str, dict[str, Any]] = {}
        for b in buckets:
            if not isinstance(b, dict):
                continue
            k = str(b.get("key") or "").strip().lower()
            if not k:
                continue
            by_key.setdefault(k, b)

        for bucket_key, bucket_thresholds in (bucket_map or {}).items():
            bkey = str(bucket_key or "").strip().lower()
            if not bkey:
                continue
            bucket = by_key.get(bkey)
            if not isinstance(bucket, dict):
                failures.append(f"missing slice bucket '{dim_key}={bkey}'")
                continue
            for metric, bounds in (bucket_thresholds or {}).items():
                _check_one(name=f"slice[{dim_key}={bkey}].{metric}", raw_val=bucket.get(metric), bounds=bounds)

    return (len(failures) == 0), failures


def _coerce_float(raw: Any) -> float | None:
    try:
        v = float(raw)
    except Exception:
        return None
    if math.isnan(v):
        return None
    return v


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _as_bounds(metric: str, *, baseline: float, rel_drop: float, abs_slack: float) -> dict[str, float]:
    metric_key = str(metric or "").strip().lower()
    baseline = _clamp01(float(baseline))
    rel = abs(float(rel_drop or 0.0))
    slack = max(abs(float(abs_slack or 0.0)), rel * baseline)

    if metric_key == "abstain_rate":
        return {"max": round(_clamp01(baseline + slack), 4)}

    return {"min": round(_clamp01(baseline - slack), 4)}


def generate_thresholds_from_summary(
    *,
    dataset_id: str,
    summary: dict[str, Any],
    metrics: list[str] | None = None,
    slice_dims: list[str] | None = None,
    slice_metrics: list[str] | None = None,
    rel_drop: float = 0.05,
    abs_slack: float = 0.02,
    min_slice_items: int = 5,
) -> dict[str, Any]:
    """
    Generate a structured thresholds config from a baseline run summary.

    Guardrails:
    - Skips metrics with missing/non-numeric values.
    - Skips slice buckets with items < min_slice_items.
    - Clamps thresholds to [0, 1].
    """
    ds = str(dataset_id or "").strip()
    if not ds:
        raise ValueError("dataset_id is required")
    summ = summary if isinstance(summary, dict) else {}

    metrics = list(metrics or [])
    slice_dims = list(slice_dims or [])
    slice_metrics = list(slice_metrics or [])
    min_slice_items = max(0, int(min_slice_items or 0))

    metrics_out: dict[str, dict[str, float]] = {}
    for m in metrics:
        key = str(m or "").strip()
        if not key:
            continue
        v = _coerce_float(summ.get(key))
        if v is None:
            continue
        metrics_out[key] = _as_bounds(key, baseline=float(v), rel_drop=rel_drop, abs_slack=abs_slack)

    slices_out: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    rs = summ.get("retrieval_slices") if isinstance(summ.get("retrieval_slices"), dict) else {}
    for dim in slice_dims:
        dim_key = str(dim or "").strip()
        if not dim_key:
            continue
        dim_obj = rs.get(dim_key) if isinstance(rs, dict) else None
        if not isinstance(dim_obj, dict):
            continue
        buckets = dim_obj.get("buckets")
        if not isinstance(buckets, list):
            continue

        dim_out: dict[str, dict[str, dict[str, float]]] = {}
        for b in buckets:
            if not isinstance(b, dict):
                continue
            bkey = str(b.get("key") or "").strip().lower()
            if not bkey:
                continue
            try:
                items = int(b.get("items") or 0)
            except Exception:
                items = 0
            if items < min_slice_items:
                continue

            bth: dict[str, dict[str, float]] = {}
            for m in slice_metrics:
                key = str(m or "").strip()
                if not key:
                    continue
                v = _coerce_float(b.get(key))
                if v is None:
                    continue
                bth[key] = _as_bounds(key, baseline=float(v), rel_drop=rel_drop, abs_slack=abs_slack)
            if bth:
                dim_out[bkey] = bth

        if dim_out:
            slices_out[dim_key] = dim_out

    return {
        "schema": "mimirq.thresholds.v2",
        "dataset_id": ds,
        "options": {
            "rel_drop": float(rel_drop),
            "abs_slack": float(abs_slack),
            "min_slice_items": int(min_slice_items),
        },
        "metrics": metrics_out,
        "slices": slices_out,
    }


def _require(cond: bool, msg: str) -> None:
    if cond:
        return
    print(f"[regression_gate] ERROR: {msg}", file=sys.stderr)
    sys.exit(2)


def _add_tristate_flag(
    p: argparse.ArgumentParser,
    *,
    enable_flag: str,
    disable_flag: str,
    dest: str,
    help: str,
) -> None:
    """
    Add a tri-state boolean flag (True/False/None) using two mutually exclusive flags.

    Example:
      --enable-query-rewrite  => args.enable_query_rewrite = True
      --disable-query-rewrite => args.enable_query_rewrite = False
      (default)               => args.enable_query_rewrite = None
    """
    g = p.add_mutually_exclusive_group()
    g.add_argument(enable_flag, dest=dest, action="store_true", help=f"Enable {help} (optional)")
    g.add_argument(disable_flag, dest=dest, action="store_false", help=f"Disable {help} (optional)")
    p.set_defaults(**{dest: None})


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run regression suite and gate on thresholds.")
    p.add_argument("--base-url", default="http://localhost:8000/api/v1", help="API base url (default: %(default)s)")
    p.add_argument("--tenant-id", default="", help="X-Tenant-ID header (optional in non-prod)")
    p.add_argument("--user-id", default="", help="X-User-ID header (AUTH_MODE=header)")
    p.add_argument("--bearer", default="", help="Bearer token (AUTH_MODE=jwt)")

    p.add_argument("--cases", type=str, required=True, help="Path to regression cases JSON (export bundle or items array)")
    p.add_argument("--skip-import", action="store_true", help="Skip importing the cases file (assumes cases already exist)")
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing cases matched by (question + dataset_id)")

    p.add_argument(
        "--metrics",
        default="faithfulness,response_relevancy",
        help='Comma-separated metrics (default: %(default)s). Use --metrics "" for retrieval-only runs (requires --thresholds for gating, or --generate-thresholds-out for baseline generation).',
    )
    p.add_argument("--poll-sec", type=float, default=2.0, help="Polling interval seconds (default: %(default)s)")
    p.add_argument("--timeout-sec", type=float, default=600.0, help="Timeout seconds (default: %(default)s)")

    p.add_argument(
        "--thresholds",
        type=str,
        default="",
        help="Thresholds JSON file (v1 flat or v2 structured) (optional)",
    )

    # Optional: retrieval config overrides for the regression run request.
    p.add_argument("--top-k", type=int, default=None, help="Override retrieval top_k for this run (optional)")
    p.add_argument("--score-threshold", type=float, default=None, help="Override retrieval score_threshold for this run (optional)")
    p.add_argument(
        "--retrieval-mode",
        type=str,
        default="",
        help="Override retrieval_mode for this run: hybrid|vector|keyword|mmr (optional)",
    )

    # Optional: broaden runtime knob coverage (aligned with RagasRegressionRunCreateRequest).
    p.add_argument("--retrieval-profile", type=str, default="", help="Override retrieval_profile preset (optional)")
    p.add_argument("--fusion-strategy", type=str, default="", help="Override fusion_strategy (optional)")
    p.add_argument(
        "--run-overrides-json",
        type=str,
        default="",
        help="JSON file of run overrides (subset of RagasRegressionRunCreateRequest fields). Merged with CLI flags; CLI wins (optional).",
    )
    _add_tristate_flag(
        p,
        enable_flag="--enable-sparse-retrieval",
        disable_flag="--disable-sparse-retrieval",
        dest="sparse_retrieval_enabled",
        help="sparse retrieval channel",
    )
    p.add_argument("--sparse-retrieval-provider", type=str, default="", help="Override sparse_retrieval_provider (optional)")
    _add_tristate_flag(
        p,
        enable_flag="--enable-query-rewrite",
        disable_flag="--disable-query-rewrite",
        dest="enable_query_rewrite",
        help="query rewrite",
    )
    _add_tristate_flag(
        p,
        enable_flag="--enable-multi-query",
        disable_flag="--disable-multi-query",
        dest="enable_multi_query",
        help="multi-query expansion",
    )
    _add_tristate_flag(
        p,
        enable_flag="--enable-reranker",
        disable_flag="--disable-reranker",
        dest="enable_reranker",
        help="reranker",
    )
    p.add_argument("--reranker-provider", type=str, default="", help="Override reranker_provider (optional)")
    p.add_argument("--reranker-top-n", type=int, default=None, help="Override reranker_top_n (optional)")

    # Optional: persist run detail JSON for CI artifacts.
    p.add_argument(
        "--out-run-json",
        default="",
        help="Write the final run detail JSON (includes summary + retrieval_slices) to a file (optional)",
    )
    p.add_argument(
        "--out-report-json",
        default="",
        help="Write a compact regression gate report JSON artifact (optional)",
    )
    p.add_argument(
        "--out-report-md",
        default="",
        help="Write a compact regression gate Markdown artifact (optional)",
    )

    # Optional: generate structured thresholds (v2) from the run summary.
    p.add_argument(
        "--generate-thresholds-out",
        default="",
        help="Write generated thresholds (v2) from this run summary to a JSON file (optional; use '-' for stdout)",
    )
    p.add_argument(
        "--gen-metrics",
        default="retrieval_recall,retrieval_hit_at_20,retrieval_mrr,retrieval_ndcg_at_20,multihop_path_completeness,multihop_order_consistency,multihop_chain_hit_rate,abstain_rate",
        help="Comma-separated top-level metrics to generate thresholds for (default: %(default)s)",
    )
    p.add_argument(
        "--gen-slice-dims",
        default="file_type,language,hit_type,quality",
        help="Comma-separated slice dims to generate per-slice thresholds for (default: %(default)s)",
    )
    p.add_argument(
        "--gen-slice-metrics",
        default="retrieval_recall,retrieval_hit_at_20,multihop_path_completeness,multihop_order_consistency,abstain_rate",
        help="Comma-separated slice metrics to generate thresholds for (default: %(default)s)",
    )
    p.add_argument("--gen-rel-drop", type=float, default=0.05, help="Relative slack (default: %(default)s)")
    p.add_argument("--gen-abs-slack", type=float, default=0.02, help="Absolute slack (default: %(default)s)")
    p.add_argument("--gen-min-slice-items", type=int, default=5, help="Min items per slice bucket (default: %(default)s)")
    p.add_argument("--gen-force", action="store_true", help="Overwrite --generate-thresholds-out if it exists")

    return p


def build_retrieval_overrides_from_args(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}

    if args.top_k is not None:
        overrides["top_k"] = int(args.top_k)
    if args.score_threshold is not None:
        overrides["score_threshold"] = float(args.score_threshold)
    if str(args.retrieval_mode or "").strip():
        overrides["retrieval_mode"] = str(args.retrieval_mode).strip()

    if str(getattr(args, "retrieval_profile", "") or "").strip():
        overrides["retrieval_profile"] = str(args.retrieval_profile).strip()
    if str(getattr(args, "fusion_strategy", "") or "").strip():
        overrides["fusion_strategy"] = str(args.fusion_strategy).strip()

    if getattr(args, "sparse_retrieval_enabled", None) is not None:
        overrides["sparse_retrieval_enabled"] = bool(args.sparse_retrieval_enabled)
    if str(getattr(args, "sparse_retrieval_provider", "") or "").strip():
        overrides["sparse_retrieval_provider"] = str(args.sparse_retrieval_provider).strip()

    if getattr(args, "enable_query_rewrite", None) is not None:
        overrides["enable_query_rewrite"] = bool(args.enable_query_rewrite)
    if getattr(args, "enable_multi_query", None) is not None:
        overrides["enable_multi_query"] = bool(args.enable_multi_query)

    if getattr(args, "enable_reranker", None) is not None:
        overrides["enable_reranker"] = bool(args.enable_reranker)
    if str(getattr(args, "reranker_provider", "") or "").strip():
        overrides["reranker_provider"] = str(args.reranker_provider).strip()
    if getattr(args, "reranker_top_n", None) is not None:
        overrides["reranker_top_n"] = int(args.reranker_top_n)

    return overrides


def normalize_run_overrides(raw: Any) -> dict[str, Any]:
    """
    Validate/normalize a run overrides JSON object.

    We keep this intentionally strict (unknown keys are rejected) so hourly/nightly
    jobs don't silently "think" they set a knob while the server ignores it.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("run overrides must be a JSON object")

    unknown = [str(k) for k in raw.keys() if str(k) not in _RUN_OVERRIDE_KEYS]
    if unknown:
        sample = ", ".join(sorted(unknown)[:10])
        raise ValueError(f"unknown run override key(s): {sample}")

    out: dict[str, Any] = {}
    for k in _RUN_OVERRIDE_KEYS:
        if k in raw and raw.get(k) is not None:
            out[k] = raw.get(k)
    return out


def main() -> int:
    p = build_arg_parser()
    args = p.parse_args()

    cases_path = Path(args.cases)
    _require(cases_path.exists(), f"cases file not found: {cases_path}")
    dataset_id, items = coerce_case_bundle(_load_json(cases_path))
    _require(len(items) > 0, "cases file contains no items")

    metrics = parse_metrics_list(args.metrics)

    thresholds: dict[str, dict[str, float]] = {}
    slice_thresholds: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    if args.thresholds:
        th_path = Path(args.thresholds)
        _require(th_path.exists(), f"thresholds file not found: {th_path}")
        raw_th = _load_json(th_path)
        if not isinstance(raw_th, dict):
            _require(False, "thresholds must be a JSON object")
        thresholds, slice_thresholds = parse_thresholds_config(raw_th)

        # Optional dataset_id guardrail (helps avoid applying thresholds from another dataset by accident).
        th_ds = str(raw_th.get("dataset_id") or "").strip()
        if th_ds and th_ds != dataset_id:
            _require(False, f"thresholds dataset_id mismatch (expected {dataset_id}, got {th_ds})")

    # Allow retrieval-only gate: empty metrics list is okay when thresholds are provided.
    if not metrics:
        _require(
            is_empty_metrics_allowed(
                metrics=metrics,
                thresholds=thresholds,
                slice_thresholds=slice_thresholds,
                thresholds_file_provided=bool(args.thresholds),
                generate_thresholds_out=str(args.generate_thresholds_out or ""),
            ),
            "metrics list is empty (set --thresholds for gating or --generate-thresholds-out for baseline generation)",
        )

    headers = _headers(args)
    _require(bool(headers.get("X-User-ID") or headers.get("Authorization")), "missing auth headers (use --user-id or --bearer)")

    base = str(args.base_url).rstrip("/")
    timeout = httpx.Timeout(30.0)

    with httpx.Client(headers=headers, timeout=timeout) as client:
        if not args.skip_import:
            r = client.post(
                f"{base}/evaluations/ragas/regression/cases/import",
                json={
                    "dataset_id": dataset_id,
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
            if q:
                want_keys.add(f"{q}\n{dataset_id}")

        matched_ids: list[str] = []
        skip = 0
        while True:
            r = client.get(
                f"{base}/evaluations/ragas/regression/cases",
                params={"skip": skip, "limit": 200, "dataset_id": dataset_id},
            )
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

        file_overrides: dict[str, Any] = {}
        if str(args.run_overrides_json or "").strip():
            ov_path = Path(str(args.run_overrides_json)).expanduser()
            _require(ov_path.exists(), f"run overrides file not found: {ov_path}")
            raw_ov = _load_json(ov_path)
            try:
                file_overrides = normalize_run_overrides(raw_ov)
            except Exception as exc:
                _require(False, f"invalid --run-overrides-json: {exc}")

        cli_overrides = build_retrieval_overrides_from_args(args)
        overrides = {**file_overrides, **cli_overrides}

        # Start regression run (defaults follow API schema unless explicitly overridden).
        run_payload = build_run_create_request_payload(
            case_ids=matched_ids,
            dataset_id=dataset_id,
            metrics=metrics,
            skip_empty_contexts=True,
            max_cases=min(500, len(matched_ids)),
            retrieval_overrides=overrides,
        )
        r = client.post(
            f"{base}/evaluations/ragas/regression/runs",
            json=run_payload,
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

        if args.out_run_json:
            out_path = str(args.out_run_json or "").strip()
            if out_path == "-":
                sys.stdout.write(json.dumps(detail, ensure_ascii=False, indent=2) + "\n")
            else:
                pth = Path(out_path)
                pth.parent.mkdir(parents=True, exist_ok=True)
                write_json_file(pth, detail)
                print(f"[regression_gate] wrote run detail: {pth}")

        print(f"[regression_gate] run completed. summary keys={list(summary.keys())}")

        # Optional: emit generated thresholds from this run summary.
        if args.generate_thresholds_out:
            out_path = str(args.generate_thresholds_out or "").strip()
            gen_cfg = generate_thresholds_from_summary(
                dataset_id=dataset_id,
                summary=summary,
                metrics=parse_metrics_list(args.gen_metrics),
                slice_dims=parse_metrics_list(args.gen_slice_dims),
                slice_metrics=parse_metrics_list(args.gen_slice_metrics),
                rel_drop=float(args.gen_rel_drop),
                abs_slack=float(args.gen_abs_slack),
                min_slice_items=int(args.gen_min_slice_items),
            )
            out_json = json.dumps(gen_cfg, ensure_ascii=False, indent=2) + "\n"
            if out_path == "-":
                sys.stdout.write(out_json)
            else:
                pth = Path(out_path)
                if pth.exists():
                    old = pth.read_text(encoding="utf-8")
                    diff = format_unified_diff(old, out_json, fromfile=str(pth), tofile=f"{pth} (generated)")
                    if diff:
                        print("[regression_gate] thresholds diff (existing -> generated):")
                        sys.stdout.write(diff)
                    if not bool(args.gen_force):
                        _require(False, f"thresholds output already exists: {pth} (use --gen-force to overwrite)")
                pth.write_text(out_json, encoding="utf-8")
                print(f"[regression_gate] wrote generated thresholds: {pth}")

        if not thresholds and not slice_thresholds:
            report = build_regression_gate_report(
                dataset_id=dataset_id,
                run_id=str(run_id),
                matched_case_count=len(matched_ids),
                metrics=metrics,
                thresholds_enabled=False,
                ok=True,
                failures=[],
                detail=detail,
                run_payload=run_payload,
            )
            if args.out_report_json:
                out_json_path = Path(str(args.out_report_json or "").strip())
                out_json_path.parent.mkdir(parents=True, exist_ok=True)
                write_json_file(out_json_path, report)
                print(f"[regression_gate] wrote report json: {out_json_path}")
            if args.out_report_md:
                out_md_path = Path(str(args.out_report_md or "").strip())
                out_md_path.parent.mkdir(parents=True, exist_ok=True)
                write_text_file(out_md_path, render_regression_gate_markdown(report))
                print(f"[regression_gate] wrote report markdown: {out_md_path}")
            print("[regression_gate] no thresholds set; PASS")
            return 0

        ok, failures = check_thresholds(summary=summary, thresholds=thresholds, slice_thresholds=slice_thresholds)
        report = build_regression_gate_report(
            dataset_id=dataset_id,
            run_id=str(run_id),
            matched_case_count=len(matched_ids),
            metrics=metrics,
            thresholds_enabled=bool(thresholds or slice_thresholds),
            ok=ok,
            failures=failures,
            detail=detail,
            run_payload=run_payload,
        )
        if args.out_report_json:
            out_json_path = Path(str(args.out_report_json or "").strip())
            out_json_path.parent.mkdir(parents=True, exist_ok=True)
            write_json_file(out_json_path, report)
            print(f"[regression_gate] wrote report json: {out_json_path}")
        if args.out_report_md:
            out_md_path = Path(str(args.out_report_md or "").strip())
            out_md_path.parent.mkdir(parents=True, exist_ok=True)
            write_text_file(out_md_path, render_regression_gate_markdown(report))
            print(f"[regression_gate] wrote report markdown: {out_md_path}")
        if ok:
            print("[regression_gate] thresholds: PASS")
            return 0
        for msg in failures or []:
            print(f"[regression_gate] FAIL: {msg}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
