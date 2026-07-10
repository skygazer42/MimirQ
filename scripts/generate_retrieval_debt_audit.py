#!/usr/bin/env python3

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


def _render_hierarchy_recall_audit() -> tuple[str, dict[str, Any]]:
    """
    Best-effort structural audit for hierarchy-aware recall overlay.

    Goal:
    - Provide quick signals about whether hierarchy recall is available and "safe-by-default".
    - Keep it deterministic: scan source files for expected knobs and guardrails.
    """

    checks: list[tuple[str, str, str]] = []
    risk_signals = 0

    profiles_path = REPO_ROOT / "app" / "rag" / "core" / "retrieval_profiles.py"
    if not profiles_path.exists():
        checks.append(("hierarchy_profiles_present", "warn", "retrieval_profiles.py missing"))
        risk_signals += 1
    else:
        text = profiles_path.read_text(encoding="utf-8", errors="ignore")
        has_profiles = all(k in text for k in ("hierarchy_recall20", "hierarchy_hybrid_ce", "hierarchy_grounded_strict"))
        checks.append(
            (
                "hierarchy_profiles_present",
                "ok" if has_profiles else "warn",
                "found hierarchy profiles" if has_profiles else "missing one or more hierarchy_* profiles",
            )
        )
        if not has_profiles:
            risk_signals += 1

        def _extract_int(pattern: str) -> int | None:
            m = re.search(pattern, text)
            if not m:
                return None
            try:
                return int(m.group(1))
            except Exception:
                return None

        parent_depth = _extract_int(r'out\["hierarchy_parent_depth"\]\s*=\s*(\d+)')
        sibling_window = _extract_int(r'out\["hierarchy_sibling_window"\]\s*=\s*(\d+)')
        if parent_depth is None or sibling_window is None:
            checks.append(("hierarchy_overlay_safe_defaults", "warn", "could not detect default parent/sibling expansion"))
            risk_signals += 1
        else:
            safe = int(parent_depth) == 0 and int(sibling_window) == 0
            checks.append(
                (
                    "hierarchy_overlay_safe_defaults",
                    "ok" if safe else "warn",
                    f"parent_depth={parent_depth}, sibling_window={sibling_window}",
                )
            )
            if not safe:
                risk_signals += 1

    orchestrator_path = REPO_ROOT / "app" / "rag" / "retrieval" / "orchestrator.py"
    if not orchestrator_path.exists():
        checks.append(("must_recall_anchor_excludes_hierarchy_context", "warn", "orchestrator.py missing"))
        risk_signals += 1
    else:
        text = orchestrator_path.read_text(encoding="utf-8", errors="ignore")
        ok = bool(re.search(r"exclude_retrieval_role_prefixes\s*=\s*\[\s*[\"']hierarchy_[\"']\s*\]", text))
        checks.append(
            (
                "must_recall_anchor_excludes_hierarchy_context",
                "ok" if ok else "warn",
                "exclude_retrieval_role_prefixes=['hierarchy_'] detected" if ok else "missing anchor-field exclusion for hierarchy_*",
            )
        )
        if not ok:
            risk_signals += 1

    eval_path = REPO_ROOT / "app" / "rag" / "evaluation" / "evidence_retrieve_gate.py"
    if not eval_path.exists():
        checks.append(("eval_summary_includes_doc_family_recall", "warn", "evidence_retrieve_gate.py missing"))
        risk_signals += 1
    else:
        text = eval_path.read_text(encoding="utf-8", errors="ignore")
        ok = "retrieval_doc_recall" in text and "retrieval_family_recall" in text
        checks.append(
            (
                "eval_summary_includes_doc_family_recall",
                "ok" if ok else "warn",
                "doc/family recall metrics detected" if ok else "missing retrieval_doc_recall / retrieval_family_recall",
            )
        )
        if not ok:
            risk_signals += 1

    lines = ["| check | status | observed |", "|---|---|---|"]
    for name, status, observed in checks:
        lines.append(f"| {name} | {status} | {observed} |")
    return "\n".join(lines), {"risk_signals": int(risk_signals), "checks": int(len(checks))}


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
    hierarchy_stats: dict[str, Any],
    todo_stats: dict[str, Any],
) -> str:
    return "\n".join(
        [
            "| category | value |",
            "|---|---:|",
            f"| stale_threshold_files | {int(threshold_stats.get('stale_files') or 0)} |",
            f"| flaky_signal_files | {int(flaky_stats.get('files_with_signals') or 0)} |",
            f"| unstable_profiles_flagged | {int(profile_stats.get('profiles_flagged') or 0)} |",
            f"| hierarchy_risk_signals | {int(hierarchy_stats.get('risk_signals') or 0)} |",
            f"| todo_hotspot_files | {int(todo_stats.get('files_with_todo') or 0)} |",
        ]
    )


def _build_action_queue(
    *,
    stale_files: int,
    flaky_files: int,
    unstable_profiles: int,
    hierarchy_risk_signals: int,
    todo_files: int,
) -> str:
    items: list[str] = []
    if stale_files > 0:
        items.append("- Refresh retrieval/release thresholds with current benchmark artifacts.")
    if flaky_files > 0:
        items.append("- Triage flaky-test signals and convert unstable tests into deterministic fixtures.")
    if unstable_profiles > 0:
        items.append("- Re-validate profile compatibility and pin profile-specific guardrails.")
    if hierarchy_risk_signals > 0:
        items.append("- Audit hierarchy recall overlay defaults + guardrails before enabling it broadly.")
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
    hierarchy_text, hierarchy_stats = _render_hierarchy_recall_audit()
    todo_text, todo_stats = _render_todo_hotspots()
    summary_text = _build_summary(
        threshold_stats=threshold_stats,
        flaky_stats=flaky_stats,
        profile_stats=profile_stats,
        hierarchy_stats=hierarchy_stats,
        todo_stats=todo_stats,
    )
    action_queue = _build_action_queue(
        stale_files=int(threshold_stats.get("stale_files") or 0),
        flaky_files=int(flaky_stats.get("files_with_signals") or 0),
        unstable_profiles=int(profile_stats.get("profiles_flagged") or 0),
        hierarchy_risk_signals=int(hierarchy_stats.get("risk_signals") or 0),
        todo_files=int(todo_stats.get("files_with_todo") or 0),
    )

    rendered = (
        template.replace("{{generated_at}}", now.isoformat())
        .replace("{{summary}}", summary_text)
        .replace("{{threshold_staleness}}", threshold_text)
        .replace("{{flaky_tests}}", flaky_text)
        .replace("{{unstable_profiles}}", profile_text)
        .replace("{{hierarchy_recall}}", hierarchy_text)
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
