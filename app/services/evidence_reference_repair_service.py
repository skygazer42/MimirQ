"""
Evidence reference_sources repair service (best-effort, bounded).

Used by:
- EvidenceSuite repair API endpoint (sync)
- Task queue job (async / retryable)

PII safety:
- Never emit chunk content or raw quotes. Only ids + counters + bounded metadata.
"""

from dataclasses import dataclass, field
from typing import Any, Sequence
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


@dataclass(frozen=True, slots=True)
class ReferenceMaps:
    documents: dict[UUID, dict[str, Any]]
    chunks: dict[UUID, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RepairCandidate:
    chunk_id: UUID
    chunk_row: dict[str, Any]
    method: str


@dataclass(slots=True)
class RepairReport:
    max_changes: int
    scanned_refs: int = 0
    drifted_refs: int = 0
    repaired_refs: int = 0
    skipped_approved: int = 0
    skipped_archived: int = 0
    changes: list[dict[str, Any]] = field(default_factory=list)
    changes_truncated: bool = False

    def append_change(self, change: dict[str, Any]) -> None:
        if len(self.changes) < self.max_changes:
            self.changes.append(change)
            return
        self.changes_truncated = True

    def as_result(self, *, suite_id: UUID, suite_dataset_id: UUID, applied: bool, scanned_items: int) -> dict[str, Any]:
        return {
            "suite_id": str(suite_id),
            "dataset_id": str(suite_dataset_id),
            "applied": bool(applied),
            "scanned_items": int(scanned_items),
            "scanned_references": int(self.scanned_refs),
            "drifted_references": int(self.drifted_refs),
            "repaired_references": int(self.repaired_refs),
            "skipped_approved_items": int(self.skipped_approved),
            "skipped_archived_items": int(self.skipped_archived),
            "changes_truncated": bool(self.changes_truncated),
            "changes": list(self.changes),
        }


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


def _load_suite_items(db: Session, *, tenant_id: UUID, suite_id: UUID, params: RepairParams) -> list[EvidenceItem]:
    q = db.query(EvidenceItem).filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
    if not params.include_archived_items:
        q = q.filter(EvidenceItem.status != "archived")
    return q.order_by(EvidenceItem.updated_at.desc()).limit(params.max_items).all()


def _normalize_item_status(item: EvidenceItem) -> str:
    return str(getattr(item, "status", "") or "").strip().lower() or "unknown"


def _limited_reference_sources(item: EvidenceItem, *, max_refs_per_item: int) -> list[Any]:
    raw_refs = getattr(item, "reference_sources", None)
    refs = raw_refs if isinstance(raw_refs, list) else []
    return refs[:max_refs_per_item]


def _coerce_ref_ids(ref: dict[str, Any]) -> tuple[UUID | None, UUID | None]:
    try:
        return UUID(str(ref.get("document_id"))), UUID(str(ref.get("chunk_id")))
    except Exception:
        return None, None


def _row_metadata(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _build_document_map(rows: Sequence[Sequence[Any]]) -> dict[UUID, dict[str, Any]]:
    return {
        row[0]: {
            "id": row[0],
            "dataset_id": row[1],
            "file_type": row[2],
            "metadata": _row_metadata(row[3]),
        }
        for row in rows
        if row and row[0] is not None
    }


def _build_chunk_row(row: Sequence[Any]) -> dict[str, Any]:
    return {
        "id": row[0],
        "document_id": row[1],
        "chunk_index": row[2],
        "metadata": _row_metadata(row[3]),
        "page_number": row[4],
        "start_char": row[5],
        "end_char": row[6],
        "disabled_at": row[7] if len(row) > 7 else None,
    }


def _build_chunk_map(rows: Sequence[Sequence[Any]]) -> dict[UUID, dict[str, Any]]:
    return {row[0]: _build_chunk_row(row) for row in rows if row and row[0] is not None}


def _collect_prefetch_ids(refs: list[Any]) -> tuple[set[UUID], set[UUID]]:
    doc_ids: set[UUID] = set()
    chunk_ids: set[UUID] = set()
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        try:
            doc_ids.add(UUID(str(ref.get("document_id"))))
            chunk_ids.add(UUID(str(ref.get("chunk_id"))))
        except Exception:
            logger.debug("Skipping item after non-critical exception", exc_info=True)
            continue
    return doc_ids, chunk_ids


def _load_reference_maps(db: Session, *, tenant_id: UUID, refs: list[Any]) -> ReferenceMaps:
    doc_ids, chunk_ids = _collect_prefetch_ids(refs)
    doc_rows = (
        db.query(DBDocument.id, DBDocument.dataset_id, DBDocument.file_type, DBDocument.doc_metadata)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(sorted(doc_ids)))
        .all()
        if doc_ids
        else []
    )
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
    return ReferenceMaps(documents=_build_document_map(doc_rows), chunks=_build_chunk_map(chunk_rows))


def _find_exact_chunk_relink(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    stale_chunk_id: UUID,
    reference_source: dict[str, Any],
) -> RepairCandidate | None:
    dpk = reference_source.get("doc_pipeline_key")
    ci = reference_source.get("chunk_index")
    if not (isinstance(dpk, str) and dpk.strip() and ci is not None):
        return None

    try:
        ci_int = int(ci)
    except Exception:
        return None

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
                DocumentChunk.document_id == document_id,
                DocumentChunk.chunk_index == ci_int,
                DocumentChunk.disabled_at.is_(None),
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext == dpk.strip(),  # type: ignore[attr-defined]
            )
            .limit(1)
            .first()
        )
    except Exception:
        row = None

    if not row or row[0] is None or row[0] == stale_chunk_id:
        return None
    return RepairCandidate(chunk_id=row[0], chunk_row=_build_chunk_row(row), method="doc_pipeline_key+chunk_index")


