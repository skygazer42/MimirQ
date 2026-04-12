#!/usr/bin/env python3
"""
Release gate: combine regression gate + SLO snapshot + cost budget signals.

This script is intentionally "ops-friendly":
- Uses only HTTP calls to the backend (no DB access).
- PII-safe by construction: it consumes already-redacted, numeric/categorical summaries.

Typical usage patterns:
1) In CI: run retrieval regression gate (existing), then run this script with --skip-regression
   to validate SLO + cost budgets from a small probe traffic.
2) In a staging/production-like environment: run with --skip-probe (use existing metrics logs),
   and use --run-regression only when you have a regression cases bundle available.

Exit codes:
  0: pass
  2: gate failed (budget violation / insufficient data with fail policy)
  1: unexpected error (network/parse/etc)
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


def _strip_trailing_slashes(value: str) -> str:
    return (value or "").strip().rstrip("/")


def _join_url(base: str, path: str) -> str:
    b = _strip_trailing_slashes(base)
    p = (path or "").strip()
    if not p:
        return b
    if not p.startswith("/"):
        p = f"/{p}"
    return f"{b}{p}"


def _load_json(path: Path) -> Any:
    # PowerShell commonly writes UTF-8 JSON with BOM; `utf-8-sig` handles both BOM/no-BOM.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _headers(*, tenant_id: str, user_id: str, bearer: str) -> dict[str, str]:
    h: dict[str, str] = {"Accept": "application/json"}
    if tenant_id:
        h["X-Tenant-ID"] = tenant_id
    if user_id:
        h["X-User-ID"] = user_id
    if bearer:
        h["Authorization"] = f"Bearer {bearer}"
    return h


def coerce_case_bundle(obj: Any) -> tuple[str, list[dict[str, Any]]]:
    """
    Normalize a cases bundle into (dataset_id, items[]).

    Supported shapes:
    - {"schema":"mimirq.regression_cases.v1","dataset_id":"...","items":[...]}
    - {"dataset_id":"...","items":[...]}
    - legacy: [{"dataset_id":"...","question":"...","reference_sources":[...], ...}, ...]
    """
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


def _safe_float(v: object) -> float | None:
    try:
        f = float(v)  # type: ignore[arg-type]
    except Exception:
        return None
    if not math.isfinite(f):
        return None
    return f


def normalize_thresholds(raw: Any) -> dict[str, dict[str, float]]:
    """
    Normalize thresholds into: { metric: { min?: float, max?: float } }.

    Back-compat:
      {"foo": 1.2} -> {"foo": {"min": 1.2}}
    """
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, float]] = {}
    for k, v in raw.items():
        metric = str(k).strip()
        if not metric:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[metric] = {"min": float(v)}
            continue
        if isinstance(v, dict):
            entry: dict[str, float] = {}
            if "min" in v:
                fv = _safe_float(v.get("min"))
                if fv is not None:
                    entry["min"] = float(fv)
            if "max" in v:
                fv = _safe_float(v.get("max"))
                if fv is not None:
                    entry["max"] = float(fv)
            if entry:
                out[metric] = entry
    return out


def _policy(raw: Any, *, default: str) -> str:
    v = str(raw or "").strip().lower()
    if not v:
        return default
    if v in {"warn", "fail"}:
        return v
    return default


@dataclass(frozen=True)
class GateViolation:
    area: str
    metric: str
    value: float | None
    threshold: dict[str, float]
    message: str


def _check_threshold(*, area: str, metric: str, value: float | None, threshold: dict[str, float]) -> GateViolation | None:
    if value is None:
        return GateViolation(
            area=area,
            metric=metric,
            value=None,
            threshold=threshold,
            message="missing value",
        )

    if "min" in threshold:
        try:
            if float(value) < float(threshold["min"]):
                return GateViolation(
                    area=area,
                    metric=metric,
                    value=float(value),
                    threshold=threshold,
                    message=f"value {value} < min {threshold['min']}",
                )
        except Exception:
            return GateViolation(
                area=area,
                metric=metric,
                value=float(value),
                threshold=threshold,
                message="failed to compare to min threshold",
            )

    if "max" in threshold:
        try:
            if float(value) > float(threshold["max"]):
                return GateViolation(
                    area=area,
                    metric=metric,
                    value=float(value),
                    threshold=threshold,
                    message=f"value {value} > max {threshold['max']}",
                )
        except Exception:
            return GateViolation(
                area=area,
                metric=metric,
                value=float(value),
                threshold=threshold,
                message="failed to compare to max threshold",
            )

    return None


def _http_get_json(client: httpx.Client, url: str, *, headers: dict[str, str], params: dict[str, Any] | None = None) -> Any:
    resp = client.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _http_post_json(client: httpx.Client, url: str, *, headers: dict[str, str], payload: dict[str, Any]) -> Any:
    resp = client.post(url, headers={**headers, "Content-Type": "application/json"}, json=payload)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _run_regression_gate_subprocess(*, args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        "scripts/regression_gate.py",
        "--base-url",
        str(args.base_url),
        "--cases",
        str(args.cases),
        "--metrics",
        str(args.regression_metrics),
    ]
    if args.tenant_id:
        cmd.extend(["--tenant-id", str(args.tenant_id)])
    if args.user_id:
        cmd.extend(["--user-id", str(args.user_id)])
    if args.bearer:
        cmd.extend(["--bearer", str(args.bearer)])
    if args.thresholds:
        cmd.extend(["--thresholds", str(args.thresholds)])
    if args.regression_retrieval_mode:
        cmd.extend(["--retrieval-mode", str(args.regression_retrieval_mode)])
    if args.regression_out_run_json:
        cmd.extend(["--out-run-json", str(args.regression_out_run_json)])
    if args.regression_skip_import:
        cmd.append("--skip-import")
    if args.regression_overwrite:
        cmd.append("--overwrite")

    proc = subprocess.run(cmd, check=False)
    return int(proc.returncode)


def _extract_questions(items: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for it in items:
        q = it.get("question")
        if isinstance(q, str) and q.strip():
            out.append(q.strip())
    return out


def _probe_chat_traffic(
    *,
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    dataset_id: str,
    questions: list[str],
    count: int,
    retrieval_mode: str,
    top_k: int,
    score_threshold: float,
) -> list[str]:
    """
    Send a small number of non-streaming chat requests to generate `event=rag_trace` records.

    Returns request_ids for debugging.
    """
    if count <= 0:
        return []
    if not dataset_id:
        raise ValueError("probe requires dataset_id")
    if not questions:
        raise ValueError("probe requires at least one question")

    request_ids: list[str] = []
    url = _join_url(base_url, "/chat")

    for i in range(count):
        q = questions[i % len(questions)]
        payload = {
            "message": q,
            "history": [],
            "dataset_id": dataset_id,
            # Stabilize probe traffic across configs.
            "rag_config": {
                "retrieval_mode": retrieval_mode,
                "top_k": int(top_k),
                "score_threshold": float(score_threshold),
                "enable_multi_query": False,
                "enable_query_alias_expansion": False,
                "enable_reranker": False,
            },
        }
        data = _http_post_json(client, url, headers=headers, payload=payload)
        rid = str((data or {}).get("request_id") or "").strip()
        if rid:
            request_ids.append(rid)
    return request_ids


def _poll_rag_trace_count(
    *,
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    window_minutes: int,
    want_increase_by: int,
    poll_sec: float,
    timeout_sec: float,
) -> dict[str, Any]:
    url = _join_url(base_url, "/observability/rag-metrics/summary")
    params = {"window_minutes": int(window_minutes), "max_bytes": 5_000_000}
    start = time.time()

    baseline = 0
    try:
        snap0 = _http_get_json(client, url, headers=headers, params=params)
        baseline = int((snap0 or {}).get("rag_trace_count") or 0)
    except Exception:
        baseline = 0

    want_total = baseline + max(0, int(want_increase_by))
    last: dict[str, Any] = {}
    while True:
        if (time.time() - start) > max(0.0, float(timeout_sec)):
            return last
        try:
            last = _http_get_json(client, url, headers=headers, params=params) or {}
            cur = int(last.get("rag_trace_count") or 0)
            if cur >= want_total:
                return last
        except Exception:
            pass
        time.sleep(max(0.05, float(poll_sec)))


def _gate_slo_snapshot(*, snapshot: dict[str, Any], budgets: dict[str, Any]) -> tuple[list[GateViolation], list[str]]:
    slo_raw = budgets.get("slo") if isinstance(budgets.get("slo"), dict) else {}
    windows_cfg = slo_raw.get("windows") if isinstance(slo_raw.get("windows"), dict) else {}
    min_count = int(slo_raw.get("min_rag_trace_count") or 0)
    on_insufficient = _policy(slo_raw.get("on_insufficient_data"), default="fail")

    notes: list[str] = []
    violations: list[GateViolation] = []

    windows = snapshot.get("windows") if isinstance(snapshot.get("windows"), list) else []
    windows_by_min: dict[int, dict[str, Any]] = {}
    for w in windows:
        if not isinstance(w, dict):
            continue
        try:
            wmin = int(w.get("window_minutes") or 0)
        except Exception:
            continue
        if wmin > 0:
            windows_by_min[wmin] = w

    for wkey, th_raw in windows_cfg.items():
        try:
            wmin = int(str(wkey).strip())
        except Exception:
            continue
        th = normalize_thresholds(th_raw)
        if not th:
            continue

        snap = windows_by_min.get(wmin)
        if not isinstance(snap, dict):
            msg = f"missing slo window snapshot: {wmin}m"
            if on_insufficient == "fail":
                violations.append(
                    GateViolation(area="slo", metric=f"window:{wmin}", value=None, threshold={}, message=msg)
                )
            else:
                notes.append(f"[release_gate] WARN: {msg}")
            continue

        rag_trace_count = snap.get("rag_trace_count")
        try:
            cnt = int(rag_trace_count) if rag_trace_count is not None else 0
        except Exception:
            cnt = 0
        if min_count > 0 and cnt < min_count:
            msg = f"insufficient rag_trace_count for {wmin}m window: {cnt} < {min_count}"
            if on_insufficient == "fail":
                violations.append(
                    GateViolation(
                        area="slo",
                        metric="rag_trace_count",
                        value=float(cnt),
                        threshold={"min": float(min_count)},
                        message=msg,
                    )
                )
            else:
                notes.append(f"[release_gate] WARN: {msg}")
            continue

        for metric, threshold in th.items():
            v = _safe_float(snap.get(metric))
            viol = _check_threshold(area=f"slo:{wmin}m", metric=metric, value=v, threshold=threshold)
            if viol is None:
                continue
            if viol.value is None and on_insufficient != "fail":
                notes.append(f"[release_gate] WARN: {viol.area}.{viol.metric}: {viol.message}")
                continue
            violations.append(viol)

    return violations, notes


def _gate_cost(*, summary: dict[str, Any], budgets: dict[str, Any]) -> tuple[list[GateViolation], list[str], dict[str, float]]:
    cost_raw = budgets.get("cost") if isinstance(budgets.get("cost"), dict) else {}
    on_insufficient = _policy(cost_raw.get("on_insufficient_data"), default="fail")
    min_count = int(cost_raw.get("min_rag_trace_count") or 0)

    notes: list[str] = []
    violations: list[GateViolation] = []

    rag_trace_count = int(summary.get("rag_trace_count") or 0)
    if min_count > 0 and rag_trace_count < min_count:
        msg = f"insufficient rag_trace_count: {rag_trace_count} < {min_count}"
        if on_insufficient == "fail":
            violations.append(
                GateViolation(
                    area="cost",
                    metric="rag_trace_count",
                    value=float(rag_trace_count),
                    threshold={"min": float(min_count)},
                    message=msg,
                )
            )
        else:
            notes.append(f"[release_gate] WARN: {msg}")
            return violations, notes, {}

    llm_prompt_tokens = int(summary.get("llm_prompt_tokens") or 0)
    llm_completion_tokens = int(summary.get("llm_completion_tokens") or 0)
    llm_total_tokens = int(summary.get("llm_total_tokens") or 0)
    embed_query_tokens = int(summary.get("embed_query_tokens") or 0)
    embed_query_count = int(summary.get("embed_query_count") or 0)
    retrieval_query_count = int(summary.get("retrieval_query_count") or 0)

    computed: dict[str, float] = {}
    if rag_trace_count > 0:
        computed["llm_prompt_tokens_avg"] = float(llm_prompt_tokens) / float(rag_trace_count)
        computed["llm_completion_tokens_avg"] = float(llm_completion_tokens) / float(rag_trace_count)
        computed["llm_total_tokens_avg"] = float(llm_total_tokens) / float(rag_trace_count)
        computed["retrieval_query_count_avg"] = float(retrieval_query_count) / float(rag_trace_count)
    if embed_query_count > 0:
        computed["embed_query_tokens_avg"] = float(embed_query_tokens) / float(embed_query_count)

    thresholds = normalize_thresholds(cost_raw.get("thresholds"))
    if not thresholds:
        # Back-compat: allow thresholds at top-level of "cost" object.
        thresholds = normalize_thresholds({k: v for k, v in cost_raw.items() if k not in {"window_minutes", "min_rag_trace_count", "on_insufficient_data"}})

    for metric, threshold in thresholds.items():
        v = computed.get(metric)
        if v is None:
            # Also allow gating on raw summary keys directly.
            v = _safe_float(summary.get(metric))
        viol = _check_threshold(area="cost", metric=metric, value=v, threshold=threshold)
        if viol is None:
            continue
        if viol.value is None and on_insufficient != "fail":
            notes.append(f"[release_gate] WARN: {viol.area}.{viol.metric}: {viol.message}")
            continue
        violations.append(viol)

    return violations, notes, computed


def _leaderboard_rows(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, dict):
        rows = obj.get("rows")
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
        return []
    if isinstance(obj, list):
        return [r for r in obj if isinstance(r, dict)]
    return []


def _gate_retrieval_leaderboard(
    *,
    leaderboard: Any,
    cfg: dict[str, Any],
) -> tuple[list[GateViolation], list[str], dict[str, Any]]:
    """
    Gate retrieval leaderboard artifact against minimum/maximum thresholds.

    Supported leaderboard shapes:
    - {"rows":[{...}]}
    - [{...}]
    """

    rows = _leaderboard_rows(leaderboard)
    policy = _policy((cfg or {}).get("policy"), default="fail")
    top_n = int((cfg or {}).get("top_n") or 1)
    top_n = max(1, min(top_n, max(1, len(rows))))
    thresholds = normalize_thresholds((cfg or {}).get("thresholds"))

    violations: list[GateViolation] = []
    notes: list[str] = []
    observed: dict[str, Any] = {"policy": policy, "rows_total": int(len(rows)), "top_n": int(top_n)}

    if not rows:
        msg = "missing leaderboard rows"
        violations.append(
            GateViolation(
                area="retrieval_leaderboard",
                metric="rows",
                value=None,
                threshold={"min": 1.0},
                message=msg,
            )
        )
        if policy == "warn":
            notes.append(f"[release_gate] WARN: {msg}")
        return violations, notes, observed

    if not thresholds:
        return violations, notes, observed

    # Use the best row among top_n candidates by retrieval_mrr (fallback to first row).
    candidates = rows[:top_n]

    def _row_score(row: dict[str, Any]) -> float:
        v = _safe_float(row.get("retrieval_mrr"))
        return float(v) if v is not None else -1.0

    best = sorted(candidates, key=_row_score, reverse=True)[0]
    observed["label"] = str(best.get("label") or "")
    observed["run_id"] = str(best.get("run_id") or "")

    for metric, threshold in thresholds.items():
        val = _safe_float(best.get(metric))
        viol = _check_threshold(
            area="retrieval_leaderboard",
            metric=metric,
            value=val,
            threshold=threshold,
        )
        if viol is None:
            continue
        violations.append(viol)
        if policy == "warn":
            notes.append(
                f"[release_gate] WARN: retrieval_leaderboard.{metric}: value={viol.value} threshold={threshold} msg={viol.message}"
            )

    return violations, notes, observed


def _gate_queryset_policy_snapshot(
    *,
    snapshot: Any,
    cfg: dict[str, Any],
) -> tuple[list[GateViolation], list[str], dict[str, Any]]:
    """
    Surface queryset-health policy metadata into release gate report and optionally gate on policy drift.
    """
    policy = _policy((cfg or {}).get("policy"), default="warn")

    observed: dict[str, Any] = {}
    if isinstance(snapshot, dict):
        trend = snapshot.get("trend") if isinstance(snapshot.get("trend"), dict) else {}
        observed = {
            "policy_source": str(snapshot.get("policy_source") or ""),
            "policy_hash": str(snapshot.get("policy_hash") or ""),
            "policy_changed": bool(trend.get("policy_changed")),
            "status": str(snapshot.get("status") or ""),
            "retrieval_mode": str(snapshot.get("retrieval_mode") or ""),
            "profile_hash": str(snapshot.get("profile_hash") or ""),
        }
        flags = snapshot.get("degradation_flags")
        if isinstance(flags, list):
            observed["degradation_flags"] = [str(x) for x in flags][:20]

    violations: list[GateViolation] = []
    notes: list[str] = []

    if bool(observed.get("policy_changed")):
        src = str(observed.get("policy_source") or "")
        hsh = str(observed.get("policy_hash") or "")
        msg = f"queryset policy changed (source={src}, policy_hash={hsh})"
        if policy == "fail":
            violations.append(
                GateViolation(
                    area="queryset_health",
                    metric="policy_changed",
                    value=1.0,
                    threshold={"max": 0.0},
                    message=msg,
                )
            )
        else:
            notes.append(f"[release_gate] WARN: {msg}")

    return violations, notes, observed


def _gate_queryset_health_diff(
    *,
    diff: Any,
    cfg: dict[str, Any],
    area: str = "queryset_health_diff",
) -> tuple[list[GateViolation], list[str], dict[str, Any]]:
    policy = _policy((cfg or {}).get("policy"), default="fail")
    thresholds = normalize_thresholds((cfg or {}).get("thresholds"))

    hard = diff.get("hard_case_drift") if isinstance(diff, dict) and isinstance(diff.get("hard_case_drift"), dict) else {}
    flags = (
        diff.get("degradation_flags_drift")
        if isinstance(diff, dict) and isinstance(diff.get("degradation_flags_drift"), dict)
        else {}
    )
    parse_tail = (
        diff.get("parse_risk_tail_drift")
        if isinstance(diff, dict) and isinstance(diff.get("parse_risk_tail_drift"), dict)
        else {}
    )

    observed = {
        "hard_case_added_count": int(len(hard.get("added_ids") or [])),
        "degradation_flag_added_count": int(len(flags.get("added_flags") or [])),
        "parse_risk_tail_added_count": int(len(parse_tail.get("added_document_ids") or [])),
    }

    violations: list[GateViolation] = []
    notes: list[str] = []
    for metric, threshold in thresholds.items():
        value = _safe_float(observed.get(metric))
        viol = _check_threshold(
            area=area,
            metric=metric,
            value=value,
            threshold=threshold,
        )
        if viol is None:
            continue
        violations.append(viol)
        if policy == "warn":
            notes.append(
                f"[release_gate] WARN: {area}.{metric}: value={viol.value} threshold={threshold} msg={viol.message}"
            )

    return violations, notes, observed


def _gate_parsing_proof_summary(
    *,
    summary: Any,
    cfg: dict[str, Any],
    area: str = "parsing_proof",
) -> tuple[list[GateViolation], list[str], dict[str, Any]]:
    policy = _policy((cfg or {}).get("policy"), default="warn")
    thresholds = normalize_thresholds((cfg or {}).get("thresholds"))

    observed = {
        "cases_total": int((summary or {}).get("cases_total") or 0),
        "hit_at_k_mean": _safe_float((summary or {}).get("hit_at_k_mean")),
        "mrr_mean": _safe_float((summary or {}).get("mrr_mean")),
        "failed_case_count": int(len((summary or {}).get("failed_case_ids") or [])),
    }

    violations: list[GateViolation] = []
    notes: list[str] = []
    for metric, threshold in thresholds.items():
        value = _safe_float(observed.get(metric))
        viol = _check_threshold(area=area, metric=metric, value=value, threshold=threshold)
        if viol is None:
            continue
        violations.append(viol)
        if policy == "warn":
            notes.append(f"[release_gate] WARN: {area}.{metric}: value={viol.value} threshold={threshold} msg={viol.message}")
    return violations, notes, observed


def _gate_parsing_proof_diff(
    *,
    diff: Any,
    cfg: dict[str, Any],
    area: str = "parsing_proof_diff",
) -> tuple[list[GateViolation], list[str], dict[str, Any]]:
    policy = _policy((cfg or {}).get("policy"), default="warn")
    thresholds = normalize_thresholds((cfg or {}).get("thresholds"))

    metric_deltas = (diff.get("metric_deltas") if isinstance(diff, dict) and isinstance(diff.get("metric_deltas"), dict) else {})
    failed_drift = (
        diff.get("failed_case_drift")
        if isinstance(diff, dict) and isinstance(diff.get("failed_case_drift"), dict)
        else {}
    )

    observed = {
        "hit_at_k_mean_delta": _safe_float(metric_deltas.get("hit_at_k_mean_delta")),
        "mrr_mean_delta": _safe_float(metric_deltas.get("mrr_mean_delta")),
        "failed_case_added_count": int(len((failed_drift.get("added_ids") or []))),
    }

    violations: list[GateViolation] = []
    notes: list[str] = []
    for metric, threshold in thresholds.items():
        value = _safe_float(observed.get(metric))
        viol = _check_threshold(area=area, metric=metric, value=value, threshold=threshold)
        if viol is None:
            continue
        violations.append(viol)
        if policy == "warn":
            notes.append(f"[release_gate] WARN: {area}.{metric}: value={viol.value} threshold={threshold} msg={viol.message}")
    return violations, notes, observed


def _render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Release Gate Report")
    lines.append("")
    lines.append(f"- Passed: `{bool(report.get('passed'))}`")
    lines.append("")

    def _emit_section(name: str) -> None:
        payload = report.get(name) if isinstance(report.get(name), dict) else {}
        lines.append(f"## {name}")
        lines.append("")
        lines.append(f"- Policy: `{str(payload.get('policy') or '')}`")
        lines.append(f"- Path: `{str(payload.get('path') or '')}`")
        observed = payload.get("observed") if isinstance(payload.get("observed"), dict) else {}
        for key, value in observed.items():
            lines.append(f"- `{key}`: `{value}`")
        lines.append("")

    for section in (
        "queryset_health",
        "queryset_health_hybrid",
        "queryset_health_diff",
        "queryset_health_diff_hybrid",
        "parsing_proof",
        "parsing_proof_diff",
        "retrieval_leaderboard",
    ):
        _emit_section(section)

    notes = list(report.get("notes") or [])
    lines.append("## Notes")
    lines.append("")
    if notes:
        for item in notes:
            lines.append(f"- {item}")
    else:
        lines.append("- None")
    lines.append("")

    violations = list(report.get("violations") or [])
    lines.append("## Violations")
    lines.append("")
    if violations:
        for item in violations:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- `{item.get('area')}.{item.get('metric')}` value=`{item.get('value')}` threshold=`{item.get('threshold')}` message=`{item.get('message')}`"
            )
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Release gate: regression + SLO + cost budgets.")
    p.add_argument("--base-url", default="http://localhost:8000/api/v1", help="API base url (default: %(default)s)")
    p.add_argument("--tenant-id", default="", help="X-Tenant-ID header (optional in non-prod)")
    p.add_argument("--user-id", default="", help="X-User-ID header (AUTH_MODE=header)")
    p.add_argument("--bearer", default="", help="Bearer token (AUTH_MODE=jwt)")

    p.add_argument("--budgets", type=str, required=True, help="Budgets JSON (schema: mimirq.release_gate_budgets.v1)")

    # Regression gate integration (delegates to scripts/regression_gate.py).
    p.add_argument("--cases", type=str, default="", help="Path to regression cases JSON (optional; used for regression and probe)")
    p.add_argument("--thresholds", type=str, default="", help="Thresholds JSON for scripts/regression_gate.py (optional)")
    p.add_argument("--skip-regression", action="store_true", help="Skip regression gate step")
    p.add_argument("--regression-metrics", default="", help='Comma-separated metrics; use "" for retrieval-only (default: empty)')
    p.add_argument("--regression-retrieval-mode", default="", help="Override retrieval_mode for regression gate run (optional)")
    p.add_argument("--regression-out-run-json", default="", help="Write regression run detail JSON (optional)")
    p.add_argument("--regression-skip-import", action="store_true", help="Pass --skip-import to regression gate")
    p.add_argument("--regression-overwrite", action="store_true", help="Pass --overwrite to regression gate")

    # Probe traffic to ensure metrics exist for SLO/cost budgets.
    p.add_argument("--probe-chat-requests", type=int, default=0, help="Send N chat requests to generate metrics (default: 0)")
    p.add_argument("--probe-retrieval-mode", default="keyword", help="Probe retrieval_mode for chat (default: %(default)s)")
    p.add_argument("--probe-top-k", type=int, default=20, help="Probe top_k (default: %(default)s)")
    p.add_argument("--probe-score-threshold", type=float, default=0.0, help="Probe score_threshold (default: %(default)s)")
    p.add_argument("--probe-window-minutes", type=int, default=60, help="Metrics window to poll for probe (default: %(default)s)")
    p.add_argument("--probe-poll-sec", type=float, default=0.25, help="Poll interval while waiting for metrics flush (default: %(default)s)")
    p.add_argument("--probe-timeout-sec", type=float, default=15.0, help="Timeout waiting for metrics flush (default: %(default)s)")

    # Optional retrieval leaderboard drift gate.
    p.add_argument("--retrieval-leaderboard", default="", help="Leaderboard JSON artifact path (optional)")
    p.add_argument(
        "--retrieval-leaderboard-policy",
        default="",
        help="Override retrieval leaderboard policy (warn|fail). Empty uses budgets file.",
    )
    p.add_argument("--queryset-health-snapshot", default="", help="Query-set health snapshot JSON path (optional)")
    p.add_argument(
        "--queryset-health-snapshot-hybrid",
        default="",
        help="Hybrid query-set health snapshot JSON path (optional)",
    )
    p.add_argument("--queryset-health-diff", default="", help="Query-set health diff JSON path (optional)")
    p.add_argument(
        "--queryset-health-diff-hybrid",
        default="",
        help="Hybrid query-set health diff JSON path (optional)",
    )
    p.add_argument(
        "--queryset-health-policy",
        default="",
        help="Override queryset health policy drift gate behavior (warn|fail). Empty uses budgets file.",
    )
    p.add_argument("--parsing-proof-summary", default="", help="Broader parsing-proof summary JSON path (optional)")
    p.add_argument("--parsing-proof-diff", default="", help="Broader parsing-proof diff JSON path (optional)")

    p.add_argument("--out-report", default="", help="Write a JSON report to a file (optional)")
    p.add_argument("--out-report-md", default="", help="Write a Markdown summary to a file (optional)")

    args = p.parse_args()

    budgets_path = Path(args.budgets)
    if not budgets_path.exists():
        print(f"[release_gate] ERROR: budgets file not found: {budgets_path}", file=sys.stderr)
        return 1
    budgets = _load_json(budgets_path)
    if not isinstance(budgets, dict):
        print("[release_gate] ERROR: budgets must be a JSON object", file=sys.stderr)
        return 1

    if not args.skip_regression:
        if not args.cases:
            print("[release_gate] ERROR: --cases is required when running regression gate", file=sys.stderr)
            return 1
        rc = _run_regression_gate_subprocess(args=args)
        if rc != 0:
            print(f"[release_gate] ERROR: regression gate failed (exit={rc})", file=sys.stderr)
            return int(rc)

    cases_path: Path | None = Path(args.cases) if args.cases else None
    dataset_id = ""
    case_items: list[dict[str, Any]] = []
    if cases_path is not None and cases_path.exists():
        try:
            dataset_id, case_items = coerce_case_bundle(_load_json(cases_path))
        except Exception:
            dataset_id, case_items = "", []

    headers = _headers(tenant_id=str(args.tenant_id), user_id=str(args.user_id), bearer=str(args.bearer))
    base_url = str(args.base_url)

    report: dict[str, Any] = {
        "schema": "mimirq.release_gate_report.v1",
        "generated_at_ts": time.time(),
        "base_url": base_url,
        "tenant_id": str(args.tenant_id or ""),
        "user_id": str(args.user_id or ""),
        "probe": {},
        "slo": {},
        "cost": {},
        "queryset_health": {},
        "queryset_health_hybrid": {},
        "queryset_health_diff": {},
        "queryset_health_diff_hybrid": {},
        "parsing_proof": {},
        "parsing_proof_diff": {},
        "retrieval_leaderboard": {},
        "violations": [],
        "notes": [],
    }

    violations: list[GateViolation] = []
    notes: list[str] = []

    timeout = httpx.Timeout(30.0)
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        # Optional probe traffic: generate rag_trace events, then wait until summaries see them.
        if int(args.probe_chat_requests or 0) > 0:
            if not cases_path or not cases_path.exists():
                print("[release_gate] ERROR: --cases is required for --probe-chat-requests", file=sys.stderr)
                return 1
            questions = _extract_questions(case_items)
            if not questions:
                print("[release_gate] ERROR: probe requires question fields in cases items", file=sys.stderr)
                return 1

            try:
                rids = _probe_chat_traffic(
                    client=client,
                    base_url=base_url,
                    headers=headers,
                    dataset_id=dataset_id,
                    questions=questions,
                    count=int(args.probe_chat_requests),
                    retrieval_mode=str(args.probe_retrieval_mode),
                    top_k=int(args.probe_top_k),
                    score_threshold=float(args.probe_score_threshold),
                )
            except Exception as exc:
                print(f"[release_gate] ERROR: probe chat traffic failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 1

            snap = _poll_rag_trace_count(
                client=client,
                base_url=base_url,
                headers=headers,
                window_minutes=int(args.probe_window_minutes),
                want_increase_by=int(args.probe_chat_requests),
                poll_sec=float(args.probe_poll_sec),
                timeout_sec=float(args.probe_timeout_sec),
            )
            report["probe"] = {
                "chat_requests": int(args.probe_chat_requests),
                "request_ids": rids[:20],
                "metrics_summary": snap,
            }

        # SLO gate.
        slo_url = _join_url(base_url, "/observability/slo/snapshot")
        slo_snapshot = _http_get_json(client, slo_url, headers=headers, params=None)
        slo_violations, slo_notes = _gate_slo_snapshot(snapshot=slo_snapshot, budgets=budgets)
        violations.extend(slo_violations)
        notes.extend(slo_notes)
        report["slo"] = {"snapshot": slo_snapshot}

        # Cost gate.
        cost_cfg = budgets.get("cost") if isinstance(budgets.get("cost"), dict) else {}
        window_minutes = int(cost_cfg.get("window_minutes") or 60)
        cost_url = _join_url(base_url, "/observability/rag-metrics/cost-attribution")
        cost_summary = _http_get_json(
            client,
            cost_url,
            headers=headers,
            params={"window_minutes": window_minutes, "max_bytes": 5_000_000},
        )
        cost_violations, cost_notes, computed = _gate_cost(summary=cost_summary, budgets=budgets)
        violations.extend(cost_violations)
        notes.extend(cost_notes)
        report["cost"] = {"summary": cost_summary, "computed": computed}

    # Optional queryset health snapshot / policy-drift gate.
    qs_cfg = budgets.get("queryset_health") if isinstance(budgets.get("queryset_health"), dict) else {}
    if args.queryset_health_snapshot:
        qs_cfg = dict(qs_cfg or {})
        qs_cfg["path"] = str(args.queryset_health_snapshot)
    if args.queryset_health_policy:
        qs_cfg = dict(qs_cfg or {})
        qs_cfg["policy"] = str(args.queryset_health_policy)

    if isinstance(qs_cfg, dict) and qs_cfg:
        qs_path_text = str(qs_cfg.get("path") or "").strip()
        qs_policy = _policy(qs_cfg.get("policy"), default="warn")
        if qs_path_text:
            qs_path = Path(qs_path_text)
            if not qs_path.exists():
                msg = f"queryset health snapshot not found: {qs_path}"
                if qs_policy == "fail":
                    violations.append(
                        GateViolation(
                            area="queryset_health",
                            metric="artifact_path",
                            value=None,
                            threshold={},
                            message=msg,
                        )
                    )
                else:
                    notes.append(f"[release_gate] WARN: {msg}")
                report["queryset_health"] = {"path": str(qs_path), "policy": qs_policy, "observed": {}}
            else:
                qs_obj = _load_json(qs_path)
                qs_violations, qs_notes, qs_observed = _gate_queryset_policy_snapshot(
                    snapshot=qs_obj,
                    cfg=qs_cfg,
                )
                report["queryset_health"] = {
                    "path": str(qs_path),
                    "policy": qs_policy,
                    "observed": qs_observed,
                }
                if qs_policy == "warn":
                    notes.extend(qs_notes)
                else:
                    violations.extend(qs_violations)
        else:
            report["queryset_health"] = {"policy": qs_policy, "observed": {}}

    qs_hybrid_cfg = budgets.get("queryset_health_hybrid") if isinstance(budgets.get("queryset_health_hybrid"), dict) else {}
    if args.queryset_health_snapshot_hybrid:
        qs_hybrid_cfg = dict(qs_hybrid_cfg or {})
        qs_hybrid_cfg["path"] = str(args.queryset_health_snapshot_hybrid)

    if isinstance(qs_hybrid_cfg, dict) and qs_hybrid_cfg:
        qs_path_text = str(qs_hybrid_cfg.get("path") or "").strip()
        qs_policy = _policy(qs_hybrid_cfg.get("policy"), default="warn")
        if qs_path_text:
            qs_path = Path(qs_path_text)
            if not qs_path.exists():
                msg = f"hybrid queryset health snapshot not found: {qs_path}"
                if qs_policy == "fail":
                    violations.append(
                        GateViolation(
                            area="queryset_health_hybrid",
                            metric="artifact_path",
                            value=None,
                            threshold={},
                            message=msg,
                        )
                    )
                else:
                    notes.append(f"[release_gate] WARN: {msg}")
                report["queryset_health_hybrid"] = {"path": str(qs_path), "policy": qs_policy, "observed": {}}
            else:
                qs_obj = _load_json(qs_path)
                qs_violations, qs_notes, qs_observed = _gate_queryset_policy_snapshot(
                    snapshot=qs_obj,
                    cfg=qs_hybrid_cfg,
                )
                report["queryset_health_hybrid"] = {
                    "path": str(qs_path),
                    "policy": qs_policy,
                    "observed": qs_observed,
                }
                if qs_policy == "warn":
                    notes.extend(qs_notes)
                else:
                    violations.extend(qs_violations)
        else:
            report["queryset_health_hybrid"] = {"policy": qs_policy, "observed": {}}

    qs_diff_cfg = budgets.get("queryset_health_diff") if isinstance(budgets.get("queryset_health_diff"), dict) else {}
    if args.queryset_health_diff:
        qs_diff_cfg = dict(qs_diff_cfg or {})
        qs_diff_cfg["path"] = str(args.queryset_health_diff)

    if isinstance(qs_diff_cfg, dict) and qs_diff_cfg:
        qs_path_text = str(qs_diff_cfg.get("path") or "").strip()
        qs_policy = _policy(qs_diff_cfg.get("policy"), default="fail")
        if qs_path_text:
            qs_path = Path(qs_path_text)
            if not qs_path.exists():
                msg = f"queryset health diff not found: {qs_path}"
                if qs_policy == "fail":
                    violations.append(
                        GateViolation(
                            area="queryset_health_diff",
                            metric="artifact_path",
                            value=None,
                            threshold={},
                            message=msg,
                        )
                    )
                else:
                    notes.append(f"[release_gate] WARN: {msg}")
                report["queryset_health_diff"] = {"path": str(qs_path), "policy": qs_policy, "observed": {}}
            else:
                qs_obj = _load_json(qs_path)
                qs_violations, qs_notes, qs_observed = _gate_queryset_health_diff(
                    diff=qs_obj,
                    cfg=qs_diff_cfg,
                    area="queryset_health_diff",
                )
                report["queryset_health_diff"] = {
                    "path": str(qs_path),
                    "policy": qs_policy,
                    "observed": qs_observed,
                }
                if qs_policy == "warn":
                    notes.extend(qs_notes)
                else:
                    violations.extend(qs_violations)
        else:
            report["queryset_health_diff"] = {"policy": qs_policy, "observed": {}}

    qs_diff_hybrid_cfg = (
        budgets.get("queryset_health_diff_hybrid")
        if isinstance(budgets.get("queryset_health_diff_hybrid"), dict)
        else {}
    )
    if args.queryset_health_diff_hybrid:
        qs_diff_hybrid_cfg = dict(qs_diff_hybrid_cfg or {})
        qs_diff_hybrid_cfg["path"] = str(args.queryset_health_diff_hybrid)

    if isinstance(qs_diff_hybrid_cfg, dict) and qs_diff_hybrid_cfg:
        qs_path_text = str(qs_diff_hybrid_cfg.get("path") or "").strip()
        qs_policy = _policy(qs_diff_hybrid_cfg.get("policy"), default="fail")
        if qs_path_text:
            qs_path = Path(qs_path_text)
            if not qs_path.exists():
                msg = f"hybrid queryset health diff not found: {qs_path}"
                if qs_policy == "fail":
                    violations.append(
                        GateViolation(
                            area="queryset_health_diff_hybrid",
                            metric="artifact_path",
                            value=None,
                            threshold={},
                            message=msg,
                        )
                    )
                else:
                    notes.append(f"[release_gate] WARN: {msg}")
                report["queryset_health_diff_hybrid"] = {"path": str(qs_path), "policy": qs_policy, "observed": {}}
            else:
                qs_obj = _load_json(qs_path)
                qs_violations, qs_notes, qs_observed = _gate_queryset_health_diff(
                    diff=qs_obj,
                    cfg=qs_diff_hybrid_cfg,
                    area="queryset_health_diff_hybrid",
                )
                report["queryset_health_diff_hybrid"] = {
                    "path": str(qs_path),
                    "policy": qs_policy,
                    "observed": qs_observed,
                }
                if qs_policy == "warn":
                    notes.extend(qs_notes)
                else:
                    violations.extend(qs_violations)
        else:
            report["queryset_health_diff_hybrid"] = {"policy": qs_policy, "observed": {}}

    parsing_proof_cfg = budgets.get("parsing_proof") if isinstance(budgets.get("parsing_proof"), dict) else {}
    if args.parsing_proof_summary:
        parsing_proof_cfg = dict(parsing_proof_cfg or {})
        parsing_proof_cfg["path"] = str(args.parsing_proof_summary)

    if isinstance(parsing_proof_cfg, dict) and parsing_proof_cfg:
        proof_path_text = str(parsing_proof_cfg.get("path") or "").strip()
        proof_policy = _policy(parsing_proof_cfg.get("policy"), default="warn")
        if proof_path_text:
            proof_path = Path(proof_path_text)
            if not proof_path.exists():
                msg = f"parsing proof summary not found: {proof_path}"
                if proof_policy == "fail":
                    violations.append(
                        GateViolation(
                            area="parsing_proof",
                            metric="artifact_path",
                            value=None,
                            threshold={},
                            message=msg,
                        )
                    )
                else:
                    notes.append(f"[release_gate] WARN: {msg}")
                report["parsing_proof"] = {"path": str(proof_path), "policy": proof_policy, "observed": {}}
            else:
                proof_obj = _load_json(proof_path)
                proof_violations, proof_notes, proof_observed = _gate_parsing_proof_summary(
                    summary=proof_obj,
                    cfg=parsing_proof_cfg,
                    area="parsing_proof",
                )
                report["parsing_proof"] = {
                    "path": str(proof_path),
                    "policy": proof_policy,
                    "observed": proof_observed,
                }
                if proof_policy == "warn":
                    notes.extend(proof_notes)
                else:
                    violations.extend(proof_violations)
        else:
            report["parsing_proof"] = {"policy": proof_policy, "observed": {}}

    parsing_proof_diff_cfg = budgets.get("parsing_proof_diff") if isinstance(budgets.get("parsing_proof_diff"), dict) else {}
    if args.parsing_proof_diff:
        parsing_proof_diff_cfg = dict(parsing_proof_diff_cfg or {})
        parsing_proof_diff_cfg["path"] = str(args.parsing_proof_diff)

    if isinstance(parsing_proof_diff_cfg, dict) and parsing_proof_diff_cfg:
        proof_diff_path_text = str(parsing_proof_diff_cfg.get("path") or "").strip()
        proof_diff_policy = _policy(parsing_proof_diff_cfg.get("policy"), default="warn")
        if proof_diff_path_text:
            proof_diff_path = Path(proof_diff_path_text)
            if not proof_diff_path.exists():
                msg = f"parsing proof diff not found: {proof_diff_path}"
                if proof_diff_policy == "fail":
                    violations.append(
                        GateViolation(
                            area="parsing_proof_diff",
                            metric="artifact_path",
                            value=None,
                            threshold={},
                            message=msg,
                        )
                    )
                else:
                    notes.append(f"[release_gate] WARN: {msg}")
                report["parsing_proof_diff"] = {"path": str(proof_diff_path), "policy": proof_diff_policy, "observed": {}}
            else:
                proof_diff_obj = _load_json(proof_diff_path)
                diff_violations, diff_notes, diff_observed = _gate_parsing_proof_diff(
                    diff=proof_diff_obj,
                    cfg=parsing_proof_diff_cfg,
                    area="parsing_proof_diff",
                )
                report["parsing_proof_diff"] = {
                    "path": str(proof_diff_path),
                    "policy": proof_diff_policy,
                    "observed": diff_observed,
                }
                if proof_diff_policy == "warn":
                    notes.extend(diff_notes)
                else:
                    violations.extend(diff_violations)
        else:
            report["parsing_proof_diff"] = {"policy": proof_diff_policy, "observed": {}}

    # Optional retrieval leaderboard drift gate.
    lb_cfg = budgets.get("retrieval_leaderboard") if isinstance(budgets.get("retrieval_leaderboard"), dict) else {}
    if args.retrieval_leaderboard:
        lb_cfg = dict(lb_cfg or {})
        lb_cfg["path"] = str(args.retrieval_leaderboard)
    if args.retrieval_leaderboard_policy:
        lb_cfg = dict(lb_cfg or {})
        lb_cfg["policy"] = str(args.retrieval_leaderboard_policy)

    if isinstance(lb_cfg, dict) and lb_cfg:
        lb_path_text = str(lb_cfg.get("path") or "").strip()
        if lb_path_text:
            lb_path = Path(lb_path_text)
            if not lb_path.exists():
                violations.append(
                    GateViolation(
                        area="retrieval_leaderboard",
                        metric="artifact_path",
                        value=None,
                        threshold={},
                        message=f"leaderboard artifact not found: {lb_path}",
                    )
                )
            else:
                lb_obj = _load_json(lb_path)
                lb_violations, lb_notes, lb_observed = _gate_retrieval_leaderboard(
                    leaderboard=lb_obj,
                    cfg=lb_cfg,
                )
                policy = _policy(lb_cfg.get("policy"), default="fail")
                report["retrieval_leaderboard"] = {
                    "path": str(lb_path),
                    "policy": policy,
                    "observed": lb_observed,
                }
                if policy == "warn":
                    notes.extend(lb_notes)
                else:
                    violations.extend(lb_violations)
        else:
            report["retrieval_leaderboard"] = {"policy": _policy(lb_cfg.get("policy"), default="fail"), "observed": {}}

    report["notes"] = notes
    report["violations"] = [
        {
            "area": v.area,
            "metric": v.metric,
            "value": v.value,
            "threshold": v.threshold,
            "message": v.message,
        }
        for v in violations
    ]
    report["passed"] = not bool(violations)

    if args.out_report:
        out_path = Path(args.out_report)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(out_path, report)
    if args.out_report_md:
        out_md = Path(args.out_report_md)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(_render_markdown(report), encoding="utf-8")

    for n in notes:
        print(str(n), file=sys.stderr)

    if not violations:
        print("[release_gate] PASS")
        return 0

    print("[release_gate] FAIL: budget violations detected", file=sys.stderr)
    for v in violations[:40]:
        thr = v.threshold
        thr_s = ",".join([f"{k}={thr[k]}" for k in sorted(thr.keys())]) if thr else ""
        print(
            f"[release_gate] VIOLATION: {v.area}.{v.metric} value={v.value} threshold=({thr_s}) msg={v.message}",
            file=sys.stderr,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
