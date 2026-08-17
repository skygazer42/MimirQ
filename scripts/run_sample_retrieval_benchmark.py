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


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


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


def _validate_fixture(payload: dict[str, Any]) -> None:
    schema = str(payload.get("schema") or "").strip()
    if schema != _FIXTURE_SCHEMA:
        raise ValueError(f"Unsupported fixture schema: expected {_FIXTURE_SCHEMA}, got {schema or '<empty>'}")

    docs = payload.get("documents")
    queries = payload.get("queries")
    if not isinstance(docs, list) or not docs:
        raise ValueError("Fixture must include a non-empty documents list")
    if not isinstance(queries, list) or not queries:
        raise ValueError("Fixture must include a non-empty queries list")

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

    for i, row in enumerate(queries):
        if not isinstance(row, dict):
            raise ValueError(f"queries[{i}] must be an object")
        q = str(row.get("question") or "").strip()
        expected = _normalize_expected_ids(row.get("expected_chunk_ids"))
        if not q:
            raise ValueError(f"queries[{i}].question is required")
        if not expected:
            raise ValueError(f"queries[{i}].expected_chunk_ids must be non-empty")
        missing = [cid for cid in expected if cid not in known_chunk_ids]
        if missing:
            raise ValueError(f"queries[{i}] references unknown chunk_id(s): {missing}")


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
    return float(score)


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
    return float(dcg / idcg)


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

    ranked: list[str] = []
    ranked_docs: list[str] = []
    ranked_families: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("chunk_id") or "").strip()
        if cid:
            ranked.append(cid)
            doc_id = str((chunk_doc_ids or {}).get(cid) or "").strip()
            if doc_id:
                ranked_docs.append(doc_id)
            fam = str((chunk_family_keys or {}).get(cid) or cid).strip() or cid
            ranked_families.append(fam)

    expected_set = set(expected_chunk_ids)
    hit = 1.0 if any(cid in expected_set for cid in ranked[:top_k]) else 0.0

    rr = 0.0
    for idx, cid in enumerate(ranked, start=1):
        if cid in expected_set:
            rr = 1.0 / float(idx)
            break

    ndcg = _ndcg_at_k_binary(ranked, expected_set, top_k)

    expected_families = _normalize_expected_ids(list(expected_family_keys or []))
    expected_family_set = set(expected_families)
    ranked_families_k = ranked_families[:top_k]
    ranked_family_unique: list[str] = []
    seen_fams: set[str] = set()
    for fid in ranked_families_k:
        if fid in seen_fams:
            continue
        seen_fams.add(fid)
        ranked_family_unique.append(fid)
    family_hit = 1.0 if any(fid in expected_family_set for fid in ranked_family_unique) else 0.0

    family_rr = 0.0
    for idx, fid in enumerate(ranked_family_unique, start=1):
        if fid in expected_family_set:
            family_rr = 1.0 / float(idx)
            break

    family_ndcg = _ndcg_at_k_binary(ranked_family_unique, expected_family_set, top_k)

    distinct_docs = len(set(ranked_docs))
    distinct_fams = len(set(ranked_family_unique))
    top_doc_share = 0.0
    if ranked_docs:
        top_doc_share = max(ranked_docs.count(d) for d in set(ranked_docs)) / float(len(ranked_docs))
    top_family_share = 0.0
    if ranked_families_k:
        top_family_share = max(ranked_families_k.count(f) for f in set(ranked_families_k)) / float(
            len(ranked_families_k)
        )
    return {
        "question": question,
        "expected_chunk_ids": expected_chunk_ids,
        "ranked_chunk_ids": ranked[:top_k],
        "expected_family_keys": expected_families,
        "ranked_family_keys": ranked_family_unique,
        "hit_at_k": round(float(hit), 6),
        "reciprocal_rank": round(float(rr), 6),
        "ndcg_at_k": round(float(ndcg), 6),
        "family_hit_at_k": round(float(family_hit), 6),
        "family_reciprocal_rank": round(float(family_rr), 6),
        "family_ndcg_at_k": round(float(family_ndcg), 6),
        "distinct_documents": int(distinct_docs),
        "distinct_families": int(distinct_fams),
        "top_doc_share": round(float(top_doc_share), 6),
        "top_family_share": round(float(top_family_share), 6),
        "latency_ms": round(float(elapsed_ms), 3),
    }