def _find_quote_needle_relink(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    stale_chunk_id: UUID,
    reference_source: dict[str, Any],
    document_row: dict[str, Any] | None,
) -> RepairCandidate | None:
    quote = reference_source.get("quote")
    if not (isinstance(quote, str) and quote.strip() and document_row is not None):
        return None

    needle = _select_quote_needle(quote)
    if len(needle) < 12:
        return None

    doc_meta = _row_metadata(document_row.get("metadata"))
    active_hash = str(doc_meta.get("active_pipeline_hash") or doc_meta.get("pipeline_hash") or "").strip()
    active_key = f"{document_id}:{active_hash}" if active_hash else ""
    pattern = f"%{_escape_like(needle)}%"
    q2 = db.query(
        DocumentChunk.id,
        DocumentChunk.document_id,
        DocumentChunk.chunk_index,
        DocumentChunk.doc_metadata,
        DocumentChunk.page_number,
        DocumentChunk.start_char,
        DocumentChunk.end_char,
    ).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
        DocumentChunk.disabled_at.is_(None),
        DocumentChunk.content.ilike(pattern, escape="\\"),
    )
    if active_key:
        try:
            q2 = q2.filter(DocumentChunk.doc_metadata["doc_pipeline_key"].astext == active_key)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.debug(_EVIDENCE_REPAIR_FALLBACK_LOG_MESSAGE, exc)

    rows = q2.limit(20).all()
    if not rows:
        return None

    best = sorted(rows, key=lambda row: (int(row[2] or 0), str(row[0] or "")))[0]
    if not best or best[0] is None or best[0] == stale_chunk_id:
        return None
    return RepairCandidate(chunk_id=best[0], chunk_row=_build_chunk_row(best), method="quote_needle")


def _find_repair_candidate(
    db: Session,
    *,
    tenant_id: UUID,
    document_id: UUID,
    stale_chunk_id: UUID,
    reference_source: dict[str, Any],
    document_row: dict[str, Any] | None,
) -> RepairCandidate | None:
    candidate = _find_exact_chunk_relink(
        db,
        tenant_id=tenant_id,
        document_id=document_id,
        stale_chunk_id=stale_chunk_id,
        reference_source=reference_source,
    )
    if candidate is not None:
        return candidate
    return _find_quote_needle_relink(
        db,
        tenant_id=tenant_id,
        document_id=document_id,
        stale_chunk_id=stale_chunk_id,
        reference_source=reference_source,
        document_row=document_row,
    )


