#!/usr/bin/env python3
"""
Diff two query-set health snapshots.

Example:
  python scripts/diff_queryset_health_snapshots.py \
    --a runs/queryset_health/base.json \
    --b runs/queryset_health/current.json \
    --out runs/queryset_health/diff.json
"""

from __future__ import annotations

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
        raise ValueError(f"snapshot root must be object: {path}")
    return obj


def run(
    *,
    baseline_path: Path,
    current_path: Path,
    out: Path | None,
    max_hard_case_ids: int,
) -> dict[str, Any]:
    from app.services.queryset_health_diff_service import diff_queryset_health_snapshots

    baseline = _load_json(baseline_path)
    current = _load_json(current_path)
    diff = diff_queryset_health_snapshots(
        baseline=baseline,
        current=current,
        max_hard_case_ids=max_hard_case_ids,
    )
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
    return diff


def _render_markdown(diff: dict[str, Any]) -> str:
    policy = diff.get("policy") if isinstance(diff.get("policy"), dict) else {}
    deltas = diff.get("metric_deltas") if isinstance(diff.get("metric_deltas"), dict) else {}
    hard = diff.get("hard_case_drift") if isinstance(diff.get("hard_case_drift"), dict) else {}

    lines: list[str] = []
    lines.append("# Queryset Health Snapshot Diff")
    lines.append("")
    lines.append("## Policy")
    lines.append("")
    lines.append(f"- Policy Changed: `{bool(policy.get('changed'))}`")
    lines.append(f"- Baseline Source: `{str(policy.get('baseline_source') or '')}`")
    lines.append(f"- Current Source: `{str(policy.get('current_source') or '')}`")
    lines.append(f"- Baseline Hash: `{str(policy.get('baseline_hash') or '')}`")
    lines.append(f"- Current Hash: `{str(policy.get('current_hash') or '')}`")
    lines.append("")
    lines.append("## Metric Deltas")
    lines.append("")
    for key in (
        "hit_at_k_delta",
        "mrr_delta",
        "ndcg_at_k_delta",
        "p95_latency_ms_delta",
        "miss_rate_delta",
        "weak_hit_rate_delta",
    ):
        if key in deltas:
            lines.append(f"- `{key}`: `{deltas.get(key)}`")
    lines.append("")
    lines.append("## Hard Case Drift")
    lines.append("")
    lines.append(f"- Added IDs: `{', '.join(hard.get('added_ids') or [])}`")
    lines.append(f"- Removed IDs: `{', '.join(hard.get('removed_ids') or [])}`")
    lines.append(f"- Retained IDs: `{', '.join(hard.get('retained_ids') or [])}`")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Diff two query-set health snapshot JSON files")
    p.add_argument("--a", required=True, help="Baseline snapshot path")
    p.add_argument("--b", required=True, help="Current snapshot path")
    p.add_argument("--out", default="", help="Optional output JSON path")
    p.add_argument("--out-md", default="", help="Optional output Markdown summary path")
    p.add_argument("--max-hard-case-ids", type=int, default=20, help="Max hard-case IDs to compare")
    p.add_argument("--compact", action="store_true", help="Print compact one-line JSON")
    args = p.parse_args(argv)

    try:
        diff = run(
            baseline_path=Path(args.a),
            current_path=Path(args.b),
            out=Path(args.out) if str(args.out or "").strip() else None,
            max_hard_case_ids=max(1, int(args.max_hard_case_ids or 1)),
        )
        if str(args.out_md or "").strip():
            out_md = Path(str(args.out_md))
            out_md.parent.mkdir(parents=True, exist_ok=True)
            out_md.write_text(_render_markdown(diff), encoding="utf-8")
    except Exception as exc:
        print(f"[diff_queryset_health_snapshots] ERROR: {exc}", file=sys.stderr)
        return 1

    if args.compact:
        print(json.dumps(diff, ensure_ascii=False))
    else:
        print(json.dumps(diff, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
