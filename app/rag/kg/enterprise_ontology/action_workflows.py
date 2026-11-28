"""Run a published sequence one approved action at a time."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid5

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.knowledge_graph.enterprise_ontology import (
    EnterpriseOntologyActionRequest,
    EnterpriseOntologyWorkflowRequest,
)
from app.rag.kg.enterprise_ontology.actions import (
    ActionInput,
    ActionView,
    advance_action,
    normalize_action_inputs,
    prepare_action,
)
from app.rag.kg.enterprise_ontology.definition import OntologyDefinition, Scalar
from app.rag.kg.enterprise_ontology.objects import ObjectKey

WorkflowOperation = Literal["preview", "approve", "execute", "receipt", "cancel"]


class WorkflowStepInput(ObjectKey):
    parameters: dict[str, Scalar] = Field(default_factory=dict, max_length=32)


class WorkflowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    steps: list[WorkflowStepInput] = Field(min_length=2, max_length=8)


class WorkflowStepView(BaseModel):
    action_id: str
    inputs: ActionInput
    action: ActionView | None = None


class WorkflowView(BaseModel):
    request_id: UUID
    workflow_id: str
    version_id: UUID
    canceled: bool
    current_step: int | None
    steps: list[WorkflowStepView]


def read_workflow(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    version_id: UUID,
    request_id: UUID,
    *,
    approve: bool = False,
    lock: bool = False,
) -> EnterpriseOntologyWorkflowRequest:
    row = db.get(EnterpriseOntologyWorkflowRequest, (tenant_id, request_id), with_for_update=lock)
    if row is None or row.version_id != version_id or (row.owner_id != account_id and not approve):
        raise HTTPException(status_code=404, detail="Workflow request not found")
    return row


def workflow_view(db: Session, row: EnterpriseOntologyWorkflowRequest) -> WorkflowView:
    steps = [WorkflowStepView.model_validate(step) for step in row.steps]
    actions = {
        action.request_id: action
        for action in db.scalars(
            select(EnterpriseOntologyActionRequest).where(
                EnterpriseOntologyActionRequest.tenant_id == row.tenant_id,
                EnterpriseOntologyActionRequest.workflow_request_id == row.request_id,
                EnterpriseOntologyActionRequest.request_id.in_([step.inputs.request_id for step in steps]),
            )
        )
    }
    for step in steps:
        action = actions.get(step.inputs.request_id)
        if action is not None:
            step.action = ActionView.model_validate(action)
    current = next(
        (index for index, step in enumerate(steps) if step.action is None or step.action.state != "succeeded"), None
    )
    return WorkflowView(
        request_id=row.request_id,
        workflow_id=row.workflow_id,
        version_id=row.version_id,
        canceled=row.canceled_at is not None,
        current_step=current,
        steps=steps,
    )


def create_workflow(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    version_id: UUID,
    workflow_id: str,
    definition: OntologyDefinition,
    inputs: WorkflowInput,
) -> WorkflowView:
    definition_workflow = definition.action_workflows.get(workflow_id)
    if definition_workflow is None:
        raise HTTPException(status_code=404, detail="Ontology workflow not found")
    if len(inputs.steps) != len(definition_workflow.actions):
        raise ValueError("Workflow inputs must match the published action sequence")
    steps = []
    for index, (action_id, step) in enumerate(zip(definition_workflow.actions, inputs.steps, strict=True)):
        action_input = ActionInput(request_id=uuid5(inputs.request_id, f"ontology-action:{index}"), **step.model_dump())
        normalized = normalize_action_inputs(definition, definition.actions[action_id], action_input)
        steps.append({"action_id": action_id, "inputs": normalized})
    identity = tenant_id, inputs.request_id
    row = db.get(EnterpriseOntologyWorkflowRequest, identity)
    if row is None:
        row = EnterpriseOntologyWorkflowRequest(
            tenant_id=tenant_id,
            request_id=inputs.request_id,
            owner_id=account_id,
            version_id=version_id,
            workflow_id=workflow_id,
            steps=steps,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            row = db.get(EnterpriseOntologyWorkflowRequest, identity)
            if row is None:
                raise
    if row.owner_id != account_id:
        raise HTTPException(status_code=404, detail="Workflow request not found")
    if (row.version_id, row.workflow_id, row.steps) != (version_id, workflow_id, steps):
        raise HTTPException(status_code=409, detail="Request ID is already bound to different workflow inputs")
    return workflow_view(db, row)


def advance_workflow(
    db: Session,
    row: EnterpriseOntologyWorkflowRequest,
    *,
    account_id: str,
    definition: OntologyDefinition,
    operation: WorkflowOperation,
    step_index: int,
    authorization: str | None,
) -> WorkflowView:
    view = workflow_view(db, row)
    if operation == "cancel":
        if view.current_step is None:
            raise HTTPException(status_code=409, detail="Completed workflow cannot be canceled")
        if row.canceled_at is None:
            row.canceled_at = datetime.now(UTC)
            db.commit()
        return workflow_view(db, row)
    if operation == "receipt":
        if step_index >= len(view.steps) or view.steps[step_index].action is None:
            raise HTTPException(status_code=404, detail="Workflow step has no action request")
    elif view.canceled or step_index != view.current_step:
        if operation == "execute" and step_index < len(view.steps):
            action = view.steps[step_index].action
            if action is not None and action.state == "succeeded":
                return view
        raise HTTPException(status_code=409, detail="Workflow has moved to a different step or has been canceled")
    step = view.steps[step_index]
    if operation == "preview":
        prepare_action(
            db,
            tenant_id=row.tenant_id,
            account_id=account_id,
            definition=definition,
            version_id=row.version_id,
            action_id=step.action_id,
            inputs=step.inputs,
            authorization=authorization,
            workflow_request_id=row.request_id,
        )
    else:
        advance_action(
            db,
            tenant_id=row.tenant_id,
            account_id=account_id,
            definition=definition,
            version_id=row.version_id,
            request_id=step.inputs.request_id,
            operation=operation,
            authorization=authorization,
            workflow_request_id=row.request_id,
        )
    return workflow_view(db, row)
