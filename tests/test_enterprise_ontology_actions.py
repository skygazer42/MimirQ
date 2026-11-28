from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.infrastructure.config import settings
from app.models.identity.workspaces import Tenant
from app.models.knowledge_graph.enterprise_ontology import (
    EnterpriseOntology,
    EnterpriseOntologyActionRequest,
    EnterpriseOntologyVersion,
    EnterpriseOntologyWorkflowRequest,
)
from app.rag.kg.enterprise_ontology import action_workflows, actions
from app.rag.kg.enterprise_ontology.definition import OntologyDefinition


@pytest.fixture
def saved_action(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'actions.sqlite'}")
    for model in (Tenant, EnterpriseOntology, EnterpriseOntologyVersion, EnterpriseOntologyActionRequest):
        model.__table__.create(engine)
    tenant_id, version_id, request_id = uuid4(), uuid4(), uuid4()
    definition = OntologyDefinition.model_validate(
        {
            "schema_version": 1,
            "ontology": "maintenance",
            "object_types": {"order": {"key": ["id"], "properties": {"id": "string"}}},
            "bindings": [
                {
                    "object_type": "order",
                    "role": "primary",
                    "asset_id": "fixture",
                    "identity_columns": ["id"],
                    "columns": {"id": "id"},
                }
            ],
            "actions": {"close_order": {"object_type": "order", "target": "maintenance"}},
        }
    )
    with Session(engine) as db:
        db.add(
            EnterpriseOntologyActionRequest(
                tenant_id=tenant_id,
                version_id=version_id,
                request_id=request_id,
                owner_id="operator",
                action_id="close_order",
                inputs={"request_id": str(request_id), "key": {"id": "WO-01"}},
                state="ready",
            )
        )
        db.commit()
    monkeypatch.setattr(settings, "ONTOLOGY_ACTION_TARGETS", {str(tenant_id): {"maintenance": "http://target.test"}})
    monkeypatch.setattr(actions, "read_business_object", lambda *args, **kwargs: None)

    def advance(operation):
        with Session(engine) as db:
            return actions.advance_action(
                db,
                tenant_id=tenant_id,
                account_id="operator",
                definition=definition,
                version_id=version_id,
                request_id=request_id,
                authorization="Bearer fixture",
                operation=operation,
            )

    yield advance, request_id, engine
    engine.dispose()


@pytest.fixture
def clock(monkeypatch):
    class Clock(datetime):
        current = datetime(2026, 11, 23, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz)

    monkeypatch.setattr(actions, "datetime", Clock)
    return Clock


def _mock_target(monkeypatch, respond):
    def handle(request):
        if request.url.path == "/authorize":
            return httpx.Response(200, json={"allowed": True})
        return respond(request)

    monkeypatch.setattr(actions.httpx, "Client", partial(httpx.Client, transport=httpx.MockTransport(handle)))


def _receipt(request_id):
    return {"request_id": str(request_id), "receipt_id": "close-wo-01", "status": "succeeded"}


