"""
Evidence reference_sources repair service (best-effort, bounded).

Used by:
- EvidenceSuite repair API endpoint (sync)
- Task queue job (async / retryable)

PII safety:
- Never emit chunk content or raw quotes. Only ids + counters + bounded metadata.
"""


from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.models.evidence import EvidenceItem, EvidenceSuite
from app.rag.core.logging import get_logger
from app.services.audit_log_service import audit_log_event
from app.services.evidence_drift_audit import classify_reference_source_drift

logger = get_logger(__name__)
_EVIDENCE_REPAIR_FALLBACK_LOG_MESSAGE = "Ignoring non-critical evidence repair fallback failure: %s"


class EvidenceSuiteNotFoundError(RuntimeError):
    pass


def _select_quote_needle(quote: str) -> str:
    """
    Build a bounded, search-friendly needle from a quote excerpt.

    We avoid returning the quote itself in API responses; this is internal only.
    """
    import re

    raw = " ".join(str(quote or "").split()).strip()
    if not raw:
        return ""
    # Prefer longer contiguous alnum/CJK runs (more specific than punctuation-heavy prefixes).
    runs = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{12,}", raw)
    if runs:
        runs.sort(key=lambda s: (-len(s), s))
        return runs[0][:80]
    return raw[:80]


def _escape_like(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True, slots=True)
class RepairParams:
    apply: bool
    allow_approved: bool
    include_archived_items: bool
    max_items: int
    max_refs_per_item: int
    max_changes: int


def _coerce_params(
    *,
    apply: bool,
    allow_approved: bool,
    include_archived_items: bool,
    max_items: int,
    max_refs_per_item: int,
    max_changes: int,
) -> RepairParams:
    try:
        max_items_i = max(1, int(max_items or 0))
    except Exception:
        max_items_i = 5000
    max_items_i = min(max_items_i, 20_000)

    try:
        max_refs_i = max(1, int(max_refs_per_item or 0))
    except Exception:
        max_refs_i = 50
    max_refs_i = min(max_refs_i, 500)

    try:
        max_changes_i = max(0, int(max_changes or 0))
    except Exception:
        max_changes_i = 500
    max_changes_i = min(max_changes_i, 5000)

    return RepairParams(
        apply=bool(apply),
        allow_approved=bool(allow_approved),
        include_archived_items=bool(include_archived_items),
        max_items=max_items_i,
        max_refs_per_item=max_refs_i,
        max_changes=max_changes_i,
    )


def repair_evidence_suite_reference_sources(
    db: Session,
    *,
    tenant_id: UUID,
    suite_id: UUID,
    apply: bool,
    allow_approved: bool,
    include_archived_items: bool,
    max_items: int,
    max_refs_per_item: int,
    max_changes: int,
    actor_id: str | None,
) -> dict[str, Any]:
    """
    Repair drifted EvidenceItem.reference_sources for a suite.

    Returns a JSON-safe dict matching `EvidenceReferenceRepairResponse` fields.
    """
    suite_row = (
        db.query(EvidenceSuite.dataset_id)
        .filter(EvidenceSuite.tenant_id == tenant_id, EvidenceSuite.id == suite_id)
        .first()
    )
    if not suite_row or suite_row[0] is None:
        raise EvidenceSuiteNotFoundError("suite_not_found")

    dataset_id: UUID = suite_row[0]
    return repair_evidence_suite_reference_sources_with_dataset(
        db,
        tenant_id=tenant_id,
        suite_id=suite_id,
        suite_dataset_id=dataset_id,
        apply=apply,
        allow_approved=allow_approved,
        include_archived_items=include_archived_items,
        max_items=max_items,
        max_refs_per_item=max_refs_per_item,
        max_changes=max_changes,
        actor_id=actor_id,
    )


