#!/usr/bin/env python3
"""Run MimirQ-direct benchmark on the same case pack with KG off/on and compare.

This script is intentionally local-first:
- reads a prebuilt case pack (same shape as dify_3way_benchmark cases)
- keeps the global backend settings unchanged
- runs the local MimirQ direct retrieval benchmark twice with request-level KG overrides
- writes both reports plus a compact comparison summary
"""


import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import dify_3way_benchmark as bench  # noqa: E402

DEFAULT_CASES = "artifacts/changzhou_eval_pack_full/cases_1000.json"
DEFAULT_OUT_DIR = "artifacts/changzhou_kg_on_off_benchmark"
DEFAULT_BASE_URL = "http://127.0.0.1:8000/api/v1"
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"
DEFAULT_USER_ID = "demo"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _headers(*, tenant_id: str, user_id: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Tenant-ID": _text(tenant_id),
        "X-User-ID": _text(user_id),
        "X-Account-ID": _text(user_id),
    }


def _get_settings(*, base_url: str, tenant_id: str, user_id: str) -> dict[str, Any]:
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=60.0, trust_env=False) as client:
        response = client.get("/settings", headers=_headers(tenant_id=tenant_id, user_id=user_id))
        response.raise_for_status()
        return response.json()


def _set_kg_enabled(*, base_url: str, tenant_id: str, user_id: str, settings_payload: dict[str, Any], enabled: bool) -> dict[str, Any]:
    feature_flags = dict(settings_payload.get("feature_flags") or {})
    feature_flags["kg_enabled"] = bool(enabled)
    payload = {"feature_flags": feature_flags}
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=120.0, trust_env=False) as client:
        response = client.put("/settings", json=payload, headers=_headers(tenant_id=tenant_id, user_id=user_id))
        response.raise_for_status()
        return response.json()


def _load_cases(path: str) -> list[dict[str, Any]]:
    return bench.load_prebuilt_cases(path)


def _mimirq_direct_report(
    *,
    cases: list[dict[str, Any]],
    base_url: str,
    tenant_id: str,
    user_id: str,
    timeout: float,
    concurrency: int,
    run_path: Path,
    env_file: str,
    retrieval_overrides: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    run = bench.run_mimirq_direct(
        cases=cases,
        base_url=base_url.rsplit("/api/v1", 1)[0],
        token=bench.load_mimirq_token("", env_file=env_file),
        timeout=timeout,
        concurrency=concurrency,
        retrieval_overrides=retrieval_overrides,
        existing_items=None,
        retry_failures=False,
        run_path=run_path,
        flush_every=50,
    )
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = bench.evaluate_mixed_rag_quality(cases=cases, runs=[run])
    report["summary"]["requested_cases"] = len(cases)
    report["summary"]["executed_cases"] = len(cases)
    return run, report


def _summary_metrics(report: dict[str, Any]) -> dict[str, Any]:
    leaderboard = report.get("leaderboard") if isinstance(report.get("leaderboard"), list) else []
    top = leaderboard[0] if leaderboard and isinstance(leaderboard[0], dict) else {}
    verdicts = report.get("audit_verdict_summary") if isinstance(report.get("audit_verdict_summary"), list) else []
    verdict = verdicts[0] if verdicts and isinstance(verdicts[0], dict) else {}
    return {
        "cases": report.get("summary", {}).get("cases"),
        "business_score": bench._business_score_system(top) if top else None,
        "mean_answer_clause_coverage": top.get("mean_answer_clause_coverage"),
        "mean_answer_subquestion_coverage": top.get("mean_answer_subquestion_coverage"),
        "mean_evidence_coverage": top.get("mean_evidence_coverage"),
        "mean_wrong_evidence_rate": top.get("mean_wrong_evidence_rate"),
        "accurate_rate": verdict.get("accurate_rate"),
        "usable_rate": verdict.get("usable_rate"),
        "accurate": verdict.get("accurate"),
        "partially_accurate": verdict.get("partially_accurate"),
        "insufficient_evidence": verdict.get("insufficient_evidence"),
        "no_answer": verdict.get("no_answer"),
    }


def _compare_summaries(off_summary: dict[str, Any], on_summary: dict[str, Any]) -> dict[str, Any]:
    metrics = [
        "business_score",
        "mean_answer_clause_coverage",
        "mean_answer_subquestion_coverage",
        "mean_evidence_coverage",
        "mean_wrong_evidence_rate",
        "accurate_rate",
        "usable_rate",
    ]
    deltas: dict[str, Any] = {}
    for metric in metrics:
        off_value = off_summary.get(metric)
        on_value = on_summary.get(metric)
        if isinstance(off_value, (int, float)) and isinstance(on_value, (int, float)):
            deltas[metric] = on_value - off_value
        else:
            deltas[metric] = None
    return deltas


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local MimirQ benchmark with KG off/on over the same case pack.")
    parser.add_argument("--cases", default=DEFAULT_CASES)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sample-per-type", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--concurrency", type=int, default=4)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = bench.select_cases_to_run(
        _load_cases(str(args.cases)),
        limit=int(args.limit or 0),
        sample_per_type=int(args.sample_per_type or 0),
    )
    current_settings = _get_settings(base_url=str(args.base_url), tenant_id=str(args.tenant_id), user_id=str(args.user_id))
    original_kg_enabled = bool((current_settings.get("feature_flags") or {}).get("kg_enabled"))

    reports: dict[str, dict[str, Any]] = {}
    summaries: dict[str, dict[str, Any]] = {}
    for mode, enabled in (("kg_off", False), ("kg_on", True)):
        run_path = out_dir / f"run_mimirq_direct_{mode}.json"
        _run, report = _mimirq_direct_report(
            cases=cases,
            base_url=str(args.base_url),
            tenant_id=str(args.tenant_id),
            user_id=str(args.user_id),
            timeout=float(args.timeout),
            concurrency=int(args.concurrency),
            run_path=run_path,
            env_file=str(args.env_file),
            retrieval_overrides={
                "enable_kg_query_expansion": enabled,
                "enable_kg_chunk_injection": enabled,
                "enable_kg_chunk_boost": enabled,
            },
        )
        reports[mode] = report
        summaries[mode] = _summary_metrics(report)
        (out_dir / f"report_{mode}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    comparison = {
        "schema": "mimirq.changzhou_gov.kg_on_off_benchmark.v1",
        "cases": len(cases),
        "original_kg_enabled": original_kg_enabled,
        "kg_off": summaries.get("kg_off"),
        "kg_on": summaries.get("kg_on"),
        "delta_on_minus_off": _compare_summaries(summaries.get("kg_off", {}), summaries.get("kg_on", {})),
    }
    (out_dir / "comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
