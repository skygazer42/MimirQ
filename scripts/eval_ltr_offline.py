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

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from app.rag.reranker.ltr import LTRFeatureSpec, LTRReranker, build_ltr_feature_spec_fingerprint
from app.rag.reranker.types import RerankCandidate

METRIC_KEYS = ("hit", "mrr", "recall", "ndcg")


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


def _extract_pipeline_hashes(items: list[dict[str, Any]], *, max_items: int = 20) -> list[str]:
    cap = max(0, int(max_items or 0))
    if cap <= 0:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for it in items or []:
        if not isinstance(it, dict):
            continue
        refs = it.get("reference_sources") or []
        if not isinstance(refs, list):
            continue
        for src in refs:
            if not isinstance(src, dict):
                continue
            ph = str(src.get("pipeline_hash") or "").strip()
            if not ph:
                continue
            ph = ph[:64]
            if ph in seen:
                continue
            seen.add(ph)
            out.append(ph)
            if len(out) >= cap:
                return out
    return out


def build_eval_summary(
    *,
    generated_at: str,
    elapsed_sec: float,
    dataset_id: str,
    cases_total: int,
    cases_used: int,
    cases_sha256: str,
    cases_schema: str | None,
    pipeline_hashes: list[str] | None,
    retrieval_config: dict[str, Any] | None,
    model_path: str,
    model_sha256: str,
    spec: LTRFeatureSpec,
    feature_spec_version: int,
    k: int,
    top_k: int,
    rerank_top_n: int,
    baseline: dict[str, float],
    ltr: dict[str, float],
) -> dict[str, Any]:
    retrieval_hash = None
    retrieval_payload = None
    if isinstance(retrieval_config, dict):
        hash_value = str(retrieval_config.get("hash") or "").strip()
        retrieval_hash = hash_value or None
        retrieval_payload = dict(retrieval_config)

    lineage: dict[str, Any] = {
        "schema": "mimirq.ltr_run_lineage.v1",
        "kind": "eval",
        "dataset_id": str(dataset_id),
        "cases_sha256": str(cases_sha256),
        "cases_schema": (str(cases_schema) if cases_schema else None),
        "pipeline_hashes": list(pipeline_hashes or []),
        "retrieval_config_hash": retrieval_hash,
        "retrieval_config": retrieval_payload,
        "model_path": str(model_path),
        "model_sha256": str(model_sha256),
        "feature_spec_version": int(feature_spec_version or 1),
        "feature_spec": build_ltr_feature_spec_fingerprint(spec=spec, version=int(feature_spec_version or 1)),
    }
    lineage = {k: v for k, v in lineage.items() if v is not None}

    return {
        "schema": "mimirq.ltr_offline_eval.v1",
        "generated_at": str(generated_at),
        "elapsed_sec": round(float(elapsed_sec or 0.0), 3),
        "dataset_id": str(dataset_id),
        "cases_total": int(cases_total or 0),
        "cases_used": int(cases_used or 0),
        "k": int(k or 0),
        "top_k": int(top_k or 0),
        "rerank_top_n": int(rerank_top_n or 0),
        "model": str(model_path),
        "model_sha256": str(model_sha256),
        "spec": str(getattr(spec, "schema", "") or ""),
        "baseline": dict(baseline or {}),
        "ltr": dict(ltr or {}),
        "lineage": lineage,
    }


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
        # Field-aware recall signals (optional; v3 feature spec).
        "field_aware_boost": _as_float(c.get("field_aware_boost")),
        "field_aware_signal": str(c.get("field_aware_signal") or "").strip() or None,
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


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Offline evaluation: baseline vs local LTR rerank (via Evidence API candidates).")
    )
    parser.add_argument(
        "--cases",
        required=True,
        help="Path to regression cases JSON (bundle v1 or legacy array)",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Path to LTR model artifact (xgboost JSON/UBJ)",
    )
    parser.add_argument(
        "--feature-spec-version",
        type=int,
        default=1,
        help="LTR feature spec version (default: %(default)s)",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000/api/v1",
        help="API base URL (default: %(default)s)",
    )
    parser.add_argument("--tenant-id", default="", help="Tenant id (X-Tenant-ID header)")
    parser.add_argument(
        "--user-id",
        default="",
        help="User id (X-User-ID header, for AUTH_MODE=header)",
    )
    parser.add_argument("--bearer", default="", help="Bearer token (Authorization: Bearer ...)")
    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=30.0,
        help="HTTP timeout seconds (default: %(default)s)",
    )
    parser.add_argument("--top-k", type=int, default=50, help="Evidence API top_k (default: %(default)s)")
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=0.0,
        help="Evidence API score_threshold (default: %(default)s)",
    )
    parser.add_argument(
        "--retrieval-mode",
        default="hybrid",
        help="hybrid|vector|keyword|mmr (default: %(default)s)",
    )
    parser.add_argument(
        "--retrieval-profile",
        default="recall50",
        help="recall20|recall50|coverage80 (default: %(default)s)",
    )
    parser.add_argument("--alpha", type=float, default=0.6, help="Fusion alpha (default: %(default)s)")
    parser.add_argument("--k", type=int, default=20, help="Compute metrics at K (default: %(default)s)")
    parser.add_argument(
        "--rerank-top-n",
        type=int,
        default=30,
        help="Rerank the top-N candidates locally (default: %(default)s)",
    )
    parser.add_argument("--max-cases", type=int, default=0, help="Limit number of cases (default: all)")
    parser.add_argument("--out-json", default="", help="Optional: write summary JSON to this path")
    return parser


