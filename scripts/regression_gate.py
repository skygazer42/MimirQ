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


import argparse
import difflib
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

REGISTERED_CHUNK_PLUGIN_REF_RE = re.compile(
    r"^plugin:[a-z0-9][a-z0-9_.-]{0,63}@[A-Za-z0-9][A-Za-z0-9_.+-]{0,31}:chunk$"
)


def _load_json(path: Path) -> Any:
    # PowerShell commonly writes UTF-8 JSON with BOM; `utf-8-sig` handles both BOM/no-BOM.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_file(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text_file(path: Path, content: str) -> None:
    path.write_text(str(content or ""), encoding="utf-8")


def coerce_case_bundle(obj: Any, *, allow_review_only: bool = False) -> tuple[str, list[dict[str, Any]]]:
    """
    Normalize case bundle payloads into: (dataset_id, items[]).

    Supported shapes:
    - Export bundle v1: {"schema":"mimirq.regression_cases.v1","dataset_id":"...","items":[...]}
    - Minimal bundle: {"dataset_id":"...","items":[...]}
    - Legacy: [{"dataset_id":"...","question":"...","reference_sources":[...], ...}, ...]
    """
    def _item_is_review_only_local_sample(item: dict[str, Any]) -> bool:
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        return (
            item.get("review_only") is True
            or str(item.get("reference_source_mode") or "").strip() == "local_sample_synthetic"
            or extra.get("review_only") is True
            or str(extra.get("reference_source_mode") or "").strip() == "local_sample_synthetic"
        )

    def _reject_review_only_items(items: list[dict[str, Any]]) -> None:
        if allow_review_only:
            return
        if any(_item_is_review_only_local_sample(item) for item in items):
            raise ValueError("review_only local Golden items cannot be imported; use --skip-import or generate dataset goldens from indexed chunks")

    if isinstance(obj, dict) and isinstance(obj.get("items"), list):
        if (
            not allow_review_only
            and (
                obj.get("review_only") is True
                or str(obj.get("reference_source_mode") or "").strip() == "local_sample_synthetic"
            )
        ):
            raise ValueError("review_only local Golden bundles cannot be imported; use --skip-import or generate dataset goldens from indexed chunks")
        ds = str(obj.get("dataset_id") or "").strip()
        if ds:
            items = [x for x in obj.get("items") if isinstance(x, dict)]  # type: ignore[union-attr]
            _reject_review_only_items(items)
            # Defensive: strip accidental dataset_id field inside each item (API expects dataset_id only at top-level).
            cleaned = [{k: v for k, v in it.items() if k != "dataset_id"} for it in items]
            return ds, cleaned
        # Fall back: accept bundles that forgot top-level dataset_id but include it per item.
        return coerce_case_bundle(list(obj.get("items") or []), allow_review_only=allow_review_only)

    if isinstance(obj, list):
        items = [x for x in obj if isinstance(x, dict)]
        _reject_review_only_items(items)
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


def build_plugin_golden_import_payload(
    *,
    dataset_id: str,
    plugin_ref: str,
    max_items: int,
    max_chunks: int,
    include_unmarked_chunks: bool,
    overwrite: bool,
) -> dict[str, Any]:
    clean_plugin_ref = str(plugin_ref or "").strip()
    if not REGISTERED_CHUNK_PLUGIN_REF_RE.fullmatch(clean_plugin_ref):
        raise ValueError("plugin_golden_ref must be a registered chunk plugin ref")
    return {
        "dataset_id": str(dataset_id),
        "plugin_ref": clean_plugin_ref,
        "max_items": int(max_items),
        "max_chunks": int(max_chunks),
        "include_unmarked_chunks": bool(include_unmarked_chunks),
        "overwrite": bool(overwrite),
    }


