#!/usr/bin/env python3
"""
Nightly ablation runner (CLI).

Wave21-T083: Continuous ablation runner nightly (scheduled).

This script is intended for automation (cron / Kubernetes CronJob). It creates
regression runs with predefined retrieval configs ("ablations") and executes
them synchronously by calling `run_regression_ragas_evaluation`.

Principles:
- Bounded by default (max_datasets, max_cases, small ablation set)
- Default to retrieval-only mode (no RAGAS, no LLM) unless metrics are provided
- Auditable: each run.params includes `nightly: true` and `ablation_key`

Examples:
  # Dry-run (plan only) for one dataset
  python scripts/run_nightly_ablations.py --dataset-id <uuid> --dry-run

  # Execute for one dataset (retrieval-only)
  python scripts/run_nightly_ablations.py --dataset-id <uuid> --execute

  # Execute for all datasets under one tenant (bounded)
  python scripts/run_nightly_ablations.py --all-datasets --execute --max-datasets 10
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from uuid import UUID

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.dataset import Dataset
from app.models.evaluation import RagasRegressionRun
from app.rag.evaluation.ragas import run_regression_ragas_evaluation


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:  # noqa: BLE001
        raise argparse.ArgumentTypeError("must be a valid UUID") from exc


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _default_ablations() -> list[dict]:
    """
    Small, industrial default ablation set (retrieval-only friendly).

    Keep this bounded; "continuous nightly" should remain cheap and stable.
    """
    return [
        {
            "ablation_key": "baseline",
            "rag_params": {
                "top_k": 20,
                "score_threshold": 0.0,
                "retrieval_mode": "hybrid",
                "alpha": 0.6,
                "enable_weight_rerank": True,
                "vector_weight": 0.6,
                "keyword_weight": 0.4,
                "mmr_lambda": 0.7,
                "enable_reranker": False,
                "reranker_provider": "llm",
                "reranker_top_n": 20,
                "prompt_template_id": None,
                "prompt_template_key": None,
                "prompt_ab_experiment_key": None,
            },
        },
        {
            "ablation_key": "topk50",
            "rag_params": {
                "top_k": 50,
                "score_threshold": 0.0,
                "retrieval_mode": "hybrid",
                "alpha": 0.6,
                "enable_weight_rerank": True,
                "vector_weight": 0.6,
                "keyword_weight": 0.4,
                "mmr_lambda": 0.7,
                "enable_reranker": False,
                "reranker_provider": "llm",
                "reranker_top_n": 50,
                "prompt_template_id": None,
                "prompt_template_key": None,
                "prompt_ab_experiment_key": None,
            },
        },
        {
            "ablation_key": "keyword_only",
            "rag_params": {
                "top_k": 50,
                "score_threshold": 0.0,
                "retrieval_mode": "keyword",
                "alpha": 0.6,
                "enable_weight_rerank": True,
                "vector_weight": 0.0,
                "keyword_weight": 1.0,
                "mmr_lambda": 0.7,
                "enable_reranker": False,
                "reranker_provider": "llm",
                "reranker_top_n": 50,
                "prompt_template_id": None,
                "prompt_template_key": None,
                "prompt_ab_experiment_key": None,
            },
        },
        {
            "ablation_key": "vector_only",
            "rag_params": {
                "top_k": 50,
                "score_threshold": 0.0,
                "retrieval_mode": "vector",
                "alpha": 0.6,
                "enable_weight_rerank": True,
                "vector_weight": 1.0,
                "keyword_weight": 0.0,
                "mmr_lambda": 0.7,
                "enable_reranker": False,
                "reranker_provider": "llm",
                "reranker_top_n": 50,
                "prompt_template_id": None,
                "prompt_template_key": None,
                "prompt_ab_experiment_key": None,
            },
        },
    ]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run nightly retrieval ablations (create regression runs + execute).")
    p.add_argument("--tenant-id", type=_parse_uuid, default=None, help="Tenant UUID (default: settings.DEFAULT_TENANT_ID)")

    scope = p.add_mutually_exclusive_group(required=True)
    scope.add_argument("--dataset-id", type=_parse_uuid, default=None, help="Dataset UUID to run")
    scope.add_argument("--all-datasets", action="store_true", help="Run for all datasets under the tenant (bounded)")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan only (no DB writes). Default.")
    mode.add_argument("--execute", action="store_true", help="Execute runs (creates DB rows + runs evaluation)")

    p.add_argument("--max-datasets", type=int, default=10, help="Max datasets when using --all-datasets (default: 10)")
    p.add_argument("--max-cases", type=int, default=50, help="Max regression cases per run (default: 50)")
    p.add_argument("--skip-empty-contexts", action="store_true", default=True, help="Skip cases with empty contexts")
    p.add_argument(
        "--metrics",
        type=str,
        default="",
        help='Comma-separated metric names. Empty means retrieval-only (default: "").',
    )

    args = p.parse_args(argv)

    tenant_id = args.tenant_id or UUID(str(settings.DEFAULT_TENANT_ID))
    execute = bool(args.execute)
    dry_run = not execute

    metric_names = [m.strip() for m in str(args.metrics or "").split(",") if m.strip()]
    ablations = _default_ablations()

    ds_ids: list[UUID] = []
    if args.dataset_id is not None:
        ds_ids = [args.dataset_id]
    elif bool(args.all_datasets):
        db = SessionLocal()
        try:
            q = db.query(Dataset.id).filter(Dataset.tenant_id == tenant_id).order_by(Dataset.created_at.asc())
            limit = max(1, int(args.max_datasets or 0))
            q = q.limit(limit)
            rows = q.all()
            ds_ids = [r[0] for r in rows if isinstance(r, tuple) and r and isinstance(r[0], UUID)]
        finally:
            db.close()

    if not ds_ids:
        print(json.dumps({"ok": False, "error": "No datasets found"}, ensure_ascii=False))
        return 2

    job_run_id = _now().strftime("%Y%m%dT%H%M%SZ")
    planned: list[dict] = []
    executed: list[dict] = []

    for ds_id in ds_ids:
        # Load dataset to pick an actor id for ACL-safe evaluation.
        db = SessionLocal()
        try:
            ds = db.query(Dataset).filter(Dataset.tenant_id == tenant_id, Dataset.id == ds_id).first()
            if ds is None:
                planned.append({"dataset_id": str(ds_id), "skipped": True, "reason": "dataset_not_found"})
                continue
            owner_id = str(getattr(ds, "owner_id", "") or "").strip()
            if not owner_id:
                planned.append({"dataset_id": str(ds_id), "skipped": True, "reason": "dataset_missing_owner_id"})
                continue

            for ab in ablations:
                key = str(ab.get("ablation_key") or "").strip() or "ablation"
                rag_params = dict(ab.get("rag_params") or {})
                if dry_run:
                    planned.append(
                        {
                            "dataset_id": str(ds_id),
                            "account_id": owner_id,
                            "ablation_key": key,
                            "metrics": metric_names,
                            "max_cases": int(args.max_cases or 0),
                            "rag_params": rag_params,
                        }
                    )
                    continue

                run = RagasRegressionRun(
                    tenant_id=tenant_id,
                    account_id=owner_id,
                    dataset_id=ds_id,
                    status="pending",
                    metrics=list(metric_names),
                    params={
                        "nightly": True,
                        "job_run_id": job_run_id,
                        "ablation_key": key,
                        "requested_metrics": list(metric_names),
                        "skip_empty_contexts": bool(args.skip_empty_contexts),
                        "max_cases": int(args.max_cases or 0),
                        "rag_params": rag_params,
                    },
                )
                db.add(run)
                db.commit()
                db.refresh(run)

                # Execute synchronously so the cron job has deterministic completion semantics.
                run_regression_ragas_evaluation(
                    run_id=run.id,
                    tenant_id=tenant_id,
                    account_id=owner_id,
                    case_ids=[],
                    dataset_id=ds_id,
                    metric_names=list(metric_names),
                    skip_empty_contexts=bool(args.skip_empty_contexts),
                    max_cases=max(1, int(args.max_cases or 0)),
                    rag_params=rag_params,
                )
                executed.append(
                    {
                        "dataset_id": str(ds_id),
                        "account_id": owner_id,
                        "ablation_key": key,
                        "run_id": str(run.id),
                    }
                )
        finally:
            db.close()

    print(
        json.dumps(
            {
                "ok": True,
                "tenant_id": str(tenant_id),
                "job_run_id": job_run_id,
                "dry_run": bool(dry_run),
                "planned": planned,
                "executed": executed,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
