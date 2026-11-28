import argparse
import json
import math
import os
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

# Ensure repo root is importable when invoked as:
#   python scripts/run_sample_retrieval_benchmark.py
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_FIXTURE_SCHEMA = "mimirq.sample_retrieval_fixture.v1"
_REPORT_SCHEMA = "mimirq.sample_retrieval_benchmark.v1"


def _repo_root() -> Path:
    return _REPO_ROOT


def _uuid_from_seed(seed: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"mimirq/sample-bench/{seed}")


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _normalize_expected_ids(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text:
            out.append(text)
    # Keep deterministic order while deduplicating.
    return list(dict.fromkeys(out))


def _family_key(meta: dict[str, Any], *, chunk_id: str) -> str:
    """
    Best-effort hierarchy family key extractor.

    This benchmark is intended to be dependency-free and deterministic, so we
    treat a missing family key as "self family" (chunk_id).
    """
    for key in ("family_collapse_key", "hierarchy_family_key", "parent_id", "parent_node_id"):
        raw = meta.get(key) if isinstance(meta, dict) else None
        s = str(raw or "").strip()
        if s:
            return s
    return str(chunk_id or "").strip() or "unknown"


def _require_fixture_rows(payload: dict[str, Any], *, key: str, message: str) -> list[Any]:
    rows = payload.get(key)
    if not isinstance(rows, list) or not rows:
        raise ValueError(message)
    return rows


def _validate_fixture_documents(docs: list[Any]) -> set[str]:
    known_chunk_ids: set[str] = set()
    for i, row in enumerate(docs):
        if not isinstance(row, dict):
            raise ValueError(f"documents[{i}] must be an object")
        cid = str(row.get("chunk_id") or "").strip()
        text = str(row.get("text") or "").strip()
        if not cid:
            raise ValueError(f"documents[{i}].chunk_id is required")
        if not text:
            raise ValueError(f"documents[{i}].text is required")
        if cid in known_chunk_ids:
            raise ValueError(f"Duplicate chunk_id in fixture: {cid}")
        known_chunk_ids.add(cid)
    return known_chunk_ids


def _validate_fixture_queries(queries: list[Any], *, known_chunk_ids: set[str]) -> None:
    for i, row in enumerate(queries):
        if not isinstance(row, dict):
            raise ValueError(f"queries[{i}] must be an object")
        question = str(row.get("question") or "").strip()
        expected = _normalize_expected_ids(row.get("expected_chunk_ids"))
        if not question:
            raise ValueError(f"queries[{i}].question is required")
        if not expected:
            raise ValueError(f"queries[{i}].expected_chunk_ids must be non-empty")
        missing = [cid for cid in expected if cid not in known_chunk_ids]
        if missing:
            raise ValueError(f"queries[{i}] references unknown chunk_id(s): {missing}")


def _validate_fixture(payload: dict[str, Any]) -> None:
    schema = str(payload.get("schema") or "").strip()
    if schema != _FIXTURE_SCHEMA:
        raise ValueError(f"Unsupported fixture schema: expected {_FIXTURE_SCHEMA}, got {schema or '<empty>'}")

    docs = _require_fixture_rows(payload, key="documents", message="Fixture must include a non-empty documents list")
    queries = _require_fixture_rows(payload, key="queries", message="Fixture must include a non-empty queries list")
    _validate_fixture_queries(queries, known_chunk_ids=_validate_fixture_documents(docs))


def _build_documents(
    *,
    fixture: dict[str, Any],
    tenant_id: uuid.UUID,
    dataset_id: uuid.UUID | None,
) -> list[Document]:
    out: list[Document] = []
    docs = fixture.get("documents") or []
    for i, row in enumerate(docs):
        item = row if isinstance(row, dict) else {}
        chunk_id = str(item.get("chunk_id") or f"chunk-{i + 1}").strip()
        document_id = str(item.get("document_id") or f"doc-{i + 1}").strip()
        text = str(item.get("text") or "")

        meta_raw = item.get("metadata")
        meta = dict(meta_raw) if isinstance(meta_raw, dict) else {}
        pipeline_hash = str(meta.get("pipeline_hash") or "sample-v1").strip() or "sample-v1"
        meta.setdefault("pipeline_hash", pipeline_hash)
        meta.setdefault("doc_pipeline_key", f"{document_id}:{pipeline_hash}")
        meta.setdefault("source", str(meta.get("source") or f"sample-{document_id}.md"))
        meta.setdefault("chunk_index", _safe_int(meta.get("chunk_index"), i))
        meta["tenant_id"] = str(tenant_id)
        if dataset_id is not None:
            meta["dataset_id"] = str(dataset_id)
        meta["document_id"] = document_id
        meta["chunk_id"] = chunk_id

        out.append(Document(page_content=text, id=chunk_id, metadata=meta))
    return out


def _dcg_at_k_binary(ranked_chunk_ids: list[str], expected_ids: set[str], k: int) -> float:
    # Explicit implementation to keep script dependency-free.
    vals: list[float] = []
    for cid in ranked_chunk_ids[:k]:
        vals.append(1.0 if cid in expected_ids else 0.0)
    score = 0.0
    for i, rel in enumerate(vals):
        rank = i + 1
        if rank == 1:
            score += rel
        else:
            score += rel / math.log2(float(rank + 1))
    return score


def _ndcg_at_k_binary(ranked_chunk_ids: list[str], expected_ids: set[str], k: int) -> float:
    if not expected_ids:
        return 0.0
    dcg = _dcg_at_k_binary(ranked_chunk_ids, expected_ids, k)
    ideal_hits = min(int(k), len(expected_ids))
    ideal_ranked = [f"ideal-{i}" for i in range(ideal_hits)]
    ideal_set = set(ideal_ranked)
    idcg = _dcg_at_k_binary(ideal_ranked, ideal_set, k)
    if idcg <= 0.0:
        return 0.0
    return dcg / idcg


def _ranked_retrieval_lists(
    *,
    rows: list[Any],
    chunk_doc_ids: dict[str, str] | None,
    chunk_family_keys: dict[str, str] | None,
) -> tuple[list[str], list[str], list[str]]:
    ranked: list[str] = []
    ranked_docs: list[str] = []
    ranked_families: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("chunk_id") or "").strip()
        if not cid:
            continue
        ranked.append(cid)
        doc_id = str((chunk_doc_ids or {}).get(cid) or "").strip()
        if doc_id:
            ranked_docs.append(doc_id)
        family = str((chunk_family_keys or {}).get(cid) or cid).strip() or cid
        ranked_families.append(family)
    return ranked, ranked_docs, ranked_families


