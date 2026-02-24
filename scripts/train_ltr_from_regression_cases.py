#!/usr/bin/env python3
"""
Train a tiny XGBoost-based LTR reranker model from regression cases (evidence pointers).

Workflow:
1) Load a regression cases bundle (mimirq.regression_cases.v1 or legacy shapes)
2) For each case, call Evidence API (retrieval-only) to fetch citations
3) Label each citation as positive if its chunk_id matches any reference_sources.chunk_id
4) Extract a stable feature map (LTRFeatureSpec.default)
5) Train and write an XGBoost model artifact (JSON bytes) to --out-model

Notes:
- This is intentionally offline and deterministic (no LLM required).
- It assumes a running backend for retrieval via /api/v1/rag/retrieve.
- By default it disables the built-in reranker so the collected candidates are pre-rerank.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

from app.rag.reranker.ltr import LTRFeatureSpec, extract_ltr_features, train_ltr_xgboost_model
from app.rag.reranker.types import RerankCandidate


def _load_json(path: Path) -> Any:
    # PowerShell commonly writes UTF-8 JSON with BOM; `utf-8-sig` handles both BOM/no-BOM.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


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


def _coerce_nonneg_int(value: Any) -> int:
    try:
        iv = int(value) if value is not None else 0
    except Exception:
        return 0
    return iv if iv >= 0 else 0


def _as_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


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


def build_ltr_feature_map(*, citation: dict[str, Any], query: str, spec: LTRFeatureSpec) -> dict[str, float]:
    # Keep feature semantics aligned with app.rag.reranker.ltr.extract_ltr_features.
    meta = {
        "vector_score": _as_float(citation.get("vector_score")),
        "bm25_score": _as_float(citation.get("bm25_score")),
        "lexical_score": _as_float(citation.get("lexical_score")),
        "sparse_score": _as_float(citation.get("sparse_score")),
        # Evidence API exposes this as relevance_score; treat it as the base retrieval score.
        "score": _as_float(citation.get("relevance_score")),
        # Optional KG ranking features (low-cardinality).
        "kg_pagerank": _as_float(citation.get("kg_pagerank")),
        "kg_shared_events": _as_float(citation.get("kg_shared_events")),
        "kg_path_length": _as_float(citation.get("kg_path_length")),
        "kg_edge_conf_low": _as_float(citation.get("kg_edge_conf_low")),
        "kg_edge_conf_mid": _as_float(citation.get("kg_edge_conf_mid")),
        "kg_edge_conf_high": _as_float(citation.get("kg_edge_conf_high")),
        "kg_evidence_anchored": _as_float(citation.get("kg_evidence_anchored")),
        "retrieval_role": citation.get("retrieval_role"),
    }
    values = extract_ltr_features(
        spec=spec,
        query=str(query or ""),
        candidate=RerankCandidate(
            id=str(citation.get("chunk_id") or ""),
            text=str(citation.get("chunk_content") or ""),
            metadata=meta,
        ),
    )
    return {name: float(v) for name, v in zip(spec.feature_names, values, strict=False)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Train an LTR reranker model from regression cases via Evidence API.")
    p.add_argument("--cases", required=True, help="Path to regression cases JSON (bundle v1 or legacy array)")
    p.add_argument("--out-model", required=True, help="Write model bytes to this path (xgboost JSON)")
    p.add_argument("--out-rows-jsonl", default="", help="Optional: write training rows as JSONL for inspection")

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
    p.add_argument(
        "--enable-weight-rerank",
        action="store_true",
        help="Enable heuristic weight rerank before collecting candidates (default: off)",
    )

    p.add_argument("--max-cases", type=int, default=0, help="Limit number of cases (default: all)")
    p.add_argument(
        "--max-negatives-per-case",
        type=int,
        default=30,
        help="Cap negatives per query (default: %(default)s)",
    )
    p.add_argument(
        "--skip-missed-cases",
        action="store_true",
        help="Skip cases where none of the reference chunks were retrieved (default: include only positives+sampled negatives from hits)",
    )

    p.add_argument("--num-boost-round", type=int, default=50, help="xgboost num_boost_round (default: %(default)s)")
    p.add_argument("--seed", type=int, default=42, help="Training seed (default: %(default)s)")
    p.add_argument(
        "--feature-spec-version",
        type=int,
        default=1,
        help="LTR feature spec version (1=base, 2=KG features) (default: %(default)s)",
    )
    p.add_argument(
        "--objective",
        default="rank:pairwise",
        help="xgboost objective: rank:pairwise|rank:ndcg|binary:logistic (default: %(default)s)",
    )
    p.add_argument(
        "--hard-negatives-per-case",
        type=int,
        default=10,
        help="Hard negatives per query group (negatives ranked above the first positive) (default: %(default)s)",
    )
    args = p.parse_args(argv)

    cases_path = Path(args.cases)
    if not cases_path.exists():
        print(f"[train_ltr] ERROR: cases file not found: {cases_path}", file=sys.stderr)
        return 2

    try:
        raw_cases = _load_json(cases_path)
        dataset_id, items = coerce_case_bundle(raw_cases)
    except Exception as exc:  # noqa: BLE001
        print(f"[train_ltr] ERROR: failed to parse cases: {str(exc)[:200]}", file=sys.stderr)
        return 2

    if args.max_cases and int(args.max_cases) > 0:
        items = list(items)[: _coerce_nonneg_int(args.max_cases)]

    spec = LTRFeatureSpec.from_version(int(args.feature_spec_version or 1))
    training_rows: list[dict[str, Any]] = []
    group_sizes: list[int] = []
    objective = str(args.objective or "rank:pairwise").strip() or "rank:pairwise"
    stats = {
        "cases_total": len(items),
        "cases_used": 0,
        "cases_missed": 0,
        "rows_total": 0,
        "rows_pos": 0,
        "rows_neg": 0,
        "rows_hard_neg": 0,
    }

    url = str(args.base_url).rstrip("/") + "/rag/retrieve"
    timeout = httpx.Timeout(float(args.timeout_sec or 30.0))

    with httpx.Client(timeout=timeout) as client:
        for item in items:
            if not isinstance(item, dict):
                continue

            question = str(item.get("question") or item.get("query") or "").strip()
            if not question:
                continue

            ref_chunk_ids = _extract_reference_chunk_ids(item)
            if not ref_chunk_ids:
                continue

            body = {
                "query": question,
                "history": [],
                "dataset_id": str(dataset_id),
                "document_ids": [],
                "rag_config": {
                    "retrieval_profile": str(args.retrieval_profile),
                    "retrieval_mode": str(args.retrieval_mode),
                    "top_k": int(args.top_k),
                    "score_threshold": float(args.score_threshold),
                    "alpha": float(args.alpha),
                    "enable_weight_rerank": bool(args.enable_weight_rerank),
                    # Collect pre-rerank candidates by default.
                    "enable_reranker": False,
                    "reranker_provider": "none",
                    "reranker_top_n": 0,
                },
            }

            try:
                resp = client.post(url, headers=_headers(args), json=body)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001
                print(f"[train_ltr] WARN: retrieve failed: {str(exc)[:200]}", file=sys.stderr)
                continue

            citations = payload.get("citations") or []
            if not isinstance(citations, list) or not citations:
                stats["cases_missed"] += 1
                continue

            rows_this_case: list[dict[str, Any]] = []
            pos = 0
            neg = 0
            for idx, c in enumerate(citations, 1):
                if not isinstance(c, dict):
                    continue
                cid = str(c.get("chunk_id") or "").strip()
                if not cid:
                    continue
                label = 1 if cid in ref_chunk_ids else 0
                feats = build_ltr_feature_map(citation=c, query=question, spec=spec)
                rows_this_case.append(
                    {
                        "features": feats,
                        "label": int(label),
                        "rank": int(idx),
                        "case_question": question,
                        "chunk_id": cid,
                        "retrieval_role": c.get("retrieval_role"),
                    }
                )
                if label:
                    pos += 1
                else:
                    neg += 1

            max_neg = _coerce_nonneg_int(args.max_negatives_per_case)
            hard_max = _coerce_nonneg_int(args.hard_negatives_per_case)
            if max_neg and hard_max > max_neg:
                hard_max = max_neg

            # Ranking objectives require at least one positive per query group.
            if pos <= 0:
                stats["cases_missed"] += 1
                if objective.startswith("rank:"):
                    continue
                if bool(args.skip_missed_cases):
                    continue

            # Hard negatives: "near-miss" candidates ranked above the first positive.
            first_pos_idx: int | None = None
            for i, row in enumerate(rows_this_case):
                if int(row.get("label") or 0) == 1:
                    first_pos_idx = i
                    break

            pos_idx = [i for i, r in enumerate(rows_this_case) if int(r.get("label") or 0) == 1]
            neg_idx = [i for i, r in enumerate(rows_this_case) if int(r.get("label") or 0) == 0]

            hard_idx: list[int] = []
            easy_idx: list[int] = []
            for i in neg_idx:
                if first_pos_idx is not None and i < first_pos_idx:
                    hard_idx.append(i)
                else:
                    easy_idx.append(i)

            hard_selected = hard_idx[:hard_max] if hard_max else []
            if max_neg:
                remaining = max(0, int(max_neg) - int(len(hard_selected)))
                easy_selected = easy_idx[:remaining]
            else:
                # max_neg=0 => keep all negatives
                easy_selected = easy_idx

            neg_selected = list(hard_selected) + list(easy_selected)
            keep_idx = sorted(set(pos_idx + neg_selected))
            kept = [rows_this_case[i] for i in keep_idx]

            # Mark hard negatives (useful for debugging/inspection outputs).
            hard_set = set(hard_selected)
            for i, row in enumerate(rows_this_case):
                if i not in keep_idx:
                    continue
                if int(row.get("label") or 0) == 0 and i in hard_set:
                    row["hard_negative"] = True
                    stats["rows_hard_neg"] += 1

            # Ranking objective requires group size >= 2 (at least one pos + one neg).
            if objective.startswith("rank:") and (len(kept) < 2 or not any(int(r.get("label") or 0) == 1 for r in kept)):
                stats["cases_missed"] += 1
                continue

            if any(int(r.get("label") or 0) == 1 for r in kept):
                stats["cases_used"] += 1

            training_rows.extend(kept)
            if objective.startswith("rank:"):
                group_sizes.append(int(len(kept)))

    # Final stats
    stats["rows_total"] = len(training_rows)
    stats["rows_pos"] = sum(1 for r in training_rows if int(r.get("label") or 0) == 1)
    stats["rows_neg"] = sum(1 for r in training_rows if int(r.get("label") or 0) == 0)

    if not training_rows:
        print("[train_ltr] ERROR: produced zero training rows", file=sys.stderr)
        return 2

    if args.out_rows_jsonl:
        _write_jsonl(Path(args.out_rows_jsonl), training_rows)

    # Train model (xgboost JSON bytes)
    model_bytes = train_ltr_xgboost_model(
        training_rows=training_rows,
        spec=spec,
        num_boost_round=int(args.num_boost_round or 0),
        seed=int(args.seed or 0),
        objective=objective,
        group_sizes=(group_sizes if objective.startswith("rank:") else None),
    )
    out_model_path = Path(args.out_model)
    out_model_path.parent.mkdir(parents=True, exist_ok=True)
    out_model_path.write_bytes(model_bytes)

    print(
        "[train_ltr] OK"
        f" cases_total={stats['cases_total']}"
        f" cases_used={stats['cases_used']}"
        f" cases_missed={stats['cases_missed']}"
        f" rows_total={stats['rows_total']}"
        f" rows_pos={stats['rows_pos']}"
        f" rows_neg={stats['rows_neg']}"
        f" rows_hard_neg={stats.get('rows_hard_neg', 0)}"
        f" objective={objective}"
        f" spec={getattr(spec, 'schema', '')}"
        f" groups={len(group_sizes) if objective.startswith('rank:') else 0}"
        f" model={out_model_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
