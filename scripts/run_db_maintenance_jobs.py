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
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


def _build_parser() -> argparse.ArgumentParser:
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
    return p


def _job_error(job: str, exc: Exception, *, tenant_id: UUID | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"job": job}
    if tenant_id is not None:
        result["tenant_id"] = str(tenant_id)
    result.update(
        {
            "ok": False,
            "error": str(type(exc).__name__),
            "detail": str(exc)[:200],
        }
    )
    return result


def _run_postgres_job(
    args: argparse.Namespace,
    *,
    dry_run: bool,
    ran_at: datetime,
    results: list[dict[str, Any]],
) -> bool:
    try:
        result = run_postgres_maintenance(
            vacuum=bool(args.vacuum),
            analyze=bool(args.analyze),
            verbose=bool(args.verbose),
            tables=[table for table in (args.table or []) if str(table or "").strip()],
            dry_run=dry_run,
            now=ran_at,
        )
        result["job"] = "postgres_maintenance"
        results.append(result)
        return bool(result.get("ok") is True)
    except Exception as exc:  # noqa: BLE001
        results.append(_job_error("postgres_maintenance", exc))
        return False


def _tenant_ids(args: argparse.Namespace, results: list[dict[str, Any]]) -> tuple[list[UUID], bool]:
    if bool(args.all_tenants):
        db = SessionLocal()
        try:
            rows = db.query(Tenant.id).all()
            tenant_ids = [row[0] for row in rows if isinstance(row, tuple) and row and isinstance(row[0], UUID)]
            return tenant_ids, True
        except Exception as exc:  # noqa: BLE001
            results.append(_job_error("tenant_list", exc))
            return [], False
        finally:
            db.close()
    if args.tenant_id is not None:
        return [args.tenant_id], True
    return [UUID(str(settings.DEFAULT_TENANT_ID))], True


def _run_retention_job(
    runner: Callable[..., dict[str, Any]],
    job: str,
    db: Any,
    tenant_id: UUID,
    args: argparse.Namespace,
    *,
    dry_run: bool,
    ran_at: datetime,
    results: list[dict[str, Any]],
) -> bool:
    try:
        result = runner(
            db,
            tenant_id=tenant_id,
            retention_days=int(args.retention_days or 0),
            max_delete=int(args.max_delete or 0),
            dry_run=dry_run,
            actor_id="system:db_maintenance",
            now=ran_at,
        )
        results.append({"job": job, "ok": True, **result})
        return True
    except Exception as exc:  # noqa: BLE001
        results.append(_job_error(job, exc, tenant_id=tenant_id))
        return False


def _run_retention_jobs(
    args: argparse.Namespace,
    *,
    dry_run: bool,
    ran_at: datetime,
    results: list[dict[str, Any]],
) -> bool:
    tenant_ids, ok = _tenant_ids(args, results)
    for tenant_id in tenant_ids:
        db = SessionLocal()
        try:
            if bool(args.audit_logs):
                job_ok = _run_retention_job(
                    run_audit_log_retention,
                    "audit_logs_retention",
                    db,
                    tenant_id,
                    args,
                    dry_run=dry_run,
                    ran_at=ran_at,
                    results=results,
                )
                ok = job_ok and ok
            if bool(args.regression_runs):
                job_ok = _run_retention_job(
                    run_regression_run_retention,
                    "regression_runs_retention",
                    db,
                    tenant_id,
                    args,
                    dry_run=dry_run,
                    ran_at=ran_at,
                    results=results,
                )
                ok = job_ok and ok
        finally:
            db.close()
    return ok


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    selected = bool(args.vacuum) or bool(args.analyze) or bool(args.audit_logs) or bool(args.regression_runs)
    if not selected:
        print(
            "No job selected. Use --vacuum/--analyze and/or --audit-logs/--regression-runs.",
            file=sys.stderr,
        )
        return 2

    dry_run = not bool(args.execute)
    ran_at = datetime.now(UTC)
    results: list[dict[str, Any]] = []
    ok = True

    if bool(args.vacuum) or bool(args.analyze):
        ok = _run_postgres_job(args, dry_run=dry_run, ran_at=ran_at, results=results) and ok
    if bool(args.audit_logs) or bool(args.regression_runs):
        ok = _run_retention_jobs(args, dry_run=dry_run, ran_at=ran_at, results=results) and ok

    print(json.dumps({"ok": bool(ok), "ran_at": ran_at.isoformat(), "results": results}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
