"""
Dataset management API.
Supports dataset creation, query, update, deletion, and permission management.
"""
import json
import re

from fastapi import APIRouter, BackgroundTasks, Depends, Query, UploadFile, File, Form, HTTPException, Response
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.database import get_db
from app.core.database import SessionLocal
from app.api.dependencies.tenant import get_tenant_id
from app.api.dependencies.auth import get_current_account_id
from app.api.schemas.dataset import DatasetCreate, DatasetUpdate, DatasetOut, DatasetListResponse
from app.api.schemas.document import DocumentPipelineOptions
from app.api.schemas.ingestion_policy import IngestionPolicy, IngestionPolicyImportResponse
from app.api.schemas.dataset_profile import (
    DatasetProfileSummary,
    DatasetProfileFindingListResponse,
    DatasetProfileScanRunCreateRequest,
    DatasetProfileScanRunListResponse,
    DatasetProfileScanRunOut,
)
from app.models.dataset import DatasetPermissionEnum, DatasetPermission
from app.services.dataset_service import DatasetService, DatasetPermissionService
from app.models.dataset import Dataset
from app.models.dataset_profile_scan import DatasetProfileScanRun as DBDatasetProfileScanRun
from app.services.pipeline_config import build_pipeline_metadata, parse_pipeline_from_metadata
from app.services.ingestion_policy import (
    export_policy_json,
    parse_ingestion_policy_from_metadata,
    validate_and_normalize_ingestion_policy,
)
from app.types.pipeline import PipelineOptions
from app.tasks.queue import enqueue_dataset_profile_scan
from app.services.dataset_profile_service import compute_dataset_profile_summary, list_finding_documents
from app.services.dataset_profile_scan_runner import run_dataset_profile_deep_scan

router = APIRouter()

def _dataset_pipeline_out(ds: Dataset) -> DocumentPipelineOptions | None:
    meta = getattr(ds, "dataset_metadata", None)
    if not isinstance(meta, dict):
        return None
    opts = parse_pipeline_from_metadata(meta)
    data = {k: getattr(opts, k) for k in opts.__dataclass_fields__}  # type: ignore[attr-defined]
    # Only return if any pipeline override exists
    if not any(v is not None for v in data.values()):
        return None
    return DocumentPipelineOptions(**data)


@router.post("/", response_model=DatasetOut, status_code=201)
def create_dataset(
    payload: DatasetCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    dataset = DatasetService.create_dataset(
        db=db,
        tenant_id=tenant_id,
        name=payload.name,
        description=payload.description,
        permission=payload.permission,
        owner_id=account_id,
        partial_members=payload.partial_member_list or [],
    )

    # Optional dataset-level pipeline defaults.
    if payload.pipeline is not None:
        options = PipelineOptions(**payload.pipeline.model_dump(exclude_none=True))
        pipeline_meta = build_pipeline_metadata(options)
        meta = dict(getattr(dataset, "dataset_metadata", None) or {})
        if pipeline_meta:
            meta["pipeline"] = pipeline_meta
        else:
            meta.pop("pipeline", None)
        dataset.dataset_metadata = meta
        db.commit()
        db.refresh(dataset)

    partial_list = None
    if dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
        partial_list = payload.partial_member_list or []

    return DatasetOut(
        id=dataset.id,
        tenant_id=dataset.tenant_id,
        name=dataset.name,
        description=dataset.description,
        permission=dataset.permission,
        owner_id=dataset.owner_id,
        partial_member_list=partial_list
        ,
        pipeline=_dataset_pipeline_out(dataset),
    )


@router.get("/", response_model=DatasetListResponse)
def list_datasets(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    # list all datasets in tenant
    query = db.query(Dataset).filter(Dataset.tenant_id == tenant_id)
    total = query.count()
    datasets = query.order_by(Dataset.created_at.desc()).offset(skip).limit(limit).all()

    # Avoid N+1 queries for PARTIAL_MEMBERS datasets
    partial_ids = [ds.id for ds in datasets if ds.permission == DatasetPermissionEnum.PARTIAL_MEMBERS]
    partial_member_map = {}
    if partial_ids:
        rows = (
            db.query(DatasetPermission)
            .filter(
                DatasetPermission.tenant_id == tenant_id,
                DatasetPermission.dataset_id.in_(partial_ids),
            )
            .all()
        )
        from collections import defaultdict

        tmp = defaultdict(list)
        for row in rows:
            tmp[row.dataset_id].append(row.account_id)
        partial_member_map = dict(tmp)

    results = []
    for ds in datasets:
        partial_list = None
        if ds.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
            partial_list = partial_member_map.get(ds.id, [])
        results.append(DatasetOut(
            id=ds.id,
            tenant_id=ds.tenant_id,
            name=ds.name,
            description=ds.description,
            permission=ds.permission,
            owner_id=ds.owner_id,
            partial_member_list=partial_list,
            pipeline=_dataset_pipeline_out(ds),
        ))
    return {"total": total, "items": results}


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(
    dataset_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)
    partial_list = None
    if dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
        partial_list = DatasetPermissionService.get_dataset_partial_member_list(db, tenant_id, dataset_id)
    return DatasetOut(
        id=dataset.id,
        tenant_id=dataset.tenant_id,
        name=dataset.name,
        description=dataset.description,
        permission=dataset.permission,
        owner_id=dataset.owner_id,
        partial_member_list=partial_list,
        pipeline=_dataset_pipeline_out(dataset),
    )


@router.patch("/{dataset_id}", response_model=DatasetOut)
def update_dataset(
    dataset_id: UUID,
    payload: DatasetUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)

    updated = DatasetService.update_dataset(
        db=db,
        dataset=dataset,
        updater_id=account_id,
        name=payload.name,
        description=payload.description,
        permission=payload.permission,
        partial_members=payload.partial_member_list,
    )

    # Update dataset-level pipeline defaults (stored in datasets.metadata.pipeline).
    if payload.pipeline is not None:
        options = PipelineOptions(**payload.pipeline.model_dump(exclude_none=True))
        pipeline_meta = build_pipeline_metadata(options)
        meta = dict(getattr(updated, "dataset_metadata", None) or {})
        if pipeline_meta:
            meta["pipeline"] = pipeline_meta
        else:
            meta.pop("pipeline", None)
        updated.dataset_metadata = meta
        db.commit()
        db.refresh(updated)

    partial_list = None
    if updated.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
        partial_list = DatasetPermissionService.get_dataset_partial_member_list(db, tenant_id, updated.id)

    return DatasetOut(
        id=updated.id,
        tenant_id=updated.tenant_id,
        name=updated.name,
        description=updated.description,
        permission=updated.permission,
        owner_id=updated.owner_id,
        partial_member_list=partial_list,
        pipeline=_dataset_pipeline_out(updated),
    )


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db)
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)
    db.delete(dataset)
    db.commit()
    return None


