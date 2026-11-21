import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def run_parsing_retrieval_proof(
    *,
    documents_path: Path,
    queries_path: Path,
    fixture_output_path: Path,
    report_output_path: Path,
    top_k: int = 1,
    retrieval_mode: str = "keyword",
) -> dict[str, Any]:
    from scripts.build_parsing_retrieval_fixture import _coerce_documents_payload, _read_json, build_retrieval_fixture
    from scripts.run_sample_retrieval_benchmark import run_benchmark

    documents_path = Path(documents_path).resolve()
    queries_path = Path(queries_path).resolve()
    fixture_output_path = Path(fixture_output_path).resolve()
    report_output_path = Path(report_output_path).resolve()
    inputs = {documents_path, queries_path}
    outputs = {fixture_output_path, report_output_path}
    if len(outputs) != 2 or inputs & outputs:
        raise ValueError("fixture and report output paths must be distinct from each other and the input files")

    documents = _coerce_documents_payload(_read_json(documents_path))
    queries = _read_json(queries_path)
    top_k = int(top_k or 1)
    retrieval_mode = str(retrieval_mode or "keyword")
    fixture = build_retrieval_fixture(
        documents=documents,
        queries=queries if isinstance(queries, list) else [],
        top_k=top_k,
        retrieval_mode=retrieval_mode,
    )

    fixture_output_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_output_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")

    return run_benchmark(
        fixture_path=fixture_output_path,
        output_path=report_output_path,
        top_k=top_k,
        retrieval_mode=retrieval_mode,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a retrieval fixture from parser-like outputs and immediately run "
            "the deterministic retrieval benchmark."
        )
    )
    parser.add_argument("--documents-json", required=True, help="Path to parser-like document rows JSON.")
    parser.add_argument("--queries-json", required=True, help="Path to query specs JSON.")
    parser.add_argument("--fixture-out", required=True, help="Output retrieval fixture JSON path.")
    parser.add_argument("--report-out", required=True, help="Output retrieval benchmark report JSON path.")
    parser.add_argument("--top-k", type=int, default=1, help="Fixture default top_k and benchmark top_k.")
    parser.add_argument("--retrieval-mode", default="keyword", help="Benchmark retrieval mode.")
    args = parser.parse_args(argv)

    report = run_parsing_retrieval_proof(
        documents_path=Path(args.documents_json),
        queries_path=Path(args.queries_json),
        fixture_output_path=Path(args.fixture_out),
        report_output_path=Path(args.report_out),
        top_k=args.top_k,
        retrieval_mode=args.retrieval_mode,
    )
    summary = report.get("summary") if isinstance(report, dict) and isinstance(report.get("summary"), dict) else {}
    print(
        "[parsing-proof] "
        f"cases={summary.get('cases_total', 0)} "
        f"hit@k={summary.get('hit_at_k', 0.0)} "
        f"mrr={summary.get('mrr', 0.0)} "
        f"fixture={Path(args.fixture_out).resolve()} "
        f"report={Path(args.report_out).resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
