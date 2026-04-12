from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_SCHEMA = "mimirq.parsing_retrieval_proof_batch.v1"
_REPORT_SCHEMA = "mimirq.parsing_retrieval_proof_batch_report.v1"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _derive_case_category(*, case_id: str, input_file: Path, declared: Any = None) -> str:
    explicit = str(declared or "").strip().lower().replace("-", "_")
    if explicit:
        return explicit
    if input_file.parent.name == "input" and input_file.parent.parent.name:
        candidate = input_file.parent.parent.name.strip().lower().replace("-", "_")
        if candidate:
            if "chart" in candidate:
                return "chart"
            if "diagram" in candidate:
                return "diagram"
            if candidate.startswith("qr") or "_qr" in candidate or "qr_" in candidate:
                return "qr"
            if "barcode" in candidate:
                return "barcode"
            return candidate
    slug = str(case_id or "unknown").strip().lower().replace("-", "_")
    if slug.endswith("_case"):
        slug = slug[: -len("_case")]
    return slug or "unknown"


def _derive_case_family(*, case_category: str, declared: Any = None) -> str:
    explicit = str(declared or "").strip().lower()
    if explicit:
        return explicit
    category = str(case_category or "").strip().lower()
    if category in {"chart", "diagram", "qr", "barcode"}:
        return "specialty"
    if "table" in category:
        return "table"
    if category in {"two_column_pdf", "header_footer_noise_pdf", "mixed_layout_pdf"} or "layout" in category:
        return "layout"
    return "document"


def _count_queries(path: Path) -> int:
    payload = _read_json(Path(path).resolve())
    if isinstance(payload, list):
        return int(len(payload))
    return 0


def run_batch(*, spec_path: Path, out_dir: Path) -> dict[str, Any]:
    from scripts.run_parsing_retrieval_proof_from_file import run_parsing_retrieval_proof_from_file

    spec = _read_json(Path(spec_path).resolve())
    if not isinstance(spec, dict):
        raise ValueError("batch_spec_invalid")
    defaults = spec.get("defaults") if isinstance(spec.get("defaults"), dict) else {}
    spec_provenance = spec.get("provenance") if isinstance(spec.get("provenance"), dict) else {}
    raw_cases = spec.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("batch_cases_required")

    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    case_reports: list[dict[str, Any]] = []
    hit_vals: list[float] = []
    mrr_vals: list[float] = []
    query_count_total = 0
    family_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}

    for index, raw in enumerate(raw_cases):
        case = raw if isinstance(raw, dict) else {}
        case_id = str(case.get("id") or f"case-{index + 1}").strip() or f"case-{index + 1}"
        input_file = Path(str(case.get("input_file") or "")).resolve()
        queries_json = Path(str(case.get("queries_json") or "")).resolve()
        parser_backend = str(case.get("parser_backend") or defaults.get("parser_backend") or "basic")
        top_k = int(case.get("top_k") or defaults.get("top_k") or 1)
        retrieval_mode = str(case.get("retrieval_mode") or defaults.get("retrieval_mode") or "keyword")
        case_category = _derive_case_category(
            case_id=case_id,
            input_file=input_file,
            declared=case.get("case_category"),
        )
        case_family = _derive_case_family(case_category=case_category, declared=case.get("case_family"))
        query_count = int(case.get("query_count") or _count_queries(queries_json))

        fixture_out = out_dir / f"{case_id}.fixture.json"
        report_out = out_dir / f"{case_id}.report.json"
        report = run_parsing_retrieval_proof_from_file(
            input_file=input_file,
            queries_path=queries_json,
            fixture_output_path=fixture_out,
            report_output_path=report_out,
            parser_backend=parser_backend,
            top_k=top_k,
            retrieval_mode=retrieval_mode,
        )
        summary = report.get("summary") if isinstance(report, dict) and isinstance(report.get("summary"), dict) else {}
        hit_at_k = float(summary.get("hit_at_k") or 0.0)
        mrr = float(summary.get("mrr") or 0.0)
        hit_vals.append(hit_at_k)
        mrr_vals.append(mrr)
        query_count_total += query_count
        family_counts[case_family] = int(family_counts.get(case_family) or 0) + 1
        category_counts[case_category] = int(category_counts.get(case_category) or 0) + 1
        case_reports.append(
            {
                "id": case_id,
                "input_file": str(input_file),
                "queries_json": str(queries_json),
                "parser_backend": parser_backend,
                "top_k": int(top_k),
                "retrieval_mode": retrieval_mode,
                "case_family": case_family,
                "case_category": case_category,
                "query_count": query_count,
                "fixture_path": str(fixture_out),
                "report_path": str(report_out),
                "provenance": {
                    "input_file": str(input_file),
                    "queries_json": str(queries_json),
                    "fixture_path": str(fixture_out),
                    "report_path": str(report_out),
                    "manifest_path": spec_provenance.get("manifest_path"),
                    "manifest_rel_path": case.get("manifest_rel_path"),
                },
                "summary": summary,
            }
        )

    report_payload = {
        "schema": _REPORT_SCHEMA,
        "spec_schema": str(spec.get("schema") or ""),
        "spec_path": str(Path(spec_path).resolve()),
        "cases_total": int(len(case_reports)),
        "query_count_total": int(query_count_total),
        "case_family_counts": family_counts,
        "case_category_counts": category_counts,
        "provenance": {
            "spec_path": str(Path(spec_path).resolve()),
            "manifest_path": spec_provenance.get("manifest_path"),
            "case_queries_path": spec_provenance.get("case_queries_path"),
            "out_dir": str(out_dir),
        },
        "summary": {
            "hit_at_k_mean": round(float(statistics.mean(hit_vals)), 6) if hit_vals else 0.0,
            "mrr_mean": round(float(statistics.mean(mrr_vals)), 6) if mrr_vals else 0.0,
        },
        "cases": case_reports,
    }
    (out_dir / "batch.report.json").write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run multiple parsing retrieval proof cases from a batch spec JSON.")
    parser.add_argument("--spec-json", required=True, help="Path to batch spec JSON.")
    parser.add_argument("--out-dir", required=True, help="Directory where per-case fixtures/reports are written.")
    args = parser.parse_args(argv)

    report = run_batch(spec_path=Path(str(args.spec_json)), out_dir=Path(str(args.out_dir)))
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    print(
        "[parsing-proof-batch] "
        f"cases={report.get('cases_total', 0)} "
        f"hit@k_mean={summary.get('hit_at_k_mean', 0.0)} "
        f"mrr_mean={summary.get('mrr_mean', 0.0)} "
        f"out={Path(str(args.out_dir)).resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
