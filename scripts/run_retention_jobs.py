#!/usr/bin/env python3
"""
Retention jobs runner (CLI).

This script is intended for automation (cron / Kubernetes CronJob) to run bounded
retention tasks with audit logging.

Currently implemented:
- Audit log retention (bounded purge), per tenant.
- Regression run retention (bounded purge), per tenant.
- Dataset document retention sweep (bounded), per tenant.
- Semantic cache retention (bounded Milvus/Redis sweep), per tenant.

Examples:
  # Dry-run (plan only) for default tenant
  python scripts/run_retention_jobs.py --audit-logs --dry-run

  # Execute purge for one tenant
  python scripts/run_retention_jobs.py --audit-logs --tenant-id <uuid> --execute --retention-days 90 --max-delete 100000

  # Dry-run (plan only) for regression runs
  python scripts/run_retention_jobs.py --regression-runs --dry-run

  # Dry-run dataset retention sweeps (Gap9) for datasets with enabled policy
  python scripts/run_retention_jobs.py --dataset-retention --dry-run

  # Execute dataset retention for one dataset (bounded)
  python scripts/run_retention_jobs.py --dataset-retention --dataset-id <uuid> --execute --max-documents 200

  # Execute for all tenants (use with care)
  python scripts/run_retention_jobs.py --audit-logs --all-tenants --execute
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:  # noqa: BLE001
        raise argparse.ArgumentTypeError("tenant-id must be a valid UUID") from exc


def _load_runtime_dependencies() -> SimpleNamespace:
    from app.core.config import settings
    from app.core.database import SessionLocal
    from app.models.dataset import Dataset
    from app.models.tenant import Tenant
    from app.services.retention_jobs import (
        run_audit_log_retention,
        run_knowledge_asset_retention,
        run_regression_run_retention,
    )
    from app.services.retention_policy import parse_retention_policy_from_metadata, run_dataset_retention_sweep
    from app.services.semantic_cache import run_semantic_cache_retention

    return SimpleNamespace(
        settings=settings,
        SessionLocal=SessionLocal,
        Dataset=Dataset,
        Tenant=Tenant,
        run_audit_log_retention=run_audit_log_retention,
        run_knowledge_asset_retention=run_knowledge_asset_retention,
        run_regression_run_retention=run_regression_run_retention,
        parse_retention_policy_from_metadata=parse_retention_policy_from_metadata,
        run_dataset_retention_sweep=run_dataset_retention_sweep,
        run_semantic_cache_retention=run_semantic_cache_retention,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run MimirQ retention jobs (bounded, auditable).")
    p.add_argument("--audit-logs", action="store_true", help="Run audit log retention")
    p.add_argument("--regression-runs", action="store_true", help="Run regression run retention")
    p.add_argument("--knowledge-assets", action="store_true", help="Run archived/disabled knowledge asset retention")
    p.add_argument(
        "--dataset-retention", action="store_true", help="Run dataset-level document retention sweeps (Gap9)"
    )
    p.add_argument("--semantic-cache", action="store_true", help="Run semantic cache retention")

    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--tenant-id", type=_parse_uuid, default=None, help="Tenant UUID to operate on")
    scope.add_argument("--all-tenants", action="store_true", help="Operate on all tenants in the DB")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan only (no deletes). Default.")
    mode.add_argument("--execute", action="store_true", help="Execute deletes (bounded).")

    p.add_argument("--retention-days", type=int, default=90, help="Retention window in days (default: 90)")
    p.add_argument("--max-delete", type=int, default=100_000, help="Max rows to delete per tenant (default: 100000)")
    p.add_argument(
        "--max-scan", type=int, default=1000, help="Max semantic-cache rows to scan per tenant (default: 1000)"
    )
    p.add_argument(
        "--dataset-id", type=_parse_uuid, default=None, help="Optional dataset UUID filter for dataset/knowledge assets"
    )
    p.add_argument(
        "--lifecycle-state",
        choices=["archived", "disabled", "either"],
        default="either",
        help="Lifecycle state to purge for knowledge assets (default: either)",
    )
    p.add_argument(
        "--max-documents", type=int, default=200, help="Max documents to process per dataset sweep (default: 200)"
    )
    p.add_argument(
        "--max-versions-pruned",
        type=int,
        default=0,
        help="Max pipeline versions to prune per dataset sweep (default: 0, disabled)",
    )

    args = p.parse_args(argv)

    if (
        (not bool(args.audit_logs))
        and (not bool(args.regression_runs))
        and (not bool(args.knowledge_assets))
        and (not bool(args.dataset_retention))
        and (not bool(args.semantic_cache))
    ):
        print(
            "No job selected. Use --audit-logs, --regression-runs, --knowledge-assets, --dataset-retention, and/or --semantic-cache.",
            file=sys.stderr,
        )
        return 2

    deps = _load_runtime_dependencies()
    dry_run = True
    if bool(args.execute):
        dry_run = False

    # Default tenant: allow running in single-tenant setups without passing args.
    tenant_ids: list[UUID] = []
    if bool(args.all_tenants):
        db = deps.SessionLocal()
        try:
            rows = db.query(deps.Tenant.id).all()
            for row in rows:
                candidate = getattr(row, "id", None)
                if candidate is None:
                    try:
                        candidate = row[0]
                    except (IndexError, KeyError, TypeError):
                        continue
                if isinstance(candidate, UUID):
                    tenant_ids.append(candidate)
        finally:
            db.close()
    elif args.tenant_id is not None:
        tenant_ids = [args.tenant_id]
    else:
        tenant_ids = [UUID(str(deps.settings.DEFAULT_TENANT_ID))]

    ran_at = datetime.now(UTC)
    results: list[dict] = []

    for tid in tenant_ids:
        if bool(args.semantic_cache):
            results.append(
                deps.run_semantic_cache_retention(
                    tenant_id=tid,
                    dry_run=bool(dry_run),
                    max_delete=int(args.max_delete or 0),
                    max_scan=int(args.max_scan or 0),
                )
            )

        if not (
            bool(args.audit_logs)
            or bool(args.regression_runs)
            or bool(args.knowledge_assets)
            or bool(args.dataset_retention)
        ):
            continue

        db = deps.SessionLocal()
        try:
            if bool(args.audit_logs):
                res = deps.run_audit_log_retention(
                    db,
                    tenant_id=tid,
                    retention_days=int(args.retention_days or 0),
                    max_delete=int(args.max_delete or 0),
                    dry_run=bool(dry_run),
                    actor_id="system:retention",
                    now=ran_at,
                )
                results.append(res)
            if bool(args.regression_runs):
                res = deps.run_regression_run_retention(
                    db,
                    tenant_id=tid,
                    retention_days=int(args.retention_days or 0),
                    max_delete=int(args.max_delete or 0),
                    dry_run=bool(dry_run),
                    actor_id="system:retention",
                    now=ran_at,
                )
                results.append(res)
            if bool(args.knowledge_assets):
                res = asyncio.run(
                    deps.run_knowledge_asset_retention(
                        db,
                        tenant_id=tid,
                        retention_days=int(args.retention_days or 0),
                        max_delete=int(args.max_delete or 0),
                        dry_run=bool(dry_run),
                        dataset_id=args.dataset_id,
                        lifecycle_state=str(args.lifecycle_state or "either"),
                        actor_id="system:retention",
                        now=ran_at,
                    )
                )
                results.append(res)
            if bool(args.dataset_retention):
                ds_query = db.query(deps.Dataset.id, deps.Dataset.dataset_metadata).filter(
                    deps.Dataset.tenant_id == tid
                )
                if args.dataset_id is not None:
                    ds_query = ds_query.filter(deps.Dataset.id == args.dataset_id)
                ds_rows = ds_query.order_by(deps.Dataset.created_at.asc()).all()

                for dsid, meta in ds_rows:
                    meta_dict = meta if isinstance(meta, dict) else {}
                    policy = deps.parse_retention_policy_from_metadata(meta_dict)
                    if policy is None or not bool(getattr(policy, "enabled", False)):
                        continue
                    res = asyncio.run(
                        deps.run_dataset_retention_sweep(
                            db,
                            tenant_id=tid,
                            dataset_id=dsid,
                            policy=policy,
                            dry_run=bool(dry_run),
                            max_documents=int(args.max_documents or 0),
                            max_versions_pruned=int(args.max_versions_pruned or 0),
                            actor_id="system:retention",
                            now=ran_at,
                        )
                    )
                    results.append(res)
        finally:
            db.close()

    failed = any(bool(item.get("failed")) for item in results if isinstance(item, dict))
    print(json.dumps({"ok": not failed, "ran_at": ran_at.isoformat(), "results": results}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
