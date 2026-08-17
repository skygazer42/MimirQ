import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError(f"JSON root must be object: {path}")
    return obj


def _load_policy(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    obj = _load_json(path)
    return dict(obj) if isinstance(obj, dict) else {}


def _resolve_profile_hash(*, args: argparse.Namespace, benchmark: dict[str, Any]) -> str:
    from app.rag.core.hashing import stable_hash

    explicit = str(args.profile_hash or "").strip()
    if explicit:
        return explicit

    from_bench = str(benchmark.get("profile_hash") or "").strip()
    if from_bench:
        return from_bench

    if args.profile_json:
        payload = Path(args.profile_json).read_text(encoding="utf-8")
        return stable_hash(payload, length=24)

    seed = json.dumps(
        {
            "retrieval_mode": str(benchmark.get("retrieval_mode") or ""),
            "top_k": int(benchmark.get("top_k") or 0),
            "fixture_hash": str(benchmark.get("fixture_hash") or ""),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return stable_hash(seed, length=24)


def _policy_source(*, has_policy_json: bool, has_cli_overrides: bool) -> str:
    if has_policy_json and has_cli_overrides:
        return "policy_json+cli_overrides"
    if has_policy_json:
        return "policy_json"
    if has_cli_overrides:
        return "cli_overrides"
    return "default"


def _effective_policy(
    *,
    policy_json: Path | None,
    miss_rate_regression_threshold: float | None,
    weak_hit_rate_regression_threshold: float | None,
    weak_hit_rr_threshold: float | None,
    hard_cases_limit: int | None,
) -> tuple[dict[str, Any], str]:
    policy = _load_policy(policy_json)
    overrides = (
        ("miss_rate_regression_threshold", miss_rate_regression_threshold, float),
        ("weak_hit_rate_regression_threshold", weak_hit_rate_regression_threshold, float),
        ("weak_hit_rr_threshold", weak_hit_rr_threshold, float),
        ("hard_cases_limit", hard_cases_limit, int),
    )
    has_cli_overrides = False
    for key, value, coerce in overrides:
        if value is None:
            continue
        policy[key] = coerce(value)
        has_cli_overrides = True
    source = _policy_source(
        has_policy_json=policy_json is not None,
        has_cli_overrides=has_cli_overrides,
    )
    return policy, source


def _history_context(
    history: Path | None,
    load_history: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if history is None:
        return [], None
    rows = load_history(history)
    return rows, rows[-1] if rows else None


def _write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def _hard_case_ids(risk: dict[str, Any]) -> list[str]:
    hard_cases = risk.get("hard_cases") if isinstance(risk.get("hard_cases"), list) else []
    ids: list[str] = []
    for row in hard_cases[:3]:
        if not isinstance(row, dict):
            continue
        case_id = str(row.get("id") or "").strip()
        if case_id:
            ids.append(case_id)
    return ids


def _cron_summary(snapshot: dict[str, Any], out: Path) -> dict[str, Any]:
    risk = snapshot.get("risk") if isinstance(snapshot.get("risk"), dict) else {}
    return {
        "schema": snapshot.get("schema"),
        "status": snapshot.get("status"),
        "degradation_flags": snapshot.get("degradation_flags"),
        "profile_hash": snapshot.get("profile_hash"),
        "policy_source": snapshot.get("policy_source"),
        "policy_hash": snapshot.get("policy_hash"),
        "policy_changed": bool((snapshot.get("trend") or {}).get("policy_changed")),
        "miss_rate": risk.get("miss_rate"),
        "weak_hit_rate": risk.get("weak_hit_rate"),
        "hard_case_ids": _hard_case_ids(risk),
        "out": str(out),
    }


def _print_summary(snapshot: dict[str, Any], out: Path, *, cron: bool) -> None:
    if cron:
        print(json.dumps(_cron_summary(snapshot, out), ensure_ascii=False))
        return
    print(f"[queryset-health] status={snapshot.get('status')} out={out} profile_hash={snapshot.get('profile_hash')}")


def run(
    *,
    benchmark_report: Path,
    out: Path,
    history: Path | None,
    profile_hash: str | None,
    profile_json: Path | None,
    policy_json: Path | None,
    miss_rate_regression_threshold: float | None,
    weak_hit_rate_regression_threshold: float | None,
    weak_hit_rr_threshold: float | None,
    hard_cases_limit: int | None,
    max_history: int,
    cron: bool,
) -> dict[str, Any]:
    from app.services.queryset_health_service import (
        build_queryset_health_snapshot,
        load_queryset_health_history,
        update_queryset_health_history,
        write_queryset_health_history,
    )

    bench = _load_json(benchmark_report)
    policy, policy_source = _effective_policy(
        policy_json=policy_json,
        miss_rate_regression_threshold=miss_rate_regression_threshold,
        weak_hit_rate_regression_threshold=weak_hit_rate_regression_threshold,
        weak_hit_rr_threshold=weak_hit_rr_threshold,
        hard_cases_limit=hard_cases_limit,
    )

    args_obj = argparse.Namespace(profile_hash=profile_hash, profile_json=str(profile_json) if profile_json else None)
    resolved_profile_hash = _resolve_profile_hash(args=args_obj, benchmark=bench)

    hist_rows, prev = _history_context(history, load_queryset_health_history)

    snapshot = build_queryset_health_snapshot(
        benchmark_report=bench,
        profile_hash=resolved_profile_hash,
        previous_snapshot=prev,
        policy=policy,
        policy_source=policy_source,
    )

    _write_snapshot(out, snapshot)

    if history is not None:
        updated = update_queryset_health_history(history=hist_rows, current=snapshot, max_items=max_history)
        write_queryset_health_history(history, updated)

    _print_summary(snapshot, out, cron=cron)

    return snapshot


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run query-set health diagnostics from a benchmark report")
    p.add_argument("--benchmark-report", required=True, help="Path to benchmark report JSON")
    p.add_argument("--out", required=True, help="Output path for health snapshot JSON")
    p.add_argument(
        "--history",
        default="runs/queryset_health/history.jsonl",
        help="History JSONL path for trend tracking (set empty to disable)",
    )
    p.add_argument("--profile-hash", default="", help="Explicit retrieval profile hash")
    p.add_argument("--profile-json", default="", help="Optional profile config JSON used to derive profile hash")
    p.add_argument("--policy-json", default="", help="Optional policy JSON with risk/regression thresholds")
    p.add_argument(
        "--miss-rate-regression-threshold",
        type=float,
        default=None,
        help="Override miss_rate_regression_threshold for this run",
    )
    p.add_argument(
        "--weak-hit-rate-regression-threshold",
        type=float,
        default=None,
        help="Override weak_hit_rate_regression_threshold for this run",
    )
    p.add_argument(
        "--weak-hit-rr-threshold",
        type=float,
        default=None,
        help="Override weak_hit_rr_threshold for risk classification",
    )
    p.add_argument(
        "--hard-cases-limit",
        type=int,
        default=None,
        help="Override number of hard cases included in risk summary",
    )
    p.add_argument("--max-history", type=int, default=90, help="Max history snapshots to keep")
    p.add_argument("--cron", action="store_true", help="Emit compact machine-readable summary line")
    args = p.parse_args(argv)

    try:
        history_path = Path(args.history) if str(args.history or "").strip() else None
        profile_json_path = Path(args.profile_json) if str(args.profile_json or "").strip() else None
        policy_json_path = Path(args.policy_json) if str(args.policy_json or "").strip() else None
        run(
            benchmark_report=Path(args.benchmark_report),
            out=Path(args.out),
            history=history_path,
            profile_hash=str(args.profile_hash or "").strip() or None,
            profile_json=profile_json_path,
            policy_json=policy_json_path,
            miss_rate_regression_threshold=args.miss_rate_regression_threshold,
            weak_hit_rate_regression_threshold=args.weak_hit_rate_regression_threshold,
            weak_hit_rr_threshold=args.weak_hit_rr_threshold,
            hard_cases_limit=args.hard_cases_limit,
            max_history=int(args.max_history or 90),
            cron=bool(args.cron),
        )
    except Exception as exc:
        print(f"[queryset-health] failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
