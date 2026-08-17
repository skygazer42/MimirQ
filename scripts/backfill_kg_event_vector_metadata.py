#!/usr/bin/env python3
"""
Backfill Milvus metadata fields for KG event vectors (kg_events).

Why:
- KG event vectors are stored in Milvus with scalar metadata fields.
- Newer indexing writes `pipeline_hash` + `doc_pipeline_key` so pipeline-scoped
  filtering can be pushed down into Milvus expr.
- Legacy vectors may be missing these fields; re-upserting the vectors updates
  metadata (best-effort, requires the collection schema to include the fields).

This script is intentionally:
- Bounded (batching)
- Safe by default (dry-run unless --execute)
- PII-safe-ish (does not print raw content; only counts and ids)

Examples:
  # Dry run for default tenant
  python scripts/backfill_kg_event_vector_metadata.py

  # Execute for a dataset
  python scripts/backfill_kg_event_vector_metadata.py --dataset-id <uuid> --execute

  # Execute for specific documents
  python scripts/backfill_kg_event_vector_metadata.py --tenant-id <uuid> \
    --document-id <uuid> --document-id <uuid> --execute
"""

import argparse
import sys
import time
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.rag.kg.models import KgSourceEvent
from app.services.indexer import Indexer


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:  # noqa: BLE001
        raise argparse.ArgumentTypeError("must be a valid UUID") from exc


def _resolve_tenant_id(db: Session, *, tenant_id: UUID | None, dataset_id: UUID | None) -> UUID:
    if tenant_id is not None:
        return tenant_id

    if dataset_id is not None:
        row = db.query(Dataset.tenant_id).filter(Dataset.id == dataset_id).first()
        if not row:
            raise ValueError("dataset not found")
        tid = row[0]
        if not isinstance(tid, UUID):
            raise ValueError("dataset tenant_id is invalid")
        return tid

    return UUID(str(settings.DEFAULT_TENANT_ID))


def _iter_event_batches(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    document_ids: list[UUID] | None,
    batch_size: int,
    max_events: int,
):
    q = db.query(KgSourceEvent).filter(KgSourceEvent.tenant_id == tenant_id)

    # We only need to upsert rows that already have vectors.
    q = q.filter(KgSourceEvent.content_vector.isnot(None))

    if document_ids is not None:
        if not document_ids:
            return
        q = q.filter(KgSourceEvent.document_id.in_(document_ids))
    elif dataset_id is not None:
        q = q.join(
            DBDocument,
            and_(
                DBDocument.id == KgSourceEvent.document_id,
                DBDocument.tenant_id == KgSourceEvent.tenant_id,
            ),
        ).filter(DBDocument.dataset_id == dataset_id)

    q = q.order_by(KgSourceEvent.id.asc())

    emitted = 0
    batch: list[KgSourceEvent] = []
    for ev in q.yield_per(min(max(100, batch_size), 5000)):
        batch.append(ev)
        if len(batch) >= batch_size:
            yield batch
            emitted += len(batch)
            batch = []
            if emitted >= max_events:
                return

    if batch:
        yield batch


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Backfill KG event vector metadata in Milvus (pipeline_hash/doc_pipeline_key)."
    )
    p.add_argument("--tenant-id", type=_parse_uuid, default=None, help="Tenant UUID (defaults to DEFAULT_TENANT_ID)")
    p.add_argument(
        "--dataset-id", type=_parse_uuid, default=None, help="Optional dataset scope (derives tenant if omitted)"
    )
    p.add_argument(
        "--document-id",
        type=_parse_uuid,
        action="append",
        default=None,
        help="Optional document scope (repeatable). If provided, dataset-id is ignored.",
    )

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan only (no Milvus writes). Default.")
    mode.add_argument("--execute", action="store_true", help="Execute Milvus upserts.")

    p.add_argument("--batch-size", type=int, default=1000, help="Events per upsert batch (default: 1000)")
    p.add_argument(
        "--max-events", type=int, default=1_000_000_000, help="Hard cap on total events processed (default: no cap)"
    )

    args = p.parse_args(argv)

    execute = bool(args.execute)
    dry_run = not execute  # default

    batch_size = max(1, int(args.batch_size or 0))
    max_events = max(0, int(args.max_events or 0))
    dataset_id = args.dataset_id
    document_ids = args.document_id

    db = SessionLocal()
    try:
        tenant_id = _resolve_tenant_id(db, tenant_id=args.tenant_id, dataset_id=dataset_id)

        if dataset_id is not None:
            # Basic scope sanity: dataset must belong to tenant.
            row = db.query(Dataset.id).filter(Dataset.id == dataset_id, Dataset.tenant_id == tenant_id).first()
            if not row:
                print("Dataset not found in tenant scope.", file=sys.stderr)
                return 2

        started = time.time()
        total_batches = 0
        total_events = 0
        total_vectors = 0

        indexer = Indexer(db)
        for batch in _iter_event_batches(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id if document_ids is None else None,
            document_ids=document_ids,
            batch_size=batch_size,
            max_events=max_events,
        ):
            total_batches += 1
            total_events += len(batch)
            if dry_run:
                continue

            # Private helper is OK in scripts; it avoids re-querying entities.
            written_ids = indexer._index_event_vectors(batch)  # noqa: SLF001
            total_vectors += len(written_ids)

            # Lightweight progress (no content).
            if total_batches == 1 or total_batches % 10 == 0:
                elapsed = time.time() - started
                print(
                    f"[kg_events.backfill] batches={total_batches} events={total_events} "
                    f"vectors={total_vectors} elapsed={elapsed:.1f}s",
                    file=sys.stderr,
                )

        elapsed = time.time() - started
        mode_str = "execute" if execute else "dry-run"
        print(
            f"[kg_events.backfill] ok mode={mode_str} tenant_id={tenant_id} dataset_id={dataset_id} "
            f"documents={len(document_ids) if document_ids else 0} batches={total_batches} events={total_events} "
            f"vectors={total_vectors} elapsed={elapsed:.2f}s"
        )
        return 0
    except ValueError as exc:
        print(f"Error: {str(exc)}", file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