@router.get("/{dataset_id}/ingestion-policy", response_model=IngestionPolicy)
def get_dataset_ingestion_policy(
    dataset_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)
    meta = getattr(dataset, "dataset_metadata", None)
    policy = parse_ingestion_policy_from_metadata(meta if isinstance(meta, dict) else {}) or IngestionPolicy(version="1", rules=[])
    return policy


@router.put("/{dataset_id}/ingestion-policy", response_model=IngestionPolicy)
def put_dataset_ingestion_policy(
    dataset_id: UUID,
    payload: IngestionPolicy,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)

    normalized = validate_and_normalize_ingestion_policy(payload)
    meta = dict(getattr(dataset, "dataset_metadata", None) or {})
    if normalized.rules:
        meta["ingestion_policy"] = normalized.model_dump()
    else:
        meta.pop("ingestion_policy", None)
    dataset.dataset_metadata = meta
    db.commit()
    db.refresh(dataset)
    return normalized


@router.post("/{dataset_id}/ingestion-policy/import", response_model=IngestionPolicyImportResponse)
async def import_dataset_ingestion_policy(
    dataset_id: UUID,
    file: UploadFile = File(...),
    replace: bool = Form(default=True),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)

    max_bytes = 256 * 1024
    raw = await file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(status_code=400, detail="policy file too large (max 256KB)")
    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON (expect UTF-8)")

    try:
        model = IngestionPolicy(**obj)
        normalized = validate_and_normalize_ingestion_policy(model)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid ingestion policy: {str(exc)[:200]}")

    meta = dict(getattr(dataset, "dataset_metadata", None) or {})
    if not replace and "ingestion_policy" in meta:
        # Best-effort: do not merge in v1 (explicit by design).
        raise HTTPException(status_code=409, detail="ingestion_policy already exists; set replace=true to overwrite")
    if normalized.rules:
        meta["ingestion_policy"] = normalized.model_dump()
    else:
        meta.pop("ingestion_policy", None)
    dataset.dataset_metadata = meta
    db.commit()
    db.refresh(dataset)
    return IngestionPolicyImportResponse(replaced=True, rule_count=len(normalized.rules))


@router.get("/{dataset_id}/ingestion-policy/export")
def export_dataset_ingestion_policy(
    dataset_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)
    meta = getattr(dataset, "dataset_metadata", None)
    policy = parse_ingestion_policy_from_metadata(meta if isinstance(meta, dict) else {}) or IngestionPolicy(version="1", rules=[])

    content = export_policy_json(policy)
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(getattr(dataset, "name", "") or "dataset"))[:64]
    filename = f"{safe}.ingestion-policy.json"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _scan_run_out_from_row(row: DBDatasetProfileScanRun) -> DatasetProfileScanRunOut:
    cfg = getattr(row, "config", None)
    if not isinstance(cfg, dict):
        cfg = {}
    summary = getattr(row, "summary", None)
    if not isinstance(summary, dict):
        summary = {}
    return DatasetProfileScanRunOut(
        id=row.id,
        tenant_id=row.tenant_id,
        dataset_id=row.dataset_id,
        requested_by=getattr(row, "requested_by", None),
        kind=str(getattr(row, "kind", "") or "deep"),
        status=str(getattr(row, "status", "") or "pending"),
        progress=int(getattr(row, "progress", 0) or 0),
        config=cfg,
        summary=summary,
        error_message=getattr(row, "error_message", None),
        started_at=getattr(row, "started_at", None),
        finished_at=getattr(row, "finished_at", None),
        created_at=getattr(row, "created_at", None),
        updated_at=getattr(row, "updated_at", None),
    )