def extract_plugin_golden_import_case_ids(response: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    import_result = response.get("import_result") if isinstance(response, dict) else None
    if not isinstance(import_result, dict):
        raise ValueError("plugin Golden import response missing import_result")
    if import_result.get("errors"):
        raise ValueError(f"plugin Golden import returned errors: {json.dumps(import_result.get('errors'), ensure_ascii=False)}")

    raw_ids = import_result.get("case_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raw_ids = [
            *(import_result.get("created_case_ids") or []),
            *(import_result.get("updated_case_ids") or []),
            *(import_result.get("skipped_case_ids") or []),
        ]

    case_ids = [str(item).strip() for item in (raw_ids or []) if str(item or "").strip()]
    if not case_ids:
        draft = response.get("draft") if isinstance(response.get("draft"), dict) else {}
        raise ValueError(f"plugin Golden import returned no case ids; draft items={draft.get('items_total')}")
    return import_result, case_ids


def summarize_plugin_golden_source_from_import_response(response: dict[str, Any]) -> dict[str, Any]:
    draft = response.get("draft") if isinstance(response, dict) else None
    draft = draft if isinstance(draft, dict) else {}
    out: dict[str, Any] = {}

    for source_key, target_key in (
        ("plugin_id", "plugin_id"),
        ("plugin_version", "plugin_version"),
        ("plugin_ref", "plugin_ref"),
    ):
        value = str(draft.get(source_key) or "").strip()
        if value:
            out[target_key] = value

    try:
        out["draft_items_total"] = int(draft.get("items_total") or 0)
    except Exception:
        out["draft_items_total"] = 0

    bundle = draft.get("bundle") if isinstance(draft.get("bundle"), dict) else {}
    items = bundle.get("items") if isinstance(bundle, dict) else []
    if isinstance(items, list):
        for item in items:
            extra = item.get("extra") if isinstance(item, dict) else None
            package_hash = str((extra or {}).get("plugin_package_hash") or "").strip() if isinstance(extra, dict) else ""
            if package_hash:
                out["plugin_package_hash"] = package_hash
                break

    return out


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


# ==================== Query-set health integration (Gap9) ====================

_QUERYSET_HEALTH_DIFF_SCHEMA_V1 = "mimirq.queryset_health_diff.v1"
_QUERYSET_HEALTH_DEFAULT_POLICY: dict[str, float | int] = {
    "hit_at_k_drop_threshold": 0.03,
    "mrr_drop_threshold": 0.03,
    "ndcg_drop_threshold": 0.03,
    "p95_latency_regression_ms": 20.0,
    "miss_rate_regression_threshold": 0.05,
    "weak_hit_rate_regression_threshold": 0.08,
    "weak_hit_rr_threshold": 0.2,
    "hard_cases_limit": 5,
}


def _qs_as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or isinstance(value, bool):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _qs_delta(current: float, baseline: float, *, digits: int) -> float:
    return round(float(current) - float(baseline), int(digits))


def _qs_hard_case_ids(snapshot: dict[str, Any], *, max_ids: int) -> list[str]:
    risk = snapshot.get("risk") if isinstance(snapshot.get("risk"), dict) else {}
    rows = risk.get("hard_cases") if isinstance(risk.get("hard_cases"), list) else []
    out: list[str] = []
    cap = max(1, int(max_ids or 1))
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "").strip()
        if not cid:
            continue
        if cid not in out:
            out.append(cid)
        if len(out) >= cap:
            break
    return out


def _qs_flag_set(snapshot: dict[str, Any]) -> set[str]:
    raw = snapshot.get("degradation_flags")
    if not isinstance(raw, list):
        return set()
    out: set[str] = set()
    for item in raw:
        key = str(item or "").strip()
        if key:
            out.add(key)
    return out


