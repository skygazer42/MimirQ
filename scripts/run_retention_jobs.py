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
from typing import Any
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


def _build_parser() -> argparse.ArgumentParser:
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
    return p


def _job_selected(args: argparse.Namespace) -> bool:
    return any(
        bool(value)
        for value in (
            args.audit_logs,
            args.regression_runs,
            args.knowledge_assets,
            args.dataset_retention,
            args.semantic_cache,
        )
    )


def _tenant_ids(args: argparse.Namespace, deps: SimpleNamespace) -> list[UUID]:
    if bool(args.all_tenants):
        tenant_ids: list[UUID] = []
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
        return tenant_ids
    if args.tenant_id is not None:
        return [args.tenant_id]
    return [UUID(str(deps.settings.DEFAULT_TENANT_ID))]


def _db_job_selected(args: argparse.Namespace) -> bool:
    return any(
        bool(value)
        for value in (
            args.audit_logs,
            args.regression_runs,
            args.knowledge_assets,
            args.dataset_retention,
        )
    )


def _run_semantic_cache_job(
    args: argparse.Namespace,
    deps: SimpleNamespace,
    *,
    tenant_id: UUID,
    dry_run: bool,
) -> dict[str, Any]:
    return deps.run_semantic_cache_retention(
        tenant_id=tenant_id,
        dry_run=dry_run,
        max_delete=int(args.max_delete or 0),
        max_scan=int(args.max_scan or 0),
    )


def _run_dataset_jobs(
    args: argparse.Namespace,
    deps: SimpleNamespace,
    db: Any,
    *,
    tenant_id: UUID,
    dry_run: bool,
    ran_at: datetime,
) -> list[dict[str, Any]]:
    query = db.query(deps.Dataset.id, deps.Dataset.dataset_metadata).filter(deps.Dataset.tenant_id == tenant_id)
    if args.dataset_id is not None:
        query = query.filter(deps.Dataset.id == args.dataset_id)
    rows = query.order_by(deps.Dataset.created_at.asc()).all()
    results: list[dict[str, Any]] = []
    for dataset_id, metadata in rows:
        policy = deps.parse_retention_policy_from_metadata(metadata if isinstance(metadata, dict) else {})
        if policy is None or not bool(getattr(policy, "enabled", False)):
            continue
        result = asyncio.run(
            deps.run_dataset_retention_sweep(
                db,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                policy=policy,
                dry_run=dry_run,
                max_documents=int(args.max_documents or 0),
                max_versions_pruned=int(args.max_versions_pruned or 0),
                actor_id="system:retention",
                now=ran_at,
            )
        )
        results.append(result)
    return results


def _run_db_jobs(
    args: argparse.Namespace,
    deps: SimpleNamespace,
    db: Any,
    *,
    tenant_id: UUID,
    dry_run: bool,
    ran_at: datetime,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    common = {
        "tenant_id": tenant_id,
        "retention_days": int(args.retention_days or 0),
        "max_delete": int(args.max_delete or 0),
        "dry_run": dry_run,
        "actor_id": "system:retention",
        "now": ran_at,
    }
    if bool(args.audit_logs):
        results.append(deps.run_audit_log_retention(db, **common))
    if bool(args.regression_runs):
        results.append(deps.run_regression_run_retention(db, **common))
    if bool(args.knowledge_assets):
        results.append(
            asyncio.run(
                deps.run_knowledge_asset_retention(
                    db,
                    **common,
                    dataset_id=args.dataset_id,
                    lifecycle_state=str(args.lifecycle_state or "either"),
                )
            )
        )
    if bool(args.dataset_retention):
        results.extend(
            _run_dataset_jobs(
                args,
                deps,
                db,
                tenant_id=tenant_id,
                dry_run=dry_run,
                ran_at=ran_at,
            )
        )
    return results


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if not _job_selected(args):
        print(
            "No job selected. Use --audit-logs, --regression-runs, "
            "--knowledge-assets, --dataset-retention, and/or --semantic-cache.",
            file=sys.stderr,
        )
        return 2

    deps = _load_runtime_dependencies()
    dry_run = not bool(args.execute)
    tenant_ids = _tenant_ids(args, deps)
    ran_at = datetime.now(UTC)
    results: list[dict[str, Any]] = []

    for tenant_id in tenant_ids:
        if bool(args.semantic_cache):
            results.append(
                _run_semantic_cache_job(
                    args,
                    deps,
                    tenant_id=tenant_id,
                    dry_run=dry_run,
                )
            )
        if not _db_job_selected(args):
            continue

        db = deps.SessionLocal()
        try:
            results.extend(
                _run_db_jobs(
                    args,
                    deps,
                    db,
                    tenant_id=tenant_id,
                    dry_run=dry_run,
                    ran_at=ran_at,
                )
            )
        finally:
            db.close()

    failed = any(bool(item.get("failed")) for item in results if isinstance(item, dict))
    print(json.dumps({"ok": not failed, "ran_at": ran_at.isoformat(), "results": results}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
