"""
Evidence drift audit service (PII-safe).

This logic is used by:
- Evidence drift audit API endpoints
- Periodic ops jobs (cron / Kubernetes CronJob)

Important: Do NOT read or emit chunk content. Ids + counters only.
"""


from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.schemas.evidence_audit import EvidenceReferenceDriftAuditOut
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.models.evidence import EvidenceItem
from app.services.evidence_drift_audit import build_drift_slice_keys, classify_reference_source_drift


def audit_reference_sources_drift(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    suite_id: UUID | None,
    suite_dataset_id: UUID | None,
    items: list[EvidenceItem],
    include_details: bool,
    details_limit: int,
    slice_top_n: int,
) -> EvidenceReferenceDriftAuditOut:
    """
    Audit EvidenceItem.reference_sources drift for a scope (suite or dataset).

    PII-safe: do NOT include quote/chunk content; ids + counters only.
    """
    now = datetime.now(UTC)

    # Flatten pointers.
    pointers: list[dict[str, Any]] = []
    invalid_refs = 0
    for it in items:
        raw_refs = getattr(it, "reference_sources", None)
        refs = raw_refs if isinstance(raw_refs, list) else []
        for ref in refs:
            if not isinstance(ref, dict):
                invalid_refs += 1
                continue
            doc_raw = ref.get("document_id")
            chunk_raw = ref.get("chunk_id")
            try:
                doc_uuid = UUID(str(doc_raw))
                chunk_uuid = UUID(str(chunk_raw))
            except Exception:
                invalid_refs += 1
                continue
            pointers.append(
                {
                    "suite_id": it.suite_id,
                    "item_id": it.id,
                    "item_status": str(getattr(it, "status", "") or "").strip().lower() or "unknown",
                    "dataset_id": it.dataset_id,
                    "reference_source": dict(ref),
                    "document_id": doc_uuid,
                    "chunk_id": chunk_uuid,
                }
            )

    doc_ids = sorted({p["document_id"] for p in pointers if p.get("document_id") is not None})
    chunk_ids = sorted({p["chunk_id"] for p in pointers if p.get("chunk_id") is not None})

    # Batch fetch docs/chunks.
    doc_rows = (
        db.query(DBDocument.id, DBDocument.dataset_id, DBDocument.file_type, DBDocument.doc_metadata)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(doc_ids))
        .all()
        if doc_ids
        else []
    )
    doc_map: dict[UUID, dict[str, Any]] = {
        row[0]: {
            "id": row[0],
            "dataset_id": row[1],
            "file_type": row[2],
            "metadata": row[3] if isinstance(row[3], dict) else {},
        }
        for row in doc_rows
        if row and row[0] is not None
    }

    chunk_rows = (
        db.query(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            DocumentChunk.doc_metadata,
            DocumentChunk.disabled_at,
        )
        .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.id.in_(chunk_ids))
        .all()
        if chunk_ids
        else []
    )
    chunk_map: dict[UUID, dict[str, Any]] = {
        row[0]: {
            "id": row[0],
            "document_id": row[1],
            "chunk_index": row[2],
            "metadata": row[3] if isinstance(row[3], dict) else {},
            "disabled_at": row[4],
        }
        for row in chunk_rows
        if row and row[0] is not None
    }

    # Aggregate counters.
    total_items = len({it.id for it in items})
    total_refs = len(pointers) + int(invalid_refs)
    ok_refs = 0
    drift_refs = 0
    reasons: Counter[str] = Counter()

    # slices[slice_name][bucket] -> (total, drift, reasons Counter)
    slice_totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    slice_drifts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    slice_reasons: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))

    details: list[dict[str, Any]] = []
    details_truncated = False

    def _slice_bucket_keys(doc: dict[str, Any] | None) -> dict[str, str]:
        if not doc:
            return {"file_type": "unknown", "language": "unknown", "quality_bucket": "unknown", "directory": "root"}
        keys = build_drift_slice_keys(document_file_type=doc.get("file_type"), document_metadata=doc.get("metadata"))
        return {
            "file_type": keys.file_type,
            "language": keys.language,
            "quality_bucket": keys.quality_bucket,
            "directory": keys.directory,
        }

    # Count invalid refs as drift (PII-safe, no details).
    if invalid_refs:
        reasons["invalid_reference"] += int(invalid_refs)
        drift_refs += int(invalid_refs)

    for p in pointers:
        ref = p["reference_source"]
        doc_uuid: UUID = p["document_id"]
        chunk_uuid: UUID = p["chunk_id"]

        doc = doc_map.get(doc_uuid)
        chunk = chunk_map.get(chunk_uuid)

        ok, reason, expected, observed = classify_reference_source_drift(
            reference_source=ref,
            document_row=doc,
            chunk_row=chunk,
            suite_dataset_id=suite_dataset_id,
        )

        slice_keys = _slice_bucket_keys(doc)
        for slice_name, bucket in slice_keys.items():
            slice_totals[slice_name][bucket] += 1
            if not ok:
                slice_drifts[slice_name][bucket] += 1
                slice_reasons[slice_name][bucket][reason] += 1

        if ok:
            ok_refs += 1
            continue

        drift_refs += 1
        reasons[reason] += 1

        if include_details:
            if len(details) < max(0, int(details_limit or 0)):
                details.append(
                    {
                        "suite_id": p["suite_id"],
                        "item_id": p["item_id"],
                        "item_status": p["item_status"],
                        "dataset_id": p["dataset_id"],
                        "document_id": doc_uuid,
                        "chunk_id": chunk_uuid,
                        "reason": reason,
                        "expected": expected,
                        "observed": observed,
                        "slice": slice_keys,
                    }
                )
            else:
                details_truncated = True

    # Build slice outputs (cap buckets to top-N by total to keep payload bounded).
    slices_out: dict[str, dict[str, Any]] = {}
    for slice_name, buckets in slice_totals.items():
        rows = sorted(buckets.items(), key=lambda kv: (-int(kv[1] or 0), kv[0]))[: max(0, int(slice_top_n or 0))]
        out_buckets: dict[str, Any] = {}
        for bucket, total in rows:
            total_i = int(total or 0)
            drift_i = int(slice_drifts[slice_name].get(bucket) or 0)
            ok_i = max(0, total_i - drift_i)
            out_buckets[bucket] = {
                "total": total_i,
                "ok": ok_i,
                "drift": drift_i,
                "drift_rate": (round(drift_i / total_i, 6) if total_i > 0 else 0.0),
                "reasons": {
                    str(k): int(v)
                    for k, v in sorted((slice_reasons[slice_name].get(bucket) or Counter()).items())
                    if int(v or 0) > 0
                },
            }
        slices_out[slice_name] = out_buckets

    drift_rate = round(drift_refs / total_refs, 6) if total_refs > 0 else 0.0
    return EvidenceReferenceDriftAuditOut(
        generated_at=now,
        dataset_id=dataset_id,
        suite_id=suite_id,
        total_items=int(total_items),
        total_references=int(total_refs),
        ok_references=int(ok_refs),
        drift_references=int(drift_refs),
        drift_rate=float(drift_rate),
        reasons={str(k): int(v) for k, v in sorted(reasons.items()) if int(v or 0) > 0},
        slices=slices_out,
        details_truncated=bool(details_truncated),
        drifted_references=details,
    )


__all__ = ["audit_reference_sources_drift"]

