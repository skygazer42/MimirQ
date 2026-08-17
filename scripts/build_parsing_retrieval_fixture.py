import argparse
import json
from pathlib import Path
from typing import Any

_SCHEMA = "mimirq.sample_retrieval_fixture.v1"


def _normalize_documents(documents: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(documents or []):
        row = raw if isinstance(raw, dict) else {}
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
        document_id = str(
            row.get("document_id") or meta.get("document_id") or meta.get("source") or f"doc-{index + 1}"
        ).strip()
        text = str(row.get("text") or row.get("element_text") or row.get("page_content") or "").strip()
        if not chunk_id or not document_id or not text:
            continue
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


def _normalize_queries(
    *, queries: list[dict[str, Any]] | None, documents: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    chunk_ids = [str(item.get("chunk_id") or "").strip() for item in documents]
    for index, raw in enumerate(queries or []):
        row = raw if isinstance(raw, dict) else {}
        question = str(row.get("question") or "").strip()
        if not question:
            continue

        expected_ids: list[str] = []
        raw_ids = row.get("expected_chunk_ids")
        if isinstance(raw_ids, list):
            for item in raw_ids:
                chunk_id = str(item or "").strip()
                if chunk_id and chunk_id not in expected_ids:
                    expected_ids.append(chunk_id)

        raw_indexes = row.get("expected_chunk_indexes")
        if not expected_ids and isinstance(raw_indexes, list):
            for item in raw_indexes:
                try:
                    idx_i = int(item)
                except Exception:
                    continue
                if 0 <= idx_i < len(chunk_ids):
                    chunk_id = chunk_ids[idx_i]
                    if chunk_id and chunk_id not in expected_ids:
                        expected_ids.append(chunk_id)

        if not expected_ids:
            continue

        out.append(
            {
                "id": str(row.get("id") or f"q-{index + 1}").strip() or f"q-{index + 1}",
                "question": question,
                "expected_chunk_ids": expected_ids,
            }
        )
    return out


def build_retrieval_fixture(
    *,
    documents: list[dict[str, Any]] | None,
    queries: list[dict[str, Any]] | None,
    top_k: int = 1,
    retrieval_mode: str = "keyword",
) -> dict[str, Any]:
    normalized_documents = _normalize_documents(documents)
    normalized_queries = _normalize_queries(queries=queries, documents=normalized_documents)
    return {
        "schema": _SCHEMA,
        "defaults": {
            "top_k": max(1, int(top_k or 1)),
            "retrieval_mode": str(retrieval_mode or "keyword").strip().lower() or "keyword",
        },
        "documents": normalized_documents,
        "queries": normalized_queries,
    }


def build_fixture(
    *,
    documents: list[dict[str, Any]] | None,
    queries: list[dict[str, Any]] | None,
    top_k: int = 1,
    retrieval_mode: str = "keyword",
) -> dict[str, Any]:
    return build_retrieval_fixture(
        documents=documents,
        queries=queries,
        top_k=top_k,
        retrieval_mode=retrieval_mode,
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _coerce_documents_payload(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("documents", "segments"):
            raw = value.get(key)
            if isinstance(raw, list):
                return [item for item in raw if isinstance(item, dict)]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a deterministic retrieval fixture from parser-like document rows and query specs."
    )
    parser.add_argument(
        "--documents-json",
        "--chunks-json",
        dest="documents_json",
        required=True,
        help="Path to document rows JSON.",
    )
    parser.add_argument("--queries-json", required=True, help="Path to query specs JSON.")
    parser.add_argument("--out", required=True, help="Output fixture JSON path.")
    parser.add_argument("--top-k", type=int, default=1, help="Fixture default top_k.")
    parser.add_argument("--retrieval-mode", default="keyword", help="Fixture default retrieval mode.")
    args = parser.parse_args(argv)

    documents = _coerce_documents_payload(_read_json(Path(str(args.documents_json)).resolve()))
    queries = _read_json(Path(str(args.queries_json)).resolve())
    fixture = build_retrieval_fixture(
        documents=documents,
        queries=queries if isinstance(queries, list) else [],
        top_k=int(args.top_k or 1),
        retrieval_mode=str(args.retrieval_mode or "keyword"),
    )
    out_path = Path(str(args.out)).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
