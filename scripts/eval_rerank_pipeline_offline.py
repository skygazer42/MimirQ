#!/usr/bin/env python3
"""
Offline evaluation: baseline retrieval vs local multi-stage rerank pipeline.

Why:
- Let teams iterate on deterministic rerank stacks (LTR, ColBERT late-interaction)
  without requiring server-side feature flags to be enabled.
- Produce retrieval-only metrics (Hit/MRR/Recall/NDCG) from regression case bundles.

How it works:
1) Use Evidence API (/api/v1/rag/retrieve) to fetch *pre-rerank* citations.
2) Apply a local rerank pipeline to the top-N candidates.
3) Compare baseline vs pipeline metrics.

Notes:
- ColBERT reranker uses chunk_content snippets returned by the Evidence API, not full chunks.
  This keeps the script dependency-light but may under-estimate late-interaction wins.
"""

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.rag.reranker.colbert import ColBERTReranker  # noqa: E402
from app.rag.reranker.ltr import LTRFeatureSpec, LTRReranker  # noqa: E402
from app.rag.reranker.types import RerankCandidate  # noqa: E402


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
        # Evidence API returns snippet-like chunk_content; keep dependency-light.
        text=str(c.get("chunk_content") or ""),
        metadata=meta,
    )


def build_colbert_reranker(args: argparse.Namespace) -> ColBERTReranker:
    return ColBERTReranker(
        provider_name=str(getattr(args, "colbert_provider", "deterministic") or "deterministic"),
        model_name=str(getattr(args, "colbert_model_name", "") or ""),
        device=str(getattr(args, "colbert_device", "cpu") or "cpu"),
        batch_size=max(1, int(getattr(args, "colbert_batch_size", 16) or 16)),
        max_length=max(8, int(getattr(args, "colbert_max_length", 256) or 256)),
        deterministic_dim=max(2, int(getattr(args, "colbert_deterministic_dim", 64) or 64)),
    )


