"""Freeze and dispatch saved actions to tenant-registered business endpoints."""

from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.config import settings
from app.models.knowledge_graph.enterprise_ontology import EnterpriseOntologyActionRequest
from app.rag.kg.enterprise_ontology.behaviors import RuleRequest, read_rule
from app.rag.kg.enterprise_ontology.definition import ActionDefinition, OntologyDefinition, Scalar
from app.rag.kg.enterprise_ontology.objects import ObjectKey, read_business_object

_DISPATCH_RECEIPT_GRACE = timedelta(seconds=60)


class ActionInput(ObjectKey):
    request_id: UUID
    parameters: dict[str, Scalar] = Field(default_factory=dict, max_length=32)


class ActionReceipt(BaseModel):
    model_config = ConfigDict(extra="ignore")

    request_id: UUID
    receipt_id: str = Field(min_length=1, max_length=255)
    status: Literal["submitted", "succeeded", "failed"]
    sync_status: Literal["pending", "synced", "failed"] = "pending"


class ActionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: UUID
    version_id: UUID
    action_id: str
    state: str
    inputs: ActionInput
    approved_by: str | None
    receipt: ActionReceipt | None


def validate_action_targets(tenant_id: UUID, definition: OntologyDefinition) -> None:
    registered = settings.ONTOLOGY_ACTION_TARGETS.get(str(tenant_id), {})
    for action_id, action in definition.actions.items():
        if action.target not in registered:
            raise ValueError(f"Unregistered business target for action {action_id}")


class ActionTarget:
    def __init__(self, tenant_id: UUID, action: ActionDefinition, authorization: str | None) -> None:
        self.url = settings.ONTOLOGY_ACTION_TARGETS.get(str(tenant_id), {}).get(action.target)
        if not self.url:
            raise HTTPException(status_code=409, detail="Action target is unavailable")
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Business target requires caller authentication")
        self.headers = {"Authorization": authorization, "X-Tenant-ID": str(tenant_id)}

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        with httpx.Client(base_url=self.url, headers=self.headers, timeout=10, trust_env=False) as client:
            return client.request(method, path, **kwargs)

    def require_permission(self, payload: dict) -> None:
        try:
            response = self.request("POST", "authorize", json=payload)
            if response.status_code in {401, 403, 404}:
                raise HTTPException(status_code=403, detail="No permission on business target")
            response.raise_for_status()
            allowed = response.json().get("allowed") is True
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            raise HTTPException(status_code=503, detail="Unable to verify business target permission") from exc
        if not allowed:
            raise HTTPException(status_code=403, detail="No permission on business target")


