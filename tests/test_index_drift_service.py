from __future__ import annotations

from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _session() -> Session:
    from app.models.index_drift_item import IndexDriftItem

    engine = create_engine("sqlite:///:memory:")
    IndexDriftItem.__table__.create(bind=engine)
    return Session(bind=engine)


def test_record_list_and_resolve_index_drift_items() -> None:
    from app.services.index_audit_service import (
        build_index_drift_marker,
        list_index_drift_items,
        record_index_drift_item,
        resolve_index_drift_item,
    )

    db = _session()
    tenant_id = uuid4()
    dataset_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()

    marker = build_index_drift_marker(
        operation="chunk.delete",
        strictness="strict",
        tenant_id=tenant_id,
        document_id=document_id,
        chunk_id=chunk_id,
        channel="vector",
        reason="vector delete failed",
        details={"retryable": True},
    )

    item = record_index_drift_item(
        db=db,
        dataset_id=dataset_id,
        marker=marker,
        reconcile_task_id="task-1",
    )

    assert item.status == "open"
    assert item.operation == "chunk.delete"
    assert item.channel == "vector"
    assert item.reconcile_task_id == "task-1"

    open_items = list_index_drift_items(db=db, tenant_id=tenant_id, status="open", limit=10)
    assert len(open_items) == 1
    assert open_items[0].id == item.id

    resolved = resolve_index_drift_item(
        db=db,
        tenant_id=tenant_id,
        item_id=item.id,
        resolved_by="ops",
        resolution_note="rebuilt",
    )

    assert resolved is not None
    assert resolved.status == "resolved"
    assert resolved.resolved_by == "ops"
    assert resolved.resolution_note == "rebuilt"

    assert list_index_drift_items(db=db, tenant_id=tenant_id, status="open", limit=10) == []
    resolved_items = list_index_drift_items(db=db, tenant_id=tenant_id, status="resolved", limit=10)
    assert len(resolved_items) == 1
    assert resolved_items[0].id == item.id
