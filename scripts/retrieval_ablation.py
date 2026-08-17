#!/usr/bin/env python3
"""
Retrieval-only regression ablation runner.

Goal: run a base regression run and N retrieval config variants, then export:
- leaderboard (summary metrics per variant)
- base-vs-variant diffs (using the existing /diff endpoints)

This script is intentionally deterministic and CI-friendly:
- stable variant ordering
- no interactive prompts
"""

import argparse
import itertools
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

_RUN_PARAM_FIELDS = (
    # Aligned with app/api/schemas/regression.py:RagasRegressionRunCreateRequest
    "retrieval_profile",
    "enable_query_alias_expansion",
    "query_alias_max_queries",
    "enable_multi_query",
    "multi_query_count",
    "multi_query_temperature",
    "multi_query_max_chars",
    "enable_hierarchy_recall",
    "hierarchy_family_collapse",
    "hierarchy_family_aggregation",
    "hierarchy_tree_dedup",
    "hierarchy_parent_depth",
    "hierarchy_sibling_window",
    "hierarchy_overfetch_factor",
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
    # Prompt template selection (kept for completeness; usually irrelevant for retrieval-only ablations).
    "prompt_template_id",
    "prompt_template_key",
    "prompt_ab_experiment_key",
)


def expand_param_grid(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """
    Expand a dict of {param: [values...]} into a cartesian product list.

    Ordering is deterministic:
    - parameters iterate in insertion order
    - the last parameter changes fastest (itertools.product behavior)
    """
    keys = [str(k) for k in (grid or {}).keys()]
    values = [list((grid or {}).get(k) or []) for k in keys]
    combos: list[dict[str, Any]] = []
    for row in itertools.product(*values):
        combos.append(dict(zip(keys, row, strict=True)))
    return combos


def variant_label_from_params(params: dict[str, Any]) -> str:
    """
    Build a stable label like: key=v__key2=v2

    Uses insertion order from params for determinism.
    """
    parts: list[str] = []
    for k, v in (params or {}).items():
        key = str(k or "").strip()
        if not key:
            continue
        parts.append(f"{key}={str(v).strip()}")
    return "__".join(parts) or "variant"


_SAFE_ARTIFACT_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def safe_artifact_name(label: str) -> str:
    """
    Convert an arbitrary label into a path-safe filename component.
    """
    s = str(label or "").strip()
    if not s:
        return "variant"
    s = s.replace("/", "_").replace("\\", "_")
    s = _SAFE_ARTIFACT_RE.sub("_", s)
    s = s.strip("._-")
    return s or "variant"


def _normalize_base_variant(matrix: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    base_raw = matrix.get("base") if isinstance(matrix.get("base"), dict) else {}
    base_label = str(base_raw.get("label") or "").strip() or "base"
    base_params = base_raw.get("rag_params") if isinstance(base_raw.get("rag_params"), dict) else {}
    return {"label": base_label, "rag_params": dict(base_params)}, dict(base_params)


def _unique_variant_label(variants: list[dict[str, Any]], label: str) -> str:
    variant_label = str(label or "").strip() or "variant"
    if not any(variant.get("label") == variant_label for variant in variants):
        return variant_label
    suffix = 2
    while True:
        candidate = f"{variant_label}__{suffix}"
        if not any(variant.get("label") == candidate for variant in variants):
            return candidate
        suffix += 1


def _append_variant(
    variants: list[dict[str, Any]],
    *,
    base_params: dict[str, Any],
    label: str,
    override: dict[str, Any],
) -> None:
    effective = {**dict(base_params), **dict(override or {})}
    if effective == dict(base_params):
        return
    variants.append(
        {
            "label": _unique_variant_label(variants, label),
            "rag_params": effective,
        }
    )


def _explicit_variant_specs(matrix: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    raw_variants = matrix.get("variants")
    if not isinstance(raw_variants, list):
        return []

    specs: list[tuple[str, dict[str, Any]]] = []
    for variant in raw_variants:
        if not isinstance(variant, dict):
            continue
        override = variant.get("rag_params") if isinstance(variant.get("rag_params"), dict) else {}
        label = str(variant.get("label") or "").strip() or variant_label_from_params(override)
        specs.append((label, override))
    return specs


def _grid_variant_specs(matrix: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    raw_grid = matrix.get("grid")
    if not isinstance(raw_grid, dict):
        return []

    grid = {str(key): list(values or []) for key, values in raw_grid.items() if isinstance(values, list)}
    combos = expand_param_grid(grid)
    return [(variant_label_from_params(combo), combo) for combo in combos]


def build_variant_plan(matrix: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Build a deterministic plan from a matrix config.

    Supported inputs:
    - Explicit variants:
      { "base": {...}, "variants": [{label, rag_params}, ...] }
    - Grid expansion:
      { "base": {...}, "grid": {param: [values...], ...} }

    Returns:
      (base_variant, variants[])

    Notes:
    - Each variant's rag_params are merged over base rag_params.
    - Variants identical to base are skipped.
    - Explicit variants are emitted first (in order), then grid-generated variants.
    """
    normalized_matrix = matrix if isinstance(matrix, dict) else {}
    base, base_params = _normalize_base_variant(normalized_matrix)
    variants: list[dict[str, Any]] = []

    for label, override in _explicit_variant_specs(normalized_matrix):
        _append_variant(
            variants,
            base_params=base_params,
            label=label,
            override=override,
        )

    for label, override in _grid_variant_specs(normalized_matrix):
        _append_variant(
            variants,
            base_params=base_params,
            label=label,
            override=override,
        )

    return base, variants


def coerce_case_bundle(obj: Any) -> tuple[str, list[dict[str, Any]]]:
    """
    Normalize case bundle payloads into: (dataset_id, items[]).

    Supported shapes:
    - Export bundle: {"schema":"mimirq.regression_cases.v1","dataset_id":"...","items":[...]}
    - Minimal bundle: {"dataset_id":"...","items":[...]}
    - Legacy list: [{"dataset_id":"...","question":"...","reference_sources":[...], ...}, ...]
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


def _load_json(path: Path) -> Any:
    # PowerShell commonly writes UTF-8 JSON with BOM; `utf-8-sig` handles both BOM/no-BOM.
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


def _require(cond: bool, msg: str) -> None:
    if cond:
        return
    print(f"[retrieval_ablation] ERROR: {msg}", file=sys.stderr)
    raise SystemExit(2)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _select_run_params(rag_params: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """
    Filter rag_params down to fields accepted by the regression run create request.

    Returns:
      (selected_params, ignored_keys[])
    """
    rp = rag_params if isinstance(rag_params, dict) else {}
    selected: dict[str, Any] = {}
    ignored: list[str] = []
    for k, v in rp.items():
        key = str(k or "").strip()
        if not key:
            continue
        if key in _RUN_PARAM_FIELDS:
            selected[key] = v
        else:
            ignored.append(key)
    ignored.sort()
    return selected, ignored


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a retrieval-only ablation matrix for regression cases.")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000/api/v1",
        help="API base url (default: %(default)s)",
    )
    parser.add_argument(
        "--tenant-id",
        default="",
        help="X-Tenant-ID header (optional in non-prod)",
    )
    parser.add_argument(
        "--user-id",
        default="",
        help="X-User-ID header (AUTH_MODE=header)",
    )
    parser.add_argument(
        "--bearer",
        default="",
        help="Bearer token (AUTH_MODE=jwt)",
    )
    parser.add_argument(
        "--cases",
        type=str,
        required=True,
        help="Path to regression cases JSON (bundle or legacy array)",
    )
    parser.add_argument(
        "--skip-import",
        action="store_true",
        help="Skip importing the cases file",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help=("Overwrite existing cases matched by (question + dataset_id)"),
    )
    parser.add_argument(
        "--matrix",
        type=str,
        required=True,
        help=("Ablation matrix JSON: {base:{...}, variants:[...]} or {grid:{...}}"),
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="ablation_out",
        help="Output directory (default: %(default)s)",
    )
    parser.add_argument(
        "--poll-sec",
        type=float,
        default=2.0,
        help="Polling interval seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=1800.0,
        help="Timeout seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=500,
        help="Max cases per run (default: %(default)s)",
    )
    parser.add_argument(
        "--no-html",
        action="store_true",
        help="Skip downloading HTML diff artifacts",
    )
    parser.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="Continue running variants even if one fails",
    )
    return parser


def _load_inputs(
    args: argparse.Namespace,
) -> tuple[Path, str, list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    cases_path = Path(args.cases)
    _require(cases_path.exists(), f"cases file not found: {cases_path}")

    matrix_path = Path(args.matrix)
    _require(matrix_path.exists(), f"matrix file not found: {matrix_path}")

    dataset_id, items = coerce_case_bundle(_load_json(cases_path))
    _require(len(items) > 0, "cases file contains no items")

    matrix_raw = _load_json(matrix_path)
    _require(isinstance(matrix_raw, dict), "matrix file must be a JSON object")

    base_variant, variants = build_variant_plan(matrix_raw)
    _require(
        len(variants) > 0,
        "matrix produced zero variants (add variants or grid)",
    )
    return cases_path, dataset_id, items, base_variant, variants


def _persist_plan(
    out_dir: Path,
    *,
    dataset_id: str,
    base_variant: dict[str, Any],
    variants: list[dict[str, Any]],
) -> None:
    _write_json(
        out_dir / "plan.resolved.json",
        {
            "dataset_id": dataset_id,
            "base": base_variant,
            "variants": variants,
            "run_param_fields": list(_RUN_PARAM_FIELDS),
        },
    )


def _poll_run(
    *,
    client: httpx.Client,
    base: str,
    run_id: str,
    poll_sec: float,
    timeout_sec: float,
) -> dict[str, Any]:
    deadline = time.time() + float(timeout_sec)
    status = ""
    detail: dict[str, Any] = {}
    while time.time() < deadline:
        r = client.get(f"{base}/evaluations/ragas/regression/runs/{run_id}", params={"include_items": False})
        r.raise_for_status()
        detail = r.json() or {}
        status = str((detail.get("run") or {}).get("status") or "")
        if status in {"completed", "failed"}:
            break
        time.sleep(float(poll_sec))

    if status != "completed":
        err = (detail.get("run") or {}).get("error_message") if isinstance(detail, dict) else None
        raise RuntimeError(f"run {run_id} status={status} error={err}")
    return detail


def _resolve_case_ids(
    *,
    client: httpx.Client,
    base: str,
    dataset_id: str,
    items: list[dict[str, Any]],
) -> list[str]:
    want_keys = set()
    for it in items:
        q = (str(it.get("question") or "")).strip()
        if q:
            want_keys.add(f"{q}\n{dataset_id}")

    matched: list[str] = []
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
                matched.append(str(row["id"]))
        skip += len(rows)
        if skip >= int(data.get("total") or 0):
            break

    return matched


def _import_cases(
    *,
    client: httpx.Client,
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
    payload = response.json() or {}
    print(
        "[retrieval_ablation] import: "
        f"created={payload.get('created')} "
        f"updated={payload.get('updated')} "
        f"skipped={payload.get('skipped')}"
    )
    if payload.get("errors"):
        print(f"[retrieval_ablation] import warnings: {len(payload.get('errors') or [])} errors")


def _run_payload(
    *,
    case_ids: list[str],
    dataset_id: str,
    max_cases: int,
    run_params: dict[str, Any],
) -> dict[str, Any]:
    return {
        "case_ids": case_ids,
        "dataset_id": dataset_id,
        "metrics": [],
        "skip_empty_contexts": True,
        "max_cases": max_cases,
        **run_params,
    }


def _create_run(
    *,
    client: httpx.Client,
    base_url: str,
    payload: dict[str, Any],
) -> str:
    response = client.post(
        f"{base_url}/evaluations/ragas/regression/runs",
        json=payload,
    )
    response.raise_for_status()
    run = response.json() or {}
    return str(run.get("id") or "").strip()


def _write_run_artifact(
    out_dir: Path,
    *,
    artifact_name: str,
    label: str,
    run_id: str,
    rag_params: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    _write_json(
        out_dir / "runs" / f"{artifact_name}.{run_id[:8]}.run.json",
        {
            "label": label,
            "run_id": run_id,
            "rag_params": rag_params,
            "summary": summary,
        },
    )


def _run_variant(
    *,
    client: httpx.Client,
    base_url: str,
    case_ids: list[str],
    dataset_id: str,
    max_cases: int,
    poll_sec: float,
    timeout_sec: float,
    label: str,
    rag_params: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    run_params, ignored = _select_run_params(rag_params)
    if ignored:
        print(f"[retrieval_ablation] {label} ignored rag_params keys: {', '.join(ignored)}")
    run_id = _create_run(
        client=client,
        base_url=base_url,
        payload=_run_payload(
            case_ids=case_ids,
            dataset_id=dataset_id,
            max_cases=max_cases,
            run_params=run_params,
        ),
    )
    _require(bool(run_id), f"failed to create run for {label} (missing run.id)")
    print(f"[retrieval_ablation] variant started: {label} id={run_id}")
    detail = _poll_run(
        client=client,
        base=base_url,
        run_id=run_id,
        poll_sec=poll_sec,
        timeout_sec=timeout_sec,
    )
    return run_id, dict((detail.get("run") or {}).get("summary") or {})


def _fetch_diff_json(
    *,
    client: httpx.Client,
    base_url: str,
    base_run_id: str,
    run_id: str,
    label: str,
    artifact_name: str,
    out_dir: Path,
) -> dict[str, Any]:
    try:
        response = client.get(
            f"{base_url}/evaluations/ragas/regression/runs/{run_id}/diff",
            params={"base_run_id": base_run_id},
        )
        response.raise_for_status()
        diff_json = response.json() or {}
        _write_json(
            out_dir / "diffs" / f"{artifact_name}.{run_id[:8]}.diff.json",
            diff_json,
        )
        return diff_json
    except Exception as exc:  # noqa: BLE001
        print(f"[retrieval_ablation] WARN: failed to fetch diff JSON for {label}: {type(exc).__name__}: {exc}")
        return {}


def _fetch_diff_html(
    *,
    client: httpx.Client,
    base_url: str,
    base_run_id: str,
    run_id: str,
    label: str,
    artifact_name: str,
    out_dir: Path,
) -> None:
    try:
        response = client.get(
            f"{base_url}/evaluations/ragas/regression/runs/{run_id}/diff/export-html",
            params={"base_run_id": base_run_id, "redact": True},
        )
        response.raise_for_status()
        (out_dir / "diffs").mkdir(parents=True, exist_ok=True)
        (out_dir / "diffs" / f"{artifact_name}.{run_id[:8]}.diff.html").write_text(
            response.text,
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[retrieval_ablation] WARN: failed to fetch diff HTML for {label}: {type(exc).__name__}: {exc}")


def _run_variants(
    *,
    client: httpx.Client,
    base_url: str,
    variants: list[dict[str, Any]],
    case_ids: list[str],
    dataset_id: str,
    max_cases: int,
    poll_sec: float,
    timeout_sec: float,
    base_run_id: str,
    out_dir: Path,
    continue_on_failure: bool,
    no_html: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    failures: list[str] = []

    for variant in variants:
        label = str(variant.get("label") or "").strip() or "variant"
        artifact_name = safe_artifact_name(label)
        rag_params = variant.get("rag_params") if isinstance(variant.get("rag_params"), dict) else {}
        try:
            run_id, summary = _run_variant(
                client=client,
                base_url=base_url,
                case_ids=case_ids,
                dataset_id=dataset_id,
                max_cases=max_cases,
                poll_sec=poll_sec,
                timeout_sec=timeout_sec,
                label=label,
                rag_params=rag_params,
            )
            _write_run_artifact(
                out_dir,
                artifact_name=artifact_name,
                label=label,
                run_id=run_id,
                rag_params=rag_params,
                summary=summary,
            )
            diff_json = _fetch_diff_json(
                client=client,
                base_url=base_url,
                base_run_id=base_run_id,
                run_id=run_id,
                label=label,
                artifact_name=artifact_name,
                out_dir=out_dir,
            )
            if not no_html:
                _fetch_diff_html(
                    client=client,
                    base_url=base_url,
                    base_run_id=base_run_id,
                    run_id=run_id,
                    label=label,
                    artifact_name=artifact_name,
                    out_dir=out_dir,
                )
            rows.append(
                {
                    "label": label,
                    "run_id": run_id,
                    "rag_params": rag_params,
                    "summary": summary,
                    "diff": diff_json,
                }
            )
        except Exception as exc:  # noqa: BLE001
            message = f"{label}: {type(exc).__name__}: {exc}"
            failures.append(message)
            print(f"[retrieval_ablation] ERROR: {message}", file=sys.stderr)
            if not continue_on_failure:
                break

    return rows, failures


def _metric(summary: dict[str, Any], key: str) -> float | None:
    try:
        value = float(summary.get(key))
    except Exception:
        return None
    if value != value:
        return None
    return value


def _leaderboard_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    leaderboard: list[dict[str, Any]] = []
    for row in rows:
        summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
        leaderboard.append(
            {
                "label": row.get("label"),
                "run_id": row.get("run_id"),
                "retrieval_recall": _metric(summary, "retrieval_recall"),
                "retrieval_hit_at_20": _metric(summary, "retrieval_hit_at_20"),
                "retrieval_mrr": _metric(summary, "retrieval_mrr"),
                "retrieval_ndcg_at_20": _metric(
                    summary,
                    "retrieval_ndcg_at_20",
                ),
                "abstain_rate": _metric(summary, "abstain_rate"),
                "items": summary.get("items"),
                "rag_params": row.get("rag_params"),
            }
        )
    leaderboard.sort(
        key=lambda row: (
            -(float(row.get("retrieval_recall") or -1.0)),
            -(float(row.get("retrieval_mrr") or -1.0)),
            -(float(row.get("retrieval_ndcg_at_20") or -1.0)),
            float(row.get("abstain_rate") or 1.0),
            str(row.get("label") or ""),
        )
    )
    return leaderboard


def _format_metric_value(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.4f}"
    return ""


def _leaderboard_markdown(leaderboard: list[dict[str, Any]]) -> str:
    lines = [
        "| label | recall | hit@20 | mrr | ndcg@20 | abstain | run_id |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in leaderboard:
        lines.append(
            ("| {label} | {recall} | {hit20} | {mrr} | {ndcg20} | {abstain} | {run_id} |").format(
                label=str(row.get("label") or ""),
                recall=_format_metric_value(row.get("retrieval_recall")),
                hit20=_format_metric_value(row.get("retrieval_hit_at_20")),
                mrr=_format_metric_value(row.get("retrieval_mrr")),
                ndcg20=_format_metric_value(row.get("retrieval_ndcg_at_20")),
                abstain=_format_metric_value(row.get("abstain_rate")),
                run_id=str(row.get("run_id") or ""),
            )
        )
    return "\n".join(lines) + "\n"


def _write_leaderboard(
    out_dir: Path,
    *,
    dataset_id: str,
    base_variant: dict[str, Any],
    base_run_id: str,
    rows: list[dict[str, Any]],
    failures: list[str],
) -> None:
    leaderboard = _leaderboard_rows(rows)
    _write_json(
        out_dir / "leaderboard.json",
        {
            "dataset_id": dataset_id,
            "base": {
                "label": base_variant.get("label"),
                "run_id": base_run_id,
            },
            "rows": leaderboard,
            "failures": failures,
        },
    )
    (out_dir / "leaderboard.md").write_text(
        _leaderboard_markdown(leaderboard),
        encoding="utf-8",
    )


def main() -> int:
    args = _build_parser().parse_args()

    headers = _headers(args)
    _require(
        bool(headers.get("X-User-ID") or headers.get("Authorization")),
        "missing auth headers (use --user-id or --bearer)",
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    _, dataset_id, items, base_variant, variants = _load_inputs(args)
    _persist_plan(
        out_dir,
        dataset_id=dataset_id,
        base_variant=base_variant,
        variants=variants,
    )

    base_url = str(args.base_url).rstrip("/")
    timeout = httpx.Timeout(30.0)

    with httpx.Client(headers=headers, timeout=timeout) as client:
        if not args.skip_import:
            _import_cases(
                client=client,
                base_url=base_url,
                dataset_id=dataset_id,
                items=items,
                overwrite=bool(args.overwrite),
            )

        case_ids = _resolve_case_ids(
            client=client,
            base=base_url,
            dataset_id=dataset_id,
            items=items,
        )
        _require(len(case_ids) > 0, "no matching cases found after import/list")
        print(f"[retrieval_ablation] matched cases: {len(case_ids)}")

        max_cases = min(int(args.max_cases or 0), len(case_ids))
        max_cases = max(1, max_cases)

        base_label = str(base_variant.get("label") or "base")
        base_rag_params = base_variant.get("rag_params") if isinstance(base_variant.get("rag_params"), dict) else {}
        base_params, ignored = _select_run_params(base_rag_params)
        if ignored:
            print(f"[retrieval_ablation] base ignored rag_params keys: {', '.join(ignored)}")

        base_run_id = _create_run(
            client=client,
            base_url=base_url,
            payload=_run_payload(
                case_ids=case_ids,
                dataset_id=dataset_id,
                max_cases=max_cases,
                run_params=base_params,
            ),
        )
        _require(bool(base_run_id), "failed to create base run (missing run.id)")
        print(f"[retrieval_ablation] base run started: {base_label} id={base_run_id}")
        base_detail = _poll_run(
            client=client,
            base=base_url,
            run_id=base_run_id,
            poll_sec=float(args.poll_sec),
            timeout_sec=float(args.timeout_sec),
        )
        base_summary = dict((base_detail.get("run") or {}).get("summary") or {})
        _write_run_artifact(
            out_dir,
            artifact_name=safe_artifact_name(base_label),
            label=base_label,
            run_id=base_run_id,
            rag_params=base_rag_params,
            summary=base_summary,
        )

        rows, failures = _run_variants(
            client=client,
            base_url=base_url,
            variants=variants,
            case_ids=case_ids,
            dataset_id=dataset_id,
            max_cases=max_cases,
            poll_sec=float(args.poll_sec),
            timeout_sec=float(args.timeout_sec),
            base_run_id=base_run_id,
            out_dir=out_dir,
            continue_on_failure=bool(args.continue_on_failure),
            no_html=bool(args.no_html),
        )
        _write_leaderboard(
            out_dir,
            dataset_id=dataset_id,
            base_variant=base_variant,
            base_run_id=base_run_id,
            rows=rows,
            failures=failures,
        )

        if failures:
            print(
                f"[retrieval_ablation] completed with failures: {len(failures)}",
                file=sys.stderr,
            )
            return 1
        print(f"[retrieval_ablation] done. variants={len(rows)} out_dir={out_dir}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