def _first_hit_reciprocal_rank(ranked_ids: list[str], expected_ids: set[str]) -> float:
    for idx, cid in enumerate(ranked_ids, start=1):
        if cid in expected_ids:
            return 1.0 / float(idx)
    return 0.0


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _top_share(values: list[str]) -> float:
    if not values:
        return 0.0
    return max(values.count(value) for value in set(values)) / float(len(values))


def _evaluate_query(
    *,
    retriever: Any,
    tenant_id: uuid.UUID,
    question: str,
    expected_chunk_ids: list[str],
    expected_family_keys: list[str] | None,
    top_k: int,
    retrieval_mode: str,
    chunk_doc_ids: dict[str, str] | None = None,
    chunk_family_keys: dict[str, str] | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    rows = retriever._hybrid_search(  # noqa: SLF001 - benchmark harness intentionally uses retriever internals.
        query=question,
        top_k=top_k,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=tenant_id,
        retrieval_mode=retrieval_mode,
        metadata_filter=None,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    ranked, ranked_docs, ranked_families = _ranked_retrieval_lists(
        rows=rows,
        chunk_doc_ids=chunk_doc_ids,
        chunk_family_keys=chunk_family_keys,
    )

    expected_set = set(expected_chunk_ids)
    hit = 1.0 if any(cid in expected_set for cid in ranked[:top_k]) else 0.0
    rr = _first_hit_reciprocal_rank(ranked, expected_set)
    ndcg = _ndcg_at_k_binary(ranked, expected_set, top_k)

    expected_families = _normalize_expected_ids(list(expected_family_keys or []))
    expected_family_set = set(expected_families)
    ranked_families_k = ranked_families[:top_k]
    ranked_family_unique = _dedupe_preserve_order(ranked_families_k)
    family_hit = 1.0 if any(fid in expected_family_set for fid in ranked_family_unique) else 0.0
    family_rr = _first_hit_reciprocal_rank(ranked_family_unique, expected_family_set)
    family_ndcg = _ndcg_at_k_binary(ranked_family_unique, expected_family_set, top_k)

    distinct_docs = len(set(ranked_docs))
    distinct_fams = len(set(ranked_family_unique))
    top_doc_share = _top_share(ranked_docs)
    top_family_share = _top_share(ranked_families_k)
    return {
        "question": question,
        "expected_chunk_ids": expected_chunk_ids,
        "ranked_chunk_ids": ranked[:top_k],
        "expected_family_keys": expected_families,
        "ranked_family_keys": ranked_family_unique,
        "hit_at_k": round(hit, 6),
        "reciprocal_rank": round(rr, 6),
        "ndcg_at_k": round(ndcg, 6),
        "family_hit_at_k": round(family_hit, 6),
        "family_reciprocal_rank": round(family_rr, 6),
        "family_ndcg_at_k": round(family_ndcg, 6),
        "distinct_documents": distinct_docs,
        "distinct_families": distinct_fams,
        "top_doc_share": round(top_doc_share, 6),
        "top_family_share": round(top_family_share, 6),
        "latency_ms": round(elapsed_ms, 3),
    }


def run_benchmark(
    *,
    fixture_path: Path,
    output_path: Path,
    top_k: int | None,
    retrieval_mode: str | None,
) -> dict[str, Any]:
    if fixture_path.resolve() == output_path.resolve():
        raise ValueError("fixture and benchmark report paths must be distinct")

    from app.infrastructure.config import settings as app_settings
    from app.infrastructure.hashing import stable_hash
    from app.rag.retrieval.corpus import get_corpus_index
    from app.rag.retrieval.recall.retriever import HybridRetriever

    fixture_raw = fixture_path.read_text(encoding="utf-8")
    fixture_obj = json.loads(fixture_raw)
    if not isinstance(fixture_obj, dict):
        raise ValueError("Fixture root must be a JSON object")
    _validate_fixture(fixture_obj)

    defaults = fixture_obj.get("defaults") if isinstance(fixture_obj.get("defaults"), dict) else {}
    default_top_k = _safe_int(defaults.get("top_k"), 5)
    default_mode = str(defaults.get("retrieval_mode") or "keyword").strip().lower() or "keyword"
    effective_top_k = max(1, int(top_k if top_k is not None else default_top_k))
    effective_mode = str(retrieval_mode or default_mode).strip().lower() or "keyword"
    # Deterministic local profile for OSS/dev reproducibility.
    overrides = {
        "VECTOR_BACKEND": "memory",
        "BM25_INDEX_ENABLED": True,
        "LEXICAL_DB_ENABLED": False,
        "ENABLE_QUERY_REWRITE": False,
        "ENABLE_MULTI_QUERY": False,
        "ENABLE_HYDE": False,
        "ENABLE_QUERY_DECOMPOSITION": False,
        "RETRIEVAL_QUERY_PARALLELISM": 1,
    }
    previous = {key: getattr(app_settings, key) for key in overrides}
    try:
        for key, value in overrides.items():
            setattr(app_settings, key, value)

        tenant_id = _uuid_from_seed("tenant")
        # This gate measures fixture ranking, not database-backed dataset runtime resolution.
        docs = _build_documents(fixture=fixture_obj, tenant_id=tenant_id, dataset_id=None)

        chunk_doc_ids: dict[str, str] = {}
        chunk_family_keys: dict[str, str] = {}
        for d in docs:
            meta = getattr(d, "metadata", None) or {}
            cid = str(meta.get("chunk_id") or getattr(d, "id", None) or "").strip()
            if not cid:
                continue
            doc_id = str(meta.get("document_id") or "").strip()
            if doc_id:
                chunk_doc_ids[cid] = doc_id
            chunk_family_keys[cid] = _family_key(meta, chunk_id=cid)

        retriever = HybridRetriever(
            tenant_id=tenant_id,
            enable_reranker=False,
        )
        get_corpus_index().upsert(None, tenant_id=tenant_id, documents=docs)

        cases: list[dict[str, Any]] = []
        q_rows = fixture_obj.get("queries") or []
        for i, row in enumerate(q_rows):
            item = row if isinstance(row, dict) else {}
            qid = str(item.get("id") or f"q-{i + 1}").strip()
            question = str(item.get("question") or "").strip()
            expected = _normalize_expected_ids(item.get("expected_chunk_ids"))
            expected_families = _normalize_expected_ids([chunk_family_keys.get(cid) or cid for cid in expected])
            result = _evaluate_query(
                retriever=retriever,
                tenant_id=tenant_id,
                question=question,
                expected_chunk_ids=expected,
                expected_family_keys=expected_families,
                top_k=effective_top_k,
                retrieval_mode=effective_mode,
                chunk_doc_ids=chunk_doc_ids,
                chunk_family_keys=chunk_family_keys,
            )
            result["id"] = qid
            cases.append(result)
    finally:
        for key, value in previous.items():
            setattr(app_settings, key, value)

    hits = [float(x.get("hit_at_k") or 0.0) for x in cases]
    rrs = [float(x.get("reciprocal_rank") or 0.0) for x in cases]
    ndcgs = [float(x.get("ndcg_at_k") or 0.0) for x in cases]
    fam_hits = [float(x.get("family_hit_at_k") or 0.0) for x in cases]
    fam_rrs = [float(x.get("family_reciprocal_rank") or 0.0) for x in cases]
    fam_ndcgs = [float(x.get("family_ndcg_at_k") or 0.0) for x in cases]
    fam_counts = [int(x.get("distinct_families") or 0) for x in cases]
    latencies = [float(x.get("latency_ms") or 0.0) for x in cases]

    lat_sorted = sorted(latencies)
    p95_idx = min(len(lat_sorted) - 1, max(0, int(round(0.95 * (len(lat_sorted) - 1)))))
    p95_latency = lat_sorted[p95_idx] if lat_sorted else 0.0

    llm_mock_env = os.getenv("LLM_MOCK_ENABLED")
    llm_mock_norm = str(llm_mock_env or "").strip().lower()
    llm_mock = llm_mock_norm in {"1", "true", "yes", "on"}

    report: dict[str, Any] = {
        "schema": _REPORT_SCHEMA,
        "fixture_schema": str(fixture_obj.get("schema") or ""),
        "fixture_path": str(fixture_path),
        "fixture_hash": stable_hash(fixture_raw, length=24),
        "llm_mock": llm_mock,
        "llm_mock_env": llm_mock_env,
        "retrieval_mode": effective_mode,
        "top_k": effective_top_k,
        "summary": {
            "cases_total": len(cases),
            "hit_at_k": round(sum(hits) / len(hits), 6) if hits else 0.0,
            "mrr": round(sum(rrs) / len(rrs), 6) if rrs else 0.0,
            "ndcg_at_k": round(sum(ndcgs) / len(ndcgs), 6) if ndcgs else 0.0,
            "family_hit_at_k": round(sum(fam_hits) / len(fam_hits), 6) if fam_hits else 0.0,
            "family_mrr": round(sum(fam_rrs) / len(fam_rrs), 6) if fam_rrs else 0.0,
            "family_ndcg_at_k": round(sum(fam_ndcgs) / len(fam_ndcgs), 6) if fam_ndcgs else 0.0,
            "distinct_families_mean": round(float(statistics.mean(fam_counts)), 3) if fam_counts else 0.0,
            "avg_latency_ms": round(float(statistics.mean(latencies)), 3) if latencies else 0.0,
            "p95_latency_ms": round(p95_latency, 3),
        },
        "cases": cases,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a deterministic retrieval benchmark on the built-in sample fixture. "
            "No proprietary API access is required."
        )
    )
    parser.add_argument(
        "--fixture",
        default=str(_repo_root() / "data" / "sample" / "retrieval_fixture_v1.json"),
        help="Path to sample fixture JSON (default: data/sample/retrieval_fixture_v1.json)",
    )
    parser.add_argument(
        "--out",
        default=str(_repo_root() / "runs" / "sample_bench.json"),
        help="Output benchmark report JSON path (default: runs/sample_bench.json)",
    )
    parser.add_argument("--top-k", type=int, default=None, help="Override top_k from fixture defaults")
    parser.add_argument(
        "--retrieval-mode",
        default=None,
        choices=["keyword", "vector", "hybrid", "mmr"],
        help="Override retrieval_mode from fixture defaults",
    )
    args = parser.parse_args(argv)

    fixture_path = Path(str(args.fixture)).expanduser().resolve()
    out_path = Path(str(args.out)).expanduser().resolve()

    report = run_benchmark(
        fixture_path=fixture_path,
        output_path=out_path,
        top_k=args.top_k,
        retrieval_mode=args.retrieval_mode,
    )
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    print(
        "[sample-bench] "
        f"cases={summary.get('cases_total', 0)} "
        f"hit@k={summary.get('hit_at_k', 0.0)} "
        f"mrr={summary.get('mrr', 0.0)} "
        f"ndcg@k={summary.get('ndcg_at_k', 0.0)} "
        f"out={out_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
