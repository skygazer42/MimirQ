from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_retrieval_fixture(
    *,
    documents: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    top_k: int = 1,
    retrieval_mode: str = "keyword",
) -> dict[str, Any]:
    return {
        "schema": "mimirq.sample_retrieval_fixture.v1",
        "defaults": {
            "top_k": int(max(1, int(top_k or 1))),
            "retrieval_mode": str(retrieval_mode or "keyword").strip().lower() or "keyword",
        },
        "documents": list(documents or []),
        "queries": list(queries or []),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic retrieval fixture from JSON inputs.")
    parser.add_argument("--documents-json", required=True, help="Path to JSON array of retrieval documents")
    parser.add_argument("--queries-json", required=True, help="Path to JSON array of benchmark queries")
    parser.add_argument("--out", required=True, help="Output fixture JSON path")
    parser.add_argument("--top-k", type=int, default=1, help="Fixture default top_k")
    parser.add_argument("--retrieval-mode", default="keyword", help="Fixture default retrieval mode")
    args = parser.parse_args(argv)

    documents = json.loads(Path(str(args.documents_json)).read_text(encoding="utf-8"))
    queries = json.loads(Path(str(args.queries_json)).read_text(encoding="utf-8"))
    payload = build_retrieval_fixture(
        documents=list(documents or []),
        queries=list(queries or []),
        top_k=int(args.top_k or 1),
        retrieval_mode=str(args.retrieval_mode or "keyword"),
    )
    out_path = Path(str(args.out)).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build-parsing-retrieval-fixture] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
