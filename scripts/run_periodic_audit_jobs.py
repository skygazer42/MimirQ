#!/usr/bin/env python3
"""
Periodic audit jobs runner (CLI).

This script is intended for automation (cron / Kubernetes CronJob) to run bounded,
PII-safe periodic audits and (optionally) write a small summary to audit logs.

Currently implemented:
- Index audit summary (dataset-scoped, bounded)
- Evidence reference drift audit summary (dataset-scoped, bounded)
- Access review summary (tenant-scoped, bounded)
- Embedding drift snapshot summary (tenant-scoped, bounded)

Examples:
  # Dry-run (no audit write) for default tenant
  python scripts/run_periodic_audit_jobs.py --index-audit --dry-run

  # Execute and write audit events for one tenant
  python scripts/run_periodic_audit_jobs.py --index-audit --evidence-drift-audit --tenant-id <uuid> --execute --max-datasets 50

  # Execute for all tenants (use with care)
  python scripts/run_periodic_audit_jobs.py --index-audit --all-tenants --execute --force
"""


import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.services.periodic_audit_jobs import (
    run_daily_access_review_summary,
    run_daily_embedding_drift_report,
    run_daily_evidence_drift_audit_report,
    run_daily_index_audit_report,
)


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:  # noqa: BLE001
        raise argparse.ArgumentTypeError("tenant-id must be a valid UUID") from exc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run MimirQ periodic audit jobs (bounded, auditable).")
    p.add_argument("--index-audit", action="store_true", help="Run dataset index-audit report")
    p.add_argument("--evidence-drift-audit", action="store_true", help="Run evidence reference drift-audit report")
    p.add_argument("--access-review", action="store_true", help="Run daily access review summary (tenant-scoped)")
    p.add_argument("--embedding-drift", action="store_true", help="Run embedding drift snapshot report (tenant-scoped)")

    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--tenant-id", type=_parse_uuid, default=None, help="Tenant UUID to operate on")
    scope.add_argument("--all-tenants", action="store_true", help="Operate on all tenants in the DB")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Compute summary only (no audit write). Default.")
    mode.add_argument("--execute", action="store_true", help="Write audit log entry (best-effort).")

    p.add_argument("--max-datasets", type=int, default=50, help="Max datasets scanned per tenant (default: 50)")

    # Index-audit bounds.
    p.add_argument("--max-check-ids", type=int, default=5000, help="Max DB vector_ids to existence-check (default: 5000)")
    p.add_argument("--milvus-list-limit", type=int, default=2000, help="Max Milvus ids to sample for orphans (default: 2000)")
    p.add_argument("--sample-limit", type=int, default=20, help="Max sample ids to return per dataset (default: 20)")

    # Drift-audit bounds.
    p.add_argument("--include-archived-items", action="store_true", help="Include archived EvidenceItems in drift audit")
    p.add_argument("--include-details", action="store_true", help="Include bounded per-ref drift details (still PII-safe)")
    p.add_argument("--details-limit", type=int, default=0, help="Max drifted references returned when include-details (default: 0)")
    p.add_argument("--slice-top-n", type=int, default=20, help="Max buckets per slice (default: 20)")

    # Embedding drift bounds.
    p.add_argument("--drift-sample-n", type=int, default=200, help="Max chunks sampled for embedding drift (default: 200)")
    p.add_argument("--drift-threshold", type=float, default=0.05, help="Cosine distance threshold for embedding drift (default: 0.05)")

    p.add_argument("--force", action="store_true", help="Write audit even if today's report already exists.")

    args = p.parse_args(argv)

    if (
        (not bool(args.index_audit))
        and (not bool(args.evidence_drift_audit))
        and (not bool(args.access_review))
        and (not bool(args.embedding_drift))
    ):
        print(
            "No job selected. Use --index-audit and/or --evidence-drift-audit and/or --access-review and/or --embedding-drift.",
            file=sys.stderr,
        )
        return 2

    execute = bool(args.execute)
    if not bool(args.dry_run) and not bool(args.execute):
        execute = False  # default dry-run

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
            if bool(args.access_review):
                res = run_daily_access_review_summary(
                    db,
                    tenant_id=tid,
                    execute=bool(execute),
                    force=bool(args.force),
                    actor_id="system:periodic_audit",
                    now=ran_at,
                )
                res["job"] = "access_review_summary"
                results.append(res)
                ok = ok and bool(res.get("ok") is True)

            if bool(args.index_audit):
                res = run_daily_index_audit_report(
                    db,
                    tenant_id=tid,
                    max_datasets=int(args.max_datasets or 0),
                    max_check_ids=int(args.max_check_ids or 0),
                    milvus_list_limit=int(args.milvus_list_limit or 0),
                    sample_limit=int(args.sample_limit or 0),
                    execute=bool(execute),
                    force=bool(args.force),
                    actor_id="system:periodic_audit",
                    now=ran_at,
                )
                res["job"] = "index_audit"
                results.append(res)
                ok = ok and bool(res.get("ok") is True)

            if bool(args.evidence_drift_audit):
                res = run_daily_evidence_drift_audit_report(
                    db,
                    tenant_id=tid,
                    max_datasets=int(args.max_datasets or 0),
                    include_archived_items=bool(args.include_archived_items),
                    include_details=bool(args.include_details),
                    details_limit=int(args.details_limit or 0),
                    slice_top_n=int(args.slice_top_n or 0),
                    execute=bool(execute),
                    force=bool(args.force),
                    actor_id="system:periodic_audit",
                    now=ran_at,
                )
                res["job"] = "evidence_drift_audit"
                results.append(res)
                ok = ok and bool(res.get("ok") is True)

            if bool(args.embedding_drift):
                res = run_daily_embedding_drift_report(
                    db,
                    tenant_id=tid,
                    execute=bool(execute),
                    force=bool(args.force),
                    sample_n=int(args.drift_sample_n or 0),
                    drift_threshold=float(args.drift_threshold),
                    actor_id="system:periodic_audit",
                    now=ran_at,
                )
                res["job"] = "embedding_drift"
                results.append(res)
                ok = ok and bool(res.get("ok") is True)
        finally:
            db.close()

    print(json.dumps({"ok": bool(ok), "ran_at": ran_at.isoformat(), "results": results}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