def test_published_action_workflow_resumes_with_frozen_steps_and_receipts(saved_action, monkeypatch):
    from fastapi import HTTPException

    _, _, engine = saved_action
    EnterpriseOntologyWorkflowRequest.__table__.create(engine)
    with Session(engine) as db:
        existing = db.scalar(select(EnterpriseOntologyActionRequest))
        tenant_id, version_id = existing.tenant_id, existing.version_id
    definition = OntologyDefinition.model_validate(
        {
            "schema_version": 1,
            "ontology": "maintenance",
            "object_types": {"order": {"key": ["id"], "properties": {"id": "string"}}},
            "bindings": [
                {
                    "object_type": "order",
                    "role": "primary",
                    "asset_id": "orders",
                    "identity_columns": ["id"],
                    "columns": {"id": "id"},
                }
            ],
            "actions": {
                "mark": {"object_type": "order", "target": "maintenance", "approval_required": True},
                "close": {"object_type": "order", "target": "maintenance"},
            },
            "action_workflows": {"complete_order": {"actions": ["mark", "close"]}},
        }
    )
    calls = []
    receipts = {}

    def respond(request):
        if request.url.path == "/execute":
            action_id = request.headers["Idempotency-Key"]
            calls.append(action_id)
            receipts[action_id] = _receipt(action_id)
            if len(calls) == 1:
                return httpx.Response(503)
            return httpx.Response(200, json=receipts[action_id])
        return httpx.Response(200, json=receipts[request.url.path.split("/")[-1]])

    _mock_target(monkeypatch, respond)
    identity = uuid4()
    inputs = action_workflows.WorkflowInput(
        request_id=identity,
        steps=[
            action_workflows.WorkflowStepInput(key={"id": "WO-01"}),
            action_workflows.WorkflowStepInput(key={"id": "WO-01"}),
        ],
    )
    with Session(engine) as db:
        created = action_workflows.create_workflow(
            db,
            tenant_id=tenant_id,
            account_id="operator",
            version_id=version_id,
            workflow_id="complete_order",
            definition=definition,
            inputs=inputs,
        )
    assert created.current_step == 0 and calls == []

    def advance(index, operation):
        with Session(engine) as db:
            row = action_workflows.read_workflow(db, tenant_id, "operator", version_id, identity, lock=True)
            return action_workflows.advance_workflow(
                db,
                row,
                account_id="operator",
                definition=definition,
                operation=operation,
                step_index=index,
                authorization="Bearer fixture",
            )

    with pytest.raises(HTTPException, match="different step"):
        advance(1, "preview")
    first = advance(0, "preview").steps[0].action
    assert first.state == "awaiting_approval"
    with pytest.raises(HTTPException, match="needs approval"):
        advance(0, "execute")
    with Session(engine) as db, pytest.raises(HTTPException, match="not found"):
        actions.advance_action(
            db,
            tenant_id=tenant_id,
            account_id="operator",
            definition=definition,
            version_id=version_id,
            request_id=first.request_id,
            authorization="Bearer fixture",
            operation="approve",
        )
    assert advance(0, "approve").steps[0].action.state == "ready"
    assert advance(0, "execute").steps[0].action.state == "unknown"
    assert advance(0, "execute").steps[0].action.state == "unknown"
    assert calls == [str(first.request_id)]
    assert advance(0, "receipt").current_step == 1
    assert advance(1, "preview").steps[1].action.state == "ready"
    assert advance(1, "execute").current_step is None
    assert advance(1, "execute").current_step is None
    assert len(calls) == 2


def test_interrupted_dispatch_waits_for_receipt_then_requires_review(saved_action, clock, monkeypatch):
    advance, request_id, _ = saved_action
    dispatch_keys = []
    receipt = None

    def respond(request):
        if request.url.path == "/execute":
            dispatch_keys.append(request.headers["Idempotency-Key"])
            raise RuntimeError("worker interrupted")
        assert request.url.path == f"/receipts/{request_id}"
        return httpx.Response(404) if receipt is None else httpx.Response(200, json=receipt)

    _mock_target(monkeypatch, respond)
    with pytest.raises(RuntimeError, match="worker interrupted"):
        advance("execute")

    clock.current += timedelta(seconds=59)
    assert advance("receipt").state == "dispatching"
    clock.current += timedelta(seconds=1)
    review = advance("receipt")
    assert review.state == "manual_review"
    assert review.receipt is None
    assert advance("execute") == review

    receipt = _receipt(request_id)
    assert advance("receipt").state == "succeeded"
    assert dispatch_keys == [str(request_id)]


def test_dispatch_without_start_time_can_be_reviewed(saved_action, monkeypatch):
    advance, _, engine = saved_action
    with Session(engine) as db:
        row = db.scalar(select(EnterpriseOntologyActionRequest))
        row.state = "dispatching"
        db.commit()
    _mock_target(monkeypatch, lambda request: httpx.Response(404))

    assert advance("receipt").state == "manual_review"


def test_late_execute_response_can_settle_manual_review(saved_action, clock, monkeypatch):
    advance, request_id, _ = saved_action

    def respond(request):
        if request.url.path == f"/receipts/{request_id}":
            return httpx.Response(404)
        assert request.url.path == "/execute"
        clock.current += timedelta(minutes=1)
        assert advance("receipt").state == "manual_review"
        return httpx.Response(200, json=_receipt(request_id))

    _mock_target(monkeypatch, respond)

    assert advance("execute").state == "succeeded"
