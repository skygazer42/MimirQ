from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.build_parsing_retrieval_fixture import build_retrieval_fixture


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _serialize_documents(items: list[Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items or []:
        meta = getattr(item, "metadata", None)
        out.append(
            {
                "page_content": str(getattr(item, "page_content", "") or ""),
                "metadata": dict(meta) if isinstance(meta, dict) else {},
                "id": getattr(item, "id", None),
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic retrieval fixture directly from a parser-readable input file.")
    parser.add_argument("--input-file", required=True, help="Source file to parse into retrieval documents.")
    parser.add_argument("--queries-json", required=True, help="Path to query specs JSON.")
    parser.add_argument("--out", required=True, help="Output fixture JSON path.")
    parser.add_argument("--parser-backend", default="basic", help="Requested parser backend (default: basic).")
    parser.add_argument("--top-k", type=int, default=1, help="Fixture default top_k.")
    parser.add_argument("--retrieval-mode", default="keyword", help="Fixture default retrieval mode.")
    args = parser.parse_args(argv)

    from app.parsing.factory import parser_factory

    input_path = Path(str(args.input_file)).resolve()
    queries = _read_json(Path(str(args.queries_json)).resolve())
    documents, _backend, _provenance = parser_factory.parse_with_provenance(
        input_path,
        parser_backend=str(args.parser_backend or "basic").strip().lower() or "basic",
    )
    fixture = build_retrieval_fixture(
        documents=_serialize_documents(documents),
        queries=queries if isinstance(queries, list) else [],
        top_k=int(args.top_k or 1),
        retrieval_mode=str(args.retrieval_mode or "keyword"),
    )

    out_path = Path(str(args.out)).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build-parsing-retrieval-fixture-from-file] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
