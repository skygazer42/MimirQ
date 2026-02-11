"""
EvidenceSuite API (enterprise ground-truth evidence workbench).

Key goals:
- Dataset-scoped evidence assets with approval lifecycle
- Reproducible snapshots (best-effort)
- Sync approved evidence into RAGAS regression cases for retrieval-only evaluation
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.evidence import (
    EvidenceItemCreateRequest,
    EvidenceItemList,
    EvidenceItemOut,
    EvidenceItemPatchRequest,
    EvidenceSuiteCreateRequest,
    EvidenceSuiteExportV1,
    EvidenceSuiteList,
    EvidenceSuiteOut,
    EvidenceSuitePatchRequest,
    EvidenceSuiteSyncRegressionResponse,
)
from app.core.database import get_db
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.evaluation import RagasRegressionCase
from app.models.evidence import EvidenceItem, EvidenceSuite
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
