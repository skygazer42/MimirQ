#!/usr/bin/env python3
"""Build shareable evidence from a raw plugin corpus closed-loop smoke report."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "mimirq.plugin_corpus_closed_loop_evidence.v1"
DEFAULT_INPUT = "/tmp/plugin_corpus_closed_loop_report.json"
DEFAULT_JSON_OUT = "/tmp/plugin_corpus_closed_loop_evidence.json"
DEFAULT_MARKDOWN_OUT = "/tmp/plugin_corpus_closed_loop_evidence.md"

SUMMARY_METRIC_KEYS = (
    "items",
    "retrieval_mrr",
    "retrieval_recall",
    "retrieval_hit_at_1",
    "retrieval_hit_at_3",
    "retrieval_hit_at_5",
    "retrieval_hit_at_10",
    "retrieval_hit_at_20",
    "retrieval_ndcg_at_10",
    "retrieval_ndcg_at_20",
    "expected_metadata_cases_total",
    "expected_metadata_hit_rate",
    "expected_metadata_recall",
    "expected_metadata_fields_total",
    "expected_metadata_fields_matched",
    "citation_accuracy",
    "citation_coverage",
    "retrieval_effective_context_rate",
    "retrieval_noise_rate",
    "citation_eval_limit_avg",
    "citation_evaluated_count_avg",
    "citation_total_count_avg",
)
CITATION_EVAL_WINDOW_KEYS = (
    "citation_eval_limit_avg",
    "citation_evaluated_count_avg",
    "citation_total_count_avg",
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _status_counts(documents: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in documents:
        if not isinstance(item, dict):
            continue
        status = _text(item.get("status")).lower() or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _chunk_totals(documents: list[Any]) -> list[int]:
    totals: list[int] = []
    for item in documents:
        if isinstance(item, dict):
            totals.append(_int_value(item.get("chunk_total")))
    return totals


def _summary(report: dict[str, Any]) -> dict[str, int]:
    documents = _list_value(report.get("documents"))
    chunks = _chunk_totals(documents)
    return {
        "uploaded_count": _int_value(report.get("uploaded_count")),
        "document_count": len(documents),
        "completed_documents": _status_counts(documents).get("completed", 0),
        "skipped_count": len(_list_value(report.get("skipped"))),
        "total_chunks": sum(chunks),
        "min_chunks_per_document": min(chunks) if chunks else 0,
        "max_chunks_per_document": max(chunks) if chunks else 0,
    }


def _plugin_source(golden: dict[str, Any]) -> dict[str, Any]:
    source = _dict_value(golden.get("plugin_source"))
    return {
        key: source[key]
        for key in ("plugin_id", "plugin_version", "plugin_ref", "plugin_package_hash", "draft_items_total")
        if _text(source.get(key))
    }


def _import_counts(golden: dict[str, Any]) -> dict[str, int]:
    result = _dict_value(golden.get("import_result"))
    return {
        "created": _int_value(result.get("created")),
        "updated": _int_value(result.get("updated")),
        "skipped": _int_value(result.get("skipped")),
        "errors": len(_list_value(result.get("errors"))),
    }


def _golden_summary(golden: dict[str, Any]) -> dict[str, Any]:
    summary = _dict_value(golden.get("summary"))
    return {key: summary.get(key) for key in SUMMARY_METRIC_KEYS if key in summary}


def _case_count(golden: dict[str, Any]) -> int:
    case_ids = [item for item in _list_value(golden.get("case_ids")) if _text(item)]
    if case_ids:
        return len(case_ids)
    counts = _import_counts(golden)
    return int(counts["created"] + counts["updated"] + counts["skipped"])


def _failed_checks(
    *,
    summary: dict[str, int],
    documents: list[Any],
    golden: dict[str, Any],
    min_expected_metadata_hit_rate: float,
    min_expected_metadata_recall: float,
    min_retrieval_recall: float,
    min_retrieval_hit_at_3: float,
    min_citation_accuracy: float,
    min_citation_coverage: float,
) -> list[str]:
    failed: list[str] = []
    if summary["uploaded_count"] <= 0:
        failed.append("uploaded_count")
    if summary["document_count"] <= 0:
        failed.append("document_count")
    if summary["completed_documents"] != summary["document_count"]:
        failed.append("completed_documents")
    if any(isinstance(item, dict) and _int_value(item.get("chunk_total")) <= 0 for item in documents):
        failed.append("document_chunks")

    import_counts = _import_counts(golden)
    if import_counts["errors"] > 0:
        failed.append("golden_import_errors")
    if _case_count(golden) <= 0:
        failed.append("golden_case_count")

    metrics = _golden_summary(golden)
    if _float_value(metrics.get("retrieval_recall")) < float(min_retrieval_recall):
        failed.append("retrieval_recall")
    if _float_value(metrics.get("retrieval_hit_at_3")) < float(min_retrieval_hit_at_3):
        failed.append("retrieval_hit_at_3")
    if _float_value(metrics.get("expected_metadata_cases_total")) <= 0:
        failed.append("expected_metadata_cases_total")
    if _float_value(metrics.get("expected_metadata_fields_total")) <= 0:
        failed.append("expected_metadata_fields_total")
    if _float_value(metrics.get("expected_metadata_hit_rate")) < float(min_expected_metadata_hit_rate):
        failed.append("expected_metadata_hit_rate")
    if _float_value(metrics.get("expected_metadata_recall")) < float(min_expected_metadata_recall):
        failed.append("expected_metadata_recall")
    citation_gate_enabled = float(min_citation_accuracy) > 0.0 or float(min_citation_coverage) > 0.0
    if citation_gate_enabled and any(_float_value(metrics.get(key)) <= 0.0 for key in CITATION_EVAL_WINDOW_KEYS):
        failed.append("citation_eval_window")
    if _float_value(metrics.get("citation_accuracy")) < float(min_citation_accuracy):
        failed.append("citation_accuracy")
    if _float_value(metrics.get("citation_coverage")) < float(min_citation_coverage):
        failed.append("citation_coverage")
    return failed


def build_evidence(
    raw_report_path: str | Path = DEFAULT_INPUT,
    *,
    min_expected_metadata_hit_rate: float = 1.0,
    min_expected_metadata_recall: float = 1.0,
    min_retrieval_recall: float = 1.0,
    min_retrieval_hit_at_3: float = 0.8,
    min_citation_accuracy: float = 0.0,
    min_citation_coverage: float = 0.0,
) -> dict[str, Any]:
    report = _load_json(raw_report_path)
    documents = _list_value(report.get("documents"))
    golden = _dict_value(report.get("golden"))
    summary = _summary(report)
    failed_checks = _failed_checks(
        summary=summary,
        documents=documents,
        golden=golden,
        min_expected_metadata_hit_rate=float(min_expected_metadata_hit_rate),
        min_expected_metadata_recall=float(min_expected_metadata_recall),
        min_retrieval_recall=float(min_retrieval_recall),
        min_retrieval_hit_at_3=float(min_retrieval_hit_at_3),
        min_citation_accuracy=float(min_citation_accuracy),
        min_citation_coverage=float(min_citation_coverage),
    )
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_report": str(raw_report_path),
        "passed": not failed_checks,
        "failed_checks": failed_checks,
        "dataset_id": _text(report.get("dataset_id")),
        "plugin_source": _plugin_source(golden),
        "summary": summary,
        "document_status_counts": _status_counts(documents),
        "golden": {
            "case_count": _case_count(golden),
            "import_counts": _import_counts(golden),
            "summary": _golden_summary(golden),
        },
    }


def _markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _header in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_text(cell).replace("\n", " ").replace("|", "\\|") for cell in row) + " |" for row in rows
    )
    return lines


def format_markdown(evidence: dict[str, Any]) -> str:
    summary = _dict_value(evidence.get("summary"))
    plugin = _dict_value(evidence.get("plugin_source"))
    golden = _dict_value(evidence.get("golden"))
    golden_summary = _dict_value(golden.get("summary"))
    import_counts = _dict_value(golden.get("import_counts"))
    status_counts = _dict_value(evidence.get("document_status_counts"))
    lines = [
        "# Plugin Corpus Closed Loop Evidence",
        "",
        f"**Status:** {'PASSED' if evidence.get('passed') is True else 'FAILED'}",
        f"**Generated at:** {_text(evidence.get('generated_at'))}",
        f"**Dataset:** {_text(evidence.get('dataset_id'))}",
        f"**Plugin:** {_text(plugin.get('plugin_ref'))}",
        "",
        "## Corpus Summary",
        "",
        *_markdown_table(
            [
                "uploaded",
                "documents",
                "completed",
                "skipped",
                "chunks",
                "min_chunks",
                "max_chunks",
            ],
            [
                [
                    _text(summary.get("uploaded_count")),
                    _text(summary.get("document_count")),
                    _text(summary.get("completed_documents")),
                    _text(summary.get("skipped_count")),
                    _text(summary.get("total_chunks")),
                    _text(summary.get("min_chunks_per_document")),
                    _text(summary.get("max_chunks_per_document")),
                ]
            ],
        ),
        "",
        "## Document Status",
        "",
        *_markdown_table(["Status", "Count"], [[key, _text(value)] for key, value in sorted(status_counts.items())]),
        "",
        "## Golden Retrieval",
        "",
        *_markdown_table(
            [
                "cases",
                "created",
                "updated",
                "skipped",
                "errors",
                "mrr",
                "hit@1",
                "hit@3",
                "hit@5",
                "recall",
                "metadata_hit_rate",
                "metadata_recall",
                "citation_accuracy",
                "citation_coverage",
                "effective_context_rate",
                "noise_rate",
                "citation_eval_limit_avg",
                "citation_evaluated_count_avg",
                "citation_total_count_avg",
            ],
            [
                [
                    _text(golden.get("case_count")),
                    _text(import_counts.get("created")),
                    _text(import_counts.get("updated")),
                    _text(import_counts.get("skipped")),
                    _text(import_counts.get("errors")),
                    _text(golden_summary.get("retrieval_mrr")),
                    _text(golden_summary.get("retrieval_hit_at_1")),
                    _text(golden_summary.get("retrieval_hit_at_3")),
                    _text(golden_summary.get("retrieval_hit_at_5")),
                    _text(golden_summary.get("retrieval_recall")),
                    _text(golden_summary.get("expected_metadata_hit_rate")),
                    _text(golden_summary.get("expected_metadata_recall")),
                    _text(golden_summary.get("citation_accuracy")),
                    _text(golden_summary.get("citation_coverage")),
                    _text(golden_summary.get("retrieval_effective_context_rate")),
                    _text(golden_summary.get("retrieval_noise_rate")),
                    _text(golden_summary.get("citation_eval_limit_avg")),
                    _text(golden_summary.get("citation_evaluated_count_avg")),
                    _text(golden_summary.get("citation_total_count_avg")),
                ]
            ],
        ),
        "",
        "## Safety",
        "",
        (
            "This evidence file intentionally omits source directories, document ids, "
            "source filenames, case ids, raw questions, and chunk content."
        ),
    ]
    failed = evidence.get("failed_checks")
    if isinstance(failed, list) and failed:
        lines.extend(["", "## Failed Checks", "", ", ".join(_text(item) for item in failed)])
    return "\n".join(lines) + "\n"


def _write_text(path: str | Path, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build shareable evidence from a raw plugin corpus closed-loop smoke report."
    )
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--json-out", default=DEFAULT_JSON_OUT)
    parser.add_argument("--markdown-out", default=DEFAULT_MARKDOWN_OUT)
    parser.add_argument("--min-expected-metadata-hit-rate", type=float, default=1.0)
    parser.add_argument("--min-expected-metadata-recall", type=float, default=1.0)
    parser.add_argument("--min-retrieval-recall", type=float, default=1.0)
    parser.add_argument("--min-retrieval-hit-at-3", type=float, default=0.8)
    parser.add_argument("--min-citation-accuracy", type=float, default=0.0)
    parser.add_argument("--min-citation-coverage", type=float, default=0.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        evidence = build_evidence(
            args.input,
            min_expected_metadata_hit_rate=float(args.min_expected_metadata_hit_rate),
            min_expected_metadata_recall=float(args.min_expected_metadata_recall),
            min_retrieval_recall=float(args.min_retrieval_recall),
            min_retrieval_hit_at_3=float(args.min_retrieval_hit_at_3),
            min_citation_accuracy=float(args.min_citation_accuracy),
            min_citation_coverage=float(args.min_citation_coverage),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[plugin-corpus-closed-loop-evidence] ERROR: {exc}", file=sys.stderr)
        return 2
    json_text = json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    if _text(args.json_out) == "-":
        print(json_text, end="")
    else:
        _write_text(args.json_out, json_text)
    if _text(args.markdown_out):
        _write_text(args.markdown_out, format_markdown(evidence))
    return 0 if evidence.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
