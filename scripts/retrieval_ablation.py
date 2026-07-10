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
    m = matrix if isinstance(matrix, dict) else {}
    base_raw = m.get("base") if isinstance(m.get("base"), dict) else {}
    base_label = str(base_raw.get("label") or "").strip() or "base"
    base_params = base_raw.get("rag_params") if isinstance(base_raw.get("rag_params"), dict) else {}
    base = {"label": base_label, "rag_params": dict(base_params)}

    out: list[dict[str, Any]] = []

    def _unique_label(label: str) -> str:
        lab = str(label or "").strip() or "variant"
        if not any(v.get("label") == lab for v in out):
            return lab
        i = 2
        while True:
            cand = f"{lab}__{i}"
            if not any(v.get("label") == cand for v in out):
                return cand
            i += 1

    def _add_variant(*, label: str, override: dict[str, Any]) -> None:
        effective = {**dict(base_params), **dict(override or {})}
        if effective == dict(base_params):
            return
        out.append({"label": _unique_label(label), "rag_params": effective})

    raw_variants = m.get("variants")
    if isinstance(raw_variants, list):
        for v in raw_variants:
            if not isinstance(v, dict):
                continue
            override = v.get("rag_params") if isinstance(v.get("rag_params"), dict) else {}
            label = str(v.get("label") or "").strip() or variant_label_from_params(override)
            _add_variant(label=label, override=override)

    raw_grid = m.get("grid")
    if isinstance(raw_grid, dict):
        combos = expand_param_grid({str(k): list(v or []) for k, v in raw_grid.items() if isinstance(v, list)})
        for combo in combos:
            _add_variant(label=variant_label_from_params(combo), override=combo)

    return base, out


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


