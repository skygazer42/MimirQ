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


import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:  # noqa: BLE001
        raise argparse.ArgumentTypeError("must be a valid UUID") from exc


def _now() -> datetime:
    return datetime.now(UTC)


def _load_json(path: Path) -> Any:
    # PowerShell commonly writes UTF-8 JSON with BOM; `utf-8-sig` handles both BOM/no-BOM.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def coerce_case_bundle(obj: Any) -> tuple[UUID, list[dict[str, Any]]]:
    """
    Normalize a regression case bundle payload into: (dataset_id, items[]).

    Supported shapes:
    - Export bundle v1: {"schema":"mimirq.regression_cases.v1","dataset_id":"...","items":[...]}
    - Minimal bundle: {"dataset_id":"...","items":[...]}
    - Legacy list: [{"dataset_id":"...","question":"...","reference_sources":[...], ...}, ...]
    """
    if isinstance(obj, dict) and isinstance(obj.get("items"), list):
        ds = str(obj.get("dataset_id") or "").strip()
        if ds:
            dsid = UUID(ds)
            items = [x for x in obj.get("items") if isinstance(x, dict)]  # type: ignore[union-attr]
            cleaned = [{k: v for k, v in it.items() if k != "dataset_id"} for it in items]
            return dsid, cleaned
        # Fall back: accept bundles that forgot top-level dataset_id but include it per item.
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
        dsid = UUID(dsids[0])
        cleaned = [{k: v for k, v in it.items() if k != "dataset_id"} for it in items]
        return dsid, cleaned

    raise ValueError("cases file must be a JSON array, or an object with { dataset_id, items: [...] }")


