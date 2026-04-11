from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

_SCHEMA = "mimirq.sample_retrieval_fixture.v1"


def _normalize_documents(raw_documents: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, item in enumerate(raw_documents or []):
        row = item if isinstance(item, dict) else {}
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        fixture_meta = dict(meta)
        for key in ("page", "pages", "bbox", "visual_kind", "kind", "element_kind", "element_id"):
            if key in fixture_meta:
                continue
            value = row.get(key)
            if value is not None:
                fixture_meta[key] = value
        chunk_id = str(
            row.get("chunk_id")
            or meta.get("chunk_id")
            or row.get("element_id")
            or row.get("id")
            or f"chunk-{index + 1}"
        ).strip()
        text = str(row.get("text") or row.get("element_text") or row.get("page_content") or "").strip()
        if not chunk_id or not text:
            continue
        document_id = str(
            row.get("document_id")
            or meta.get("document_id")
            or meta.get("source")
            or f"doc-{index + 1}"
        ).strip()
        fixture_meta.setdefault("source", str(meta.get("source") or f"{document_id}.md"))
        out.append(
            {
                "chunk_id": chunk_id,
                "document_id": document_id,
                "text": text,
                "metadata": fixture_meta,
            }
        )
    return out


def _normalize_queries(raw_queries: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, item in enumerate(raw_queries or []):
        row = item if isinstance(item, dict) else {}
        question = str(row.get("question") or "").strip()
        if not question:
            continue
        expected_raw = row.get("expected_chunk_ids")
        expected = []
        if isinstance(expected_raw, list):
            seen: set[str] = set()
            for value in expected_raw:
                chunk_id = str(value or "").strip()
                if not chunk_id or chunk_id in seen:
                    continue
                seen.add(chunk_id)
                expected.append(chunk_id)
        if not expected:
            continue
        out.append(
            {
                "id": str(row.get("id") or f"q-{index + 1}").strip() or f"q-{index + 1}",
                "question": question,
                "expected_chunk_ids": expected,
            }
        )
    return out


def build_fixture(
    *,
    documents: list[dict[str, Any]] | None,
    queries: list[dict[str, Any]] | None,
    top_k: int = 1,
    retrieval_mode: str = "keyword",
) -> dict[str, Any]:
    return {
        "schema": _SCHEMA,
        "defaults": {
            "top_k": max(1, int(top_k or 1)),
            "retrieval_mode": str(retrieval_mode or "keyword").strip().lower() or "keyword",
        },
        "documents": _normalize_documents(documents),
        "queries": _normalize_queries(queries),
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic sample retrieval fixture from parser-like chunks and query specs.")
    parser.add_argument("--chunks-json", required=True, help="Path to parser chunk JSON array.")
    parser.add_argument("--queries-json", required=True, help="Path to query-spec JSON array.")
    parser.add_argument("--out", required=True, help="Path to output fixture JSON.")
    parser.add_argument("--top-k", type=int, default=1, help="Fixture default top_k.")
    parser.add_argument("--retrieval-mode", default="keyword", help="Fixture default retrieval mode.")
    args = parser.parse_args(argv)

    chunks_path = Path(str(args.chunks_json)).resolve()
    queries_path = Path(str(args.queries_json)).resolve()
    out_path = Path(str(args.out)).resolve()

    documents = _read_json(chunks_path)
    queries = _read_json(queries_path)
    fixture = build_fixture(
        documents=documents if isinstance(documents, list) else [],
        queries=queries if isinstance(queries, list) else [],
        top_k=int(args.top_k or 1),
        retrieval_mode=str(args.retrieval_mode or "keyword"),
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
