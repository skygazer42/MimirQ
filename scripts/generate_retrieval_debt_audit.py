#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = REPO_ROOT / "docs" / "templates" / "retrieval_debt_audit_template.md"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _safe_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _age_days(path: Path, now: datetime) -> int | None:
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    delta = now - mtime
    return max(0, int(delta.total_seconds() // 86400))


def _render_threshold_staleness(*, now: datetime, stale_days: int) -> tuple[str, dict[str, Any]]:
    files = [
        REPO_ROOT / "ci" / "retrieval_thresholds.v2.json",
        REPO_ROOT / "ci" / "release_gate_budgets.v1.json",
        REPO_ROOT / "ci" / "kg_search_thresholds.v1.json",
    ]
    lines: list[str] = ["| file | age_days | stale |", "|---|---:|---|"]
    stale_count = 0
    checked = 0
    for path in files:
        age = _age_days(path, now)
        if age is None:
            lines.append(f"| {path.relative_to(REPO_ROOT)} | missing | yes |")
            stale_count += 1
            checked += 1
            continue
        checked += 1
        stale = age >= int(stale_days)
        if stale:
            stale_count += 1
        lines.append(f"| {path.relative_to(REPO_ROOT)} | {age} | {'yes' if stale else 'no'} |")
    return "\n".join(lines), {"files_checked": checked, "stale_files": stale_count}


def _render_flaky_tests() -> tuple[str, dict[str, Any]]:
    tests_dir = REPO_ROOT / "tests"
    if not tests_dir.exists():
        return "No tests directory found.", {"files_with_signals": 0, "signal_count": 0}

    patterns = [
        re.compile(r"@pytest\\.mark\\.flaky"),
        re.compile(r"@pytest\\.mark\\.xfail"),
        re.compile(r"rerun", flags=re.IGNORECASE),
        re.compile(r"non[-_ ]?determin", flags=re.IGNORECASE),
        re.compile(r"sleep\(", flags=re.IGNORECASE),
    ]

    hits: list[tuple[str, int, str]] = []
    for path in sorted(tests_dir.rglob("test_*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if any(p.search(line) for p in patterns):
                rel = str(path.relative_to(REPO_ROOT))
                hits.append((rel, lineno, line.strip()))

    if not hits:
        return "No obvious flaky-test signals found.", {"files_with_signals": 0, "signal_count": 0}

    by_file: dict[str, int] = {}
    for rel, _, _ in hits:
        by_file[rel] = by_file.get(rel, 0) + 1
    top = sorted(by_file.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    lines = ["| file | signal_count |", "|---|---:|"]
    for rel, cnt in top:
        lines.append(f"| {rel} | {cnt} |")
    return "\n".join(lines), {"files_with_signals": len(by_file), "signal_count": len(hits)}


def _render_unstable_profiles() -> tuple[str, dict[str, Any]]:
    path = REPO_ROOT / "app" / "rag" / "core" / "retrieval_profiles.py"
    if not path.exists():
        return "Profile definition file not found.", {"profiles_flagged": 0}

    text = path.read_text(encoding="utf-8", errors="ignore")
    # Keep this heuristic explicit and deterministic.
    rows: list[tuple[str, str]] = []
    if "recall50" in text:
        rows.append(("recall50", "high fanout (top_k>=50), sensitive to latency/cost drift"))
    if "coverage80" in text:
        rows.append(("coverage80", "very high fanout (top_k>=80), sensitive to timeout/recall tradeoff"))
    if "hybrid_ce" in text:
        rows.append(("hybrid_ce", "depends on cross-encoder reranker availability/versioning"))

    if not rows:
        return "No profile risk signals detected.", {"profiles_flagged": 0}

    lines = ["| profile | risk_signal |", "|---|---|"]
    for name, reason in rows:
        lines.append(f"| {name} | {reason} |")
    return "\n".join(lines), {"profiles_flagged": len(rows)}


def _render_todo_hotspots() -> tuple[str, dict[str, Any]]:
    roots = [REPO_ROOT / "app", REPO_ROOT / "scripts", REPO_ROOT / "tests", REPO_ROOT / "docs"]
    marker = re.compile(r"\\b(TODO|FIXME|HACK)\\b", flags=re.IGNORECASE)
    counts: dict[str, int] = {}

    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".py", ".md", ".yml", ".yaml", ".json", ".txt"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            n = sum(1 for line in text.splitlines() if marker.search(line))
            if n > 0:
                counts[str(path.relative_to(REPO_ROOT))] = n

    if not counts:
        return "No TODO/FIXME/HACK hotspots found.", {"files_with_todo": 0, "todo_total": 0}

    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    lines = ["| file | todo_markers |", "|---|---:|"]
    for rel, cnt in top:
        lines.append(f"| {rel} | {cnt} |")
    return "\n".join(lines), {"files_with_todo": len(counts), "todo_total": sum(counts.values())}


def _build_summary(
    *,
    threshold_stats: dict[str, Any],
    flaky_stats: dict[str, Any],
    profile_stats: dict[str, Any],
    todo_stats: dict[str, Any],
) -> str:
    return "\n".join(
        [
            "| category | value |",
            "|---|---:|",
            f"| stale_threshold_files | {int(threshold_stats.get('stale_files') or 0)} |",
            f"| flaky_signal_files | {int(flaky_stats.get('files_with_signals') or 0)} |",
            f"| unstable_profiles_flagged | {int(profile_stats.get('profiles_flagged') or 0)} |",
            f"| todo_hotspot_files | {int(todo_stats.get('files_with_todo') or 0)} |",
        ]
    )


def _build_action_queue(
    *,
    stale_files: int,
    flaky_files: int,
    unstable_profiles: int,
    todo_files: int,
) -> str:
    items: list[str] = []
    if stale_files > 0:
        items.append("- Refresh retrieval/release thresholds with current benchmark artifacts.")
    if flaky_files > 0:
        items.append("- Triage flaky-test signals and convert unstable tests into deterministic fixtures.")
    if unstable_profiles > 0:
        items.append("- Re-validate profile compatibility and pin profile-specific guardrails.")
    if todo_files > 0:
        items.append("- Burn down top TODO hotspots with owner + due date.")
    if not items:
        items.append("- No high-risk debt signals detected; keep quarterly cadence.")
    return "\n".join(items)


def generate_report(*, out_path: Path, template_path: Path, stale_days: int) -> str:
    now = _now_utc()
    template = template_path.read_text(encoding="utf-8") if template_path.exists() else (
        "# Retrieval Debt Audit\n\nGenerated At: {{generated_at}}\n\n{{summary}}\n"
    )

    threshold_text, threshold_stats = _render_threshold_staleness(now=now, stale_days=stale_days)
    flaky_text, flaky_stats = _render_flaky_tests()
    profile_text, profile_stats = _render_unstable_profiles()
    todo_text, todo_stats = _render_todo_hotspots()
    summary_text = _build_summary(
        threshold_stats=threshold_stats,
        flaky_stats=flaky_stats,
        profile_stats=profile_stats,
        todo_stats=todo_stats,
    )
    action_queue = _build_action_queue(
        stale_files=int(threshold_stats.get("stale_files") or 0),
        flaky_files=int(flaky_stats.get("files_with_signals") or 0),
        unstable_profiles=int(profile_stats.get("profiles_flagged") or 0),
        todo_files=int(todo_stats.get("files_with_todo") or 0),
    )

    rendered = (
        template.replace("{{generated_at}}", now.isoformat())
        .replace("{{summary}}", summary_text)
        .replace("{{threshold_staleness}}", threshold_text)
        .replace("{{flaky_tests}}", flaky_text)
        .replace("{{unstable_profiles}}", profile_text)
        .replace("{{todo_hotspots}}", todo_text)
        .replace("{{action_queue}}", action_queue)
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered.rstrip() + "\n", encoding="utf-8")
    return rendered


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate quarterly retrieval debt audit report.")
    p.add_argument("--out", default="runs/retrieval_debt_audit.md", help="Output markdown path")
    p.add_argument("--template", default=str(DEFAULT_TEMPLATE), help="Template markdown path")
    p.add_argument("--stale-days", type=int, default=90, help="Threshold staleness cutoff in days")
    args = p.parse_args(argv)

    out = Path(args.out)
    template = Path(args.template)
    generate_report(out_path=out, template_path=template, stale_days=max(1, int(args.stale_days or 90)))
    print(f"[retrieval-debt-audit] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
