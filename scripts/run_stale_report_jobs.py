#!/usr/bin/env python3
"""
Daily stale report runner (CLI).

This script is intended for automation (cron / Kubernetes CronJob) to generate a bounded,
PII-safe stale summary for connector-created documents and (optionally) write the result
to audit logs.

Examples:
  # Dry-run (no audit write) for default tenant
  python scripts/run_stale_report_jobs.py --dry-run

  # Execute and write audit event for one tenant
  python scripts/run_stale_report_jobs.py --tenant-id <uuid> --execute --stale-after-days 30 --max-documents 5000

  # Execute for all tenants (use with care)
  python scripts/run_stale_report_jobs.py --all-tenants --execute
"""

import argparse
import json
from datetime import UTC, datetime
from uuid import UUID

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.services.stale_report_jobs import run_daily_stale_report


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:  # noqa: BLE001
        raise argparse.ArgumentTypeError("tenant-id must be a valid UUID") from exc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run MimirQ stale report job (bounded, auditable).")

    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--tenant-id", type=_parse_uuid, default=None, help="Tenant UUID to operate on")
    scope.add_argument("--all-tenants", action="store_true", help="Operate on all tenants in the DB")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Compute report only (no audit write). Default.")
    mode.add_argument("--execute", action="store_true", help="Write audit log entry (best-effort).")

    p.add_argument("--stale-after-days", type=int, default=30, help="Mark stale when older than N days (default: 30)")
    p.add_argument(
        "--max-documents", type=int, default=5000, help="Max connector documents scanned per tenant (default: 5000)"
    )
    p.add_argument("--force", action="store_true", help="Write audit even if today's report already exists.")

    args = p.parse_args(argv)

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

    ran_at = datetime.now(UTC)
    results: list[dict] = []
    ok = True

    for tid in tenant_ids:
        db = SessionLocal()
        try:
            res = run_daily_stale_report(
                db,
                tenant_id=tid,
                stale_after_days=int(args.stale_after_days or 0),
                max_documents=int(args.max_documents or 0),
                execute=bool(args.execute),
                force=bool(args.force),
                actor_id="system:stale_report",
                now=ran_at,
            )
            results.append(res)
            ok = ok and bool(res.get("ok") is True)
        finally:
            db.close()

    print(json.dumps({"ok": bool(ok), "ran_at": ran_at.isoformat(), "results": results}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