def diff_queryset_health_snapshots(
    *,
    baseline: dict[str, Any],
    current: dict[str, Any],
    max_hard_case_ids: int = 20,
) -> dict[str, Any]:
    """
    Minimal diff for `mimirq.queryset_health_snapshot.v1` snapshots.

    Kept local to the gate script to avoid importing backend modules in CI runners.
    """
    base_metrics = baseline.get("metrics") if isinstance(baseline.get("metrics"), dict) else {}
    curr_metrics = current.get("metrics") if isinstance(current.get("metrics"), dict) else {}
    base_risk = baseline.get("risk") if isinstance(baseline.get("risk"), dict) else {}
    curr_risk = current.get("risk") if isinstance(current.get("risk"), dict) else {}

    metric_deltas = {
        "hit_at_k_delta": _qs_delta(_qs_as_float(curr_metrics.get("hit_at_k")), _qs_as_float(base_metrics.get("hit_at_k")), digits=6),
        "mrr_delta": _qs_delta(_qs_as_float(curr_metrics.get("mrr")), _qs_as_float(base_metrics.get("mrr")), digits=6),
        "ndcg_at_k_delta": _qs_delta(_qs_as_float(curr_metrics.get("ndcg_at_k")), _qs_as_float(base_metrics.get("ndcg_at_k")), digits=6),
        "p95_latency_ms_delta": _qs_delta(
            _qs_as_float(curr_metrics.get("p95_latency_ms")),
            _qs_as_float(base_metrics.get("p95_latency_ms")),
            digits=3,
        ),
        "miss_rate_delta": _qs_delta(_qs_as_float(curr_risk.get("miss_rate")), _qs_as_float(base_risk.get("miss_rate")), digits=6),
        "weak_hit_rate_delta": _qs_delta(
            _qs_as_float(curr_risk.get("weak_hit_rate")),
            _qs_as_float(base_risk.get("weak_hit_rate")),
            digits=6,
        ),
    }

    base_hash = str(baseline.get("policy_hash") or "").strip()
    curr_hash = str(current.get("policy_hash") or "").strip()
    policy_changed = bool((base_hash or curr_hash) and base_hash != curr_hash)

    base_cases = set(_qs_hard_case_ids(baseline, max_ids=max_hard_case_ids))
    curr_cases = set(_qs_hard_case_ids(current, max_ids=max_hard_case_ids))

    base_flags = _qs_flag_set(baseline)
    curr_flags = _qs_flag_set(current)

    return {
        "schema": _QUERYSET_HEALTH_DIFF_SCHEMA_V1,
        "baseline_generated_at": str(baseline.get("generated_at") or ""),
        "current_generated_at": str(current.get("generated_at") or ""),
        "policy": {
            "baseline_source": str(baseline.get("policy_source") or ""),
            "current_source": str(current.get("policy_source") or ""),
            "baseline_hash": base_hash,
            "current_hash": curr_hash,
            "changed": policy_changed,
        },
        "metric_deltas": metric_deltas,
        "hard_case_drift": {
            "added_ids": sorted(curr_cases - base_cases),
            "removed_ids": sorted(base_cases - curr_cases),
            "retained_ids": sorted(base_cases & curr_cases),
        },
        "degradation_flags_drift": {
            "added_flags": sorted(curr_flags - base_flags),
            "removed_flags": sorted(base_flags - curr_flags),
            "retained_flags": sorted(base_flags & curr_flags),
        },
    }


def _qs_resolve_policy(snapshot: dict[str, Any]) -> dict[str, float | int]:
    raw = snapshot.get("policy") if isinstance(snapshot.get("policy"), dict) else {}
    out: dict[str, float | int] = dict(_QUERYSET_HEALTH_DEFAULT_POLICY)
    for k in out.keys():
        if k not in raw:
            continue
        v = raw.get(k)
        if k in {"hard_cases_limit"}:
            try:
                out[k] = int(v)
            except Exception:
                pass
            continue
        try:
            out[k] = float(v)  # type: ignore[assignment]
        except Exception:
            pass
    return out


