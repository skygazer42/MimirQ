#!/usr/bin/env python3
"""
Retention jobs runner (CLI).

This script is intended for automation (cron / Kubernetes CronJob) to run bounded
retention tasks with audit logging.

Currently implemented:
- Audit log retention (bounded purge), per tenant.
- Regression run retention (bounded purge), per tenant.

Examples:
  # Dry-run (plan only) for default tenant
  python scripts/run_retention_jobs.py --audit-logs --dry-run

  # Execute purge for one tenant
  python scripts/run_retention_jobs.py --audit-logs --tenant-id <uuid> --execute --retention-days 90 --max-delete 100000

  # Dry-run (plan only) for regression runs
  python scripts/run_retention_jobs.py --regression-runs --dry-run

  # Execute for all tenants (use with care)
  python scripts/run_retention_jobs.py --audit-logs --all-tenants --execute
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from uuid import UUID

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.services.retention_jobs import (
    run_audit_log_retention,
    run_knowledge_asset_retention,
    run_regression_run_retention,
)


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:  # noqa: BLE001
        raise argparse.ArgumentTypeError("tenant-id must be a valid UUID") from exc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run MimirQ retention jobs (bounded, auditable).")
    p.add_argument("--audit-logs", action="store_true", help="Run audit log retention")
    p.add_argument("--regression-runs", action="store_true", help="Run regression run retention")
    p.add_argument("--knowledge-assets", action="store_true", help="Run archived/disabled knowledge asset retention")

    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--tenant-id", type=_parse_uuid, default=None, help="Tenant UUID to operate on")
    scope.add_argument("--all-tenants", action="store_true", help="Operate on all tenants in the DB")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan only (no deletes). Default.")
    mode.add_argument("--execute", action="store_true", help="Execute deletes (bounded).")

    p.add_argument("--retention-days", type=int, default=90, help="Retention window in days (default: 90)")
    p.add_argument("--max-delete", type=int, default=100_000, help="Max rows to delete per tenant (default: 100000)")
    p.add_argument("--dataset-id", type=_parse_uuid, default=None, help="Optional dataset UUID filter for knowledge assets")
    p.add_argument(
        "--lifecycle-state",
        choices=["archived", "disabled", "either"],
        default="either",
        help="Lifecycle state to purge for knowledge assets (default: either)",
    )

    args = p.parse_args(argv)

    if (not bool(args.audit_logs)) and (not bool(args.regression_runs)) and (not bool(args.knowledge_assets)):
        print("No job selected. Use --audit-logs, --regression-runs, and/or --knowledge-assets.", file=sys.stderr)
        return 2

    dry_run = True
    if bool(args.execute):
        dry_run = False

    # Default tenant: allow running in single-tenant setups without passing args.
    tenant_ids: list[UUID] = []
    if bool(args.all_tenants):
        db = SessionLocal()
        try:
            rows = db.query(Tenant.id).all()
            tenant_ids = [r[0] for r in rows if isinstance(r, tuple) and r and isinstance(r[0], UUID)]
        finally:
            db.close()
    elif args.tenant_id is not None:
        tenant_ids = [args.tenant_id]
    else:
        tenant_ids = [UUID(str(settings.DEFAULT_TENANT_ID))]

    ran_at = datetime.now(timezone.utc)
    results: list[dict] = []

    for tid in tenant_ids:
        db = SessionLocal()
        try:
            if bool(args.audit_logs):
                res = run_audit_log_retention(
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
                res = run_regression_run_retention(
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
                    run_knowledge_asset_retention(
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
        finally:
            db.close()

    print(json.dumps({"ok": True, "ran_at": ran_at.isoformat(), "results": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