def _configured_action(definition: OntologyDefinition, action_id: str) -> ActionDefinition:
    action = definition.actions.get(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Ontology action not found")
    return action


def _payload(row: EnterpriseOntologyActionRequest, action: ActionDefinition) -> dict:
    return {
        "action_id": row.action_id,
        "version_id": str(row.version_id),
        "object_type": action.object_type,
        **row.inputs,
    }


def _check_preconditions(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    version_id: UUID,
    definition: OntologyDefinition,
    action: ActionDefinition,
    key: dict,
) -> None:
    if not action.preconditions:
        read_business_object(
            db,
            definition=definition,
            tenant_id=tenant_id,
            account_id=account_id,
            object_type=action.object_type,
            key=key,
            properties=set(),
        )
        return
    request = RuleRequest(key=key, observed_at=datetime.now(UTC))
    for rule_id in action.preconditions:
        outcome = read_rule(
            db,
            definition=definition,
            version_id=version_id,
            tenant_id=tenant_id,
            account_id=account_id,
            rule_id=rule_id,
            request=request,
        ).outcome
        if outcome != "true":
            raise HTTPException(status_code=409, detail={"precondition": rule_id, "outcome": outcome})


def normalize_action_inputs(definition: OntologyDefinition, action: ActionDefinition, inputs: ActionInput) -> dict:
    if inputs.parameters.keys() - action.parameters.keys() or any(
        prop.required and name not in inputs.parameters for name, prop in action.parameters.items()
    ):
        raise ValueError("Action parameters must match the published definition")
    arguments = {name: action.parameters[name].parse(value) for name, value in inputs.parameters.items()}
    normalized = inputs.model_dump(mode="json")
    obj = definition.object_types[action.object_type]
    if inputs.key.keys() != set(obj.key):
        raise ValueError("Action requires the declared business key")
    keys = {name: obj.properties[name].parse(value) for name, value in inputs.key.items()}
    normalized["key"] = {name: value.isoformat() if isinstance(value, date) else value for name, value in keys.items()}
    normalized["parameters"] = {
        name: value.isoformat() if isinstance(value, date) else value for name, value in arguments.items()
    }
    return normalized


def prepare_action(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    definition: OntologyDefinition,
    version_id: UUID,
    action_id: str,
    inputs: ActionInput,
    authorization: str | None,
    workflow_request_id: UUID | None = None,
) -> ActionView:
    action = _configured_action(definition, action_id)
    normalized = normalize_action_inputs(definition, action, inputs)
    target = ActionTarget(tenant_id, action, authorization)
    identity = tenant_id, inputs.request_id
    row = db.get(EnterpriseOntologyActionRequest, identity)
    if row is None:
        row = EnterpriseOntologyActionRequest(
            tenant_id=tenant_id,
            request_id=inputs.request_id,
            version_id=version_id,
            action_id=action_id,
            owner_id=account_id,
            inputs=normalized,
            state="awaiting_approval" if action.approval_required else "ready",
            workflow_request_id=workflow_request_id,
        )
        _check_preconditions(db, tenant_id, account_id, version_id, definition, action, normalized["key"])
        target.require_permission(_payload(row, action))
        db.add(row)
        try:
            db.commit()
            db.refresh(row)
            return ActionView.model_validate(row)
        except IntegrityError:
            db.rollback()
            row = db.get(EnterpriseOntologyActionRequest, identity)
            if row is None:
                raise
    if row.owner_id != account_id or row.workflow_request_id != workflow_request_id:
        raise HTTPException(status_code=404, detail="Action request not found")
    if (row.version_id, row.action_id, row.inputs) != (version_id, action_id, normalized):
        raise HTTPException(status_code=409, detail="Request ID is already bound to different action inputs")
    target.require_permission(_payload(row, action))
    return ActionView.model_validate(row)


def _apply_receipt(row: EnterpriseOntologyActionRequest, response: httpx.Response) -> None:
    response.raise_for_status()
    receipt = ActionReceipt.model_validate(response.json())
    if receipt.request_id != row.request_id:
        raise ValueError("Receipt request ID does not match")
    row.state = receipt.status
    row.receipt = receipt.model_dump(mode="json")


def _dispatch_grace_elapsed(started_at: datetime | None) -> bool:
    if started_at is None:
        return True  # Dispatches recorded before the timestamp was added can be reviewed immediately.
    started_at = started_at.replace(tzinfo=started_at.tzinfo or UTC)
    return datetime.now(UTC) - started_at >= _DISPATCH_RECEIPT_GRACE


def advance_action(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    definition: OntologyDefinition,
    version_id: UUID,
    request_id: UUID,
    authorization: str | None,
    operation: Literal["approve", "execute", "receipt"],
    workflow_request_id: UUID | None = None,
) -> ActionView:
    row = db.get(EnterpriseOntologyActionRequest, (tenant_id, request_id), with_for_update=True)
    if (
        row is None
        or row.version_id != version_id
        or row.workflow_request_id != workflow_request_id
        or (operation != "approve" and row.owner_id != account_id)
    ):
        raise HTTPException(status_code=404, detail="Action request not found")
    action = _configured_action(definition, row.action_id)
    target = ActionTarget(tenant_id, action, authorization)
    payload = _payload(row, action)
    target.require_permission(payload)
    if operation == "approve":
        if row.state != "awaiting_approval":
            raise HTTPException(status_code=409, detail="Action request is not awaiting approval")
        _check_preconditions(db, tenant_id, account_id, version_id, definition, action, row.inputs["key"])
        row.approved_by = account_id
        row.state = "ready"
    elif operation == "execute":
        if row.state == "awaiting_approval":
            raise HTTPException(status_code=409, detail="Action request needs approval")
        if row.state != "ready":
            return ActionView.model_validate(row)
        _check_preconditions(db, tenant_id, account_id, version_id, definition, action, row.inputs["key"])
        row.state = "dispatching"
        row.dispatch_started_at = datetime.now(UTC)
        db.commit()
        try:
            response = target.request("POST", "execute", json=payload, headers={"Idempotency-Key": str(request_id)})
        except httpx.HTTPError:
            response = None
        row = db.get(
            EnterpriseOntologyActionRequest, (tenant_id, request_id), with_for_update=True, populate_existing=True
        )
        try:
            if response is not None and row.state in {"dispatching", "manual_review"}:
                _apply_receipt(row, response)
        except (httpx.HTTPError, ValueError):
            response = None
        if response is None and row.state == "dispatching":
            row.state = "unknown"
    elif row.state in {"dispatching", "unknown", "submitted", "manual_review"} or (
        row.receipt and row.receipt["sync_status"] == "pending"
    ):
        try:
            response = target.request("GET", f"receipts/{request_id}")
            if response.status_code == 404:
                if row.state == "unknown" or (
                    row.state == "dispatching" and _dispatch_grace_elapsed(row.dispatch_started_at)
                ):
                    row.state = "manual_review"
            else:
                _apply_receipt(row, response)
        except (httpx.HTTPError, ValueError):
            return ActionView.model_validate(row)
    db.commit()
    db.refresh(row)
    return ActionView.model_validate(row)
