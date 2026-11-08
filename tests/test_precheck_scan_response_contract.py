import asyncio
from dataclasses import fields
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import BackgroundTasks, UploadFile
from sqlalchemy import JSON, Uuid, create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class Scan(Base):
    __tablename__ = "scans"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    status: Mapped[str]

    def __init__(self, **values):
        self.status = values["status"]


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    dataset_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


@pytest.fixture
def batch_context(tmp_path, monkeypatch):
    from app.services import document_batch_ingestion as module

    engine = create_engine("sqlite:///" + str(tmp_path / "state.db"))
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=True) as db:
        dataset = Dataset(dataset_metadata={})
        db.add(dataset)
        db.commit()
        monkeypatch.setattr(module.settings, "UPLOAD_DIR", str(tmp_path))
        monkeypatch.setattr(module, "DBDatasetPrecheckScanRun", Scan)
        monkeypatch.setattr(module.dataset_service, "resolve_writable_dataset", lambda *a: dataset)
        monkeypatch.setattr(module, "enforce_tenant_upload_quotas", lambda *a, **k: None)
        monkeypatch.setattr(module, "_link_precheck_staging_tree", lambda *a, **k: True)
        monkeypatch.setattr(module, "_apply_precheck_policy_suggestion", lambda **k: None)
        monkeypatch.setattr(module, "SessionLocal", MagicMock)
        staged = dict(
            success=True,
            filename="sample.txt",
            file_ext=".txt",
            upload_key="sample.txt",
            source_path=None,
            file_id=uuid4(),
            file_path=str(tmp_path / "sample.txt"),
            file_size=1,
            file_sha256="a" * 64,
            content_type="text/plain",
        )
        monkeypatch.setattr(module, "_stage_upload_for_precheck", AsyncMock(return_value=staged))
        monkeypatch.setattr(
            module,
            "_process_saved_batch_upload",
            AsyncMock(return_value={"success": False, "filename": "sample.txt", "error": "unrelated per-file failure"}),
        )
        form = module.UploadDocumentsBatchFormFields(
            parser_backend="auto",
            chunk_strategy="recursive",
            pipeline=None,
            dataset_id=dataset.id,
            precheck_first=True,
            precheck_only=False,
            upload_only=True,
            user_metadata_map=None,
            max_concurrent=1,
        )
        overrides = module.PipelineOverridesFormFields(
            **{f.name: None for f in fields(module.PipelineOverridesFormFields)}
        )

        def invoke():
            return asyncio.run(
                module.ingest_batch(
                    background_tasks=BackgroundTasks(),
                    files=[UploadFile(BytesIO(b"x"), filename="sample.txt")],
                    form=form,
                    overrides_form=overrides,
                    tenant_id=uuid4(),
                    account_id="owner",
                    db=db,
                )
            )

        yield SimpleNamespace(module=module, engine=engine, db=db, dataset=dataset, invoke=invoke)
    engine.dispose()


def test_failed_persisted_scan_remains_linked_in_batch_response(batch_context, monkeypatch):
    ctx = batch_context
    run_ids = []
    expired_on_rollback = []

    def scan_job(**kwargs):
        run_ids.append(kwargs["scan_run_id"])
        with Session(ctx.engine) as worker:
            run = worker.get(Scan, kwargs["scan_run_id"])
            run.status = "failed"
            worker.commit()
        raise RuntimeError("scan failed after run creation")

    def observe_rollback(session, transaction):
        expired_on_rollback.extend(
            inspect(row).expired for row in session.identity_map.values() if isinstance(row, Scan)
        )

    event.listen(ctx.db, "after_soft_rollback", observe_rollback)
    monkeypatch.setattr(ctx.module, "_run_precheck_scan_job", scan_job)
    response = ctx.invoke()
    assert response.model_dump(mode="json")["precheck_scan_run_id"] == str(run_ids[0])
    assert expired_on_rollback == [True]
    assert ctx.db.get(Scan, run_ids[0]).status == "failed"


@pytest.mark.parametrize("phase", ["initial_scan", "completed_scan", "dataset"])
def test_refresh_failure_propagates_from_batch_precheck(phase, batch_context, monkeypatch):
    ctx = batch_context
    failure = RuntimeError("refresh unavailable")
    refresh = ctx.db.refresh
    scan_refreshes = 0

    def fail_refresh(row, *args, **kwargs):
        nonlocal scan_refreshes
        if isinstance(row, Scan):
            scan_refreshes += 1
            if (phase == "initial_scan" and scan_refreshes == 1) or (phase == "completed_scan" and scan_refreshes == 2):
                raise failure
        elif phase == "dataset":
            raise failure
        return refresh(row, *args, **kwargs)

    monkeypatch.setattr(ctx.db, "refresh", fail_refresh)
    monkeypatch.setattr(ctx.module, "_run_precheck_scan_job", lambda **k: None)
    with pytest.raises(RuntimeError) as raised:
        ctx.invoke()
    assert raised.value is failure