def compute_queryset_health_degradation_flags(
    *,
    baseline: dict[str, Any],
    current: dict[str, Any],
    policy: dict[str, float | int],
) -> list[str]:
    base_metrics = baseline.get("metrics") if isinstance(baseline.get("metrics"), dict) else {}
    curr_metrics = current.get("metrics") if isinstance(current.get("metrics"), dict) else {}
    base_risk = baseline.get("risk") if isinstance(baseline.get("risk"), dict) else {}
    curr_risk = current.get("risk") if isinstance(current.get("risk"), dict) else {}

    hit_at_k_delta = _qs_delta(_qs_as_float(curr_metrics.get("hit_at_k")), _qs_as_float(base_metrics.get("hit_at_k")), digits=6)
    mrr_delta = _qs_delta(_qs_as_float(curr_metrics.get("mrr")), _qs_as_float(base_metrics.get("mrr")), digits=6)
    ndcg_delta = _qs_delta(_qs_as_float(curr_metrics.get("ndcg_at_k")), _qs_as_float(base_metrics.get("ndcg_at_k")), digits=6)
    p95_delta = _qs_delta(_qs_as_float(curr_metrics.get("p95_latency_ms")), _qs_as_float(base_metrics.get("p95_latency_ms")), digits=3)
    miss_rate_delta = _qs_delta(_qs_as_float(curr_risk.get("miss_rate")), _qs_as_float(base_risk.get("miss_rate")), digits=6)
    weak_hit_rate_delta = _qs_delta(_qs_as_float(curr_risk.get("weak_hit_rate")), _qs_as_float(base_risk.get("weak_hit_rate")), digits=6)

    flags: list[str] = []
    if hit_at_k_delta <= -float(policy.get("hit_at_k_drop_threshold") or 0.03):
        flags.append("hit_at_k_drop")
    if mrr_delta <= -float(policy.get("mrr_drop_threshold") or 0.03):
        flags.append("mrr_drop")
    if ndcg_delta <= -float(policy.get("ndcg_drop_threshold") or 0.03):
        flags.append("ndcg_drop")
    if p95_delta >= float(policy.get("p95_latency_regression_ms") or 20.0):
        flags.append("p95_latency_regression")
    if miss_rate_delta >= float(policy.get("miss_rate_regression_threshold") or 0.05):
        flags.append("miss_rate_regression")
    if weak_hit_rate_delta >= float(policy.get("weak_hit_rate_regression_threshold") or 0.08):
        flags.append("weak_hit_rate_regression")

    return flags


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
    case_source: dict[str, Any] | None = None,
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
        "case_source": dict(case_source or {"kind": "case_bundle"}),
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
    notes = [str(x) for x in (payload.get("notes") or []) if str(x or "").strip()]
    qs = payload.get("queryset_health") if isinstance(payload.get("queryset_health"), dict) else {}
    case_source = payload.get("case_source") if isinstance(payload.get("case_source"), dict) else {}
    case_source_kind = str(case_source.get("kind") or "case_bundle")
    plugin_golden_ref = str(case_source.get("plugin_ref") or "").strip()
    plugin_package_hash = str(case_source.get("plugin_package_hash") or "").strip()

    lines = [
        "# Retrieval Regression Gate Report",
        "",
        f"- Gate status: `{payload.get('gate_status') or 'unknown'}`",
        f"- Run status: `{payload.get('run_status') or 'unknown'}`",
        f"- Dataset ID: `{payload.get('dataset_id') or ''}`",
        f"- Run ID: `{payload.get('run_id') or ''}`",
        f"- Case source: `{case_source_kind}`",
        f"- Matched cases: `{int(payload.get('matched_case_count') or 0)}`",
        f"- Thresholds enabled: `{bool(payload.get('thresholds_enabled'))}`",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    if plugin_golden_ref:
        lines.insert(8, f"- Plugin Golden ref: `{plugin_golden_ref}`")
    if plugin_package_hash:
        insert_at = 9 if plugin_golden_ref else 8
        lines.insert(insert_at, f"- Plugin package hash: `{plugin_package_hash}`")

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

    if qs:
        flags = qs.get("degradation_flags")
        flags = [str(x) for x in (flags or []) if str(x or "").strip()] if isinstance(flags, list) else []
        diff = qs.get("diff") if isinstance(qs.get("diff"), dict) else {}
        deltas = diff.get("metric_deltas") if isinstance(diff.get("metric_deltas"), dict) else {}
        lines.extend(
            [
                "## Query-set Health",
                "",
                f"- Policy: `{qs.get('policy') or ''}`",
                f"- Degradation flags: `{', '.join(flags) if flags else 'none'}`",
                "",
                "| Delta metric | Value |",
                "| --- | ---: |",
                f"| hit_at_k_delta | {_coerce_float(deltas.get('hit_at_k_delta'))} |",
                f"| mrr_delta | {_coerce_float(deltas.get('mrr_delta'))} |",
                f"| ndcg_at_k_delta | {_coerce_float(deltas.get('ndcg_at_k_delta'))} |",
                f"| p95_latency_ms_delta | {_coerce_float(deltas.get('p95_latency_ms_delta'))} |",
                f"| miss_rate_delta | {_coerce_float(deltas.get('miss_rate_delta'))} |",
                f"| weak_hit_rate_delta | {_coerce_float(deltas.get('weak_hit_rate_delta'))} |",
                "",
            ]
        )

    if notes:
        lines.extend(["## Notes", ""])
        for msg in notes:
            lines.append(f"- {msg}")
        lines.append("")

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


def normalize_threshold_case_source(case_source: Any) -> dict[str, Any]:
    """
    Keep only stable provenance fields that are safe to pin in thresholds files.

    Runtime-only import details such as case ids are intentionally excluded:
    those identify one import operation, not the plugin package that produced
    the Golden baseline.
    """
    if not isinstance(case_source, dict):
        return {}

    kind = str(case_source.get("kind") or "").strip()
    if not kind:
        return {}

    out: dict[str, Any] = {"kind": kind}
    if kind != "plugin_golden":
        return out

    for key in ("plugin_ref", "plugin_id", "plugin_version", "plugin_package_hash"):
        value = str(case_source.get(key) or "").strip()
        if value:
            out[key] = value

    if "draft_items_total" in case_source:
        try:
            out["draft_items_total"] = int(case_source.get("draft_items_total") or 0)
        except Exception:
            pass

    return out


def compare_threshold_case_source(*, expected: Any, actual: Any) -> list[str]:
    """
    Return mismatch messages between a thresholds baseline source and this run.

    Backward compatible: thresholds files without case_source do not constrain
    the run. When a field is present in the thresholds source, the current run
    must match it exactly.
    """
    expected_source = normalize_threshold_case_source(expected)
    if not expected_source:
        return []

    actual_source = normalize_threshold_case_source(actual)
    failures: list[str] = []
    if not actual_source:
        return ["thresholds case_source is set but current run has no case_source"]

    expected_kind = str(expected_source.get("kind") or "").strip()
    actual_kind = str(actual_source.get("kind") or "").strip()
    if expected_kind and expected_kind != actual_kind:
        failures.append(f"kind expected {expected_kind!r}, got {actual_kind!r}")
        return failures

    for key, expected_value in expected_source.items():
        if key == "kind":
            continue
        actual_value = actual_source.get(key)
        if actual_value != expected_value:
            failures.append(f"{key} expected {expected_value!r}, got {actual_value!r}")

    return failures


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
    case_source: dict[str, Any] | None = None,
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

    cfg: dict[str, Any] = {
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
    threshold_case_source = normalize_threshold_case_source(case_source)
    if threshold_case_source:
        cfg["case_source"] = threshold_case_source
    return cfg


def _require(cond: bool, msg: str) -> None:
    if cond:
        return
    print(f"[regression_gate] ERROR: {msg}", file=sys.stderr)
    sys.exit(2)


def _fetch_run_detail(
    client: httpx.Client,
    *,
    base_url: str,
    run_id: str,
    include_items: bool,
    include_contexts: bool | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"include_items": bool(include_items)}
    if include_contexts is not None:
        params["include_contexts"] = bool(include_contexts)
    response = client.get(f"{base_url}/evaluations/ragas/regression/runs/{run_id}", params=params)
    response.raise_for_status()
    detail = response.json() or {}
    return detail if isinstance(detail, dict) else {}


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

    p.add_argument("--cases", type=str, default="", help="Path to regression cases JSON (export bundle or items array)")
    p.add_argument("--dataset-id", type=str, default="", help="Dataset UUID (required when using --plugin-golden-ref)")
    p.add_argument(
        "--plugin-golden-ref",
        type=str,
        default="",
        help="Use plugin-generated Golden cases as the case source, e.g. plugin:<id>@<version>:chunk (optional)",
    )
    p.add_argument("--plugin-golden-max-items", type=int, default=500, help="Max plugin Golden cases to import (default: %(default)s)")
    p.add_argument("--plugin-golden-max-chunks", type=int, default=5000, help="Max chunks to inspect for plugin Golden import (default: %(default)s)")
    p.add_argument(
        "--plugin-golden-include-unmarked-chunks",
        action="store_true",
        help=(
            "Debug only: request plugin Golden import to inspect unmarked chunks. "
            "The API rejects this unless PYTHON_PIPELINE_PLUGIN_ALLOW_UNMARKED_GOLDEN_CHUNKS=true."
        ),
    )
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

    # Gap9 (P2): Optional queryset-health gate integration.
    p.add_argument(
        "--queryset-health-baseline",
        default="",
        help="Baseline queryset health snapshot JSON path (optional; schema: mimirq.queryset_health_snapshot.v1)",
    )
    p.add_argument(
        "--queryset-health-current",
        default="",
        help="Current queryset health snapshot JSON path (optional; defaults to artifacts/queryset_health.snapshot.json when present)",
    )
    p.add_argument(
        "--queryset-health-policy",
        default="fail",
        help="Queryset health gate policy: warn|fail (default: %(default)s)",
    )
    p.add_argument(
        "--queryset-health-diff-out",
        default="",
        help="Write computed queryset health diff JSON to a file (optional; schema: mimirq.queryset_health_diff.v1)",
    )

    # Optional: generate structured thresholds (v2) from the run summary.
    p.add_argument(
        "--generate-thresholds-out",
        default="",
        help="Write generated thresholds (v2) from this run summary to a JSON file (optional; use '-' for stdout)",
    )
    p.add_argument(
        "--gen-metrics",
        default="retrieval_recall,retrieval_hit_at_20,retrieval_mrr,retrieval_ndcg_at_20,expected_metadata_hit_rate,expected_metadata_recall,multihop_path_completeness,multihop_order_consistency,multihop_chain_hit_rate,abstain_rate",
        help="Comma-separated top-level metrics to generate thresholds for (default: %(default)s)",
    )
    p.add_argument(
        "--gen-slice-dims",
        default="file_type,language,hit_type,quality",
        help="Comma-separated slice dims to generate per-slice thresholds for (default: %(default)s)",
    )
    p.add_argument(
        "--gen-slice-metrics",
        default="retrieval_recall,retrieval_hit_at_20,expected_metadata_hit_rate,expected_metadata_recall,multihop_path_completeness,multihop_order_consistency,abstain_rate",
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

    cases_arg = str(args.cases or "").strip()
    plugin_golden_ref = str(getattr(args, "plugin_golden_ref", "") or "").strip()
    _require(
        bool(cases_arg) != bool(plugin_golden_ref),
        "set exactly one case source: --cases or --plugin-golden-ref",
    )
    _require(
        not (plugin_golden_ref and bool(args.skip_import)),
        "--skip-import cannot be used with --plugin-golden-ref",
    )

    items: list[dict[str, Any]] = []
    if plugin_golden_ref:
        dataset_id = str(getattr(args, "dataset_id", "") or "").strip()
        _require(bool(dataset_id), "--dataset-id is required with --plugin-golden-ref")
    else:
        cases_path = Path(cases_arg)
        _require(cases_path.exists(), f"cases file not found: {cases_path}")
        try:
            dataset_id, items = coerce_case_bundle(_load_json(cases_path), allow_review_only=bool(args.skip_import))
        except ValueError as exc:
            _require(False, str(exc))
        _require(len(items) > 0, "cases file contains no items")

    metrics = parse_metrics_list(args.metrics)

    thresholds: dict[str, dict[str, float]] = {}
    slice_thresholds: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    threshold_case_source: dict[str, Any] = {}
    if args.thresholds:
        th_path = Path(args.thresholds)
        _require(th_path.exists(), f"thresholds file not found: {th_path}")
        raw_th = _load_json(th_path)
        if not isinstance(raw_th, dict):
            _require(False, "thresholds must be a JSON object")
        thresholds, slice_thresholds = parse_thresholds_config(raw_th)
        threshold_case_source = normalize_threshold_case_source(raw_th.get("case_source"))

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
    case_source: dict[str, Any] = (
        {
            "kind": "plugin_golden",
            "plugin_ref": plugin_golden_ref,
            "max_items": int(getattr(args, "plugin_golden_max_items", 500) or 500),
            "max_chunks": int(getattr(args, "plugin_golden_max_chunks", 5000) or 5000),
            "include_unmarked_chunks": bool(getattr(args, "plugin_golden_include_unmarked_chunks", False)),
            "overwrite": bool(args.overwrite),
        }
        if plugin_golden_ref
        else {
            "kind": "case_bundle",
            "path": cases_arg,
            "skip_import": bool(args.skip_import),
            "overwrite": bool(args.overwrite),
        }
    )

    with httpx.Client(headers=headers, timeout=timeout) as client:
        matched_ids: list[str] = []
        if plugin_golden_ref:
            payload = build_plugin_golden_import_payload(
                dataset_id=dataset_id,
                plugin_ref=plugin_golden_ref,
                max_items=int(getattr(args, "plugin_golden_max_items", 500) or 500),
                max_chunks=int(getattr(args, "plugin_golden_max_chunks", 5000) or 5000),
                include_unmarked_chunks=bool(getattr(args, "plugin_golden_include_unmarked_chunks", False)),
                overwrite=bool(args.overwrite),
            )
            r = client.post(f"{base}/pipeline/plugins/golden-draft/import", json=payload)
            r.raise_for_status()
            import_response = r.json() or {}
            try:
                imp, matched_ids = extract_plugin_golden_import_case_ids(import_response)
            except ValueError as exc:
                _require(False, str(exc))
            case_source.update(summarize_plugin_golden_source_from_import_response(import_response))
            case_source["plugin_ref"] = str(case_source.get("plugin_ref") or plugin_golden_ref)
            case_source["import_result"] = {
                "created": int(imp.get("created") or 0),
                "updated": int(imp.get("updated") or 0),
                "skipped": int(imp.get("skipped") or 0),
                "case_ids": [str(x) for x in (matched_ids or [])],
            }
            print(
                "[regression_gate] plugin golden import: "
                f"created={imp.get('created')} updated={imp.get('updated')} skipped={imp.get('skipped')}"
            )
            print(f"[regression_gate] matched cases: {len(matched_ids)}/{len(matched_ids)}")
        else:
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

        case_source_failures = compare_threshold_case_source(expected=threshold_case_source, actual=case_source)
        _require(
            not case_source_failures,
            "thresholds case_source mismatch: " + "; ".join(case_source_failures),
        )

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
            detail = _fetch_run_detail(client, base_url=base, run_id=str(run_id), include_items=False)
            status = str((detail.get("run") or {}).get("status") or "")
            summary = dict((detail.get("run") or {}).get("summary") or {})
            if status in {"completed", "failed"}:
                break
            time.sleep(float(args.poll_sec))

        if status != "completed":
            err = (detail.get("run") or {}).get("error_message") if isinstance(detail, dict) else None
            print(f"[regression_gate] ERROR: run status={status} error={err}", file=sys.stderr)
            return 1

        detail = _fetch_run_detail(
            client,
            base_url=base,
            run_id=str(run_id),
            include_items=True,
            include_contexts=False,
        )
        status = str((detail.get("run") or {}).get("status") or "")
        summary = dict((detail.get("run") or {}).get("summary") or {})
        if status != "completed":
            err = (detail.get("run") or {}).get("error_message") if isinstance(detail, dict) else None
            print(f"[regression_gate] ERROR: final run detail status={status} error={err}", file=sys.stderr)
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

        # Optional: queryset health diff + gate (Gap9).
        qs_section: dict[str, Any] | None = None
        qs_failures: list[str] = []
        qs_notes: list[str] = []
        if str(getattr(args, "queryset_health_baseline", "") or "").strip():
            baseline_path = Path(str(args.queryset_health_baseline or "")).expanduser()
            _require(baseline_path.exists(), f"queryset health baseline snapshot not found: {baseline_path}")

            current_path: Path | None = None
            if str(getattr(args, "queryset_health_current", "") or "").strip():
                current_path = Path(str(args.queryset_health_current or "")).expanduser()
            else:
                default_current = Path("artifacts/queryset_health.snapshot.json")
                if default_current.exists():
                    current_path = default_current

            _require(
                current_path is not None and current_path.exists(),
                "queryset health current snapshot not found (set --queryset-health-current)",
            )

            baseline_obj = _load_json(baseline_path)
            current_obj = _load_json(current_path)
            _require(isinstance(baseline_obj, dict), f"baseline snapshot must be a JSON object: {baseline_path}")
            _require(isinstance(current_obj, dict), f"current snapshot must be a JSON object: {current_path}")
            baseline_snap = dict(baseline_obj)
            current_snap = dict(current_obj)

            qs_policy = str(getattr(args, "queryset_health_policy", "fail") or "fail").strip().lower()
            _require(qs_policy in {"warn", "fail"}, "--queryset-health-policy must be warn|fail")

            diff = diff_queryset_health_snapshots(baseline=baseline_snap, current=current_snap, max_hard_case_ids=20)
            if str(getattr(args, "queryset_health_diff_out", "") or "").strip():
                out_diff = Path(str(args.queryset_health_diff_out or "")).expanduser()
                out_diff.parent.mkdir(parents=True, exist_ok=True)
                write_json_file(out_diff, diff)
                print(f"[regression_gate] wrote queryset health diff: {out_diff}")

            policy = _qs_resolve_policy(current_snap)
            degradation_flags = compute_queryset_health_degradation_flags(
                baseline=baseline_snap,
                current=current_snap,
                policy=policy,
            )

            pol = diff.get("policy") if isinstance(diff.get("policy"), dict) else {}
            if bool(pol.get("changed")):
                msg = (
                    "queryset policy changed "
                    f"(baseline_hash={pol.get('baseline_hash')}, current_hash={pol.get('current_hash')})"
                )
                qs_notes.append(msg)

            if degradation_flags:
                msg = f"queryset health degraded: flags={degradation_flags}"
                if qs_policy == "fail":
                    qs_failures.append(msg)
                else:
                    qs_notes.append(msg)

            qs_section = {
                "baseline_path": str(baseline_path),
                "current_path": str(current_path),
                "policy": qs_policy,
                "degradation_flags": degradation_flags,
                "diff": diff,
            }

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
                case_source=case_source,
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
            overall_ok = len(qs_failures) == 0
            overall_failures = list(qs_failures)
            report = build_regression_gate_report(
                dataset_id=dataset_id,
                run_id=str(run_id),
                matched_case_count=len(matched_ids),
                metrics=metrics,
                thresholds_enabled=False,
                ok=overall_ok,
                failures=overall_failures,
                detail=detail,
                run_payload=run_payload,
                case_source=case_source,
            )
            if qs_section:
                report["queryset_health"] = qs_section
            if qs_notes:
                report["notes"] = list(qs_notes)
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
            if overall_ok:
                print("[regression_gate] no thresholds set; PASS")
                return 0
            for msg in overall_failures:
                print(f"[regression_gate] FAIL: {msg}", file=sys.stderr)
            return 1

        ok, failures = check_thresholds(summary=summary, thresholds=thresholds, slice_thresholds=slice_thresholds)
        failures = list(failures or []) + list(qs_failures)
        ok = bool(ok and not qs_failures)
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
            case_source=case_source,
        )
        if qs_section:
            report["queryset_health"] = qs_section
        if qs_notes:
            report["notes"] = list(qs_notes)
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
