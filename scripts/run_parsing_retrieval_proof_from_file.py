from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

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


def _serialize_documents(items: list[Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items or []:
        meta = getattr(item, "metadata", None)
        safe_meta = _json_safe(dict(meta)) if isinstance(meta, dict) else {}
        out.append(
            {
                "page_content": str(getattr(item, "page_content", "") or ""),
                "metadata": safe_meta if isinstance(safe_meta, dict) else {},
                "id": getattr(item, "id", None),
            }
        )
    return out


def _apply_governance_cleaning(
    *,
    text: str,
    governance_rule_packs: list[str] | None = None,
) -> str:
    packs = [str(item).strip() for item in (governance_rule_packs or []) if str(item).strip()]
    if not packs:
        return str(text or "")

    from app.rag.preprocessing.cleaning import clean_markdown
    from app.rag.preprocessing.rules import build_governance_rules

    result = clean_markdown(
        str(text or ""),
        rules=build_governance_rules([], rule_packs=packs),
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        collapse_blank_lines=True,
    )
    return str(result.markdown or text or "")


def run_parsing_retrieval_proof_from_file(
    *,
    input_file: Path,
    queries_path: Path,
    fixture_output_path: Path,
    report_output_path: Path,
    parser_backend: str = "basic",
    top_k: int = 1,
    retrieval_mode: str = "keyword",
    sparse_retrieval_enabled: bool = False,
    sparse_retrieval_provider: str = "deterministic",
    colbert_retrieval_enabled: bool | None = None,
    colbert_retrieval_provider: str | None = None,
    governance_rule_packs: list[str] | None = None,
) -> dict[str, Any]:
    from app.parsing.enrich.image_ocr import add_image_ocr_blocks
    from app.parsing.factory import parser_factory
    from scripts.build_parsing_retrieval_fixture import _read_json, build_retrieval_fixture
    from scripts.run_sample_retrieval_benchmark import run_benchmark

    input_file = Path(input_file).resolve()
    queries = _read_json(Path(queries_path).resolve())
    documents, _backend, _provenance = parser_factory.parse_with_provenance(
        input_file,
        parser_backend=str(parser_backend or "basic").strip().lower() or "basic",
    )
    augmented_documents = []
    for item in documents or []:
        page_content = str(getattr(item, "page_content", "") or "")
        metadata = dict(getattr(item, "metadata", None) or {})
        try:
            next_content, _added, _audit = add_image_ocr_blocks(page_content, origin_path=input_file)
        except Exception:
            next_content = page_content
        next_content = _apply_governance_cleaning(
            text=next_content,
            governance_rule_packs=governance_rule_packs,
        )
        item.page_content = next_content
        item.metadata = metadata
        augmented_documents.append(item)
    fixture = build_retrieval_fixture(
        documents=_serialize_documents(augmented_documents),
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
        description="Parse a real source file, build a retrieval fixture from the parser output, and immediately run the deterministic retrieval benchmark."
    )
    parser.add_argument("--input-file", required=True, help="Source file to parse.")
    parser.add_argument("--queries-json", required=True, help="Path to query specs JSON.")
    parser.add_argument("--fixture-out", required=True, help="Output retrieval fixture JSON path.")
    parser.add_argument("--report-out", required=True, help="Output retrieval benchmark report JSON path.")
    parser.add_argument("--parser-backend", default="basic", help="Requested parser backend (default: basic).")
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
    parser.add_argument(
        "--governance-rule-pack",
        action="append",
        default=[],
        help="Optional governance rule pack(s) applied to parsed text before building the retrieval fixture.",
    )
    args = parser.parse_args(argv)

    report = run_parsing_retrieval_proof_from_file(
        input_file=Path(str(args.input_file)),
        queries_path=Path(str(args.queries_json)),
        fixture_output_path=Path(str(args.fixture_out)),
        report_output_path=Path(str(args.report_out)),
        parser_backend=str(args.parser_backend or "basic"),
        top_k=int(args.top_k or 1),
        retrieval_mode=str(args.retrieval_mode or "keyword"),
        sparse_retrieval_enabled=bool(args.enable_sparse_retrieval),
        sparse_retrieval_provider=str(args.sparse_retrieval_provider or "deterministic"),
        colbert_retrieval_enabled=args.enable_colbert_retrieval,
        colbert_retrieval_provider=args.colbert_retrieval_provider,
        governance_rule_packs=[
            str(item).strip()
            for item in (args.governance_rule_pack or [])
            if str(item).strip()
        ],
    )
    summary = report.get("summary") if isinstance(report, dict) and isinstance(report.get("summary"), dict) else {}
    print(
        "[parsing-proof-file] "
        f"cases={summary.get('cases_total', 0)} "
        f"hit@k={summary.get('hit_at_k', 0.0)} "
        f"mrr={summary.get('mrr', 0.0)} "
        f"fixture={Path(str(args.fixture_out)).resolve()} "
        f"report={Path(str(args.report_out)).resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
