#!/usr/bin/env python3
"""
Offline retrieval-only evaluation: baseline vs local LTR rerank.

Why:
- Avoid depending on evaluation endpoints or backend-side LTR configuration.
- Use Evidence API for candidate generation, then apply the LTR model locally.

Metrics (binary relevance, chunk_id match):
- Hit@K
- MRR@K
- Recall@K
- NDCG@K
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import httpx

from app.rag.reranker.ltr import LTRFeatureSpec, LTRReranker
from app.rag.reranker.types import RerankCandidate


def _load_json(path: Path) -> Any:
    # PowerShell commonly writes UTF-8 JSON with BOM; `utf-8-sig` handles both BOM/no-BOM.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _headers(args: argparse.Namespace) -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if args.tenant_id:
        h["X-Tenant-ID"] = str(args.tenant_id)
    if args.user_id:
        h["X-User-ID"] = str(args.user_id)
    if args.bearer:
        h["Authorization"] = f"Bearer {args.bearer}"
    return h


def coerce_case_bundle(obj: Any) -> tuple[str, list[dict[str, Any]]]:
    """
    Normalize case bundle payloads into: (dataset_id, items[]).

    Supported shapes:
    - Export bundle v1: {"schema":"mimirq.regression_cases.v1","dataset_id":"...","items":[...]}
    - Minimal bundle: {"dataset_id":"...","items":[...]}
    - Legacy: [{"dataset_id":"...","question":"...","reference_sources":[...], ...}, ...]
    """
    if isinstance(obj, dict) and isinstance(obj.get("items"), list):
        ds = str(obj.get("dataset_id") or "").strip()
        if ds:
            items = [x for x in obj.get("items") if isinstance(x, dict)]
            cleaned = [{k: v for k, v in it.items() if k != "dataset_id"} for it in items]
            return ds, cleaned
        return coerce_case_bundle(list(obj.get("items") or []))

    if isinstance(obj, list):
        items = [x for x in obj if isinstance(x, dict)]
        dsids: list[str] = []
        for it in items:
            ds = str(it.get("dataset_id") or "").strip()
            if ds and ds not in dsids:
                dsids.append(ds)
        if not dsids:
            raise ValueError("dataset_id is required in cases bundle")
        if len(dsids) > 1:
            raise ValueError("mixed dataset_id in cases bundle")
        dsid = dsids[0]
        cleaned = [{k: v for k, v in it.items() if k != "dataset_id"} for it in items]
        return dsid, cleaned

    raise ValueError("cases file must be a JSON array, or an object with { dataset_id, items: [...] }")


def _extract_reference_chunk_ids(item: dict[str, Any]) -> set[str]:
    refs = item.get("reference_sources") or []
    if not isinstance(refs, list):
        return set()
    out: set[str] = set()
    for src in refs:
        if not isinstance(src, dict):
            continue
        cid = str(src.get("chunk_id") or "").strip()
        if cid:
            out.add(cid)
    return out


def _as_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _hit_mrr_recall_ndcg_at_k(*, ranked_ids: list[str], relevant: set[str], k: int) -> dict[str, float]:
    kk = max(1, int(k or 0))
    top = ranked_ids[:kk]
    if not relevant:
        return {"hit": 0.0, "mrr": 0.0, "recall": 0.0, "ndcg": 0.0}

    hit = 1.0 if any(cid in relevant for cid in top) else 0.0

    rr = 0.0
    for i, cid in enumerate(top, 1):
        if cid in relevant:
            rr = 1.0 / float(i)
            break

    rel_found = sum(1 for cid in top if cid in relevant)
    recall = float(rel_found) / float(len(relevant)) if relevant else 0.0

    # Binary NDCG@K
    def _dcg(ids: list[str]) -> float:
        total = 0.0
        for i, cid in enumerate(ids, 1):
            if cid not in relevant:
                continue
            denom = math.log2(float(i) + 1.0)
            total += 1.0 / denom
        return total

    dcg = _dcg(top)
    ideal = sorted([1] * min(len(relevant), kk) + [0] * max(0, kk - min(len(relevant), kk)), reverse=True)
    idcg = 0.0
    for i, rel in enumerate(ideal, 1):
        if not rel:
            continue
        idcg += 1.0 / math.log2(float(i) + 1.0)
    ndcg = (dcg / idcg) if idcg > 0.0 else 0.0

    return {"hit": float(hit), "mrr": float(rr), "recall": float(recall), "ndcg": float(ndcg)}


def _build_candidate_from_citation(c: dict[str, Any]) -> RerankCandidate | None:
    cid = str(c.get("chunk_id") or "").strip()
    if not cid:
        return None
    meta = {
        "vector_score": _as_float(c.get("vector_score")),
        "bm25_score": _as_float(c.get("bm25_score")),
        "lexical_score": _as_float(c.get("lexical_score")),
        "sparse_score": _as_float(c.get("sparse_score")),
        # Treat evidence relevance_score as the base retrieval score.
        "score": _as_float(c.get("relevance_score")),
        "retrieval_role": c.get("retrieval_role"),
        # Optional KG features.
        "kg_pagerank": _as_float(c.get("kg_pagerank")),
        "kg_shared_events": _as_float(c.get("kg_shared_events")),
        "kg_path_length": _as_float(c.get("kg_path_length")),
        "kg_edge_conf_low": _as_float(c.get("kg_edge_conf_low")),
        "kg_edge_conf_mid": _as_float(c.get("kg_edge_conf_mid")),
        "kg_edge_conf_high": _as_float(c.get("kg_edge_conf_high")),
        "kg_evidence_anchored": _as_float(c.get("kg_evidence_anchored")),
    }
    return RerankCandidate(
        id=cid,
        text=str(c.get("chunk_content") or ""),
        metadata=meta,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Offline evaluation: baseline vs local LTR rerank (via Evidence API candidates).")
    p.add_argument("--cases", required=True, help="Path to regression cases JSON (bundle v1 or legacy array)")
    p.add_argument("--model", required=True, help="Path to LTR model artifact (xgboost JSON/UBJ)")
    p.add_argument("--feature-spec-version", type=int, default=1, help="LTR feature spec version (default: %(default)s)")

    p.add_argument("--base-url", default="http://localhost:8000/api/v1", help="API base URL (default: %(default)s)")
    p.add_argument("--tenant-id", default="", help="Tenant id (X-Tenant-ID header)")
    p.add_argument("--user-id", default="", help="User id (X-User-ID header, for AUTH_MODE=header)")
    p.add_argument("--bearer", default="", help="Bearer token (Authorization: Bearer ...)")
    p.add_argument("--timeout-sec", type=float, default=30.0, help="HTTP timeout seconds (default: %(default)s)")

    p.add_argument("--top-k", type=int, default=50, help="Evidence API top_k (default: %(default)s)")
    p.add_argument("--score-threshold", type=float, default=0.0, help="Evidence API score_threshold (default: %(default)s)")
    p.add_argument("--retrieval-mode", default="hybrid", help="hybrid|vector|keyword|mmr (default: %(default)s)")
    p.add_argument("--retrieval-profile", default="recall50", help="recall20|recall50|coverage80 (default: %(default)s)")
    p.add_argument("--alpha", type=float, default=0.6, help="Fusion alpha (default: %(default)s)")

    p.add_argument("--k", type=int, default=20, help="Compute metrics at K (default: %(default)s)")
    p.add_argument("--rerank-top-n", type=int, default=30, help="Rerank the top-N candidates locally (default: %(default)s)")
    p.add_argument("--max-cases", type=int, default=0, help="Limit number of cases (default: all)")
    p.add_argument("--out-json", default="", help="Optional: write summary JSON to this path")
    args = p.parse_args(argv)

    cases_path = Path(args.cases)
    if not cases_path.exists():
        print(f"[eval_ltr] ERROR: cases file not found: {cases_path}", file=sys.stderr)
        return 2

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"[eval_ltr] ERROR: model file not found: {model_path}", file=sys.stderr)
        return 2

    try:
        raw_cases = _load_json(cases_path)
        dataset_id, items = coerce_case_bundle(raw_cases)
    except Exception as exc:  # noqa: BLE001
        print(f"[eval_ltr] ERROR: failed to parse cases: {str(exc)[:200]}", file=sys.stderr)
        return 2

    if args.max_cases and int(args.max_cases) > 0:
        items = list(items)[: int(args.max_cases)]

    k = max(1, int(args.k or 0))
    top_k = max(k, int(args.top_k or 0))
    rerank_top_n = max(0, int(args.rerank_top_n or 0))
    rerank_top_n = min(rerank_top_n, top_k) if rerank_top_n else top_k

    spec = LTRFeatureSpec.from_version(int(args.feature_spec_version or 1))
    reranker = LTRReranker(model_path=str(model_path), spec=spec)

    url = str(args.base_url).rstrip("/") + "/rag/retrieve"
    timeout = httpx.Timeout(float(args.timeout_sec or 30.0))

    summary = {
        "cases_total": len(items),
        "cases_used": 0,
        "k": k,
        "top_k": top_k,
        "rerank_top_n": rerank_top_n,
        "model": str(model_path),
        "spec": getattr(spec, "schema", ""),
        "baseline": {"hit": 0.0, "mrr": 0.0, "recall": 0.0, "ndcg": 0.0},
        "ltr": {"hit": 0.0, "mrr": 0.0, "recall": 0.0, "ndcg": 0.0},
    }

    with httpx.Client(timeout=timeout) as client:
        for item in items:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or item.get("query") or "").strip()
            if not question:
                continue
            relevant = _extract_reference_chunk_ids(item)
            if not relevant:
                continue

            body = {
                "query": question,
                "history": [],
                "dataset_id": str(dataset_id),
                "document_ids": [],
                "rag_config": {
                    "retrieval_profile": str(args.retrieval_profile),
                    "retrieval_mode": str(args.retrieval_mode),
                    "top_k": int(top_k),
                    "score_threshold": float(args.score_threshold),
                    "alpha": float(args.alpha),
                    # Always collect pre-rerank candidates from the backend.
                    "enable_reranker": False,
                    "reranker_provider": "none",
                    "reranker_top_n": 0,
                },
            }

            try:
                resp = client.post(url, headers=_headers(args), json=body)
                resp.raise_for_status()
                payload = resp.json() or {}
            except Exception as exc:  # noqa: BLE001
                print(f"[eval_ltr] WARN: retrieve failed: {str(exc)[:200]}", file=sys.stderr)
                continue

            citations = payload.get("citations") or []
            if not isinstance(citations, list) or not citations:
                continue

            ranked_ids = [str(c.get("chunk_id") or "").strip() for c in citations if isinstance(c, dict)]
            ranked_ids = [cid for cid in ranked_ids if cid]
            if not ranked_ids:
                continue

            base_metrics = _hit_mrr_recall_ndcg_at_k(ranked_ids=ranked_ids, relevant=relevant, k=k)

            candidates: list[RerankCandidate] = []
            id_to_citation: dict[str, dict[str, Any]] = {}
            for c in citations[:rerank_top_n]:
                if not isinstance(c, dict):
                    continue
                cand = _build_candidate_from_citation(c)
                if cand is None:
                    continue
                candidates.append(cand)
                id_to_citation[str(cand.id)] = c

            rr = reranker.rerank(query=question, candidates=candidates, top_n=len(candidates))
            ordered_ids = list(rr.ordered_ids or [])
            used = set(ordered_ids)
            reranked = ordered_ids + [cid for cid in ranked_ids if cid not in used]

            ltr_metrics = _hit_mrr_recall_ndcg_at_k(ranked_ids=reranked, relevant=relevant, k=k)

            summary["cases_used"] += 1
            for key in ("hit", "mrr", "recall", "ndcg"):
                summary["baseline"][key] += float(base_metrics.get(key, 0.0) or 0.0)
                summary["ltr"][key] += float(ltr_metrics.get(key, 0.0) or 0.0)

    used = int(summary.get("cases_used") or 0)
    if used > 0:
        for sec in ("baseline", "ltr"):
            for key in ("hit", "mrr", "recall", "ndcg"):
                summary[sec][key] = round(float(summary[sec][key]) / float(used), 4)

    print(
        "[eval_ltr] OK"
        f" cases_total={summary['cases_total']}"
        f" cases_used={summary['cases_used']}"
        f" k={k}"
        f" baseline_hit={summary['baseline']['hit']}"
        f" ltr_hit={summary['ltr']['hit']}"
        f" baseline_mrr={summary['baseline']['mrr']}"
        f" ltr_mrr={summary['ltr']['mrr']}"
        f" baseline_ndcg={summary['baseline']['ndcg']}"
        f" ltr_ndcg={summary['ltr']['ndcg']}"
        f" model={summary['model']}"
        f" spec={summary['spec']}"
    )

    if args.out_json:
        out = Path(args.out_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

