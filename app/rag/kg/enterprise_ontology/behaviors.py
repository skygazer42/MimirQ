"""Evaluate saved rules and functions against current authorized data."""

from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy.orm import Session

from app.rag.kg.enterprise_ontology.definition import (
    RULE_COMPARISONS,
    Fact,
    ObjectDefinition,
    OntologyDefinition,
    RuleDefinition,
)
from app.rag.kg.enterprise_ontology.metrics import MetricQuery, MetricResult, evaluate_snapshot_metric
from app.rag.kg.enterprise_ontology.objects import BusinessObject, ObjectKey, read_business_object

RuleOutcome = Literal["true", "false", "unknown"]


class RuleRequest(ObjectKey):
    observed_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class RuleResult(BaseModel):
    version_id: UUID
    rule: str
    outcome: RuleOutcome
    observed_at: AwareDatetime
    evidence: BusinessObject
    functions: list[MetricResult] = Field(default_factory=list)


class FunctionResult(BaseModel):
    version_id: UUID
    function: str
    result: MetricResult


def evaluate_rule(
    rule: RuleDefinition,
    facts: dict[str, Fact | None],
    observed_at: datetime,
    *,
    object_definition: ObjectDefinition | None = None,
    function_values: dict[int, int | float] | None = None,
) -> RuleOutcome:
    unknown = False
    for index, condition in enumerate(rule.conditions):
        value = facts.get(condition.property)
        if value is None:
            unknown = True
            continue
        operand = condition.value
        if condition.operand == "observed_at":
            operand = observed_at if isinstance(value, datetime) else observed_at.date()
        elif condition.operand == "function":
            operand = (function_values or {}).get(index)
            if operand is None:
                unknown = True
                continue
        elif object_definition is not None:
            operand = object_definition.properties[condition.property].parse(operand)
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        if isinstance(operand, datetime) and operand.tzinfo is None:
            operand = operand.replace(tzinfo=UTC)
        if not RULE_COMPARISONS[condition.operator](value, operand):
            return "false"
    return "unknown" if unknown else "true"


def read_rule(
    db: Session,
    *,
    version_id: UUID,
    tenant_id: UUID,
    account_id: str,
    definition: OntologyDefinition,
    rule_id: str,
    request: RuleRequest,
) -> RuleResult:
    rule = definition.rules.get(rule_id)
    if rule is None:
        raise ValueError("Unknown ontology rule")
    evidence = read_business_object(
        db,
        definition=definition,
        tenant_id=tenant_id,
        account_id=account_id,
        object_type=rule.object_type,
        key=request.key,
        properties={
            field
            for condition in rule.conditions
            for field in (condition.property, *condition.function_filters.values())
        },
    )
    functions = []
    function_values = {}
    for index, condition in enumerate(rule.conditions):
        if condition.function is None:
            continue
        filters = {dimension: evidence.attributes.get(prop) for dimension, prop in condition.function_filters.items()}
        if any(value is None for value in filters.values()):
            continue
        try:
            query = MetricQuery(
                observed_at=request.observed_at,
                filters={
                    field: value.isoformat() if isinstance(value, date) else value for field, value in filters.items()
                },
            )
            result = run_function(
                db,
                version_id=version_id,
                tenant_id=tenant_id,
                account_id=account_id,
                definition=definition,
                function_id=condition.function,
                request=query,
            ).result
        except (HTTPException, PermissionError, ValueError, FileNotFoundError):
            continue
        functions.append(result)
        if result.complete and result.value is not None:
            function_values[index] = result.value
    outcome = evaluate_rule(
        rule,
        evidence.attributes,
        request.observed_at,
        object_definition=definition.object_types[rule.object_type],
        function_values=function_values,
    )
    return RuleResult(
        version_id=version_id,
        rule=rule_id,
        outcome=outcome,
        observed_at=request.observed_at,
        evidence=evidence,
        functions=functions,
    )


def run_function(
    db: Session,
    *,
    version_id: UUID,
    tenant_id: UUID,
    account_id: str,
    definition: OntologyDefinition,
    function_id: str,
    request: MetricQuery,
) -> FunctionResult:
    function = definition.functions.get(function_id)
    if function is None:
        raise ValueError("Unknown ontology function")
    if request.group_by:
        raise ValueError("Scalar ontology functions do not accept grouping dimensions")
    result = evaluate_snapshot_metric(
        db,
        definition=definition,
        metric_id=function.metric,
        query=request,
        tenant_id=tenant_id,
        account_id=account_id,
    )
    return FunctionResult(version_id=version_id, function=function_id, result=result)
