"""
EvidenceSuite API (enterprise ground-truth evidence workbench).

Key goals:
- Dataset-scoped evidence assets with approval lifecycle
- Reproducible snapshots (best-effort)
- Sync approved evidence into RAGAS regression cases for retrieval-only evaluation
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.evidence import (
    EvidenceItemCreateRequest,
    EvidenceItemImportResponse,
    EvidenceItemList,
    EvidenceItemOut,
    EvidenceItemPatchRequest,
    EvidenceSuiteCreateRequest,
    EvidenceSuiteDashboardOut,
    EvidenceSuiteExportV1,
    EvidenceSuiteList,
    EvidenceSuiteOut,
    EvidenceSuitePatchRequest,
    EvidenceSuiteSyncRegressionResponse,
)
from app.api.schemas.evidence_audit import EvidenceReferenceDriftAuditOut
from app.api.schemas.evidence_repair import (
    EvidenceReferenceRepairRequest,
    EvidenceReferenceRepairResponse,
)
from app.core.database import get_db
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.models.evaluation import RagasRegressionCase
from app.models.evidence import EvidenceItem, EvidenceSuite
from app.services.audit_log_service import audit_log_event
from app.services.dataset_service import DatasetService

router = APIRouter()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_status(item: EvidenceItem, *, expected: str) -> None:
    cur = str(getattr(item, "status", "") or "").strip().lower()
    if cur != expected:
        raise HTTPException(status_code=400, detail=f"Invalid status transition (expected {expected}, got {cur or 'unknown'})")


def _suite_counts(db: Session, *, tenant_id: UUID, suite_ids: list[UUID]) -> dict[str, dict[str, int]]:
    """
    Build per-suite status counts.

    Returns: {suite_id: {"total": n, "draft": n, "reviewed": n, "approved": n, "archived": n}}
    """
    out: dict[str, dict[str, int]] = {}
    if not suite_ids:
        return out

    rows = (
        db.query(EvidenceItem.suite_id, EvidenceItem.status, func.count(EvidenceItem.id))
        .filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id.in_(suite_ids))
        .group_by(EvidenceItem.suite_id, EvidenceItem.status)
        .all()
    )
    for suite_id, status, cnt in rows:
        sid = str(suite_id)
        st = str(status or "").strip().lower() or "unknown"
        out.setdefault(sid, {"total": 0, "draft": 0, "reviewed": 0, "approved": 0, "archived": 0})
        if st in out[sid]:
            out[sid][st] = int(cnt or 0)
        out[sid]["total"] += int(cnt or 0)

    for _sid, m in out.items():
        m.setdefault("total", sum(v for k, v in m.items() if k != "total"))
        for k in ("draft", "reviewed", "approved", "archived"):
            m.setdefault(k, 0)
    return out


def _audit_reference_sources_drift(
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
    from app.services.evidence_drift_audit_service import audit_reference_sources_drift

    return audit_reference_sources_drift(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        suite_id=suite_id,
        suite_dataset_id=suite_dataset_id,
        items=items,
        include_details=bool(include_details),
        details_limit=int(details_limit or 0),
        slice_top_n=int(slice_top_n or 0),
    )


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


@router.post("/suites/{suite_id}/repair-reference-sources", response_model=EvidenceReferenceRepairResponse)
async def repair_evidence_suite_reference_sources(
    suite_id: UUID,
    payload: EvidenceReferenceRepairRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Best-effort repair for drifted `reference_sources`.

    Repair strategy:
    1) (doc_pipeline_key + chunk_index) exact relink
    2) quote needle match (within active pipeline chunks when available)

    Safety:
    - Does not mutate approved items unless `allow_approved=true`.
    - Dry-run by default (`apply=false`).
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    if bool(payload.apply):
        DatasetService.assert_dataset_writable(db, ds, account_id)
    else:
        DatasetService.assert_dataset_readable(db, ds, account_id)

    max_items = int(payload.max_items or 0)
    q = db.query(EvidenceItem).filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
    if not bool(payload.include_archived_items):
        q = q.filter(EvidenceItem.status != "archived")
    items = q.order_by(EvidenceItem.updated_at.desc()).limit(max_items).all()

    from app.services.evidence_drift_audit import classify_reference_source_drift

    scanned_refs = 0
    drifted_refs = 0
    repaired_refs = 0
    skipped_approved = 0
    skipped_archived = 0
    changes: list[dict[str, Any]] = []
    changes_truncated = False

    def _append_change(change: dict[str, Any]) -> None:
        nonlocal changes_truncated
        if len(changes) < int(payload.max_changes or 0):
            changes.append(change)
        else:
            changes_truncated = True

    for it in items:
        st = str(getattr(it, "status", "") or "").strip().lower() or "unknown"
        if st == "archived" and not bool(payload.include_archived_items):
            skipped_archived += 1
            continue
        if st == "approved" and not bool(payload.allow_approved):
            skipped_approved += 1
            continue

        raw_refs = getattr(it, "reference_sources", None)
        refs = raw_refs if isinstance(raw_refs, list) else []
        if not refs:
            continue

        # Guardrail per item to avoid pathological payloads.
        refs = refs[: int(payload.max_refs_per_item or 0)]

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
                continue

        doc_rows = (
            db.query(DBDocument.id, DBDocument.dataset_id, DBDocument.file_type, DBDocument.doc_metadata)
            .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(sorted(doc_ids)))
            .all()
            if doc_ids
            else []
        )
        doc_map: dict[UUID, dict[str, Any]] = {
            row[0]: {"id": row[0], "dataset_id": row[1], "file_type": row[2], "metadata": row[3] if isinstance(row[3], dict) else {}}
            for row in doc_rows
            if row and row[0] is not None
        }
        chunk_rows = (
            db.query(DocumentChunk.id, DocumentChunk.document_id, DocumentChunk.chunk_index, DocumentChunk.doc_metadata, DocumentChunk.page_number, DocumentChunk.start_char, DocumentChunk.end_char, DocumentChunk.disabled_at)
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
                suite_dataset_id=suite.dataset_id,
            )
            if ok:
                patched_refs.append(ref)
                continue

            drifted_refs += 1

            # Do not attempt repair if the document is missing or out of scope.
            if reason in {"document_missing", "document_dataset_mismatch"}:
                _append_change(
                    {
                        "suite_id": suite_id,
                        "item_id": it.id,
                        "item_status": st,
                        "dataset_id": it.dataset_id,
                        "document_id": doc_uuid,
                        "chunk_id_before": chunk_uuid,
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
                            except Exception:
                                pass
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
                except Exception:
                    pass
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

                if bool(payload.apply):
                    changed_item = True
                patched_refs.append(patched)

                _append_change(
                    {
                        "suite_id": suite_id,
                        "item_id": it.id,
                        "item_status": st,
                        "dataset_id": it.dataset_id,
                        "document_id": doc_uuid,
                        "chunk_id_before": chunk_uuid,
                        "chunk_id_after": new_chunk_id,
                        "reason": reason,
                        "repaired": True,
                        "method": method,
                        "meta": {"needle_len": len(_select_quote_needle(str(ref.get("quote") or ""))) if method == "quote_needle" else None},
                    }
                )
                continue

            # No repair found.
            _append_change(
                {
                    "suite_id": suite_id,
                    "item_id": it.id,
                    "item_status": st,
                    "dataset_id": it.dataset_id,
                    "document_id": doc_uuid,
                    "chunk_id_before": chunk_uuid,
                    "chunk_id_after": None,
                    "reason": reason,
                    "repaired": False,
                    "method": None,
                    "meta": {},
                }
            )
            patched_refs.append(ref)

        if bool(payload.apply) and changed_item:
            it.reference_sources = patched_refs
            db.add(it)
            db.commit()
            db.refresh(it)
            # Best-effort audit log (do not include evidence content).
            try:
                from app.services.audit_log_service import audit_log_event

                audit_log_event(
                    db,
                    tenant_id=tenant_id,
                    actor_id=account_id,
                    action="evidence.reference_sources.repair",
                    resource_type="evidence_item",
                    resource_id=str(it.id),
                    details={
                        "suite_id": str(suite_id),
                        "dataset_id": str(suite.dataset_id),
                        "item_status": st,
                        "applied": True,
                    },
                )
                db.commit()
            except Exception:
                db.rollback()

    return EvidenceReferenceRepairResponse(
        suite_id=suite_id,
        dataset_id=suite.dataset_id,
        applied=bool(payload.apply),
        scanned_items=len(items),
        scanned_references=int(scanned_refs),
        drifted_references=int(drifted_refs),
        repaired_references=int(repaired_refs),
        skipped_approved_items=int(skipped_approved),
        skipped_archived_items=int(skipped_archived),
        changes_truncated=bool(changes_truncated),
        changes=changes,
    )


@router.post("/suites", response_model=EvidenceSuiteOut, status_code=201)
async def create_evidence_suite(
    payload: EvidenceSuiteCreateRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    ds = DatasetService.get_dataset(db, tenant_id, payload.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    row = EvidenceSuite(
        tenant_id=tenant_id,
        dataset_id=payload.dataset_id,
        name=payload.name,
        description=payload.description,
        tags=list(payload.tags or []),
        config=dict(payload.config or {}),
        created_by=account_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    out = EvidenceSuiteOut.model_validate(row).model_dump()
    out["item_counts"] = {"total": 0, "draft": 0, "reviewed": 0, "approved": 0, "archived": 0}
    return out


@router.get("/suites", response_model=EvidenceSuiteList)
async def list_evidence_suites(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    dataset_id: UUID | None = None,
    include_archived: bool = False,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    q = db.query(EvidenceSuite).filter(EvidenceSuite.tenant_id == tenant_id)
    if dataset_id is not None:
        ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)
        q = q.filter(EvidenceSuite.dataset_id == dataset_id)
    else:
        # Security trimming: list only suites under datasets readable by the caller.
        from sqlalchemy import and_, exists, or_  # noqa: WPS433

        allowed_ds = (
            db.query(Dataset.id)
            .filter(Dataset.tenant_id == tenant_id)
            .filter(
                or_(
                    Dataset.owner_id == account_id,
                    Dataset.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                    and_(
                        Dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS,
                        exists()
                        .where(DatasetPermission.tenant_id == tenant_id)
                        .where(DatasetPermission.dataset_id == Dataset.id)
                        .where(DatasetPermission.account_id == account_id),
                    ),
                )
            )
            .subquery()
        )
        q = q.filter(EvidenceSuite.dataset_id.in_(allowed_ds))
    if not include_archived:
        q = q.filter(EvidenceSuite.archived_at.is_(None))

    total = q.count()
    suites = q.order_by(EvidenceSuite.updated_at.desc()).offset(skip).limit(limit).all()
    suite_ids = [s.id for s in suites if s and s.id]
    counts = _suite_counts(db, tenant_id=tenant_id, suite_ids=suite_ids)

    items_out: list[dict[str, Any]] = []
    for s in suites:
        out = EvidenceSuiteOut.model_validate(s).model_dump()
        out["item_counts"] = counts.get(str(s.id)) or {"total": 0, "draft": 0, "reviewed": 0, "approved": 0, "archived": 0}
        items_out.append(out)

    return {"total": total, "items": items_out}


@router.get("/suites/{suite_id}", response_model=EvidenceSuiteOut)
async def get_evidence_suite(
    suite_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Suite not found")

    ds = DatasetService.get_dataset(db, tenant_id, row.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    counts = _suite_counts(db, tenant_id=tenant_id, suite_ids=[row.id])
    out = EvidenceSuiteOut.model_validate(row).model_dump()
    out["item_counts"] = counts.get(str(row.id)) or {"total": 0, "draft": 0, "reviewed": 0, "approved": 0, "archived": 0}
    return out


@router.get("/suites/{suite_id}/dashboard", response_model=EvidenceSuiteDashboardOut)
async def get_evidence_suite_dashboard(
    suite_id: UUID,
    include_archived_items: bool = False,
    top_n: int = Query(default=12, ge=1, le=50),
    heatmap_top_n: int = Query(default=8, ge=2, le=20),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Suite-level dashboard: status counts + slice coverage + throughput metrics.

    Coverage is derived from reference_sources by resolving referenced documents.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    # Counts: include archived so the dashboard matches suite list badges.
    counts = _suite_counts(db, tenant_id=tenant_id, suite_ids=[suite_id])
    item_counts = counts.get(str(suite_id)) or {"total": 0, "draft": 0, "reviewed": 0, "approved": 0, "archived": 0}

    q = db.query(EvidenceItem).filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
    if not include_archived_items:
        q = q.filter(EvidenceItem.status != "archived")
    items = q.order_by(EvidenceItem.updated_at.desc()).limit(10_000).all()

    # Resolve document slice metadata (language/file_type/quality bucket).
    doc_ids: set[UUID] = set()
    for it in items:
        refs = it.reference_sources if isinstance(getattr(it, "reference_sources", None), list) else []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            try:
                doc_ids.add(UUID(str(ref.get("document_id"))))
            except Exception:
                continue

    doc_map: dict[UUID, dict[str, Any]] = {}
    if doc_ids:
        doc_rows = (
            db.query(DBDocument.id, DBDocument.file_type, DBDocument.doc_metadata)
            .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(sorted(doc_ids)))
            .all()
        )
        for did, ft, meta in doc_rows:
            if did is None:
                continue
            doc_map[did] = {
                "id": did,
                "file_type": str(ft or "").strip().lower() or "unknown",
                "metadata": meta if isinstance(meta, dict) else {},
            }

    from app.services.evidence_dashboard import compute_suite_coverage, compute_suite_throughput  # noqa: WPS433

    now = _now_utc()
    throughput = compute_suite_throughput(items, now=now, window_days=7)
    coverage = compute_suite_coverage(items, documents=doc_map, top_n=int(top_n), heatmap_top_n=int(heatmap_top_n))

    return EvidenceSuiteDashboardOut(
        generated_at=now,
        suite_id=suite_id,
        dataset_id=suite.dataset_id,
        item_counts=item_counts,
        coverage=coverage,
        throughput=throughput,
    )


@router.patch("/suites/{suite_id}", response_model=EvidenceSuiteOut)
async def patch_evidence_suite(
    suite_id: UUID,
    payload: EvidenceSuitePatchRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Suite not found")

    ds = DatasetService.get_dataset(db, tenant_id, row.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    fields = set(getattr(payload, "model_fields_set", set()) or set())
    if "name" in fields and payload.name is not None:
        row.name = payload.name
    if "description" in fields:
        row.description = payload.description
    if "tags" in fields and payload.tags is not None:
        row.tags = list(payload.tags or [])
    if "config" in fields and payload.config is not None:
        row.config = dict(payload.config or {})
    if "archived_at" in fields:
        row.archived_at = payload.archived_at

    db.add(row)
    db.commit()
    db.refresh(row)

    counts = _suite_counts(db, tenant_id=tenant_id, suite_ids=[row.id])
    out = EvidenceSuiteOut.model_validate(row).model_dump()
    out["item_counts"] = counts.get(str(row.id)) or {"total": 0, "draft": 0, "reviewed": 0, "approved": 0, "archived": 0}
    return out


@router.get("/suites/{suite_id}/drift-audit", response_model=EvidenceReferenceDriftAuditOut)
async def audit_evidence_suite_reference_sources_drift(
    suite_id: UUID,
    include_archived_items: bool = False,
    include_details: bool = True,
    details_limit: int = Query(default=200, ge=0, le=2000),
    slice_top_n: int = Query(default=20, ge=1, le=200),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    q = db.query(EvidenceItem).filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
    if not include_archived_items:
        q = q.filter(EvidenceItem.status != "archived")
    items = q.order_by(EvidenceItem.updated_at.desc()).limit(5000).all()

    return _audit_reference_sources_drift(
        db,
        tenant_id=tenant_id,
        dataset_id=suite.dataset_id,
        suite_id=suite_id,
        suite_dataset_id=suite.dataset_id,
        items=items,
        include_details=bool(include_details),
        details_limit=int(details_limit or 0),
        slice_top_n=int(slice_top_n or 0),
    )


@router.get("/datasets/{dataset_id}/drift-audit", response_model=EvidenceReferenceDriftAuditOut)
async def audit_dataset_reference_sources_drift(
    dataset_id: UUID,
    include_archived_items: bool = False,
    include_details: bool = True,
    details_limit: int = Query(default=200, ge=0, le=2000),
    slice_top_n: int = Query(default=20, ge=1, le=200),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    suite_ids = [
        row[0]
        for row in (
            db.query(EvidenceSuite.id)
            .filter(EvidenceSuite.tenant_id == tenant_id, EvidenceSuite.dataset_id == dataset_id, EvidenceSuite.archived_at.is_(None))
            .all()
        )
        if row and row[0] is not None
    ]
    if not suite_ids:
        return EvidenceReferenceDriftAuditOut(
            generated_at=_now_utc(),
            dataset_id=dataset_id,
            suite_id=None,
            total_items=0,
            total_references=0,
            ok_references=0,
            drift_references=0,
            drift_rate=0.0,
            reasons={},
            slices={},
            details_truncated=False,
            drifted_references=[],
        )

    q = db.query(EvidenceItem).filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id.in_(suite_ids))
    if not include_archived_items:
        q = q.filter(EvidenceItem.status != "archived")
    items = q.order_by(EvidenceItem.updated_at.desc()).limit(10_000).all()

    return _audit_reference_sources_drift(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        suite_id=None,
        suite_dataset_id=dataset_id,
        items=items,
        include_details=bool(include_details),
        details_limit=int(details_limit or 0),
        slice_top_n=int(slice_top_n or 0),
    )


@router.post("/suites/{suite_id}/items", response_model=EvidenceItemOut, status_code=201)
async def create_evidence_item(
    suite_id: UUID,
    payload: EvidenceItemCreateRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")
    if suite.archived_at is not None:
        raise HTTPException(status_code=400, detail="Suite is archived")

    if payload.suite_id != suite_id:
        raise HTTPException(status_code=400, detail="suite_id mismatch")
    if payload.dataset_id != suite.dataset_id:
        raise HTTPException(status_code=400, detail="dataset_id mismatch")

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    # Normalize and validate evidence pointers before persisting.
    from app.api.v1.evaluations import _finalize_reference_sources  # noqa: WPS433

    reference_sources = _finalize_reference_sources(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=suite.dataset_id,
        reference_sources=payload.reference_sources,
    )

    row = EvidenceItem(
        tenant_id=tenant_id,
        dataset_id=suite.dataset_id,
        suite_id=suite.id,
        status="draft",
        query=payload.query,
        expected_answer=payload.expected_answer,
        tags=list(payload.tags or []),
        source_metadata=dict(payload.source_metadata or {}),
        reference_sources=reference_sources,
        retrieval_snapshot=dict(payload.retrieval_snapshot or {}),
        rag_config_snapshot=dict(payload.rag_config_snapshot or {}),
        notes=payload.notes,
        created_by=account_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/suites/{suite_id}/items/import", response_model=EvidenceItemImportResponse)
async def import_evidence_items(
    suite_id: UUID,
    file: UploadFile = File(...),
    max_items: int = Query(default=2000, ge=1, le=10_000),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Import QA/FAQ rows (CSV/JSONL) as draft EvidenceItems.

    Notes:
    - Imported items are created in `draft` status.
    - reference_sources starts empty; users can later label evidence and progress review/approve.
    - Dedupes by query (query.strip(), whitespace-collapsed) within the suite.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")
    if suite.archived_at is not None:
        raise HTTPException(status_code=400, detail="Suite is archived")

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    max_bytes = 5 * 1024 * 1024
    raw = await file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(status_code=400, detail="import file too large (max 5MB)")

    from app.services.evidence_item_import import parse_qa_faq_import_bytes, plan_evidence_item_import  # noqa: WPS433

    try:
        items, parse_errors = parse_qa_faq_import_bytes(raw=raw, filename=getattr(file, "filename", None), max_items=int(max_items))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:200]) from exc

    def _norm(s: Any) -> str:
        return " ".join(str(s or "").strip().split())

    existing_rows = (
        db.query(EvidenceItem.query)
        .filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
        .all()
    )
    existing = {_norm(r[0]) for r in existing_rows if r and r[0] is not None}

    plan = plan_evidence_item_import(existing_queries=existing, items=items, max_items=int(max_items))
    created = 0
    skipped = int(plan.get("skipped") or 0) + int(len(parse_errors))
    errors: list[dict[str, Any]] = list(parse_errors or []) + list(plan.get("errors") or [])

    for payload in plan.get("create_items") or []:
        try:
            row = EvidenceItem(
                tenant_id=tenant_id,
                dataset_id=suite.dataset_id,
                suite_id=suite.id,
                status="draft",
                query=str(payload.get("query") or "").strip(),
                expected_answer=payload.get("expected_answer"),
                reference_sources=[],
                retrieval_snapshot={"created_from": "qa_faq_import"},
                rag_config_snapshot={},
                notes=None,
                tags=list(payload.get("tags") or []),
                source_metadata=dict(payload.get("source_metadata") or {}),
                created_by=account_id,
            )
            db.add(row)
            created += 1
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            errors.append({"query": payload.get("query"), "error": str(exc)[:200]})

    db.commit()

    return EvidenceItemImportResponse(
        suite_id=suite_id,
        dataset_id=suite.dataset_id,
        parsed=int(len(items)),
        created=int(created),
        skipped=int(skipped),
        errors=errors,
    )


@router.get("/suites/{suite_id}/items", response_model=EvidenceItemList)
async def list_evidence_items(
    suite_id: UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status: Optional[str] = None,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    q = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
    )
    if status:
        q = q.filter(EvidenceItem.status == str(status).strip().lower())

    total = q.count()
    items = q.order_by(EvidenceItem.updated_at.desc()).offset(skip).limit(limit).all()
    return {"total": total, "items": items}


@router.patch("/items/{item_id}", response_model=EvidenceItemOut)
async def patch_evidence_item(
    item_id: UUID,
    payload: EvidenceItemPatchRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.id == item_id, EvidenceItem.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == row.suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    # Keep lifecycle strict: only editable in draft.
    _ensure_status(row, expected="draft")

    fields = set(getattr(payload, "model_fields_set", set()) or set())
    if "query" in fields and payload.query is not None:
        row.query = payload.query
    if "expected_answer" in fields:
        row.expected_answer = payload.expected_answer
    if "tags" in fields and payload.tags is not None:
        row.tags = list(payload.tags or [])
    if "source_metadata" in fields and payload.source_metadata is not None:
        row.source_metadata = dict(payload.source_metadata or {})
    if "notes" in fields:
        row.notes = payload.notes
    if "retrieval_snapshot" in fields and payload.retrieval_snapshot is not None:
        row.retrieval_snapshot = dict(payload.retrieval_snapshot or {})
    if "rag_config_snapshot" in fields and payload.rag_config_snapshot is not None:
        row.rag_config_snapshot = dict(payload.rag_config_snapshot or {})
    if "reference_sources" in fields and payload.reference_sources is not None:
        from app.api.v1.evaluations import _finalize_reference_sources  # noqa: WPS433

        row.reference_sources = _finalize_reference_sources(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=suite.dataset_id,
            reference_sources=payload.reference_sources,
        )

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/items/{item_id}/review", response_model=EvidenceItemOut)
async def review_evidence_item(
    item_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.id == item_id, EvidenceItem.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == row.suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    _ensure_status(row, expected="draft")
    refs = row.reference_sources if isinstance(getattr(row, "reference_sources", None), list) else []
    if not refs:
        raise HTTPException(status_code=400, detail="Cannot review item without reference_sources")
    row.status = "reviewed"
    row.reviewed_by = account_id
    row.reviewed_at = _now_utc()

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/items/{item_id}/approve", response_model=EvidenceItemOut)
async def approve_evidence_item(
    item_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.id == item_id, EvidenceItem.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == row.suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    _ensure_status(row, expected="reviewed")
    refs = row.reference_sources if isinstance(getattr(row, "reference_sources", None), list) else []
    if not refs:
        raise HTTPException(status_code=400, detail="Cannot approve item without reference_sources")
    row.status = "approved"
    row.approved_by = account_id
    row.approved_at = _now_utc()

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/items/{item_id}/archive", response_model=EvidenceItemOut)
async def archive_evidence_item(
    item_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.id == item_id, EvidenceItem.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Item not found")

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == row.suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    cur = str(getattr(row, "status", "") or "").strip().lower()
    if cur == "archived":
        return row

    row.status = "archived"
    row.archived_by = account_id
    row.archived_at = _now_utc()

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/suites/{suite_id}/sync-regression", response_model=EvidenceSuiteSyncRegressionResponse)
async def sync_suite_to_regression_cases(
    suite_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    approved_items = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.tenant_id == tenant_id,
            EvidenceItem.suite_id == suite_id,
            EvidenceItem.status == "approved",
        )
        .order_by(EvidenceItem.updated_at.desc())
        .all()
    )

    from app.api.v1.evaluations import _finalize_reference_sources  # noqa: WPS433

    created = 0
    updated = 0
    skipped = 0
    errors: list[dict[str, Any]] = []

    for item in approved_items:
        try:
            refs = _finalize_reference_sources(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=suite.dataset_id,
                reference_sources=list(item.reference_sources or []),
            )
            if not refs:
                skipped += 1
                continue

            tags = ["evidence_suite", f"evidence_suite:{str(suite_id)}"]
            extra = {
                "evidence_suite_id": str(suite_id),
                "evidence_item_id": str(item.id),
            }

            case: RagasRegressionCase | None = None
            if item.regression_case_id:
                case = (
                    db.query(RagasRegressionCase)
                    .filter(RagasRegressionCase.id == item.regression_case_id, RagasRegressionCase.tenant_id == tenant_id)
                    .first()
                )

            if case is None:
                case = RagasRegressionCase(
                    tenant_id=tenant_id,
                    dataset_id=suite.dataset_id,
                    document_ids=[],
                    question=item.query,
                    expected_answer=item.expected_answer,
                    reference_sources=refs,
                    tags=tags,
                    extra=extra,
                    created_by=account_id,
                )
                db.add(case)
                db.commit()
                db.refresh(case)
                item.regression_case_id = case.id
                db.add(item)
                db.commit()
                created += 1
                continue

            # Update existing case (dataset_id immutable, enforce match).
            if case.dataset_id is not None and UUID(str(case.dataset_id)) != suite.dataset_id:
                raise HTTPException(status_code=400, detail="Existing regression case dataset mismatch")

            case.question = item.query
            case.expected_answer = item.expected_answer
            case.reference_sources = refs

            existing_tags = case.tags if isinstance(case.tags, list) else []
            merged_tags = []
            seen: set[str] = set()
            for t in list(existing_tags) + tags:
                s = str(t or "").strip()
                if not s or s in seen:
                    continue
                seen.add(s)
                merged_tags.append(s)
            case.tags = merged_tags

            existing_extra = case.extra if isinstance(case.extra, dict) else {}
            merged_extra = dict(existing_extra)
            merged_extra.update(extra)
            case.extra = merged_extra

            db.add(case)
            db.commit()
            updated += 1
        except Exception as exc:  # noqa: BLE001
            errors.append({"item_id": str(item.id), "error": str(exc)[:200]})

    return EvidenceSuiteSyncRegressionResponse(
        suite_id=suite_id,
        dataset_id=suite.dataset_id,
        created=created,
        updated=updated,
        skipped=skipped,
        errors=errors,
    )


@router.get("/suites/{suite_id}/export", response_model=EvidenceSuiteExportV1)
async def export_evidence_suite(
    suite_id: UUID,
    include_archived_items: bool = False,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    q = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
        .order_by(EvidenceItem.created_at.asc())
    )
    if not include_archived_items:
        q = q.filter(EvidenceItem.status != "archived")
    items = q.all()

    suite_payload = {
        "id": str(suite.id),
        "name": suite.name,
        "description": suite.description,
        "tags": list(suite.tags or []),
        "config": dict(suite.config or {}),
        "created_by": suite.created_by,
        "created_at": suite.created_at.isoformat() if suite.created_at else None,
        "updated_at": suite.updated_at.isoformat() if suite.updated_at else None,
    }
    items_payload: list[dict[str, Any]] = []
    for it in items:
        items_payload.append(
            {
                "id": str(it.id),
                "status": it.status,
                "query": it.query,
                "expected_answer": it.expected_answer,
                "tags": list(getattr(it, "tags", []) or []),
                "source_metadata": dict(getattr(it, "source_metadata", {}) or {}),
                "reference_sources": it.reference_sources,
                "retrieval_snapshot": it.retrieval_snapshot or {},
                "rag_config_snapshot": it.rag_config_snapshot or {},
                "notes": it.notes,
                "regression_case_id": str(it.regression_case_id) if it.regression_case_id else None,
                "created_by": it.created_by,
                "reviewed_by": it.reviewed_by,
                "approved_by": it.approved_by,
                "archived_by": it.archived_by,
                "reviewed_at": it.reviewed_at.isoformat() if it.reviewed_at else None,
                "approved_at": it.approved_at.isoformat() if it.approved_at else None,
                "archived_at": it.archived_at.isoformat() if it.archived_at else None,
                "created_at": it.created_at.isoformat() if it.created_at else None,
                "updated_at": it.updated_at.isoformat() if it.updated_at else None,
            }
        )

    return EvidenceSuiteExportV1(
        exported_at=_now_utc().isoformat(),
        dataset_id=suite.dataset_id,
        suite=suite_payload,
        items=items_payload,
    )


@router.get("/suites/{suite_id}/export-ltr-training")
async def export_evidence_suite_ltr_training_bundle(
    suite_id: UUID,
    include_archived_items: bool = False,
    max_items: int = Query(default=2000, ge=1, le=10_000, description="Max items to include in export"),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Export a PII-minimized LTR training bundle from an Evidence Suite.

    Contents:
    - manifest.json: export metadata + feature spec
    - training_rows.ndjson: per-citation features + labels (0/1), grouped by query_hash
    - hard_negatives.ndjson: mined near-miss negatives (PII-safe) per query_hash

    Notes:
    - This endpoint intentionally avoids including raw query text in training rows.
    - It relies on per-item retrieval_snapshot for reproducibility; items without a snapshot are skipped.
    """
    from app.core.config import settings
    from app.rag.core.hashing import stable_hash
    from app.rag.evaluation.hard_negative_mining import mine_hard_negatives_for_case_from_trace
    from app.rag.reranker.ltr import LTRFeatureSpec, extract_ltr_features
    from app.rag.reranker.types import RerankCandidate

    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    q = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
        .order_by(EvidenceItem.created_at.asc())
        .limit(int(max_items or 0))
    )
    if not include_archived_items:
        q = q.filter(EvidenceItem.status != "archived")
    items = q.all()

    exported_at = _now_utc()

    spec_version = int(getattr(settings, "LTR_FEATURE_SPEC_VERSION", 1) or 1)
    spec = LTRFeatureSpec.from_version(spec_version)

    def _as_float(v: Any) -> float:
        try:
            if v is None:
                return 0.0
            return float(v)
        except Exception:
            return 0.0

    def _extract_reference_chunk_ids(item: EvidenceItem) -> set[str]:
        refs = getattr(item, "reference_sources", None) or []
        if not isinstance(refs, list):
            return set()
        out: set[str] = set()
        for src in refs:
            if not isinstance(src, dict):
                continue
            cid = str(src.get("chunk_id") or "").strip()
            if cid:
                out.add(cid)
        return out

    training_lines: list[str] = []
    hard_lines: list[str] = []

    items_total = int(len(items))
    items_with_snapshot = 0
    rows_total = 0
    hard_total = 0

    for it in items:
        snap = getattr(it, "retrieval_snapshot", None) or {}
        if not isinstance(snap, dict):
            continue
        citations = snap.get("citations") or []
        if not isinstance(citations, list) or not citations:
            continue

        items_with_snapshot += 1

        query = str(getattr(it, "query", "") or "")
        query_hash = stable_hash(query, length=64)
        ref_chunk_ids = _extract_reference_chunk_ids(it)

        metrics = snap.get("metrics") if isinstance(snap.get("metrics"), dict) else {}
        retrieval_cfg_hash = str(metrics.get("retrieval_config_hash") or "").strip() or None
        if retrieval_cfg_hash is None:
            # Best-effort: try to recover from retrieval_trace.
            trace = snap.get("retrieval_trace") if isinstance(snap.get("retrieval_trace"), dict) else None
            fp = (trace or {}).get("retrieval_config") if isinstance((trace or {}).get("retrieval_config"), dict) else None
            maybe = (fp or {}).get("hash") if isinstance(fp, dict) else None
            retrieval_cfg_hash = str(maybe or "").strip() or None

        # Training rows: per-citation features + labels.
        for rank, c in enumerate(citations, 1):
            if not isinstance(c, dict):
                continue
            cid = str(c.get("chunk_id") or "").strip()
            if not cid:
                continue

            meta = {
                "vector_score": _as_float(c.get("vector_score")),
                "bm25_score": _as_float(c.get("bm25_score")),
                "lexical_score": _as_float(c.get("lexical_score")),
                "sparse_score": _as_float(c.get("sparse_score")),
                # Prefer evidence API's overall score (relevance_score).
                "score": _as_float(c.get("relevance_score") or c.get("retrieval_score") or c.get("score")),
                "retrieval_role": c.get("retrieval_role"),
                # Optional KG ranking signals (low-cardinality, numeric only).
                "kg_pagerank": _as_float(c.get("kg_pagerank")),
                "kg_shared_events": _as_float(c.get("kg_shared_events")),
                "kg_path_length": _as_float(c.get("kg_path_length")),
                "kg_edge_conf_low": _as_float(c.get("kg_edge_conf_low")),
                "kg_edge_conf_mid": _as_float(c.get("kg_edge_conf_mid")),
                "kg_edge_conf_high": _as_float(c.get("kg_edge_conf_high")),
                "kg_evidence_anchored": _as_float(c.get("kg_evidence_anchored")),
            }
            values = extract_ltr_features(
                spec=spec,
                query="",  # reserved for future query-dependent features; keep export PII-minimized
                candidate=RerankCandidate(id=cid, text="", metadata=meta),
            )
            features = {name: float(v) for name, v in zip(spec.feature_names, values, strict=False)}

            row = {
                "schema": "mimirq.ltr_training_row.v1",
                "suite_id": str(suite.id),
                "item_id": str(it.id),
                "dataset_id": str(suite.dataset_id),
                "query_hash": query_hash,
                "retrieval_config_hash": retrieval_cfg_hash,
                "rank": int(rank),
                "label": int(1 if cid in ref_chunk_ids else 0),
                "candidate": {
                    "chunk_id": cid,
                    "document_id": str(c.get("document_id") or "").strip() or None,
                },
                "slices": {
                    "status": str(getattr(it, "status", "") or "").strip().lower() or None,
                    "tags": list(getattr(it, "tags", []) or []),
                },
                "features": features,
            }
            training_lines.append(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str))
            rows_total += 1

        # Hard negatives: near-miss negatives before first positive (PII-safe).
        try:
            trace_record = {
                "citations": citations,
                "retrieval": {"retrieval_config_hash": retrieval_cfg_hash},
            }
            case = {"reference_sources": getattr(it, "reference_sources", None) or []}
            hn = mine_hard_negatives_for_case_from_trace(
                case=case,
                trace_record=trace_record,
                query_hash=query_hash,
                max_hard_negatives=10,
                max_negatives_per_document=2,
            )
            if isinstance(hn, dict):
                hn["suite_id"] = str(suite.id)
                hn["item_id"] = str(it.id)
                hn["dataset_id"] = str(suite.dataset_id)
                hn["tags"] = list(getattr(it, "tags", []) or [])
                hard_lines.append(json.dumps(hn, ensure_ascii=False, separators=(",", ":"), default=str))
                hard_total += 1
        except Exception:
            # Hard negatives are best-effort; training rows are the primary export.
            pass

    manifest: dict[str, Any] = {
        "schema": "mimirq.ltr_training_export.v1",
        "exported_at": exported_at.isoformat(),
        "tenant_id": str(tenant_id),
        "dataset_id": str(suite.dataset_id),
        "suite": {
            "id": str(suite.id),
            "name": str(getattr(suite, "name", "") or ""),
            "tags": list(getattr(suite, "tags", []) or []),
            "include_archived_items": bool(include_archived_items),
            "max_items": int(max_items or 0),
        },
        "feature_spec": {
            "version": int(spec_version),
            "schema": str(spec.schema),
            "feature_names": list(spec.feature_names),
        },
        "counts": {
            "items_total": int(items_total),
            "items_with_snapshot": int(items_with_snapshot),
            "training_rows": int(rows_total),
            "hard_negative_records": int(hard_total),
        },
    }

    # Best-effort audit log (PII-minimal).
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="evidence_suite.export_ltr_training",
            resource_type="evidence_suite",
            resource_id=str(suite_id),
            details={
                "dataset_id": str(suite.dataset_id),
                "items_total": int(items_total),
                "items_with_snapshot": int(items_with_snapshot),
                "training_rows": int(rows_total),
                "hard_negative_records": int(hard_total),
                "feature_spec_version": int(spec_version),
            },
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    # Write ZIP bundle in memory (bounded by max_items).
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), default=str))
        zf.writestr(
            "training_rows.ndjson",
            ("\n".join(training_lines) + ("\n" if training_lines else "")).encode("utf-8"),
        )
        zf.writestr(
            "hard_negatives.ndjson",
            ("\n".join(hard_lines) + ("\n" if hard_lines else "")).encode("utf-8"),
        )
        zf.writestr(
            "README.txt",
            (
                "MimirQ Evidence Suite LTR Training Export\n\n"
                "- manifest.json: export metadata + LTR feature spec\n"
                "- training_rows.ndjson: one row per (query_hash, candidate chunk_id) with features + label\n"
                "- hard_negatives.ndjson: mined near-miss negatives (PII-safe) per query_hash\n"
                "\n"
                "Notes:\n"
                "- training_rows is PII-minimized: it does not include raw query text.\n"
                "- This export relies on per-item retrieval_snapshot for reproducibility.\n"
            ),
        )

    raw = buf.getvalue()
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(getattr(suite, "name", "") or "evidence_suite"))[:64]
    filename = f"{safe}.ltr_training.zip"
    return Response(
        content=raw,
        media_type="application/zip",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