def _existing_path(path_value: str, *, label: str) -> Path | None:
    path = Path(path_value)
    if path.exists():
        return path
    print(f"[eval_ltr] ERROR: {label} file not found: {path}", file=sys.stderr)
    return None


def _load_cases_bundle_from_path(
    cases_path: Path,
    *,
    max_cases: int,
) -> tuple[str, list[dict[str, Any]], str, str | None]:
    try:
        try:
            cases_sha256 = hashlib.sha256(cases_path.read_bytes()).hexdigest()
        except Exception:
            cases_sha256 = ""

        raw_cases = _load_json(cases_path)
        cases_schema = str(raw_cases.get("schema") or "").strip() if isinstance(raw_cases, dict) else ""
        dataset_id, items = coerce_case_bundle(raw_cases)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(str(exc)[:200]) from exc

    if max_cases > 0:
        items = list(items)[:max_cases]
    return dataset_id, items, cases_sha256, (cases_schema or None)


def _resolve_eval_window(args: argparse.Namespace) -> tuple[int, int, int]:
    k = max(1, int(args.k or 0))
    top_k = max(k, int(args.top_k or 0))
    rerank_top_n = max(0, int(args.rerank_top_n or 0))
    rerank_top_n = min(rerank_top_n, top_k) if rerank_top_n else top_k
    return k, top_k, rerank_top_n


