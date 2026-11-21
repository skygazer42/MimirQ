import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.documents import Document

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            safe = _json_safe(item)
            if safe is not None:
                out[str(key)] = safe
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            safe = _json_safe(item)
            if safe is not None:
                out.append(safe)
        return out
    return None


def _serialize_documents(items: list["Document"]) -> list[dict[str, Any]]:
    return [{"page_content": item.page_content, "metadata": _json_safe(item.metadata), "id": item.id} for item in items]


def _apply_governance_cleaning(
    *,
    text: str,
    governance_rule_packs: list[str] | None = None,
) -> str:
    packs = [pack for item in governance_rule_packs or [] if (pack := item.strip())]
    if not packs:
        return text

    from app.rag.ingestion.governance.cleaning import clean_markdown
    from app.rag.ingestion.governance.rules import build_governance_rules

    result = clean_markdown(
        text,
        rules=build_governance_rules([], rule_packs=packs),
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        collapse_blank_lines=True,
    )
    return result.markdown or text


def run_parsing_retrieval_proof_from_file(
    *,
    input_file: Path,
    queries_path: Path,
    fixture_output_path: Path,
    report_output_path: Path,
    parser_backend: str = "basic",
    top_k: int = 1,
    retrieval_mode: str = "keyword",
    governance_rule_packs: list[str] | None = None,
) -> dict[str, Any]:
    input_file = Path(input_file).resolve()
    queries_path = Path(queries_path).resolve()
    fixture_output_path = Path(fixture_output_path).resolve()
    report_output_path = Path(report_output_path).resolve()
    if fixture_output_path == report_output_path:
        raise ValueError("fixture and benchmark report paths must be distinct")
    if {fixture_output_path, report_output_path} & {input_file, queries_path}:
        raise ValueError("proof output paths must be distinct from source inputs")

    from app.rag.ingestion.parsing.enrich.image_ocr import add_image_ocr_blocks
    from app.rag.ingestion.parsing.factory import parser_factory
    from scripts.build_parsing_retrieval_fixture import _read_json, build_retrieval_fixture
    from scripts.run_sample_retrieval_benchmark import run_benchmark

    queries = _read_json(queries_path)
    documents, _backend, _provenance = parser_factory.parse_with_provenance(
        input_file,
        parser_backend=str(parser_backend or "basic").strip().lower() or "basic",
    )
    for item in documents:
        page_content = item.page_content
        try:
            next_content, _added, _audit = add_image_ocr_blocks(page_content, origin_path=input_file)
        except Exception:
            next_content = page_content
        next_content = _apply_governance_cleaning(
            text=next_content,
            governance_rule_packs=governance_rule_packs,
        )
        item.page_content = next_content
    top_k = int(top_k or 1)
    retrieval_mode = str(retrieval_mode or "keyword")
    fixture = build_retrieval_fixture(
        documents=_serialize_documents(documents),
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
            "Parse a real source file, build a retrieval fixture from the parser output, "
            "and immediately run the deterministic retrieval benchmark."
        )
    )
    parser.add_argument("--input-file", required=True, help="Source file to parse.")
    parser.add_argument("--queries-json", required=True, help="Path to query specs JSON.")
    parser.add_argument("--fixture-out", required=True, help="Output retrieval fixture JSON path.")
    parser.add_argument("--report-out", required=True, help="Output retrieval benchmark report JSON path.")
    parser.add_argument("--parser-backend", default="basic", help="Requested parser backend (default: basic).")
    parser.add_argument("--top-k", type=int, default=1, help="Fixture default top_k and benchmark top_k.")
    parser.add_argument("--retrieval-mode", default="keyword", help="Benchmark retrieval mode.")
    parser.add_argument(
        "--governance-rule-pack",
        action="append",
        default=[],
        help="Optional governance rule pack(s) applied to parsed text before building the retrieval fixture.",
    )
    args = parser.parse_args(argv)

    report = run_parsing_retrieval_proof_from_file(
        input_file=Path(args.input_file),
        queries_path=Path(args.queries_json),
        fixture_output_path=Path(args.fixture_out),
        report_output_path=Path(args.report_out),
        parser_backend=args.parser_backend,
        top_k=args.top_k,
        retrieval_mode=args.retrieval_mode,
        governance_rule_packs=args.governance_rule_pack,
    )
    summary = report.get("summary") if isinstance(report, dict) and isinstance(report.get("summary"), dict) else {}
    print(
        "[parsing-proof-file] "
        f"cases={summary.get('cases_total', 0)} "
        f"hit@k={summary.get('hit_at_k', 0.0)} "
        f"mrr={summary.get('mrr', 0.0)} "
        f"fixture={Path(args.fixture_out).resolve()} "
        f"report={Path(args.report_out).resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