def repair_evidence_suite_reference_sources_with_dataset(
    db: Session,
    *,
    tenant_id: UUID,
    suite_id: UUID,
    suite_dataset_id: UUID,
    apply: bool,
    allow_approved: bool,
    include_archived_items: bool,
    max_items: int,
    max_refs_per_item: int,
    max_changes: int,
    actor_id: str | None,
) -> dict[str, Any]:
    """
    Internal helper when suite.dataset_id is already known (avoids a DB query).

    Notes:
    - Bounded by max_items/max_refs_per_item/max_changes.
    - Best-effort: applies changes item-by-item when apply=True.
    """
    params = _coerce_params(
        apply=apply,
        allow_approved=allow_approved,
        include_archived_items=include_archived_items,
        max_items=max_items,
        max_refs_per_item=max_refs_per_item,
        max_changes=max_changes,
    )

    q = db.query(EvidenceItem).filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
    if not bool(params.include_archived_items):
        q = q.filter(EvidenceItem.status != "archived")
    items = q.order_by(EvidenceItem.updated_at.desc()).limit(params.max_items).all()

    scanned_refs = 0
    drifted_refs = 0
    repaired_refs = 0
    skipped_approved = 0
    skipped_archived = 0
    changes: list[dict[str, Any]] = []
    changes_truncated = False

    def _append_change(change: dict[str, Any]) -> None:
        nonlocal changes_truncated
        if len(changes) < params.max_changes:
            changes.append(change)
        else:
            changes_truncated = True

    for it in items:
        st = str(getattr(it, "status", "") or "").strip().lower() or "unknown"
        if st == "archived" and not bool(params.include_archived_items):
            skipped_archived += 1
            continue
        if st == "approved" and not bool(params.allow_approved):
            skipped_approved += 1
            continue

        raw_refs = getattr(it, "reference_sources", None)
        refs = raw_refs if isinstance(raw_refs, list) else []
        if not refs:
            continue

        # Guardrail per item to avoid pathological payloads.
        refs = refs[: params.max_refs_per_item]

        # Prefetch docs/chunks for drift classification.
        doc_ids: set[UUID] = set()
        chunk_ids: set[UUID] = set()
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            try:
                doc_ids.add(UUID(str(ref.get("document_id"))))
                chunk_ids.add(UUID(str(ref.get("chunk_id"))))
            except Exception:
                get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue

        doc_rows = (
            db.query(DBDocument.id, DBDocument.dataset_id, DBDocument.file_type, DBDocument.doc_metadata)
            .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(sorted(doc_ids)))
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
                DocumentChunk.page_number,
                DocumentChunk.start_char,
                DocumentChunk.end_char,
                DocumentChunk.disabled_at,
            )
            .filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.id.in_(sorted(chunk_ids)))
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
                "page_number": row[4],
                "start_char": row[5],
                "end_char": row[6],
                "disabled_at": row[7],
            }
            for row in chunk_rows
            if row and row[0] is not None
        }

        patched_refs: list[dict[str, Any]] = []
        changed_item = False

        for ref in refs:
            if not isinstance(ref, dict):
                patched_refs.append(ref)
                continue

            scanned_refs += 1
            try:
                doc_uuid = UUID(str(ref.get("document_id")))
                chunk_uuid = UUID(str(ref.get("chunk_id")))
            except Exception:
                drifted_refs += 1
                patched_refs.append(ref)
                continue

            doc = doc_map.get(doc_uuid)
            chunk = chunk_map.get(chunk_uuid)

            ok, reason, _expected, _observed = classify_reference_source_drift(
                reference_source=ref,
                document_row=doc,
                chunk_row=chunk,
                suite_dataset_id=suite_dataset_id,
            )
            if ok:
                patched_refs.append(ref)
                continue

            drifted_refs += 1

            # Do not attempt repair if the document is missing or out of scope.
            if reason in {"document_missing", "document_dataset_mismatch"}:
                _append_change(
                    {
                        "suite_id": str(suite_id),
                        "item_id": str(it.id),
                        "item_status": st,
                        "document_id": str(doc_uuid),
                        "chunk_id_before": str(chunk_uuid),
                        "chunk_id_after": None,
                        "reason": reason,
                        "repaired": False,
                        "method": None,
                        "meta": {},
                    }
                )
                patched_refs.append(ref)
                continue

            repaired = False
            method: str | None = None
            new_chunk_id: UUID | None = None
            new_chunk_row: dict[str, Any] | None = None

            # 1) Exact relink by (doc_pipeline_key + chunk_index) within the same document.
            dpk = ref.get("doc_pipeline_key")
            ci = ref.get("chunk_index")
            if isinstance(dpk, str) and dpk.strip() and ci is not None:
                try:
                    ci_int = int(ci)
                except Exception:
                    ci_int = None
                if ci_int is not None:
                    try:
                        row = (
                            db.query(
                                DocumentChunk.id,
                                DocumentChunk.document_id,
                                DocumentChunk.chunk_index,
                                DocumentChunk.doc_metadata,
                                DocumentChunk.page_number,
                                DocumentChunk.start_char,
                                DocumentChunk.end_char,
                                DocumentChunk.disabled_at,
                            )
                            .filter(
                                DocumentChunk.tenant_id == tenant_id,
                                DocumentChunk.document_id == doc_uuid,
                                DocumentChunk.chunk_index == ci_int,
                                DocumentChunk.disabled_at.is_(None),
                                DocumentChunk.doc_metadata["doc_pipeline_key"].astext == dpk.strip(),  # type: ignore[attr-defined]
                            )
                            .limit(1)
                            .first()
                        )
                    except Exception:
                        row = None
                    if row and row[0] is not None:
                        new_chunk_id = row[0]
                        new_chunk_row = {
                            "id": row[0],
                            "document_id": row[1],
                            "chunk_index": row[2],
                            "metadata": row[3] if isinstance(row[3], dict) else {},
                            "page_number": row[4],
                            "start_char": row[5],
                            "end_char": row[6],
                            "disabled_at": row[7],
                        }
                        if new_chunk_id != chunk_uuid:
                            repaired = True
                            method = "doc_pipeline_key+chunk_index"

            # 2) Quote needle match (prefer active pipeline when available).
            if not repaired:
                quote = ref.get("quote")
                if isinstance(quote, str) and quote.strip():
                    needle = _select_quote_needle(quote)
                    if needle and len(needle) >= 12 and doc is not None:
                        doc_meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
                        active_hash = str(doc_meta.get("active_pipeline_hash") or doc_meta.get("pipeline_hash") or "").strip()
                        active_key = f"{doc_uuid}:{active_hash}" if active_hash else ""
                        pattern = f"%{_escape_like(needle)}%"
                        q2 = (
                            db.query(
                                DocumentChunk.id,
                                DocumentChunk.document_id,
                                DocumentChunk.chunk_index,
                                DocumentChunk.doc_metadata,
                                DocumentChunk.page_number,
                                DocumentChunk.start_char,
                                DocumentChunk.end_char,
                            )
                            .filter(
                                DocumentChunk.tenant_id == tenant_id,
                                DocumentChunk.document_id == doc_uuid,
                                DocumentChunk.disabled_at.is_(None),
                                DocumentChunk.content.ilike(pattern, escape="\\"),
                            )
                        )
                        if active_key:
                            try:
                                q2 = q2.filter(DocumentChunk.doc_metadata["doc_pipeline_key"].astext == active_key)  # type: ignore[attr-defined]
                            except Exception as exc:
                                logger.debug(_EVIDENCE_REPAIR_FALLBACK_LOG_MESSAGE, exc)
                        rows = q2.limit(20).all()
                        if rows:
                            # Pick the lowest chunk_index (stable) among matches.
                            rows_sorted = sorted(rows, key=lambda r: (int(r[2] or 0), str(r[0] or "")))
                            best = rows_sorted[0]
                            if best and best[0] is not None:
                                new_chunk_id = best[0]
                                new_chunk_row = {
                                    "id": best[0],
                                    "document_id": best[1],
                                    "chunk_index": best[2],
                                    "metadata": best[3] if isinstance(best[3], dict) else {},
                                    "page_number": best[4],
                                    "start_char": best[5],
                                    "end_char": best[6],
                                    "disabled_at": None,
                                }
                                if new_chunk_id != chunk_uuid:
                                    repaired = True
                                    method = "quote_needle"

            if repaired and new_chunk_id is not None and new_chunk_row is not None:
                repaired_refs += 1
                patched = dict(ref)
                patched["chunk_id"] = str(new_chunk_id)
                # Refresh audit fields from the newly linked chunk (best-effort).
                try:
                    patched["chunk_index"] = int(new_chunk_row.get("chunk_index") or 0)
                except Exception as exc:
                    logger.debug(_EVIDENCE_REPAIR_FALLBACK_LOG_MESSAGE, exc)
                cmeta = new_chunk_row.get("metadata") if isinstance(new_chunk_row.get("metadata"), dict) else {}
                ph = str(cmeta.get("pipeline_hash") or "").strip()
                if ph:
                    patched["pipeline_hash"] = ph
                dpk2 = str(cmeta.get("doc_pipeline_key") or "").strip()
                if dpk2:
                    patched["doc_pipeline_key"] = dpk2
                pn = new_chunk_row.get("page_number")
                if isinstance(pn, int) and pn > 0:
                    patched["page_number"] = pn
                sc = new_chunk_row.get("start_char")
                if isinstance(sc, int) and sc >= 0:
                    patched["start_char"] = sc
                ec = new_chunk_row.get("end_char")
                if isinstance(ec, int) and ec >= 0:
                    patched["end_char"] = ec

                if bool(params.apply):
                    changed_item = True
                patched_refs.append(patched)

                _append_change(
                    {
                        "suite_id": str(suite_id),
                        "item_id": str(it.id),
                        "item_status": st,
                        "document_id": str(doc_uuid),
                        "chunk_id_before": str(chunk_uuid),
                        "chunk_id_after": str(new_chunk_id),
                        "reason": reason,
                        "repaired": True,
                        "method": method,
                        "meta": {
                            "needle_len": len(_select_quote_needle(str(ref.get("quote") or "")))
                            if method == "quote_needle"
                            else None
                        },
                    }
                )
                continue

            # No repair found.
            _append_change(
                {
                    "suite_id": str(suite_id),
                    "item_id": str(it.id),
                    "item_status": st,
                    "document_id": str(doc_uuid),
                    "chunk_id_before": str(chunk_uuid),
                    "chunk_id_after": None,
                    "reason": reason,
                    "repaired": False,
                    "method": None,
                    "meta": {},
                }
            )
            patched_refs.append(ref)

        if bool(params.apply) and changed_item:
            it.reference_sources = patched_refs
            db.add(it)
            db.commit()
            db.refresh(it)
            # Best-effort audit log (do not include evidence content).
            try:
                audit_log_event(
                    db,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    action="evidence.reference_sources.repair",
                    resource_type="evidence_item",
                    resource_id=str(it.id),
                    details={
                        "suite_id": str(suite_id),
                        "dataset_id": str(suite_dataset_id),
                        "item_status": st,
                        "applied": True,
                    },
                )
                db.commit()
            except Exception:
                try:
                    db.rollback()
                except Exception as exc:
                    logger.debug(_EVIDENCE_REPAIR_FALLBACK_LOG_MESSAGE, exc)

    return {
        "suite_id": str(suite_id),
        "dataset_id": str(suite_dataset_id),
        "applied": bool(params.apply),
        "scanned_items": int(len(items)),
        "scanned_references": int(scanned_refs),
        "drifted_references": int(drifted_refs),
        "repaired_references": int(repaired_refs),
        "skipped_approved_items": int(skipped_approved),
        "skipped_archived_items": int(skipped_archived),
        "changes_truncated": bool(changes_truncated),
        "changes": list(changes),
    }


__all__ = [
    "EvidenceSuiteNotFoundError",
    "repair_evidence_suite_reference_sources",
    "repair_evidence_suite_reference_sources_with_dataset",
]