def _build_retrieve_request(
    *,
    args: argparse.Namespace,
    dataset_id: str,
    question: str,
    top_k: int,
) -> dict[str, Any]:
    return {
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


def _extract_retrieval_config(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    retrieval_trace = payload.get("retrieval_trace")
    if not isinstance(retrieval_trace, dict):
        return None
    retrieval_config = retrieval_trace.get("retrieval_config")
    if not isinstance(retrieval_config, dict):
        return None
    has_schema = str(retrieval_config.get("schema") or "").strip()
    has_hash = str(retrieval_config.get("hash") or "").strip()
    if not has_schema or not has_hash:
        return None
    return dict(retrieval_config)


def _collect_ranked_ids(citations: Any) -> list[str]:
    if not isinstance(citations, list) or not citations:
        return []
    ranked_ids = [str(c.get("chunk_id") or "").strip() for c in citations if isinstance(c, dict)]
    return [chunk_id for chunk_id in ranked_ids if chunk_id]


def _build_reranked_ids(
    *,
    citations: list[Any],
    reranker: LTRReranker,
    question: str,
    ranked_ids: list[str],
    rerank_top_n: int,
) -> list[str]:
    candidates: list[RerankCandidate] = []
    for citation in citations[:rerank_top_n]:
        if not isinstance(citation, dict):
            continue
        candidate = _build_candidate_from_citation(citation)
        if candidate is not None:
            candidates.append(candidate)

    rerank_result = reranker.rerank(query=question, candidates=candidates, top_n=len(candidates))
    ordered_ids = list(rerank_result.ordered_ids or [])
    used = set(ordered_ids)
    return ordered_ids + [chunk_id for chunk_id in ranked_ids if chunk_id not in used]


def _average_metrics(metric_sum: dict[str, float], *, cases_used: int) -> dict[str, float]:
    if cases_used <= 0:
        return metric_sum
    return {key: round(float(metric_sum[key]) / float(cases_used), 4) for key in METRIC_KEYS}


def _evaluate_items(
    *,
    args: argparse.Namespace,
    dataset_id: str,
    items: list[dict[str, Any]],
    reranker: LTRReranker,
    top_k: int,
    k: int,
    rerank_top_n: int,
) -> tuple[dict[str, float], dict[str, float], int, dict[str, Any] | None]:
    url = str(args.base_url).rstrip("/") + "/rag/retrieve"
    timeout = httpx.Timeout(float(args.timeout_sec or 30.0))
    retrieval_config: dict[str, Any] | None = None
    baseline_sum = {key: 0.0 for key in METRIC_KEYS}
    ltr_sum = {key: 0.0 for key in METRIC_KEYS}
    cases_used = 0

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

            request_body = _build_retrieve_request(
                args=args,
                dataset_id=dataset_id,
                question=question,
                top_k=top_k,
            )
            try:
                response = client.post(url, headers=_headers(args), json=request_body)
                response.raise_for_status()
                payload = response.json() or {}
            except Exception as exc:  # noqa: BLE001
                print(f"[eval_ltr] WARN: retrieve failed: {str(exc)[:200]}", file=sys.stderr)
                continue

            if retrieval_config is None:
                retrieval_config = _extract_retrieval_config(payload)

            citations = payload.get("citations") or []
            ranked_ids = _collect_ranked_ids(citations)
            if not ranked_ids:
                continue

            base_metrics = _hit_mrr_recall_ndcg_at_k(ranked_ids=ranked_ids, relevant=relevant, k=k)
            reranked = _build_reranked_ids(
                citations=citations,
                reranker=reranker,
                question=question,
                ranked_ids=ranked_ids,
                rerank_top_n=rerank_top_n,
            )
            ltr_metrics = _hit_mrr_recall_ndcg_at_k(ranked_ids=reranked, relevant=relevant, k=k)
            cases_used += 1
            for key in METRIC_KEYS:
                baseline_sum[key] += float(base_metrics.get(key, 0.0) or 0.0)
                ltr_sum[key] += float(ltr_metrics.get(key, 0.0) or 0.0)

    return baseline_sum, ltr_sum, cases_used, retrieval_config


def _write_summary_json(out_json: str, *, summary: dict[str, Any]) -> None:
    if not out_json:
        return
    out = Path(out_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    t0 = time.monotonic()
    args = _build_argument_parser().parse_args(argv)

    cases_path = _existing_path(args.cases, label="cases")
    if cases_path is None:
        return 2

    model_path = _existing_path(args.model, label="model")
    if model_path is None:
        return 2

    try:
        dataset_id, items, cases_sha256, cases_schema = _load_cases_bundle_from_path(
            cases_path,
            max_cases=int(args.max_cases or 0),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[eval_ltr] ERROR: failed to parse cases: {str(exc)[:200]}", file=sys.stderr)
        return 2

    k, top_k, rerank_top_n = _resolve_eval_window(args)
    pipeline_hashes = _extract_pipeline_hashes(items)

    try:
        model_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
    except Exception:
        model_sha256 = ""

    feature_spec_version = int(args.feature_spec_version or 1)
    spec = LTRFeatureSpec.from_version(feature_spec_version)
    reranker = LTRReranker(model_path=str(model_path), spec=spec)
    baseline_sum, ltr_sum, cases_used, retrieval_config = _evaluate_items(
        args=args,
        dataset_id=str(dataset_id),
        items=items,
        reranker=reranker,
        top_k=top_k,
        k=k,
        rerank_top_n=rerank_top_n,
    )
    baseline_sum = _average_metrics(baseline_sum, cases_used=cases_used)
    ltr_sum = _average_metrics(ltr_sum, cases_used=cases_used)

    summary = build_eval_summary(
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        elapsed_sec=float(time.monotonic() - t0),
        dataset_id=str(dataset_id),
        cases_total=len(items),
        cases_used=cases_used,
        cases_sha256=cases_sha256,
        cases_schema=cases_schema,
        pipeline_hashes=pipeline_hashes,
        retrieval_config=retrieval_config,
        model_path=str(model_path),
        model_sha256=model_sha256,
        spec=spec,
        feature_spec_version=feature_spec_version,
        k=k,
        top_k=top_k,
        rerank_top_n=rerank_top_n,
        baseline=baseline_sum,
        ltr=ltr_sum,
    )

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
    _write_summary_json(args.out_json, summary=summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
