#!/usr/bin/env python3
"""
Retention jobs runner (CLI).

This script is intended for automation (cron / Kubernetes CronJob) to run bounded
retention tasks with audit logging.

Currently implemented:
- Audit log retention (bounded purge), per tenant.

Examples:
  # Dry-run (plan only) for default tenant
  python scripts/run_retention_jobs.py --audit-logs --dry-run

  # Execute purge for one tenant
  python scripts/run_retention_jobs.py --audit-logs --tenant-id <uuid> --execute --retention-days 90 --max-delete 100000

  # Execute for all tenants (use with care)
  python scripts/run_retention_jobs.py --audit-logs --all-tenants --execute
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from uuid import UUID

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.services.retention_jobs import run_audit_log_retention


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:  # noqa: BLE001
        raise argparse.ArgumentTypeError("tenant-id must be a valid UUID") from exc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run MimirQ retention jobs (bounded, auditable).")
    p.add_argument("--audit-logs", action="store_true", help="Run audit log retention")

    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--tenant-id", type=_parse_uuid, default=None, help="Tenant UUID to operate on")
    scope.add_argument("--all-tenants", action="store_true", help="Operate on all tenants in the DB")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan only (no deletes). Default.")
    mode.add_argument("--execute", action="store_true", help="Execute deletes (bounded).")

    p.add_argument("--retention-days", type=int, default=90, help="Retention window in days (default: 90)")
    p.add_argument("--max-delete", type=int, default=100_000, help="Max rows to delete per tenant (default: 100000)")

    args = p.parse_args(argv)

    if not bool(args.audit_logs):
        print("No job selected. Use --audit-logs.", file=sys.stderr)
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
        tenant_ids = [UUID(str(getattr(settings, "DEFAULT_TENANT_ID")))]

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
        finally:
            db.close()

    print(json.dumps({"ok": True, "ran_at": ran_at.isoformat(), "results": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