def _build_change_record(
    *,
    suite_id: UUID,
    item_id: UUID,
    item_status: str,
    document_id: UUID,
    chunk_id_before: UUID,
    chunk_id_after: UUID | None,
    reason: str,
    repaired: bool,
    method: str | None,
    meta: dict[str, Any],
) -> dict[str, Any]:
    return {
        "suite_id": str(suite_id),
        "item_id": str(item_id),
        "item_status": item_status,
        "document_id": str(document_id),
        "chunk_id_before": str(chunk_id_before),
        "chunk_id_after": str(chunk_id_after) if chunk_id_after is not None else None,
        "reason": reason,
        "repaired": repaired,
        "method": method,
        "meta": meta,
    }


def _patch_reference_source(reference_source: dict[str, Any], *, candidate: RepairCandidate) -> dict[str, Any]:
    patched = dict(reference_source)
    patched["chunk_id"] = str(candidate.chunk_id)
    try:
        patched["chunk_index"] = int(candidate.chunk_row.get("chunk_index") or 0)
    except Exception as exc:
        logger.debug(_EVIDENCE_REPAIR_FALLBACK_LOG_MESSAGE, exc)

    cmeta = _row_metadata(candidate.chunk_row.get("metadata"))
    pipeline_hash = str(cmeta.get("pipeline_hash") or "").strip()
    if pipeline_hash:
        patched["pipeline_hash"] = pipeline_hash
    doc_pipeline_key = str(cmeta.get("doc_pipeline_key") or "").strip()
    if doc_pipeline_key:
        patched["doc_pipeline_key"] = doc_pipeline_key

    for key, value, predicate in (
        ("page_number", candidate.chunk_row.get("page_number"), lambda v: isinstance(v, int) and v > 0),
        ("start_char", candidate.chunk_row.get("start_char"), lambda v: isinstance(v, int) and v >= 0),
        ("end_char", candidate.chunk_row.get("end_char"), lambda v: isinstance(v, int) and v >= 0),
    ):
        if predicate(value):
            patched[key] = value
    return patched


def _persist_repaired_item(
    db: Session,
    *,
    item: EvidenceItem,
    patched_refs: list[Any],
    tenant_id: UUID,
    suite_id: UUID,
    suite_dataset_id: UUID,
    actor_id: str | None,
    item_status: str,
) -> None:
    item.reference_sources = patched_refs
    db.add(item)
    db.commit()
    db.refresh(item)
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="evidence.reference_sources.repair",
            resource_type="evidence_item",
            resource_id=str(item.id),
            details={
                "suite_id": str(suite_id),
                "dataset_id": str(suite_dataset_id),
                "item_status": item_status,
                "applied": True,
            },
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug(_EVIDENCE_REPAIR_FALLBACK_LOG_MESSAGE, exc)