def _run_deep_scan_background(
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    scan_run_id: UUID,
) -> None:
    """
    BackgroundTasks wrapper for deep scan when the queue is disabled.

    Uses a dedicated DB session and marks the run as failed on exception.
    """
    db = SessionLocal()
    try:
        run_dataset_profile_deep_scan(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            scan_run_id=scan_run_id,
        )
    except Exception as exc:  # noqa: BLE001
        try:
            row = (
                db.query(DBDatasetProfileScanRun)
                .filter(
                    DBDatasetProfileScanRun.id == scan_run_id,
                    DBDatasetProfileScanRun.tenant_id == tenant_id,
                    DBDatasetProfileScanRun.dataset_id == dataset_id,
                )
                .first()
            )
            if row is not None:
                row.status = "failed"
                row.error_message = str(exc)[:200]
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.get("/{dataset_id}/profile/summary", response_model=DatasetProfileSummary)
def get_dataset_profile_summary(
    dataset_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    summary = compute_dataset_profile_summary(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
    )
    return summary


@router.get("/{dataset_id}/profile/findings/{finding_key}", response_model=DatasetProfileFindingListResponse)
def list_dataset_profile_finding_documents(
    dataset_id: UUID,
    finding_key: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    try:
        return list_finding_documents(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            finding_key=finding_key,
            skip=int(skip or 0),
            limit=int(limit or 50),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:200]) from exc


@router.post("/{dataset_id}/profile/scan-runs", response_model=DatasetProfileScanRunOut, status_code=201)
async def create_dataset_profile_scan_run(
    dataset_id: UUID,
    body: DatasetProfileScanRunCreateRequest,
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_writable(db, dataset, account_id)

    # Prevent accidental duplicate long-running scans.
    existing = (
        db.query(DBDatasetProfileScanRun)
        .filter(
            DBDatasetProfileScanRun.tenant_id == tenant_id,
            DBDatasetProfileScanRun.dataset_id == dataset_id,
            DBDatasetProfileScanRun.status.in_(["pending", "running"]),
        )
        .order_by(DBDatasetProfileScanRun.created_at.desc())
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="A scan run is already pending/running for this dataset")

    cfg = body.model_dump(exclude_none=True)
    row = DBDatasetProfileScanRun(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        requested_by=account_id,
        kind="deep",
        status="pending",
        progress=0,
        config=cfg,
        summary={},
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    job_id = f"dataset_profile_scan:{tenant_id}:{dataset_id}:{row.id}"
    task_id = await enqueue_dataset_profile_scan(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        scan_run_id=row.id,
        requested_by=account_id,
        job_id=job_id,
    )
    if not task_id:
        # Queue disabled; run in-process after response.
        background_tasks.add_task(
            _run_deep_scan_background,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            scan_run_id=row.id,
        )

    return _scan_run_out_from_row(row)


@router.get("/{dataset_id}/profile/scan-runs", response_model=DatasetProfileScanRunListResponse)
def list_dataset_profile_scan_runs(
    dataset_id: UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    q = (
        db.query(DBDatasetProfileScanRun)
        .filter(DBDatasetProfileScanRun.tenant_id == tenant_id, DBDatasetProfileScanRun.dataset_id == dataset_id)
    )
    total = int(q.count())
    rows = (
        q.order_by(DBDatasetProfileScanRun.created_at.desc())
        .offset(int(skip or 0))
        .limit(int(limit or 20))
        .all()
    )
    return DatasetProfileScanRunListResponse(total=total, items=[_scan_run_out_from_row(r) for r in rows])


@router.get("/{dataset_id}/profile/scan-runs/{scan_run_id}", response_model=DatasetProfileScanRunOut)
def get_dataset_profile_scan_run(
    dataset_id: UUID,
    scan_run_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    row = (
        db.query(DBDatasetProfileScanRun)
        .filter(
            DBDatasetProfileScanRun.id == scan_run_id,
            DBDatasetProfileScanRun.tenant_id == tenant_id,
            DBDatasetProfileScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Scan run not found")
    return _scan_run_out_from_row(row)


@router.get("/{dataset_id}/profile/export")
def export_dataset_profile_summary(
    dataset_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, dataset, account_id)

    summary = compute_dataset_profile_summary(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
    )
    content = json.dumps(summary.model_dump(), ensure_ascii=False, separators=(",", ":"))
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(getattr(dataset, "name", "") or "dataset"))[:64]
    filename = f"{safe}.profile.json"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'},
    )
