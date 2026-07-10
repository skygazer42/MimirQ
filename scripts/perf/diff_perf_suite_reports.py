#!/usr/bin/env python3
"""
Diff two perf suite reports and flag p95/p99 latency regressions.

Example:
  python scripts/perf/diff_perf_suite_reports.py \
    --baseline ci/perf_suite_baseline.v1.json \
    --current artifacts/perf_suite.current.json \
    --policy ci/perf_regression_policy.v1.json \
    --out artifacts/perf_suite.diff.json \
    --out-md artifacts/perf_suite.diff.md \
    --strict
"""


import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError(f"report root must be object: {path}")
    return obj


def _render_markdown(diff: dict[str, Any]) -> str:
    strict_gate = diff.get("strict_gate") if isinstance(diff.get("strict_gate"), dict) else {}
    cases = diff.get("cases") if isinstance(diff.get("cases"), dict) else {}
    regressions = [c for c in cases.values() if isinstance(c, dict) and bool(c.get("regressed"))]
    lines: list[str] = []
    lines.append("# Perf Suite Diff")
    lines.append("")
    lines.append(f"- Strict Gate Passed: `{bool(strict_gate.get('passed'))}`")
    lines.append(f"- Regressions: `{int(strict_gate.get('regressions', 0) or 0)}`")
    lines.append(f"- Baseline Suite: `{diff.get('baseline_suite')}`")
    lines.append(f"- Current Suite: `{diff.get('current_suite')}`")
    lines.append("")
    if regressions:
        lines.append("## Regressions")
        lines.append("")
        for row in regressions[:20]:
            name = str(row.get("name") or "")
            p95 = row.get("p95") if isinstance(row.get("p95"), dict) else {}
            p99 = row.get("p99") if isinstance(row.get("p99"), dict) else {}
            lines.append(
                f"- `{name}`: p95 `{p95.get('baseline_ms')}` → `{p95.get('current_ms')}`; "
                f"p99 `{p99.get('baseline_ms')}` → `{p99.get('current_ms')}`"
            )
        lines.append("")
    else:
        lines.append("## Regressions")
        lines.append("")
        lines.append("- (none)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Diff perf suite reports (p95/p99 regression gate).")
    p.add_argument("--baseline", required=True, help="Baseline JSON report path")
    p.add_argument("--current", required=True, help="Current JSON report path")
    p.add_argument("--policy", default="", help="Optional regression policy JSON path")
    p.add_argument("--out", default="", help="Optional output diff JSON path")
    p.add_argument("--out-md", default="", help="Optional output Markdown summary path")
    p.add_argument("--strict", action="store_true", help="Exit non-zero if strict gate fails")
    p.add_argument("--compact", action="store_true", help="Print compact one-line JSON")
    args = p.parse_args(argv)

    try:
        baseline = _load_json(Path(args.baseline))
        current = _load_json(Path(args.current))
        policy = _load_json(Path(args.policy)) if str(args.policy or "").strip() else None

        from app.services.perf_suite_diff_service import diff_perf_suite_reports

        diff = diff_perf_suite_reports(baseline=baseline, current=current, policy=policy)

        if str(args.out or "").strip():
            out = Path(str(args.out))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
        if str(args.out_md or "").strip():
            out_md = Path(str(args.out_md))
            out_md.parent.mkdir(parents=True, exist_ok=True)
            out_md.write_text(_render_markdown(diff), encoding="utf-8")
    except Exception as exc:
        print(f"[diff_perf_suite_reports] ERROR: {exc}", file=sys.stderr)
        return 1

    if args.compact:
        print(json.dumps(diff, ensure_ascii=False))
    else:
        print(json.dumps(diff, ensure_ascii=False, indent=2))

    strict_gate = diff.get("strict_gate") if isinstance(diff.get("strict_gate"), dict) else {}
    if bool(args.strict) and (not bool(strict_gate.get("passed"))):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