def build_pipeline_summary(
    *,
    cases_total: int,
    cases_used: int,
    k: int,
    top_k: int,
    pipeline: list[dict[str, Any]],
    baseline: dict[str, float],
    pipeline_metrics: dict[str, float],
    case_metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    metric_keys = ("hit", "mrr", "recall", "ndcg")
    baseline_out = {key: round(_as_float(baseline.get(key)), 4) for key in metric_keys}
    pipeline_out = {key: round(_as_float(pipeline_metrics.get(key)), 4) for key in metric_keys}
    delta_metrics = {key: round(pipeline_out.get(key, 0.0) - baseline_out.get(key, 0.0), 4) for key in metric_keys}

    delta_counts: dict[str, dict[str, int]] = {}
    for key in metric_keys:
        wins = 0
        losses = 0
        ties = 0
        for item in case_metrics or []:
            base_case = _as_float((item.get("baseline") or {}).get(key))
            pipe_case = _as_float((item.get("pipeline") or {}).get(key))
            if pipe_case > base_case:
                wins += 1
            elif pipe_case < base_case:
                losses += 1
            else:
                ties += 1
        delta_counts[key] = {"wins": wins, "losses": losses, "ties": ties}

    return {
        "schema": "mimirq.rerank_pipeline_eval.v1",
        "cases_total": int(cases_total or 0),
        "cases_used": int(cases_used or 0),
        "k": int(k or 0),
        "top_k": int(top_k or 0),
        "pipeline": list(pipeline or []),
        "baseline": baseline_out,
        "pipeline_metrics": pipeline_out,
        "delta_metrics": delta_metrics,
        "delta_counts": delta_counts,
    }


def _parse_pipeline(raw: str) -> list[dict[str, Any]]:
    text = str(raw or "").strip()
    if not text:
        return []

    path = Path(text)
    if path.exists() and path.is_file() and path.suffix.lower() in {".json"}:
        obj = _load_json(path)
    else:
        obj = json.loads(text)

    if not isinstance(obj, list):
        raise ValueError("pipeline must be a JSON list")

    out: list[dict[str, Any]] = []
    for st in obj:
        if not isinstance(st, dict):
            continue
        provider = str(st.get("provider") or "").strip().lower()
        if not provider:
            continue
        top_n_raw = st.get("top_n")
        try:
            top_n = int(top_n_raw) if top_n_raw is not None else 0
        except Exception:
            top_n = 0
        out.append({"provider": provider, "top_n": max(0, top_n)})
    return out


def apply_pipeline(
    *,
    query: str,
    candidates: list[RerankCandidate],
    ranked_ids: list[str],
    pipeline: list[dict[str, Any]],
    ltr: LTRReranker | None,
    colbert: ColBERTReranker | None,
) -> list[str]:
    out = list(ranked_ids)
    for st in pipeline or []:
        provider = str(st.get("provider") or "").strip().lower()
        if provider in {"none", "off", "false", "0"}:
            continue
        top_n = int(st.get("top_n") or 0)
        if top_n <= 0:
            continue
        top_n = min(top_n, len(out))
        if top_n <= 0:
            continue

        prefix_ids = out[:top_n]
        id_set = set(prefix_ids)
        prefix_candidates = [c for c in candidates if str(c.id) in id_set]

        if not prefix_candidates:
            continue

        if provider == "ltr":
            if ltr is None:
                raise ValueError("pipeline includes provider=ltr but no --ltr-model was provided")
            rr = ltr.rerank(query=query, candidates=prefix_candidates, top_n=len(prefix_candidates))
        elif provider in {"colbert", "late_interaction"}:
            if colbert is None:
                raise ValueError("pipeline includes provider=colbert but ColBERTReranker is unavailable")
            rr = colbert.rerank(query=query, candidates=prefix_candidates, top_n=len(prefix_candidates))
        else:
            raise ValueError(f"unsupported pipeline provider: {provider} (supported: ltr, colbert)")

        ordered_ids = list(rr.ordered_ids or [])
        used = set(ordered_ids)
        out = ordered_ids + [cid for cid in out if cid not in used]
    return out


_METRIC_KEYS = ("hit", "mrr", "recall", "ndcg")


class _CliError(RuntimeError):
    pass


@dataclass(frozen=True)
class _EvaluationConfig:
    args: argparse.Namespace
    pipeline: list[dict[str, Any]]
    ltr: LTRReranker | None
    colbert: ColBERTReranker | None
    dataset_id: str
    items: list[dict[str, Any]]
    k: int
    top_k: int
    url: str
    timeout: httpx.Timeout


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Offline evaluation: baseline vs local rerank pipeline (candidates via Evidence API)."
    )
    p.add_argument("--cases", required=True, help="Path to regression cases JSON (bundle v1 or legacy array)")
    p.add_argument("--pipeline", required=True, help="Pipeline JSON string or path to a JSON file")

    p.add_argument("--ltr-model", default="", help="Path to LTR model artifact (required if pipeline includes 'ltr')")
    p.add_argument(
        "--ltr-feature-spec-version", type=int, default=1, help="LTR feature spec version (default: %(default)s)"
    )
    p.add_argument("--colbert-provider", default="deterministic", help="deterministic|hf (default: %(default)s)")
    p.add_argument("--colbert-model-name", default="", help="HF model name for provider=hf")
    p.add_argument("--colbert-device", default="cpu", help="cpu|cuda|auto (default: %(default)s)")
    p.add_argument("--colbert-batch-size", type=int, default=16, help="ColBERT token batch size (default: %(default)s)")
    p.add_argument(
        "--colbert-max-length", type=int, default=256, help="Max token length for HF provider (default: %(default)s)"
    )
    p.add_argument(
        "--colbert-deterministic-dim",
        type=int,
        default=64,
        help="Deterministic provider embedding dimension (default: %(default)s)",
    )

    p.add_argument("--base-url", default="http://localhost:8000/api/v1", help="API base URL (default: %(default)s)")
    p.add_argument("--tenant-id", default="", help="Tenant id (X-Tenant-ID header)")
    p.add_argument("--user-id", default="", help="User id (X-User-ID header, for AUTH_MODE=header)")
    p.add_argument("--bearer", default="", help="Bearer token (Authorization: Bearer ...)")
    p.add_argument("--timeout-sec", type=float, default=30.0, help="HTTP timeout seconds (default: %(default)s)")

    p.add_argument("--top-k", type=int, default=50, help="Evidence API rag_config.top_k (default: %(default)s)")
    p.add_argument(
        "--score-threshold",
        type=float,
        default=0.0,
        help="Evidence API rag_config.score_threshold (default: %(default)s)",
    )
    p.add_argument("--retrieval-mode", default="hybrid", help="hybrid|vector|keyword|mmr (default: %(default)s)")
    p.add_argument(
        "--retrieval-profile", default="recall50", help="recall20|recall50|coverage80 (default: %(default)s)"
    )
    p.add_argument("--alpha", type=float, default=0.6, help="Fusion alpha (default: %(default)s)")

    p.add_argument("--k", type=int, default=20, help="Compute metrics at K (default: %(default)s)")
    p.add_argument("--max-cases", type=int, default=0, help="Limit number of cases (default: all)")
    p.add_argument("--out-json", default="", help="Optional: write summary JSON to this path")
    return p


