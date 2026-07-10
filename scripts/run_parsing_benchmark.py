#!/usr/bin/env python3
"""
Run parsing backend benchmark on a golden-set corpus (Opt 1).

This script is intentionally lightweight and best-effort:
- It can be used in CI/nightly jobs where only a subset of backends is available.
- It uses proxy metrics (text similarity, table cell overlap, reading-order score, image recall).

Golden-set format:
- Provide a JSON file with a list of cases:
  {
    "cases": [
      {
        "id": "case-1",
        "input_path": "inputs/doc1.pdf",
        "golden_markdown_path": "golden/doc1.md"
      }
    ]
  }
Paths are resolved relative to --golden-dir when not absolute.
"""


import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.parsing.factory import ParserFactory
from app.parsing.quality.benchmark import compute_parsing_proxy_metrics


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_path(base: Path, raw: str) -> Path:
    p = Path(str(raw or "").strip())
    if not p.is_absolute():
        p = (base / p).resolve()
    return p


def _load_cases(*, golden_dir: Path, cases_json: Path) -> list[dict[str, Any]]:
    data = _load_json(cases_json)
    rows = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("cases_json must contain a list or {'cases':[...]} structure")

    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or f"case-{i+1}").strip()
        input_path = str(row.get("input_path") or row.get("input") or "").strip()
        golden_md = str(row.get("golden_markdown_path") or row.get("golden_markdown") or "").strip()
        if not input_path or not golden_md:
            continue
        out.append(
            {
                "id": cid,
                "input_path": _resolve_path(golden_dir, input_path),
                "golden_markdown_path": _resolve_path(golden_dir, golden_md),
            }
        )
    return out


def _join_docs_markdown(docs: list[Any]) -> str:
    parts: list[str] = []
    for d in docs or []:
        parts.append(str(getattr(d, "page_content", "") or "").strip())
    return "\n\n".join([p for p in parts if p]) + ("\n" if parts else "")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run parsing benchmark on a golden-set corpus")
    p.add_argument("--golden-dir", required=True, help="Root dir containing inputs and golden outputs")
    p.add_argument("--cases-json", default="cases.json", help="Cases JSON path (relative to golden-dir)")
    p.add_argument(
        "--backends",
        default="basic,docling,markitdown,magicpdf",
        help="Comma-separated parser backends to benchmark",
    )
    p.add_argument("--output", default="", help="Write JSON report to this path (defaults to stdout)")
    p.add_argument("--skip-unavailable", action="store_true", help="Skip backends that are not configured/enabled")
    args = p.parse_args(argv)

    golden_dir = Path(args.golden_dir).resolve()
    cases_json = _resolve_path(golden_dir, str(args.cases_json))
    cases = _load_cases(golden_dir=golden_dir, cases_json=cases_json)
    if not cases:
        raise SystemExit("No cases loaded (check cases.json)")

    backends = [b.strip() for b in str(args.backends or "").split(",") if b.strip()]
    if not backends:
        raise SystemExit("No backends selected")

    factory = ParserFactory()
    report: dict[str, Any] = {
        "schema": "mimirq.parsing_benchmark_report.v1",
        "golden_dir": str(golden_dir),
        "cases": [],
        "backends": backends,
    }

    for case in cases:
        cid = str(case["id"])
        input_path = Path(case["input_path"])
        golden_md_path = Path(case["golden_markdown_path"])
        case_row: dict[str, Any] = {
            "id": cid,
            "input_path": str(input_path),
            "golden_markdown_path": str(golden_md_path),
            "results": {},
        }

        try:
            golden_md = golden_md_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:  # noqa: BLE001
            case_row["error"] = f"golden_read_failed:{exc.__class__.__name__}"
            report["cases"].append(case_row)
            continue

        for backend in backends:
            key = str(backend)
            try:
                # resolve_backend validates enablement/configuration; we keep this explicit so
                # "skip-unavailable" can work without running the backend.
                factory.resolve_backend(input_path.suffix.lower(), backend)
            except Exception as exc:  # noqa: BLE001
                if args.skip_unavailable:
                    case_row["results"][key] = {"status": "skipped", "reason": str(exc)[:200]}
                    continue
                case_row["results"][key] = {"status": "error", "error": str(exc)[:200]}
                continue

            try:
                docs, resolved, prov = factory.parse_with_provenance(
                    input_path,
                    parser_backend=backend,
                    dataset_id=None,
                    document_id=cid,
                    tenant_id=None,
                    pdf_quality=None,
                    html_xpath=None,
                )
                parsed_md = _join_docs_markdown(docs)
                metrics = compute_parsing_proxy_metrics(parsed_markdown=parsed_md, golden_markdown=golden_md)
                case_row["results"][key] = {
                    "status": "ok",
                    "resolved_backend": resolved,
                    "metrics": metrics,
                    "provenance": prov,
                }
            except Exception as exc:  # noqa: BLE001
                case_row["results"][key] = {"status": "error", "error": f"{exc.__class__.__name__}:{str(exc)[:200]}"}

        report["cases"].append(case_row)

    out = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

