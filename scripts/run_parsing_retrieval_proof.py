from __future__ import annotations

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
    sparse_retrieval_enabled: bool = False,
    sparse_retrieval_provider: str = "deterministic",
    colbert_retrieval_enabled: bool | None = None,
    colbert_retrieval_provider: str | None = None,
) -> dict[str, Any]:
    from scripts.build_parsing_retrieval_fixture import _coerce_documents_payload, _read_json, build_retrieval_fixture
    from scripts.run_sample_retrieval_benchmark import run_benchmark

    documents = _coerce_documents_payload(_read_json(Path(documents_path).resolve()))
    queries = _read_json(Path(queries_path).resolve())
    fixture = build_retrieval_fixture(
        documents=documents,
        queries=queries if isinstance(queries, list) else [],
        top_k=int(top_k or 1),
        retrieval_mode=str(retrieval_mode or "keyword"),
    )

    fixture_output_path = Path(fixture_output_path).resolve()
    fixture_output_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_output_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")

    return run_benchmark(
        fixture_path=fixture_output_path,
        output_path=Path(report_output_path).resolve(),
        top_k=int(top_k or 1),
        retrieval_mode=str(retrieval_mode or "keyword"),
        sparse_retrieval_enabled=bool(sparse_retrieval_enabled),
        sparse_retrieval_provider=str(sparse_retrieval_provider or "deterministic"),
        colbert_retrieval_enabled=colbert_retrieval_enabled,
        colbert_retrieval_provider=colbert_retrieval_provider,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a retrieval fixture from parser-like outputs and immediately run the deterministic retrieval benchmark."
    )
    parser.add_argument("--documents-json", required=True, help="Path to parser-like document rows JSON.")
    parser.add_argument("--queries-json", required=True, help="Path to query specs JSON.")
    parser.add_argument("--fixture-out", required=True, help="Output retrieval fixture JSON path.")
    parser.add_argument("--report-out", required=True, help="Output retrieval benchmark report JSON path.")
    parser.add_argument("--top-k", type=int, default=1, help="Fixture default top_k and benchmark top_k.")
    parser.add_argument("--retrieval-mode", default="keyword", help="Benchmark retrieval mode.")
    parser.add_argument(
        "--enable-sparse-retrieval",
        action="store_true",
        help="Enable sparse retrieval channel for this proof run.",
    )
    parser.add_argument(
        "--sparse-retrieval-provider",
        default="deterministic",
        help="Sparse retrieval provider (deterministic|splade; unknown values fallback downstream).",
    )
    parser.add_argument(
        "--enable-colbert-retrieval",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable ColBERT ANN fallback retrieval for this proof run.",
    )
    parser.add_argument(
        "--colbert-retrieval-provider",
        default=None,
        help="ColBERT retrieval provider (deterministic|hf).",
    )
    args = parser.parse_args(argv)

    report = run_parsing_retrieval_proof(
        documents_path=Path(str(args.documents_json)),
        queries_path=Path(str(args.queries_json)),
        fixture_output_path=Path(str(args.fixture_out)),
        report_output_path=Path(str(args.report_out)),
        top_k=int(args.top_k or 1),
        retrieval_mode=str(args.retrieval_mode or "keyword"),
        sparse_retrieval_enabled=bool(args.enable_sparse_retrieval),
        sparse_retrieval_provider=str(args.sparse_retrieval_provider or "deterministic"),
        colbert_retrieval_enabled=args.enable_colbert_retrieval,
        colbert_retrieval_provider=args.colbert_retrieval_provider,
    )
    summary = report.get("summary") if isinstance(report, dict) and isinstance(report.get("summary"), dict) else {}
    print(
        "[parsing-proof] "
        f"cases={summary.get('cases_total', 0)} "
        f"hit@k={summary.get('hit_at_k', 0.0)} "
        f"mrr={summary.get('mrr', 0.0)} "
        f"fixture={Path(str(args.fixture_out)).resolve()} "
        f"report={Path(str(args.report_out)).resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