def run_benchmark(
    *,
    fixture_path: Path,
    output_path: Path,
    top_k: int | None,
    retrieval_mode: str | None,
    sparse_retrieval_enabled: bool = False,
    sparse_retrieval_provider: str = "deterministic",
    colbert_retrieval_enabled: bool | None = None,
    colbert_retrieval_provider: str | None = None,
) -> dict[str, Any]:
    from app.core.config import settings as app_settings
    from app.rag.core.hashing import stable_hash
    from app.rag.retrieval.sparse import normalize_sparse_provider_name
    from app.rag.retriever import HybridRetriever

    fixture_raw = fixture_path.read_text(encoding="utf-8")
    fixture_obj = json.loads(fixture_raw)
    if not isinstance(fixture_obj, dict):
        raise ValueError("Fixture root must be a JSON object")
    _validate_fixture(fixture_obj)

    defaults = fixture_obj.get("defaults") if isinstance(fixture_obj.get("defaults"), dict) else {}
    default_top_k = _safe_int((defaults or {}).get("top_k"), 5)
    default_mode = str((defaults or {}).get("retrieval_mode") or "keyword").strip().lower() or "keyword"
    effective_top_k = max(1, int(top_k if top_k is not None else default_top_k))
    effective_mode = str(retrieval_mode or default_mode).strip().lower() or "keyword"
    default_colbert_enabled = bool((defaults or {}).get("colbert_retrieval_enabled"))
    default_colbert_provider = (
        str((defaults or {}).get("colbert_retrieval_provider") or "deterministic").strip().lower()
    )
    effective_colbert_enabled = (
        bool(colbert_retrieval_enabled) if colbert_retrieval_enabled is not None else default_colbert_enabled
    )
    effective_colbert_provider = (
        str(colbert_retrieval_provider or default_colbert_provider or "deterministic").strip().lower()
    )
    if effective_colbert_provider not in {"deterministic", "hf"}:
        effective_colbert_provider = "deterministic"

    settings_keys = (
        "VECTOR_BACKEND",
        "BM25_INDEX_ENABLED",
        "LEXICAL_DB_ENABLED",
        "SPARSE_RETRIEVAL_ENABLED",
        "SPARSE_RETRIEVAL_PROVIDER",
        "COLBERT_RETRIEVAL_ENABLED",
        "COLBERT_RETRIEVAL_PROVIDER",
        "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED",
        "ENABLE_QUERY_REWRITE",
        "ENABLE_MULTI_QUERY",
        "ENABLE_HYDE",
        "ENABLE_QUERY_DECOMPOSITION",
        "RETRIEVAL_QUERY_PARALLELISM",
    )
    previous: dict[str, Any] = {k: getattr(app_settings, k) for k in settings_keys}
    sparse_provider = normalize_sparse_provider_name(str(sparse_retrieval_provider or "deterministic"))
    if sparse_provider not in {"deterministic", "splade"}:
        sparse_provider = "deterministic"
    try:
        # Deterministic local profile for OSS/dev reproducibility.
        app_settings.VECTOR_BACKEND = "memory"
        app_settings.BM25_INDEX_ENABLED = True
        app_settings.LEXICAL_DB_ENABLED = False
        app_settings.SPARSE_RETRIEVAL_ENABLED = bool(sparse_retrieval_enabled)
        app_settings.SPARSE_RETRIEVAL_PROVIDER = sparse_provider
        app_settings.COLBERT_RETRIEVAL_ENABLED = bool(effective_colbert_enabled)
        app_settings.COLBERT_RETRIEVAL_PROVIDER = effective_colbert_provider
        app_settings.COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED = False
        app_settings.ENABLE_QUERY_REWRITE = False
        app_settings.ENABLE_MULTI_QUERY = False
        app_settings.ENABLE_HYDE = False
        app_settings.ENABLE_QUERY_DECOMPOSITION = False
        app_settings.RETRIEVAL_QUERY_PARALLELISM = 1

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
            sparse_enabled=bool(sparse_retrieval_enabled),
            sparse_provider=sparse_provider,
        )
        retriever.upsert_bm25_documents(docs, tenant_id=tenant_id)

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
    p95_latency = float(lat_sorted[p95_idx]) if lat_sorted else 0.0

    llm_mock_env = os.getenv("LLM_MOCK_ENABLED")
    llm_mock_norm = str(llm_mock_env or "").strip().lower()
    llm_mock = llm_mock_norm in {"1", "true", "yes", "on"}

    report: dict[str, Any] = {
        "schema": _REPORT_SCHEMA,
        "fixture_schema": str(fixture_obj.get("schema") or ""),
        "fixture_path": str(fixture_path),
        "fixture_hash": stable_hash(fixture_raw, length=24),
        "llm_mock": bool(llm_mock),
        "llm_mock_env": llm_mock_env,
        "retrieval_mode": effective_mode,
        "top_k": int(effective_top_k),
        "runtime": {
            "sparse_retrieval_enabled": bool(sparse_retrieval_enabled),
            "sparse_retrieval_provider": sparse_provider,
            "colbert_retrieval_enabled": bool(effective_colbert_enabled),
            "colbert_retrieval_provider": effective_colbert_provider,
        },
        "summary": {
            "cases_total": int(len(cases)),
            "hit_at_k": round(float(sum(hits) / len(hits)), 6) if hits else 0.0,
            "mrr": round(float(sum(rrs) / len(rrs)), 6) if rrs else 0.0,
            "ndcg_at_k": round(float(sum(ndcgs) / len(ndcgs)), 6) if ndcgs else 0.0,
            "family_hit_at_k": round(float(sum(fam_hits) / len(fam_hits)), 6) if fam_hits else 0.0,
            "family_mrr": round(float(sum(fam_rrs) / len(fam_rrs)), 6) if fam_rrs else 0.0,
            "family_ndcg_at_k": round(float(sum(fam_ndcgs) / len(fam_ndcgs)), 6) if fam_ndcgs else 0.0,
            "distinct_families_mean": round(float(statistics.mean(fam_counts)), 3) if fam_counts else 0.0,
            "avg_latency_ms": round(float(statistics.mean(latencies)), 3) if latencies else 0.0,
            "p95_latency_ms": round(float(p95_latency), 3),
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
    parser.add_argument(
        "--enable-sparse-retrieval",
        action="store_true",
        help="Enable sparse retrieval channel for this benchmark run.",
    )
    parser.add_argument(
        "--sparse-retrieval-provider",
        default="deterministic",
        help="Sparse retrieval provider (deterministic|splade; unknown values fallback to deterministic).",
    )
    parser.add_argument(
        "--enable-colbert-retrieval",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable ColBERT ANN fallback retrieval for this benchmark run.",
    )
    parser.add_argument(
        "--colbert-retrieval-provider",
        default=None,
        help="ColBERT retrieval provider (deterministic|hf; unknown values fallback to deterministic).",
    )
    args = parser.parse_args(argv)

    fixture_path = Path(str(args.fixture)).expanduser().resolve()
    out_path = Path(str(args.out)).expanduser().resolve()

    report = run_benchmark(
        fixture_path=fixture_path,
        output_path=out_path,
        top_k=args.top_k,
        retrieval_mode=args.retrieval_mode,
        sparse_retrieval_enabled=bool(args.enable_sparse_retrieval),
        sparse_retrieval_provider=str(args.sparse_retrieval_provider or "deterministic"),
        colbert_retrieval_enabled=args.enable_colbert_retrieval,
        colbert_retrieval_provider=args.colbert_retrieval_provider,
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
