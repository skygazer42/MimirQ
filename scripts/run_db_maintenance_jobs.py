#!/usr/bin/env python3
"""
DB maintenance jobs runner (CLI).

This script is intended for automation (cron / Kubernetes CronJob) to run bounded,
safe DB maintenance operations and existing retention jobs from a single entrypoint.

Supported operations:
- Postgres VACUUM / ANALYZE (optional table allowlist)
- Audit log retention (bounded purge), per tenant
- Regression run retention (bounded purge), per tenant

Examples:
  # Plan (no changes): show maintenance SQL + retention summaries
  python scripts/run_db_maintenance_jobs.py --vacuum --analyze --audit-logs --dry-run

  # Execute: run VACUUM (ANALYZE) + retention for default tenant
  python scripts/run_db_maintenance_jobs.py --vacuum --analyze --audit-logs --execute --retention-days 90

  # Execute for all tenants (use with care)
  python scripts/run_db_maintenance_jobs.py --audit-logs --regression-runs --all-tenants --execute
"""


import argparse
import json
import sys
from datetime import UTC, datetime
from uuid import UUID

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.services.db_maintenance_jobs import run_postgres_maintenance
from app.services.retention_jobs import run_audit_log_retention, run_regression_run_retention


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:  # noqa: BLE001
        raise argparse.ArgumentTypeError("tenant-id must be a valid UUID") from exc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run MimirQ DB maintenance jobs (bounded, idempotent).")

    # Postgres maintenance
    p.add_argument("--vacuum", action="store_true", help="Run Postgres VACUUM")
    p.add_argument("--analyze", action="store_true", help="Run Postgres ANALYZE (or VACUUM ANALYZE when combined)")
    p.add_argument("--verbose", action="store_true", help="Use VERBOSE mode where supported")
    p.add_argument(
        "--table",
        action="append",
        default=[],
        help="Optional table identifier (repeatable). Supports `table` or `schema.table`.",
    )

    # Retention jobs
    p.add_argument("--audit-logs", action="store_true", help="Run audit log retention")
    p.add_argument("--regression-runs", action="store_true", help="Run regression run retention")

    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--tenant-id", type=_parse_uuid, default=None, help="Tenant UUID to operate on (retention)")
    scope.add_argument("--all-tenants", action="store_true", help="Operate on all tenants in the DB (retention)")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan only (no writes). Default.")
    mode.add_argument("--execute", action="store_true", help="Execute changes (VACUUM/retention).")

    p.add_argument("--retention-days", type=int, default=90, help="Retention window in days (default: 90)")
    p.add_argument("--max-delete", type=int, default=100_000, help="Max rows to delete per tenant (default: 100000)")

    args = p.parse_args(argv)

    selected = bool(args.vacuum) or bool(args.analyze) or bool(args.audit_logs) or bool(args.regression_runs)
    if not selected:
        print(
            "No job selected. Use --vacuum/--analyze and/or --audit-logs/--regression-runs.",
            file=sys.stderr,
        )
        return 2

    dry_run = True
    if bool(args.execute):
        dry_run = False

    ran_at = datetime.now(UTC)
    results: list[dict] = []
    ok = True

    # 1) Postgres maintenance (global, not per-tenant)
    if bool(args.vacuum) or bool(args.analyze):
        try:
            res = run_postgres_maintenance(
                vacuum=bool(args.vacuum),
                analyze=bool(args.analyze),
                verbose=bool(args.verbose),
                tables=[t for t in (args.table or []) if str(t or "").strip()],
                dry_run=bool(dry_run),
                now=ran_at,
            )
            res["job"] = "postgres_maintenance"
            results.append(res)
            ok = ok and bool(res.get("ok") is True)
        except Exception as exc:  # noqa: BLE001
            results.append({"job": "postgres_maintenance", "ok": False, "error": str(type(exc).__name__), "detail": str(exc)[:200]})
            ok = False

    # 2) Retention jobs (per-tenant)
    if bool(args.audit_logs) or bool(args.regression_runs):
        tenant_ids: list[UUID] = []
        if bool(args.all_tenants):
            db = SessionLocal()
            try:
                rows = db.query(Tenant.id).all()
                tenant_ids = [r[0] for r in rows if isinstance(r, tuple) and r and isinstance(r[0], UUID)]
            except Exception as exc:  # noqa: BLE001
                results.append({"job": "tenant_list", "ok": False, "error": str(type(exc).__name__), "detail": str(exc)[:200]})
                ok = False
                tenant_ids = []
            finally:
                db.close()
        elif args.tenant_id is not None:
            tenant_ids = [args.tenant_id]
        else:
            tenant_ids = [UUID(str(settings.DEFAULT_TENANT_ID))]

        for tid in tenant_ids:
            db = SessionLocal()
            try:
                if bool(args.audit_logs):
                    try:
                        res = run_audit_log_retention(
                            db,
                            tenant_id=tid,
                            retention_days=int(args.retention_days or 0),
                            max_delete=int(args.max_delete or 0),
                            dry_run=bool(dry_run),
                            actor_id="system:db_maintenance",
                            now=ran_at,
                        )
                        results.append({"job": "audit_logs_retention", "ok": True, **res})
                    except Exception as exc:  # noqa: BLE001
                        results.append(
                            {
                                "job": "audit_logs_retention",
                                "tenant_id": str(tid),
                                "ok": False,
                                "error": str(type(exc).__name__),
                                "detail": str(exc)[:200],
                            }
                        )
                        ok = False
                if bool(args.regression_runs):
                    try:
                        res = run_regression_run_retention(
                            db,
                            tenant_id=tid,
                            retention_days=int(args.retention_days or 0),
                            max_delete=int(args.max_delete or 0),
                            dry_run=bool(dry_run),
                            actor_id="system:db_maintenance",
                            now=ran_at,
                        )
                        results.append({"job": "regression_runs_retention", "ok": True, **res})
                    except Exception as exc:  # noqa: BLE001
                        results.append(
                            {
                                "job": "regression_runs_retention",
                                "tenant_id": str(tid),
                                "ok": False,
                                "error": str(type(exc).__name__),
                                "detail": str(exc)[:200],
                            }
                        )
                        ok = False
            finally:
                db.close()

    print(json.dumps({"ok": bool(ok), "ran_at": ran_at.isoformat(), "results": results}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