def _normalized_unique_questions(items: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for it in items or []:
        q = str((it or {}).get("question") or "").strip()
        if not q:
            continue
        if q in seen:
            continue
        seen.add(q)
        out.append(q)
    return out


def _resolve_case_ids_from_questions(
    *,
    db: Any,
    tenant_id: UUID,
    dataset_id: UUID,
    questions: list[str],
    case_model: Any,
) -> list[UUID]:
    if not questions:
        return []

    want = set(questions)
    rows = (
        db.query(case_model)
        .filter(case_model.tenant_id == tenant_id, case_model.dataset_id == dataset_id)
        .all()
    )

    by_question: dict[str, UUID] = {}
    duplicates: list[str] = []
    for row in rows or []:
        question = str(getattr(row, "question", "") or "").strip()
        if not question or question not in want:
            continue
        cid = getattr(row, "id", None)
        if cid is None:
            continue
        if question in by_question:
            duplicates.append(question)
            continue
        by_question[question] = UUID(str(cid))

    missing = [q for q in questions if q not in by_question]
    if duplicates:
        dup = ", ".join(sorted(set(duplicates))[:5])
        raise ValueError(f"duplicate regression cases found for question(s): {dup}")
    if missing:
        sample = ", ".join(missing[:5])
        raise ValueError(f"missing regression cases in DB: {len(missing)} (e.g. {sample})")

    return [by_question[q] for q in questions]


def _default_ablations(*, reranker_top_n: int = 20) -> list[dict]:
    """
    Small, industrial default ablation set (retrieval-only friendly).

    Keep this bounded; "continuous nightly" should remain cheap and stable.
    """
    base_rag_params: dict[str, Any] = {
        # Runtime knobs (aligned with scripts/retrieval_ablation.py + app/api/schemas/regression.py).
        "retrieval_profile": None,
        "enable_query_alias_expansion": False,
        "query_alias_max_queries": 0,
        "enable_multi_query": False,
        "multi_query_count": 0,
        "multi_query_temperature": 0.0,
        "multi_query_max_chars": 0,
        "enable_query_rewrite": False,
        "query_rewrite_strategy": None,
        "query_rewrite_temperature": 0.0,
        "query_rewrite_max_chars": 0,
        "sparse_retrieval_enabled": False,
        "sparse_retrieval_provider": "deterministic",
        # Core retrieval controls.
        "top_k": 20,
        "score_threshold": 0.0,
        "retrieval_mode": "hybrid",
        "alpha": 0.6,
        "fusion_strategy": "rrf",
        "fusion_budgets": None,
        "fusion_min_scores": None,
        "fusion_weights": None,
        "enable_weight_rerank": True,
        "vector_weight": 0.6,
        "keyword_weight": 0.4,
        "mmr_lambda": 0.7,
        # Reranker (keep retrieval-only safe by default; no LLM required).
        "enable_reranker": False,
        "reranker_provider": "none",
        "reranker_top_n": 20,
        # Prompt template selection (kept for completeness; usually irrelevant for retrieval-only).
        "prompt_template_id": None,
        "prompt_template_key": None,
        "prompt_ab_experiment_key": None,
    }

    def _ablation(ablation_key: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        rp = dict(base_rag_params)
        if overrides:
            rp.update(overrides)
        return {"ablation_key": str(ablation_key), "rag_params": rp}

    return [
        _ablation("baseline"),
        _ablation("topk50", {"top_k": 50}),
        _ablation("keyword_only", {"top_k": 50, "retrieval_mode": "keyword", "vector_weight": 0.0, "keyword_weight": 1.0}),
        _ablation("vector_only", {"top_k": 50, "retrieval_mode": "vector", "vector_weight": 1.0, "keyword_weight": 0.0}),
        # Retrieval profile ablation: exercises apply_retrieval_profile_overrides (non-LLM).
        _ablation("profile_recall50", {"retrieval_profile": "recall50"}),
        # Fusion strategy ablations (non-LLM).
        _ablation("fusion_linear", {"fusion_strategy": "linear"}),
        _ablation(
            "sparse_budgeted_rrf",
            {
                "fusion_strategy": "budgeted_rrf",
                "fusion_budgets": {"vector": 10, "bm25": 8, "lexical": 0, "sparse": 2},
                "sparse_retrieval_enabled": True,
                "sparse_retrieval_provider": "deterministic",
            },
        ),
        _ablation(
            "sparse_bounded_slice",
            {
                "retrieval_mode": "keyword",
                "fusion_strategy": "budgeted_rrf",
                # Deterministic sparse-heavy bounded slice for nightly regression drift checks.
                "fusion_budgets": {"vector": 0, "bm25": 4, "lexical": 0, "sparse": 4},
                "sparse_retrieval_enabled": True,
                "sparse_retrieval_provider": "deterministic",
            },
        ),
        # Reranker wiring: keep it non-LLM for default nightly safety.
        _ablation(
            "hybrid_rerank",
            {
                "enable_reranker": True,
                "reranker_provider": "pc",
                "reranker_top_n": min(20, int(reranker_top_n or 20)),
            },
        ),
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
        "--cases",
        type=str,
        default="",
        help="Optional regression cases bundle (mimirq.regression_cases.v1) to lock suite deterministically. "
        "Requires cases already imported into DB.",
    )
    p.add_argument(
        "--metrics",
        type=str,
        default="",
        help='Comma-separated metric names. Empty means retrieval-only (default: "").',
    )

    args = p.parse_args(argv)

    from app.core.config import settings
    from app.core.database import SessionLocal
    from app.models.dataset import Dataset
    from app.models.evaluation import RagasRegressionCase, RagasRegressionRun
    from app.rag.evaluation.ragas import run_regression_ragas_evaluation

    tenant_id = args.tenant_id or UUID(str(settings.DEFAULT_TENANT_ID))
    execute = bool(args.execute)
    dry_run = not execute

    metric_names = [m.strip() for m in str(args.metrics or "").split(",") if m.strip()]
    ablations = _default_ablations(reranker_top_n=int(settings.RERANKER_TOP_N or 20))

    cases_path: Path | None = None
    bundle_dataset_id: UUID | None = None
    bundle_questions: list[str] = []
    if str(args.cases or "").strip():
        if bool(args.all_datasets):
            print(json.dumps({"ok": False, "error": "--cases is only supported with --dataset-id"}, ensure_ascii=False))
            return 2
        cases_path = Path(str(args.cases)).expanduser()
        if not cases_path.exists():
            print(json.dumps({"ok": False, "error": f"cases file not found: {cases_path}"}, ensure_ascii=False))
            return 2
        try:
            bundle_dataset_id, items = coerce_case_bundle(_load_json(cases_path))
            bundle_questions = _normalized_unique_questions(items)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": f"invalid cases bundle: {exc}"}, ensure_ascii=False))
            return 2

        if args.dataset_id is not None and bundle_dataset_id != args.dataset_id:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "cases dataset_id mismatch",
                        "expected": str(args.dataset_id),
                        "got": str(bundle_dataset_id),
                    },
                    ensure_ascii=False,
                )
            )
            return 2

        if not bundle_questions:
            print(json.dumps({"ok": False, "error": "cases bundle contains no questions"}, ensure_ascii=False))
            return 2

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
                if cases_path is not None:
                    print(json.dumps({"ok": False, "error": "dataset_not_found", "dataset_id": str(ds_id)}, ensure_ascii=False))
                    return 2
                planned.append({"dataset_id": str(ds_id), "skipped": True, "reason": "dataset_not_found"})
                continue
            owner_id = str(getattr(ds, "owner_id", "") or "").strip()
            if not owner_id:
                if cases_path is not None:
                    print(json.dumps({"ok": False, "error": "dataset_missing_owner_id", "dataset_id": str(ds_id)}, ensure_ascii=False))
                    return 2
                planned.append({"dataset_id": str(ds_id), "skipped": True, "reason": "dataset_missing_owner_id"})
                continue

            explicit_case_ids: list[UUID] = []
            cases_total: int | None = None
            if cases_path is not None:
                try:
                    full_ids = _resolve_case_ids_from_questions(
                        db=db,
                        tenant_id=tenant_id,
                        dataset_id=ds_id,
                        questions=bundle_questions,
                        case_model=RagasRegressionCase,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(
                        json.dumps(
                            {"ok": False, "error": f"cases_resolve_failed: {exc}", "dataset_id": str(ds_id), "cases_file": str(cases_path)},
                            ensure_ascii=False,
                        )
                    )
                    return 2

                cases_total = int(len(full_ids))
                cap = max(1, int(args.max_cases or 0))
                if len(full_ids) > cap:
                    explicit_case_ids = list(full_ids[:cap])
                    print(
                        json.dumps(
                            {
                                "warn": "cases bundle truncated by --max-cases",
                                "dataset_id": str(ds_id),
                                "cases_total": int(len(full_ids)),
                                "cases_used": int(len(explicit_case_ids)),
                                "cases_file": str(cases_path.name),
                            },
                            ensure_ascii=False,
                        )
                    )
                else:
                    explicit_case_ids = list(full_ids)
                if not explicit_case_ids:
                    print(
                        json.dumps(
                            {"ok": False, "error": "cases bundle resolved to empty case_ids", "dataset_id": str(ds_id), "cases_file": str(cases_path)},
                            ensure_ascii=False,
                        )
                    )
                    return 2

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
                            "cases_file": str(cases_path.name) if cases_path is not None else None,
                            "cases_count": int(len(explicit_case_ids)) if cases_path is not None else None,
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
                        "cases_file": str(cases_path.name) if cases_path is not None else None,
                        "cases_total": cases_total,
                        "cases_count": int(len(explicit_case_ids)) if cases_path is not None else None,
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
                    case_ids=list(explicit_case_ids) if explicit_case_ids else [],
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