def _pipeline_has_provider(pipeline: list[dict[str, Any]], providers: set[str]) -> bool:
    return any(str(stage.get("provider") or "").strip().lower() in providers for stage in pipeline)


def _build_ltr_reranker(args: argparse.Namespace, pipeline: list[dict[str, Any]]) -> LTRReranker | None:
    if not _pipeline_has_provider(pipeline, {"ltr"}):
        return None
    model_path = Path(args.ltr_model) if str(args.ltr_model or "").strip() else None
    if model_path is None or not model_path.exists():
        raise _CliError("pipeline includes 'ltr' but --ltr-model is missing/not found")
    spec = LTRFeatureSpec.from_version(int(args.ltr_feature_spec_version or 1))
    return LTRReranker(model_path=str(model_path), spec=spec)


def _build_optional_colbert(
    args: argparse.Namespace,
    pipeline: list[dict[str, Any]],
) -> ColBERTReranker | None:
    if not _pipeline_has_provider(pipeline, {"colbert", "late_interaction"}):
        return None
    return build_colbert_reranker(args)


def _build_evaluation_config(args: argparse.Namespace) -> _EvaluationConfig:
    cases_path = Path(args.cases)
    if not cases_path.exists():
        raise _CliError(f"cases file not found: {cases_path}")

    try:
        pipeline = _parse_pipeline(str(args.pipeline))
    except Exception as exc:  # noqa: BLE001
        raise _CliError(f"failed to parse pipeline: {str(exc)[:200]}") from exc
    if not pipeline:
        raise _CliError("pipeline is empty")

    ltr = _build_ltr_reranker(args, pipeline)
    colbert = _build_optional_colbert(args, pipeline)

    try:
        raw_cases = _load_json(cases_path)
        dataset_id, items = coerce_case_bundle(raw_cases)
    except Exception as exc:  # noqa: BLE001
        raise _CliError(f"failed to parse cases: {str(exc)[:200]}") from exc

    if args.max_cases and int(args.max_cases) > 0:
        items = list(items)[: int(args.max_cases)]

    k = max(1, int(args.k or 0))
    top_k = max(k, int(args.top_k or 0))
    url = str(args.base_url).rstrip("/") + "/rag/retrieve"
    timeout = httpx.Timeout(float(args.timeout_sec or 30.0))
    return _EvaluationConfig(
        args=args,
        pipeline=pipeline,
        ltr=ltr,
        colbert=colbert,
        dataset_id=dataset_id,
        items=items,
        k=k,
        top_k=top_k,
        url=url,
        timeout=timeout,
    )


def _build_retrieve_body(config: _EvaluationConfig, question: str) -> dict[str, Any]:
    args = config.args
    return {
        "query": question,
        "history": [],
        "dataset_id": str(config.dataset_id),
        "document_ids": [],
        "rag_config": {
            "retrieval_profile": str(args.retrieval_profile),
            "retrieval_mode": str(args.retrieval_mode),
            "top_k": int(config.top_k),
            "score_threshold": float(args.score_threshold),
            "alpha": float(args.alpha),
            "enable_reranker": False,
            "reranker_provider": "none",
            "reranker_top_n": 0,
        },
    }


def _retrieve_citations(
    client: httpx.Client,
    config: _EvaluationConfig,
    question: str,
) -> list[Any]:
    try:
        response = client.post(
            config.url,
            headers=_headers(config.args),
            json=_build_retrieve_body(config, question),
        )
        response.raise_for_status()
        payload = response.json() or {}
    except Exception as exc:  # noqa: BLE001
        print(f"[pipeline-eval] WARN: retrieve failed: {str(exc)[:200]}", file=sys.stderr)
        return []
    citations = payload.get("citations") or []
    return citations if isinstance(citations, list) else []


def _ranked_chunk_ids(citations: list[Any]) -> list[str]:
    ranked_ids = [str(citation.get("chunk_id") or "").strip() for citation in citations if isinstance(citation, dict)]
    return [chunk_id for chunk_id in ranked_ids if chunk_id]


