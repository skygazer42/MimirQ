"""Validate the same ontology definition at the editor and import boundaries."""

import json
from datetime import UTC, date, datetime
from operator import eq, ge, gt, le, lt, ne
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

SemanticId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
PropertyType = Literal["string", "integer", "number", "boolean", "date", "datetime"]
Scalar = str | int | float | bool
Fact = Scalar | date | datetime
_PROPERTY_TYPES = {
    "string": TypeAdapter(str),
    "integer": TypeAdapter(int),
    "number": TypeAdapter(float),
    "boolean": TypeAdapter(bool),
    "date": TypeAdapter(date),
    "datetime": TypeAdapter(datetime),
}
RULE_COMPARISONS = {"eq": eq, "ne": ne, "lt": lt, "le": le, "gt": gt, "ge": ge}


class DefinitionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PropertyDefinition(DefinitionModel):
    type: PropertyType
    label: Name | None = None
    required: bool = False
    multiple: bool = False
    enum: list[Name] = Field(default_factory=list)

    def parse(self, raw: object) -> Fact:
        value = _PROPERTY_TYPES[self.type].validate_python(raw)
        if self.enum and value not in self.enum:
            raise ValueError("Value is outside the declared enumeration")
        return value

    @model_validator(mode="after")
    def check_enum(self) -> Self:
        if self.enum and (self.type != "string" or len(set(self.enum)) != len(self.enum)):
            raise ValueError("Enum values must be unique and belong to a string property")
        return self


class ObjectDefinition(DefinitionModel):
    label: Name | None = None
    aliases: list[Name] = Field(default_factory=list)
    display_property: SemanticId | None = None
    key_prefix: Name | None = None
    key: list[SemanticId] = Field(min_length=1)
    properties: dict[SemanticId, PropertyDefinition] = Field(min_length=1)

    @field_validator("properties", mode="before")
    @classmethod
    def expand_property_types(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {key: {"type": prop} if isinstance(prop, str) else prop for key, prop in value.items()}

    @model_validator(mode="after")
    def check_key(self) -> Self:
        if len(set(self.key)) != len(self.key):
            raise ValueError("Business key properties must be unique")
        for field in self.key:
            if field not in self.properties or self.properties[field].multiple:
                raise ValueError(f"Business key field must be a declared scalar property: {field}")
        if self.display_property is not None:
            prop = self.properties.get(self.display_property)
            if prop is None or prop.type != "string" or prop.multiple:
                raise ValueError("Display property must be a declared scalar string")
        return self


class RelationDefinition(DefinitionModel):
    label: Name | None = None
    source_type: SemanticId = Field(alias="from")
    target_type: SemanticId = Field(alias="to")
    cardinality: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]


class ColumnMapping(DefinitionModel):
    column: Name
    values: dict[str, str] = Field(default_factory=dict)


class EdoBinding(DefinitionModel):
    endpoint: SemanticId
    ontology_id: Name
    working_revision: int = Field(ge=0)
    table: Name


