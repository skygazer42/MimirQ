
import argparse
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def run_sample_parsing_retrieval_proof(
    *,
    manifest_path: Path,
    case_queries_path: Path,
    out_dir: Path,
    thresholds_path: Path | None = None,
    baseline_summary_path: Path | None = None,
    rollout_path: Path | None = None,
) -> dict[str, Any]:
    import json

    from scripts.build_parsing_retrieval_proof_artifacts import (
        build_parsing_proof_report,
        build_parsing_proof_summary,
    )
    from scripts.build_parsing_retrieval_proof_batch_spec import build_batch_spec
    from scripts.build_parsing_retrieval_proof_review import build_review_markdown
    from scripts.diff_parsing_retrieval_proof_summaries import run as run_parsing_proof_diff
    from scripts.parsing_retrieval_proof_gate import normalize_thresholds
    from scripts.run_parsing_retrieval_proof_batch import run_batch
    from scripts.validate_parsing_retrieval_proof_rollout import validate_rollout

    case_queries = json.loads(Path(case_queries_path).resolve().read_text(encoding="utf-8"))
    spec = build_batch_spec(
        manifest_path=Path(manifest_path).resolve(),
        case_queries=case_queries if isinstance(case_queries, dict) else {},
        defaults={"parser_backend": "basic", "top_k": 1, "retrieval_mode": "keyword"},
        case_queries_path=Path(case_queries_path).resolve(),
    )

    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_path = out_dir / "parsing_proof_batch.spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    report = run_batch(spec_path=spec_path, out_dir=out_dir)

    if baseline_summary_path is None:
        baseline_summary_path = _REPO_ROOT / "ci" / "parsing_retrieval_proof_summary_baseline.v1.json"

    summary_path = out_dir / "summary.json"
    report_path = out_dir / "report.json"
    rollout_artifact_path = out_dir / "rollout.json"
    gate_path = out_dir / "gate.json"
    diff_path = out_dir / "diff.json"
    diff_md_path = out_dir / "diff.md"
    review_md_path = out_dir / "review.md"
    if rollout_path is None:
        rollout_path = _REPO_ROOT / "ci" / "parsing_retrieval_proof_rollout.v1.json"
    resolved_rollout_path = Path(rollout_path).resolve() if rollout_path is not None else None
    rollout_payload = None
    if resolved_rollout_path is not None and resolved_rollout_path.exists():
        rollout_raw = json.loads(resolved_rollout_path.read_text(encoding="utf-8"))
        rollout_payload = validate_rollout(rollout_raw if isinstance(rollout_raw, dict) else {})
        rollout_artifact_path.write_text(json.dumps(rollout_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary_payload = build_parsing_proof_summary(report)
    report_payload = build_parsing_proof_report(
        summary_payload,
        summary_path=str(summary_path),
        thresholds={
            "hit_at_k_mean": 1.0,
            "mrr_mean": 1.0,
        },
        rollout=rollout_payload,
    )

    if thresholds_path is not None:
        thresholds_obj = json.loads(Path(thresholds_path).resolve().read_text(encoding="utf-8"))
        normalized = normalize_thresholds(thresholds_obj)
        report_payload = build_parsing_proof_report(
            summary_payload,
            summary_path=str(summary_path),
            thresholds={
                "hit_at_k_mean": float((normalized.get("hit_at_k_mean") or {}).get("min") or 0.0),
                "mrr_mean": float((normalized.get("mrr_mean") or {}).get("min") or 0.0),
            },
            rollout=rollout_payload,
        )

    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gate_payload = {
        "schema": "mimirq.parsing_retrieval_proof_gate_report.v1",
        "passed": bool(report_payload.get("passed")),
        "checks": list(report_payload.get("checks") or []),
        "failures": [],
        "input": str(summary_path),
        "thresholds": str(Path(thresholds_path).resolve()) if thresholds_path is not None else None,
        "provenance": {
            "manifest_path": str(Path(manifest_path).resolve()),
            "case_queries_path": str(Path(case_queries_path).resolve()),
            "spec_path": str(spec_path),
            "batch_report_path": str(out_dir / "batch.report.json"),
            "rollout_path": str(resolved_rollout_path) if resolved_rollout_path is not None else None,
        },
    }
    for check in list(report_payload.get("checks") or []):
        if isinstance(check, dict) and not bool(check.get("passed")):
            gate_payload["failures"].append(f"{check.get('metric')}: below threshold")
    gate_path.write_text(json.dumps(gate_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if baseline_summary_path is not None and Path(baseline_summary_path).exists():
        run_parsing_proof_diff(
            baseline_path=Path(baseline_summary_path).resolve(),
            current_path=summary_path,
            out=diff_path,
            out_md=diff_md_path,
        )
    if diff_path.exists():
        diff_payload = json.loads(diff_path.read_text(encoding="utf-8"))
        review_md_path.write_text(
            build_review_markdown(
                summary=summary_payload,
                report=report_payload,
                gate=gate_payload,
                diff=diff_payload if isinstance(diff_payload, dict) else {},
            ),
            encoding="utf-8",
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the repo sample broader parsing retrieval proof sweep.")
    parser.add_argument(
        "--manifest-json",
        default=str(_REPO_ROOT / "tests" / "fixtures" / "parsing_golden_broader" / "manifest.json"),
        help="Parser manifest JSON (default: tests/fixtures/parsing_golden_broader/manifest.json).",
    )
    parser.add_argument(
        "--case-queries-json",
        default=str(_REPO_ROOT / "tests" / "fixtures" / "parsing_retrieval_proof" / "broader_case_queries.sample.json"),
        help="Case-id to queries mapping JSON.",
    )
    parser.add_argument(
        "--out-dir",
        default=str(_REPO_ROOT / "runs" / "parsing_proof_broader_sample"),
        help="Output directory for generated batch spec and reports.",
    )
    parser.add_argument(
        "--thresholds-json",
        default=str(_REPO_ROOT / "ci" / "parsing_retrieval_proof_thresholds.v1.json"),
        help="Thresholds JSON used to derive the parsing-proof gate artifact.",
    )
    parser.add_argument(
        "--baseline-summary-json",
        default=str(_REPO_ROOT / "ci" / "parsing_retrieval_proof_summary_baseline.v1.json"),
        help="Optional baseline parsing-proof summary JSON used to derive diff artifacts.",
    )
    parser.add_argument(
        "--rollout-json",
        default=str(_REPO_ROOT / "ci" / "parsing_retrieval_proof_rollout.v1.json"),
        help="Optional staged rollout JSON used to annotate parsing-proof artifacts.",
    )
    args = parser.parse_args(argv)

    report = run_sample_parsing_retrieval_proof(
        manifest_path=Path(str(args.manifest_json)),
        case_queries_path=Path(str(args.case_queries_json)),
        out_dir=Path(str(args.out_dir)),
        thresholds_path=Path(str(args.thresholds_json)) if str(args.thresholds_json or "").strip() else None,
        baseline_summary_path=Path(str(args.baseline_summary_json)) if str(args.baseline_summary_json or "").strip() else None,
        rollout_path=Path(str(args.rollout_json)) if str(args.rollout_json or "").strip() else None,
    )
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    print(
        "[sample-parsing-proof] "
        f"cases={report.get('cases_total', 0)} "
        f"queries={report.get('query_count_total', 0)} "
        f"hit@k_mean={summary.get('hit_at_k_mean', 0.0)} "
        f"mrr_mean={summary.get('mrr_mean', 0.0)} "
        f"out={Path(str(args.out_dir)).resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