def _process_reference(
    db: Session,
    *,
    tenant_id: UUID,
    suite_id: UUID,
    suite_dataset_id: UUID,
    item: EvidenceItem,
    item_status: str,
    reference_source: Any,
    reference_maps: ReferenceMaps,
    report: RepairReport,
    params: RepairParams,
) -> tuple[Any, bool]:
    if not isinstance(reference_source, dict):
        return reference_source, False

    report.scanned_refs += 1
    document_id, chunk_id = _coerce_ref_ids(reference_source)
    if document_id is None or chunk_id is None:
        report.drifted_refs += 1
        return reference_source, False

    document_row = reference_maps.documents.get(document_id)
    chunk_row = reference_maps.chunks.get(chunk_id)
    ok, reason, _expected, _observed = classify_reference_source_drift(
        reference_source=reference_source,
        document_row=document_row,
        chunk_row=chunk_row,
        suite_dataset_id=suite_dataset_id,
    )
    if ok:
        return reference_source, False

    report.drifted_refs += 1
    if reason in {"document_missing", "document_dataset_mismatch"}:
        report.append_change(
            _build_change_record(
                suite_id=suite_id,
                item_id=item.id,
                item_status=item_status,
                document_id=document_id,
                chunk_id_before=chunk_id,
                chunk_id_after=None,
                reason=reason,
                repaired=False,
                method=None,
                meta={},
            )
        )
        return reference_source, False

    candidate = _find_repair_candidate(
        db,
        tenant_id=tenant_id,
        document_id=document_id,
        stale_chunk_id=chunk_id,
        reference_source=reference_source,
        document_row=document_row,
    )
    if candidate is None:
        report.append_change(
            _build_change_record(
                suite_id=suite_id,
                item_id=item.id,
                item_status=item_status,
                document_id=document_id,
                chunk_id_before=chunk_id,
                chunk_id_after=None,
                reason=reason,
                repaired=False,
                method=None,
                meta={},
            )
        )
        return reference_source, False

    report.repaired_refs += 1
    patched = _patch_reference_source(reference_source, candidate=candidate)
    needle_len = (
        len(_select_quote_needle(str(reference_source.get("quote") or "")))
        if candidate.method == "quote_needle"
        else None
    )
    report.append_change(
        _build_change_record(
            suite_id=suite_id,
            item_id=item.id,
            item_status=item_status,
            document_id=document_id,
            chunk_id_before=chunk_id,
            chunk_id_after=candidate.chunk_id,
            reason=reason,
            repaired=True,
            method=candidate.method,
            meta={"needle_len": needle_len},
        )
    )
    return patched, params.apply


def _process_item(
    db: Session,
    *,
    tenant_id: UUID,
    suite_id: UUID,
    suite_dataset_id: UUID,
    item: EvidenceItem,
    report: RepairReport,
    params: RepairParams,
    actor_id: str | None,
) -> None:
    item_status = _normalize_item_status(item)
    if item_status == "archived" and not params.include_archived_items:
        report.skipped_archived += 1
        return
    if item_status == "approved" and not params.allow_approved:
        report.skipped_approved += 1
        return

    refs = _limited_reference_sources(item, max_refs_per_item=params.max_refs_per_item)
    if not refs:
        return

    reference_maps = _load_reference_maps(db, tenant_id=tenant_id, refs=refs)
    patched_refs: list[Any] = []
    changed_item = False
    for ref in refs:
        patched_ref, ref_changed = _process_reference(
            db,
            tenant_id=tenant_id,
            suite_id=suite_id,
            suite_dataset_id=suite_dataset_id,
            item=item,
            item_status=item_status,
            reference_source=ref,
            reference_maps=reference_maps,
            report=report,
            params=params,
        )
        patched_refs.append(patched_ref)
        changed_item = changed_item or ref_changed

    if params.apply and changed_item:
        _persist_repaired_item(
            db,
            item=item,
            patched_refs=patched_refs,
            tenant_id=tenant_id,
            suite_id=suite_id,
            suite_dataset_id=suite_dataset_id,
            actor_id=actor_id,
            item_status=item_status,
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
    items = _load_suite_items(db, tenant_id=tenant_id, suite_id=suite_id, params=params)
    report = RepairReport(max_changes=params.max_changes)
    for item in items:
        _process_item(
            db,
            tenant_id=tenant_id,
            suite_id=suite_id,
            suite_dataset_id=suite_dataset_id,
            item=item,
            report=report,
            params=params,
            actor_id=actor_id,
        )
    return report.as_result(
        suite_id=suite_id,
        suite_dataset_id=suite_dataset_id,
        applied=params.apply,
        scanned_items=len(items),
    )


__all__ = [
    "EvidenceSuiteNotFoundError",
    "repair_evidence_suite_reference_sources",
    "repair_evidence_suite_reference_sources_with_dataset",
]