class ObjectBinding(DefinitionModel):
    object_type: SemanticId
    role: Literal["primary", "enrichment", "document_evidence"]
    asset_id: Name
    asset_revision: Name | None = None
    identity_namespace: Name | None = None
    row_access_column: Name | None = None
    identity_columns: list[Name] = Field(default_factory=list)
    columns: dict[SemanticId, ColumnMapping] = Field(default_factory=dict)
    edo_binding: EdoBinding | None = None
    coverage_start: AwareDatetime | None = None
    coverage_end: AwareDatetime | None = None
    snapshot_observed_at: AwareDatetime | None = None

    @field_validator("columns", mode="before")
    @classmethod
    def expand_column_names(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {key: {"column": mapping} if isinstance(mapping, str) else mapping for key, mapping in value.items()}

    @model_validator(mode="after")
    def check_source(self) -> Self:
        if len(set(self.identity_columns)) != len(self.identity_columns):
            raise ValueError("Identity columns must be unique")
        if self.role == "document_evidence" and self.edo_binding is not None:
            raise ValueError("An EDO source requires a structured data binding")
        if (
            self.coverage_start is not None
            and self.coverage_end is not None
            and self.coverage_start >= self.coverage_end
        ):
            raise ValueError("Snapshot coverage must end after it starts")
        return self


class RelationBinding(DefinitionModel):
    source_columns: list[Name] = Field(min_length=1)
    target_columns: list[Name] = Field(min_length=1)
    bridge_asset_id: Name | None = None
    bridge_row_access_column: Name | None = None
    bridge_source_columns: list[Name] = Field(default_factory=list)
    bridge_target_columns: list[Name] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_join(self) -> Self:
        if self.bridge_asset_id is None:
            if self.bridge_source_columns or self.bridge_target_columns or self.bridge_row_access_column is not None:
                raise ValueError("Bridge columns require a bridge asset")
            if len(self.source_columns) != len(self.target_columns):
                raise ValueError("Join columns must have the same arity")
        elif len(self.source_columns) != len(self.bridge_source_columns) or len(self.target_columns) != len(
            self.bridge_target_columns
        ):
            raise ValueError("Bridge columns must match the arity of each endpoint")
        return self


class MetricFormula(DefinitionModel):
    operation: Literal["difference", "ratio", "percent"]
    metric: SemanticId


class MetricDefinition(DefinitionModel):
    object_type: SemanticId
    property: SemanticId
    aggregate: Literal["count", "count_distinct", "sum", "avg", "min", "max"]
    time_property: SemanticId | None = None
    timezone: str = "UTC"
    allowed_filters: list[SemanticId] = Field(default_factory=list)
    dimensions: list[SemanticId] = Field(default_factory=list, exclude_if=lambda value: not value)
    required_filters: dict[SemanticId, Scalar] = Field(default_factory=dict)
    before_observation: bool = False
    label: Name | None = None
    unit: Name | None = None
    formula: MetricFormula | None = Field(default=None, exclude_if=lambda value: value is None)

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use an IANA timezone for the metric") from exc
        return value


class DocumentField(DefinitionModel):
    label: Name
    source: Literal["object_key", "metric", "citations", "metadata", "manual"]
    required: bool = True
    type: PropertyType = "string"
    metadata_field: SemanticId | None = None

    @model_validator(mode="after")
    def check_source(self) -> Self:
        if (self.source == "metadata") != (self.metadata_field is not None):
            raise ValueError("A metadata field is required only for metadata-sourced fields")
        return self


class DocumentTemplate(DefinitionModel):
    title: Name
    fields: dict[SemanticId, DocumentField] = Field(min_length=1)
    field_order: list[SemanticId] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_order(self) -> Self:
        if not self.field_order:
            self.field_order = list(self.fields)
        if len(self.field_order) != len(self.fields) or set(self.field_order) != self.fields.keys():
            raise ValueError("Document template field_order must list each field once")
        return self


class DocumentMetadataField(PropertyDefinition):
    compare_across_documents: bool = False
    method: Literal["extract", "manual"] = "extract"
    aliases: list[Name] = Field(default_factory=list)


class RuleCondition(DefinitionModel):
    property: SemanticId
    operator: Literal["eq", "ne", "lt", "le", "gt", "ge"]
    operand: Literal["literal", "observed_at", "function"] = "literal"
    value: Scalar | None = None
    function: SemanticId | None = None
    function_filters: dict[SemanticId, SemanticId] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_operand(self) -> Self:
        if (self.operand == "literal") != (self.value is not None):
            raise ValueError("Only literal conditions take a literal value")
        if (self.operand == "function") != (self.function is not None) or (
            self.operand != "function" and self.function_filters
        ):
            raise ValueError("Function conditions require a named function and its filter mapping")
        return self


class RuleDefinition(DefinitionModel):
    object_type: SemanticId
    conditions: list[RuleCondition] = Field(min_length=1, max_length=32)
    label: Name | None = None


class QueryParameter(DefinitionModel):
    type: PropertyType = "string"
    required: bool = True
    object_type: SemanticId | None = None
    enum: list[Name] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_enum(self) -> Self:
        if self.enum and (self.type != "string" or len(set(self.enum)) != len(self.enum)):
            raise ValueError("Query parameter enums must be unique string values")
        return self


class NamedQueryDefinition(DefinitionModel):
    label: Name
    description: str = Field(min_length=1, max_length=8000)
    objects: list[SemanticId] = Field(min_length=1, max_length=8)
    sql: str = Field(min_length=1, max_length=20000)
    parameters: dict[SemanticId, QueryParameter] = Field(default_factory=dict)
    sources: list[UUID] = Field(default_factory=list, max_length=20)


class ConceptDefinition(DefinitionModel):
    label: Name
    description: str = Field(min_length=1, max_length=2000)
    aliases: list[Name] = Field(default_factory=list)
    sources: list[UUID] = Field(min_length=1, max_length=20)


def _literal_conditions_are_impossible(prop: PropertyDefinition, conditions: list[RuleCondition]) -> bool:
    values = [(condition.operator, prop.parse(condition.value)) for condition in conditions]
    if prop.type == "datetime":
        values = [
            (operator, value.replace(tzinfo=UTC) if value.tzinfo is None else value) for operator, value in values
        ]
    candidates = prop.enum or ([False, True] if prop.type == "boolean" else [])
    if not candidates:
        candidates = [value for operator, value in values if operator == "eq"]
    if candidates:
        return not any(
            all(RULE_COMPARISONS[operator](candidate, value) for operator, value in values) for candidate in candidates
        )
    lower = [(value, operator == "gt") for operator, value in values if operator in {"gt", "ge"}]
    upper = [(value, operator == "lt") for operator, value in values if operator in {"lt", "le"}]
    if not (lower and upper):
        return False
    minimum, excludes_minimum = max(lower)
    maximum, excludes_maximum = min(upper, key=lambda bound: (bound[0], not bound[1]))
    return minimum > maximum or (
        minimum == maximum and (excludes_minimum or excludes_maximum or ("ne", minimum) in values)
    )


class FunctionDefinition(DefinitionModel):
    metric: SemanticId
    executor: Literal["metric"] = "metric"
    returns: Literal["number"] = "number"
    label: Name | None = None


class ActionDefinition(DefinitionModel):
    object_type: SemanticId
    target: SemanticId
    parameters: dict[SemanticId, PropertyDefinition] = Field(default_factory=dict)
    preconditions: list[SemanticId] = Field(default_factory=list)
    approval_required: bool = False
    label: Name | None = None


class ActionWorkflowDefinition(DefinitionModel):
    actions: list[SemanticId] = Field(min_length=2, max_length=8)
    label: Name | None = None


class OntologyDefinition(DefinitionModel):
    schema_version: Literal[1]
    ontology: SemanticId
    object_types: dict[SemanticId, ObjectDefinition] = Field(min_length=1)
    relations: dict[SemanticId, RelationDefinition] = Field(default_factory=dict)
    bindings: list[ObjectBinding] = Field(default_factory=list)
    relation_bindings: dict[SemanticId, RelationBinding] = Field(default_factory=dict)
    metrics: dict[SemanticId, MetricDefinition] = Field(default_factory=dict)
    named_queries: dict[SemanticId, NamedQueryDefinition] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )
    concepts: dict[SemanticId, ConceptDefinition] = Field(default_factory=dict, exclude_if=lambda value: not value)
    rules: dict[SemanticId, RuleDefinition] = Field(default_factory=dict)
    functions: dict[SemanticId, FunctionDefinition] = Field(default_factory=dict)
    actions: dict[SemanticId, ActionDefinition] = Field(default_factory=dict)
    action_workflows: dict[SemanticId, ActionWorkflowDefinition] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )
    document_templates: dict[SemanticId, DocumentTemplate] = Field(default_factory=dict)
    document_metadata: dict[SemanticId, DocumentMetadataField] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_references(self) -> Self:
        if len({key.casefold() for key in self.object_types}) != len(self.object_types):
            raise ValueError("Object type names must be unique ignoring case")
        for relation_id, relation in self.relations.items():
            for object_type in (relation.source_type, relation.target_type):
                if object_type not in self.object_types:
                    raise ValueError(f"Unknown object type {object_type} in relation {relation_id}")
        for field in ("effective_at", "expires_at"):
            metadata = self.document_metadata.get(field)
            if metadata is not None and (metadata.type not in {"date", "datetime"} or metadata.multiple):
                raise ValueError(f"Document metadata field {field} requires a single date or datetime")
        primary = self._validate_bindings()
        for query in self.named_queries.values():
            if set(query.objects) - primary.keys():
                raise ValueError("Named queries require primary object bindings")
            if any(p.object_type is not None and p.object_type not in query.objects for p in query.parameters.values()):
                raise ValueError("Query key parameter must reference a declared query object")
        self._validate_behaviors(primary)
        for template_id, template in self.document_templates.items():
            if any(
                field.source == "metadata" and field.metadata_field not in self.document_metadata
                for field in template.fields.values()
            ):
                raise ValueError(f"Unknown metadata field in template {template_id}")
        for metric_id, metric in self.metrics.items():
            binding = primary.get(metric.object_type)
            fields = {metric.property, *metric.allowed_filters, *metric.required_filters, *metric.dimensions}
            if metric.time_property is not None:
                fields.add(metric.time_property)
            if binding is None or not fields <= binding.columns.keys():
                raise ValueError(f"Metric fields must be bound to the primary asset: {metric_id}")
            if metric.before_observation and metric.time_property is None:
                raise ValueError(f"Metric needs a time property: {metric_id}")
            properties = self.object_types[metric.object_type].properties
            if len(set(metric.dimensions)) != len(metric.dimensions) or any(
                properties[field].multiple for field in metric.dimensions
            ):
                raise ValueError(f"Metric dimensions must be unique scalar properties: {metric_id}")
            for key, value in metric.required_filters.items():
                properties[key].parse(value)
            if metric.formula is not None:
                reference = self.metrics.get(metric.formula.metric)
                if reference is None or reference.formula is not None:
                    raise ValueError(f"Formula needs an existing base metric: {metric_id}")
                if metric.dimensions or not set(metric.allowed_filters) <= set(reference.allowed_filters):
                    raise ValueError(f"Formula needs shared filters and cannot declare dimensions: {metric_id}")
                if bool(metric.time_property) != bool(reference.time_property) or (
                    metric.before_observation != reference.before_observation
                ):
                    raise ValueError(f"Formula requires compatible time scopes: {metric_id}")
        for relation_id, mapping in self.relation_bindings.items():
            relation = self.relations.get(relation_id)
            if relation is None:
                raise ValueError(f"Unknown relation binding: {relation_id}")
            for type_id, fields in (
                (relation.source_type, mapping.source_columns),
                (relation.target_type, mapping.target_columns),
            ):
                if type_id not in primary or not set(fields) <= {
                    column.column for column in primary[type_id].columns.values()
                }:
                    raise ValueError(f"Unmapped relation column in {relation_id} for {type_id}")
        return self

    def validate_rules_for_publication(self) -> None:
        for rule_id, rule in self.rules.items():
            literals: dict[str, list[RuleCondition]] = {}
            for condition in rule.conditions:
                if condition.operand == "literal":
                    literals.setdefault(condition.property, []).append(condition)
            properties = self.object_types[rule.object_type].properties
            for field, conditions in literals.items():
                if _literal_conditions_are_impossible(properties[field], conditions):
                    raise ValueError(f"Contradictory conditions for {field} in rule {rule_id}")

    def _validate_behaviors(self, primary: dict[str, ObjectBinding]) -> None:
        for rule_id, rule in self.rules.items():
            binding = primary.get(rule.object_type)
            available = {
                key for source in self.bindings if source.object_type == rule.object_type for key in source.columns
            }
            for condition in rule.conditions:
                if binding is None or condition.property not in available:
                    raise ValueError(f"Unbound property {condition.property} in rule {rule_id}")
                prop = self.object_types[rule.object_type].properties[condition.property]
                if prop.multiple or (condition.operand == "observed_at" and prop.type not in {"date", "datetime"}):
                    raise ValueError(f"Invalid operand for {condition.property} in rule {rule_id}")
                if condition.operand == "literal":
                    prop.parse(condition.value)
                if condition.function is not None:
                    function = self.functions.get(condition.function)
                    metric = self.metrics.get(function.metric) if function is not None else None
                    if (
                        metric is None
                        or prop.type not in {"integer", "number"}
                        or condition.function_filters.keys() - set(metric.allowed_filters)
                        or set(condition.function_filters.values()) - available
                    ):
                        raise ValueError(f"Invalid function operand in rule {rule_id}")
        for function_id, function in self.functions.items():
            if function.metric not in self.metrics:
                raise ValueError(f"Unknown metric in function {function_id}")
        for action_id, action in self.actions.items():
            if action.object_type not in primary:
                raise ValueError(f"Action needs a bound object type: {action_id}")
            for rule_id in action.preconditions:
                rule = self.rules.get(rule_id)
                if rule is None or rule.object_type != action.object_type:
                    raise ValueError(f"Invalid precondition {rule_id} for action {action_id}")
        for workflow_id, workflow in self.action_workflows.items():
            if set(workflow.actions) - self.actions.keys():
                raise ValueError(f"Unknown action in workflow {workflow_id}")

    def _validate_bindings(self) -> dict[str, ObjectBinding]:
        primary: dict[str, ObjectBinding] = {}
        seen: set[tuple[str, str, str]] = set()
        for binding in self.bindings:
            type_id = binding.object_type
            if type_id not in self.object_types:
                raise ValueError(f"Unknown object type in binding: {type_id}")
            key = type_id, binding.role, binding.asset_id
            if key in seen:
                raise ValueError(f"Duplicate binding for {type_id} and {binding.asset_id}")
            seen.add(key)
            definition = self.object_types[type_id]
            if binding.columns.keys() - definition.properties.keys():
                raise ValueError(f"Unknown property mapping for {type_id}")
            if binding.role == "document_evidence":
                if binding.identity_columns or binding.columns or binding.row_access_column is not None:
                    raise ValueError("Document evidence binding does not define physical identity columns")
                continue
            if not binding.columns:
                raise ValueError(f"Column mappings required for {type_id}")
            if binding.role == "enrichment":
                if not binding.identity_columns or len(binding.identity_columns) != len(definition.key):
                    raise ValueError(f"Identity columns for enrichment must match the business key of {type_id}")
                continue
            expected = [binding.columns[field].column for field in definition.key if field in binding.columns]
            if len(expected) != len(definition.key) or binding.identity_columns != expected:
                raise ValueError(f"Identity columns must match the mapped business key of {type_id}")
            if type_id in primary:
                raise ValueError(f"Only one primary binding is allowed for {type_id}")
            primary[type_id] = binding
        return primary