def _build_candidates(citations: list[Any]) -> list[RerankCandidate]:
    candidates: list[RerankCandidate] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        candidate = _build_candidate_from_citation(citation)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _evaluate_case(
    client: httpx.Client,
    config: _EvaluationConfig,
    item: dict[str, Any],
) -> tuple[dict[str, float], dict[str, float]] | None:
    question = str(item.get("question") or item.get("query") or "").strip()
    if not question:
        return None
    relevant = _extract_reference_chunk_ids(item)
    if not relevant:
        return None
    citations = _retrieve_citations(client, config, question)
    if not citations:
        return None
    ranked_ids = _ranked_chunk_ids(citations)
    if not ranked_ids:
        return None

    candidates = _build_candidates(citations)
    baseline = _hit_mrr_recall_ndcg_at_k(ranked_ids=ranked_ids, relevant=relevant, k=config.k)
    piped_ids = apply_pipeline(
        query=question,
        candidates=candidates,
        ranked_ids=ranked_ids,
        pipeline=config.pipeline,
        ltr=config.ltr,
        colbert=config.colbert,
    )
    piped = _hit_mrr_recall_ndcg_at_k(ranked_ids=piped_ids, relevant=relevant, k=config.k)
    return baseline, piped


def _evaluate_items(
    client: httpx.Client,
    config: _EvaluationConfig,
) -> tuple[dict[str, float], dict[str, float], list[dict[str, Any]], int]:
    baseline_totals = {key: 0.0 for key in _METRIC_KEYS}
    pipeline_totals = {key: 0.0 for key in _METRIC_KEYS}
    case_metrics: list[dict[str, Any]] = []
    cases_used = 0
    for item in config.items:
        if not isinstance(item, dict):
            continue
        metrics = _evaluate_case(client, config, item)
        if metrics is None:
            continue
        baseline, piped = metrics
        cases_used += 1
        case_metrics.append({"baseline": baseline, "pipeline": piped})
        for key in _METRIC_KEYS:
            baseline_totals[key] += float(baseline.get(key, 0.0) or 0.0)
            pipeline_totals[key] += float(piped.get(key, 0.0) or 0.0)
    return baseline_totals, pipeline_totals, case_metrics, cases_used


def _average_metrics(totals: dict[str, float], cases_used: int) -> dict[str, float]:
    averaged = dict(totals)
    if cases_used <= 0:
        return averaged
    for key in _METRIC_KEYS:
        averaged[key] = round(float(totals[key]) / float(cases_used), 4)
    return averaged


def _print_summary(summary: dict[str, Any], *, k: int) -> None:
    print(
        "[pipeline-eval] OK"
        f" cases_total={summary['cases_total']}"
        f" cases_used={summary['cases_used']}"
        f" k={k}"
        f" baseline_hit={summary['baseline']['hit']}"
        f" pipe_hit={summary['pipeline_metrics']['hit']}"
        f" baseline_mrr={summary['baseline']['mrr']}"
        f" pipe_mrr={summary['pipeline_metrics']['mrr']}"
        f" baseline_ndcg={summary['baseline']['ndcg']}"
        f" pipe_ndcg={summary['pipeline_metrics']['ndcg']}"
        f" mrr_wins={summary['delta_counts']['mrr']['wins']}"
        f" mrr_losses={summary['delta_counts']['mrr']['losses']}"
    )


def _write_summary(path_value: str, summary: dict[str, Any]) -> None:
    if not path_value:
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        config = _build_evaluation_config(args)
    except _CliError as exc:
        print(f"[pipeline-eval] ERROR: {exc}", file=sys.stderr)
        return 2

    with httpx.Client(timeout=config.timeout) as client:
        baseline_totals, pipeline_totals, case_metrics, cases_used = _evaluate_items(client, config)
    baseline_avg = _average_metrics(baseline_totals, cases_used)
    pipeline_avg = _average_metrics(pipeline_totals, cases_used)

    summary = build_pipeline_summary(
        cases_total=len(config.items),
        cases_used=cases_used,
        k=config.k,
        top_k=config.top_k,
        pipeline=config.pipeline,
        baseline=baseline_avg,
        pipeline_metrics=pipeline_avg,
        case_metrics=case_metrics,
    )
    _print_summary(summary, k=config.k)
    _write_summary(str(args.out_json or ""), summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