def main() -> int:
    p = argparse.ArgumentParser(description="Run a retrieval-only ablation matrix for regression cases.")
    p.add_argument("--base-url", default="http://localhost:8000/api/v1", help="API base url (default: %(default)s)")
    p.add_argument("--tenant-id", default="", help="X-Tenant-ID header (optional in non-prod)")
    p.add_argument("--user-id", default="", help="X-User-ID header (AUTH_MODE=header)")
    p.add_argument("--bearer", default="", help="Bearer token (AUTH_MODE=jwt)")
    p.add_argument("--cases", type=str, required=True, help="Path to regression cases JSON (bundle or legacy array)")
    p.add_argument("--skip-import", action="store_true", help="Skip importing the cases file")
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing cases matched by (question + dataset_id)")

    p.add_argument("--matrix", type=str, required=True, help="Ablation matrix JSON: {base:{...}, variants:[...]} or {grid:{...}}")
    p.add_argument("--out-dir", type=str, default="ablation_out", help="Output directory (default: %(default)s)")

    p.add_argument("--poll-sec", type=float, default=2.0, help="Polling interval seconds (default: %(default)s)")
    p.add_argument("--timeout-sec", type=float, default=1800.0, help="Timeout seconds (default: %(default)s)")
    p.add_argument("--max-cases", type=int, default=500, help="Max cases per run (default: %(default)s)")
    p.add_argument("--no-html", action="store_true", help="Skip downloading HTML diff artifacts")
    p.add_argument("--continue-on-failure", action="store_true", help="Continue running variants even if one fails")

    args = p.parse_args()

    headers = _headers(args)
    _require(bool(headers.get("X-User-ID") or headers.get("Authorization")), "missing auth headers (use --user-id or --bearer)")

    cases_path = Path(args.cases)
    _require(cases_path.exists(), f"cases file not found: {cases_path}")
    matrix_path = Path(args.matrix)
    _require(matrix_path.exists(), f"matrix file not found: {matrix_path}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    dataset_id, items = coerce_case_bundle(_load_json(cases_path))
    _require(len(items) > 0, "cases file contains no items")

    matrix_raw = _load_json(matrix_path)
    _require(isinstance(matrix_raw, dict), "matrix file must be a JSON object")
    base_variant, variants = build_variant_plan(matrix_raw)
    _require(len(variants) > 0, "matrix produced zero variants (add variants or grid)")

    # Persist the resolved plan for reproducibility.
    _write_json(
        out_dir / "plan.resolved.json",
        {
            "dataset_id": dataset_id,
            "base": base_variant,
            "variants": variants,
            "run_param_fields": list(_RUN_PARAM_FIELDS),
        },
    )

    base_url = str(args.base_url).rstrip("/")
    timeout = httpx.Timeout(30.0)

    with httpx.Client(headers=headers, timeout=timeout) as client:
        if not args.skip_import:
            r = client.post(
                f"{base_url}/evaluations/ragas/regression/cases/import",
                json={
                    "dataset_id": dataset_id,
                    "overwrite": bool(args.overwrite),
                    "max_items": min(2000, len(items)),
                    "items": items,
                },
            )
            r.raise_for_status()
            imp = r.json() or {}
            print(
                f"[retrieval_ablation] import: created={imp.get('created')} updated={imp.get('updated')} skipped={imp.get('skipped')}"
            )
            if imp.get("errors"):
                print(f"[retrieval_ablation] import warnings: {len(imp.get('errors') or [])} errors")

        case_ids = _resolve_case_ids(client=client, base=base_url, dataset_id=dataset_id, items=items)
        _require(len(case_ids) > 0, "no matching cases found after import/list")
        print(f"[retrieval_ablation] matched cases: {len(case_ids)}")

        max_cases = min(int(args.max_cases or 0), len(case_ids))
        max_cases = max(1, max_cases)

        # ---- Base run ----
        base_params, ignored = _select_run_params(base_variant.get("rag_params") or {})
        if ignored:
            print(f"[retrieval_ablation] base ignored rag_params keys: {', '.join(ignored)}")
        r = client.post(
            f"{base_url}/evaluations/ragas/regression/runs",
            json={
                "case_ids": case_ids,
                "dataset_id": dataset_id,
                "metrics": [],  # retrieval-only
                "skip_empty_contexts": True,
                "max_cases": max_cases,
                **base_params,
            },
        )
        r.raise_for_status()
        base_run = r.json() or {}
        base_run_id = str(base_run.get("id") or "").strip()
        _require(bool(base_run_id), "failed to create base run (missing run.id)")
        print(f"[retrieval_ablation] base run started: {base_variant.get('label')} id={base_run_id}")

        base_detail = _poll_run(
            client=client,
            base=base_url,
            run_id=base_run_id,
            poll_sec=float(args.poll_sec),
            timeout_sec=float(args.timeout_sec),
        )
        base_summary = dict((base_detail.get("run") or {}).get("summary") or {})
        base_art = safe_artifact_name(str(base_variant.get("label") or "base"))
        _write_json(
            out_dir / "runs" / f"{base_art}.{base_run_id[:8]}.run.json",
            {"label": base_variant.get("label"), "run_id": base_run_id, "rag_params": base_variant.get("rag_params"), "summary": base_summary},
        )

        # ---- Variant runs ----
        rows: list[dict[str, Any]] = []
        failures: list[str] = []
        for v in variants:
            label = str(v.get("label") or "").strip() or "variant"
            art = safe_artifact_name(label)
            rag_params = v.get("rag_params") if isinstance(v.get("rag_params"), dict) else {}
            run_params, ignored = _select_run_params(rag_params)
            if ignored:
                print(f"[retrieval_ablation] {label} ignored rag_params keys: {', '.join(ignored)}")

            try:
                r = client.post(
                    f"{base_url}/evaluations/ragas/regression/runs",
                    json={
                        "case_ids": case_ids,
                        "dataset_id": dataset_id,
                        "metrics": [],  # retrieval-only
                        "skip_empty_contexts": True,
                        "max_cases": max_cases,
                        **run_params,
                    },
                )
                r.raise_for_status()
                run = r.json() or {}
                run_id = str(run.get("id") or "").strip()
                _require(bool(run_id), f"failed to create run for {label} (missing run.id)")
                print(f"[retrieval_ablation] variant started: {label} id={run_id}")

                detail = _poll_run(
                    client=client,
                    base=base_url,
                    run_id=run_id,
                    poll_sec=float(args.poll_sec),
                    timeout_sec=float(args.timeout_sec),
                )
                summary = dict((detail.get("run") or {}).get("summary") or {})
                _write_json(
                    out_dir / "runs" / f"{art}.{run_id[:8]}.run.json",
                    {"label": label, "run_id": run_id, "rag_params": rag_params, "summary": summary},
                )

                diff_json: dict[str, Any] = {}
                try:
                    r = client.get(
                        f"{base_url}/evaluations/ragas/regression/runs/{run_id}/diff",
                        params={"base_run_id": base_run_id},
                    )
                    r.raise_for_status()
                    diff_json = r.json() or {}
                    _write_json(out_dir / "diffs" / f"{art}.{run_id[:8]}.diff.json", diff_json)
                except Exception as exc:  # noqa: BLE001
                    print(f"[retrieval_ablation] WARN: failed to fetch diff JSON for {label}: {type(exc).__name__}: {exc}")

                if not bool(args.no_html):
                    try:
                        r = client.get(
                            f"{base_url}/evaluations/ragas/regression/runs/{run_id}/diff/export-html",
                            params={"base_run_id": base_run_id, "redact": True},
                        )
                        r.raise_for_status()
                        (out_dir / "diffs").mkdir(parents=True, exist_ok=True)
                        (out_dir / "diffs" / f"{art}.{run_id[:8]}.diff.html").write_text(r.text, encoding="utf-8")
                    except Exception as exc:  # noqa: BLE001
                        print(
                            f"[retrieval_ablation] WARN: failed to fetch diff HTML for {label}: {type(exc).__name__}: {exc}"
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
                msg = f"{label}: {type(exc).__name__}: {exc}"
                failures.append(msg)
                print(f"[retrieval_ablation] ERROR: {msg}", file=sys.stderr)
                if not bool(args.continue_on_failure):
                    break

        # ---- Leaderboard ----
        def _metric(summary: dict[str, Any], key: str) -> float | None:
            try:
                v = float(summary.get(key))
            except Exception:
                return None
            if v != v:
                return None
            return v

        leaderboard: list[dict[str, Any]] = []
        for row in rows:
            s = row.get("summary") if isinstance(row.get("summary"), dict) else {}
            leaderboard.append(
                {
                    "label": row.get("label"),
                    "run_id": row.get("run_id"),
                    "retrieval_recall": _metric(s, "retrieval_recall"),
                    "retrieval_hit_at_20": _metric(s, "retrieval_hit_at_20"),
                    "retrieval_mrr": _metric(s, "retrieval_mrr"),
                    "retrieval_ndcg_at_20": _metric(s, "retrieval_ndcg_at_20"),
                    "abstain_rate": _metric(s, "abstain_rate"),
                    "items": s.get("items"),
                    "rag_params": row.get("rag_params"),
                }
            )

        leaderboard.sort(
            key=lambda r: (
                -(float(r.get("retrieval_recall") or -1.0)),
                -(float(r.get("retrieval_mrr") or -1.0)),
                -(float(r.get("retrieval_ndcg_at_20") or -1.0)),
                float(r.get("abstain_rate") or 1.0),
                str(r.get("label") or ""),
            )
        )

        _write_json(
            out_dir / "leaderboard.json",
            {
                "dataset_id": dataset_id,
                "base": {"label": base_variant.get("label"), "run_id": base_run_id},
                "rows": leaderboard,
                "failures": failures,
            },
        )

        # Also emit a quick markdown table for human scanning in PR artifacts.
        md_lines = [
            "| label | recall | hit@20 | mrr | ndcg@20 | abstain | run_id |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
        for r in leaderboard:
            md_lines.append(
                "| {label} | {recall} | {hit20} | {mrr} | {ndcg20} | {abstain} | {run_id} |".format(
                    label=str(r.get("label") or ""),
                    recall=f"{r.get('retrieval_recall'):.4f}" if isinstance(r.get("retrieval_recall"), (int, float)) else "",
                    hit20=f"{r.get('retrieval_hit_at_20'):.4f}" if isinstance(r.get("retrieval_hit_at_20"), (int, float)) else "",
                    mrr=f"{r.get('retrieval_mrr'):.4f}" if isinstance(r.get("retrieval_mrr"), (int, float)) else "",
                    ndcg20=f"{r.get('retrieval_ndcg_at_20'):.4f}" if isinstance(r.get("retrieval_ndcg_at_20"), (int, float)) else "",
                    abstain=f"{r.get('abstain_rate'):.4f}" if isinstance(r.get("abstain_rate"), (int, float)) else "",
                    run_id=str(r.get("run_id") or ""),
                )
            )
        (out_dir / "leaderboard.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

        if failures:
            print(f"[retrieval_ablation] completed with failures: {len(failures)}", file=sys.stderr)
            return 1
        print(f"[retrieval_ablation] done. variants={len(rows)} out_dir={out_dir}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