class _UniqueYamlLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        return _unique_mapping(self.construct_pairs(node, deep=deep))


def _unique_mapping(pairs):
    mapping = {}
    for key, value in pairs:
        if not isinstance(key, str):
            raise ValueError("Ontology mapping keys must be strings")
        if key in mapping:
            raise ValueError(f"Duplicate key: {key}")
        mapping[key] = value
    return mapping


def load_ontology_definition(content: str, *, format: Literal["yaml", "json"]) -> OntologyDefinition:
    try:
        data = (
            yaml.load(content, Loader=_UniqueYamlLoader)
            if format == "yaml"
            else json.loads(content, object_pairs_hook=_unique_mapping)
        )
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        mark = exc.problem_mark if isinstance(exc, yaml.MarkedYAMLError) else None
        line = mark.line + 1 if mark is not None else getattr(exc, "lineno", None)
        raise ValueError(f"Invalid {format.upper()} syntax" + (f" at line {line}" if line else "")) from exc
    return OntologyDefinition.model_validate(data)


def validate_ontology_relation(
    definition: OntologyDefinition, predicate: str, subject_type: str, object_type: str
) -> Literal["unknown_relation", "relation_endpoint_type_mismatch"] | None:
    relation = definition.relations.get(predicate)
    if relation is None:
        return "unknown_relation"
    if (subject_type, object_type) != (relation.source_type, relation.target_type):
        return "relation_endpoint_type_mismatch"
    return None
