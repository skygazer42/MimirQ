"""Compile named ontology metrics over authorized structured assets."""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.infrastructure.config import settings
from app.rag.kg.enterprise_ontology.definition import (
    Fact,
    MetricDefinition,
    ObjectBinding,
    OntologyDefinition,
    PropertyDefinition,
    Scalar,
    SemanticId,
)
from app.rag.kg.enterprise_ontology.edo_source import (
    EdoProvenance,
    EdoResult,
    EdoSourceError,
    authorized_edo_table,
    edo_property_matches,
)
from app.rag.kg.enterprise_ontology.mysql_source import authorized_mysql_asset, mysql_identifier
from app.rag.kg.enterprise_ontology.objects import primary_binding
from app.rag.kg.enterprise_ontology.snapshots import authorized_snapshot
from app.services.tables.store import run_table_query
from app.services.tables.store_paths import quote_sqlite_ident

_MAX_METRIC_GROUPS = 50


class MetricWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def check_window(self):
        if self.start >= self.end:
            raise ValueError("Comparison window start must be earlier than its end")
        return self


class MetricQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    filters: dict[str, Scalar] = Field(default_factory=dict)
    group_by: list[SemanticId] = Field(default_factory=list, max_length=8, exclude_if=lambda value: not value)
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None
    observed_at: AwareDatetime | None = None
    historical_state: bool = False
    comparison: MetricWindow | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def check_query(self):
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("Metric window start must be earlier than its end")
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("Metric grouping dimensions must be unique")
        return self


class MetricGroup(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    dimensions: dict[str, Fact | None]
    value: Decimal | int | float | None


class MetricComparison(BaseModel):
    value: Decimal | int | float | None
    complete: bool
    reason: str | None
    change: Decimal | None = None
    change_percent: Decimal | None = None


class MetricFormulaEvidence(BaseModel):
    operation: Literal["difference", "ratio", "percent"]
    base_value: Decimal | int | float | None
    reference_metric: str
    reference_value: Decimal | int | float | None
    reference_asset_id: str


class MetricResult(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    metric: str
    value: Decimal | int | float | None
    complete: bool
    asset_id: str
    source_updated_at: datetime | None
    query: MetricQuery
    groups: list[MetricGroup] | None = Field(default=None, exclude_if=lambda value: value is None)
    reason: str | None = None
    edo: EdoProvenance | None = None
    comparison: MetricComparison | None = Field(default=None, exclude_if=lambda value: value is None)
    formula: MetricFormulaEvidence | None = Field(default=None, exclude_if=lambda value: value is None)


def _check_metric_scope(metric: MetricDefinition, query: MetricQuery) -> None:
    if query.filters.keys() - set(metric.allowed_filters):
        raise ValueError("Metric filter is outside its declared scope")
    if set(query.group_by) - set(metric.dimensions):
        raise ValueError("Metric grouping is outside its declared dimensions")


def compile_snapshot_metric(
    definition: OntologyDefinition,
    metric_id: str,
    sql_table: str,
    query: MetricQuery,
    *,
    account_id: str,
    dialect: Literal["sqlite", "mysql"] = "sqlite",
    edo_columns: dict[str, str] | None = None,
) -> tuple[str, tuple[Scalar, ...]]:
    metric = definition.metrics.get(metric_id)
    if metric is None:
        raise ValueError("Unknown ontology metric")
    binding = primary_binding(definition, metric.object_type)
    _check_metric_scope(metric, query)
    properties = definition.object_types[metric.object_type].properties
    conditions: list[str] = []
    parameters: list[Scalar] = []
    quote = mysql_identifier if dialect == "mysql" else quote_sqlite_ident
    placeholder = "%s" if dialect == "mysql" else "?"

    def column(property_id: str) -> str:
        mapping = binding.columns[property_id]
        quoted = quote(mapping.column)
        if not mapping.values:
            return quoted
        for source, target in mapping.values.items():
            parameters.extend((source, target))
        clauses = " ".join(f"WHEN {placeholder} THEN {placeholder}" for _ in mapping.values)
        return f"(CASE {quoted} {clauses} ELSE {quoted} END)"

    dimension_selects = [
        f"{column(field)} AS {quote(f'dimension_{index}')}" for index, field in enumerate(query.group_by)
    ]
    value_mapping = binding.columns[metric.property]
    decimal_column = edo_columns is not None and edo_columns[value_mapping.column] == "DECIMAL"
    if decimal_column and value_mapping.values and metric.aggregate != "count":
        # shortcut: decimal aggregate operands must be direct columns, revisit when EDO supports exact transforms.
        raise ValueError("EDO decimal aggregation requires an untransformed value column")
    exact_decimal = decimal_column and metric.aggregate in {"sum", "avg"}
    operand = column(metric.property)
    if metric.aggregate == "count_distinct":
        expression = f"COUNT(DISTINCT {operand})"
    else:
        aggregate = "decimal_" + metric.aggregate if exact_decimal else metric.aggregate.upper()
        expression = f"{aggregate}({operand})"
    if binding.row_access_column is not None:
        conditions.append(f"{quote(binding.row_access_column)} = {placeholder}")
        parameters.append(account_id)
    for filters in (metric.required_filters, query.filters):
        for property_id, raw in filters.items():
            prop = properties[property_id]
            parsed = prop.parse(raw)
            if isinstance(parsed, float) and not isfinite(parsed):
                raise ValueError(f"Metric filter must be finite: {property_id}")
            mapping = binding.columns[property_id]
            source_type = edo_columns[mapping.column] if edo_columns is not None else None
            value = parsed.isoformat() if isinstance(parsed, date) else parsed
            if source_type == "DECIMAL":
                value = str(int(raw) if isinstance(raw, bool) else raw).strip()
            if exact_decimal and mapping.values:
                # EDO's exact decimal SQL validator accepts scalar predicates, so invert the enum mapping.
                sources = [source for source, target in mapping.values.items() if prop.parse(target) == parsed]
                if str(value) not in mapping.values:
                    sources.append(value)
                predicates = [f"{quote(mapping.column)} = {placeholder}" for _ in sources]
                conditions.append("(" + " OR ".join(predicates) + ")" if predicates else "1 = 0")
                parameters.extend(sources)
            else:
                operand = column(property_id)
                equality = f"{operand} = {placeholder}"
                if source_type == "DATETIME":
                    equality = f"julianday({operand}) = julianday({placeholder})"
                conditions.append(equality)
                parameters.append(value)
    time_limits = (
        (query.start, ">="),
        (query.end, "<"),
        (query.observed_at if metric.before_observation else None, "<"),
    )
    if metric.before_observation and query.observed_at is None:
        raise ValueError("Observed time is required by this metric")
    for value, operator in time_limits:
        if value is not None:
            if metric.time_property is None:
                raise ValueError("This metric does not have a time property")
            operand = column(metric.time_property)
            if dialect == "mysql":
                conditions.append(f"{operand} {operator} {placeholder}")
                parameters.append(value.astimezone(UTC).replace(tzinfo=None).isoformat(sep=" "))
            else:
                conditions.append(f"julianday({operand}) {operator} julianday(?)")
                parameters.append(value.isoformat())
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    projection = ", ".join([*dimension_selects, f"{expression} AS value"])
    statement = f"SELECT {projection} FROM {quote(sql_table)}{where}"
    if dimension_selects:
        positions = ", ".join(str(index) for index in range(1, len(dimension_selects) + 1))
        statement += f" GROUP BY {positions} ORDER BY {positions}"
    return statement, tuple(parameters)


def _coverage_issue(binding: ObjectBinding, query: MetricQuery) -> str | None:
    if query.historical_state and (query.observed_at is None or binding.snapshot_observed_at != query.observed_at):
        return "historical_state_unavailable"
    if (
        binding.coverage_start is not None
        and (query.start is None or query.start < binding.coverage_start)
        or binding.coverage_end is not None
        and (query.end is None or query.end > binding.coverage_end)
    ):
        return "source_window_incomplete"
    return None


def _covered_query(binding: ObjectBinding, query: MetricQuery) -> MetricQuery | None:
    starts = [value for value in (binding.coverage_start, query.start) if value is not None]
    ends = [value for value in (binding.coverage_end, query.end) if value is not None]
    start, end = max(starts, default=None), min(ends, default=None)
    if start is not None and end is not None and start >= end:
        return None
    return query.model_copy(update={"start": start, "end": end})


def _edo_metric_value(result: EdoResult, *, decimal_output: bool) -> Decimal | int | float | None:
    if not result.rows and not result.complete:
        return None
    if len(result.rows) != 1 or len(result.rows[0]) != 1:
        raise EdoSourceError("edo_invalid_response")
    value = result.rows[0][0]
    if isinstance(value, str):
        try:
            value = Decimal(value) if decimal_output else int(value)
        except (InvalidOperation, ValueError) as exc:
            raise EdoSourceError("edo_invalid_response") from exc
    if isinstance(value, bool) or (isinstance(value, Decimal) and not value.is_finite()):
        raise EdoSourceError("edo_invalid_response")
    return value


def _metric_groups(
    rows: Sequence[Sequence[Fact | Decimal | None]],
    fields: list[str],
    properties: dict[str, PropertyDefinition],
) -> list[MetricGroup]:
    return [
        MetricGroup(
            dimensions={
                field: properties[field].parse(raw) if raw is not None else None
                for field, raw in zip(fields, row[:-1], strict=True)
            },
            value=row[-1],
        )
        for row in rows[:_MAX_METRIC_GROUPS]
    ]


def evaluate_snapshot_metric(
    db: Session, *, definition: OntologyDefinition, metric_id: str, query: MetricQuery, tenant_id: UUID, account_id: str
) -> MetricResult:
    window = query.comparison
    if window is None:
        return _evaluate_metric_window(
            db, definition=definition, metric_id=metric_id, query=query, tenant_id=tenant_id, account_id=account_id
        )
    if query.start is None or query.end is None or window.end > query.start or query.group_by:
        raise ValueError("Comparison requires two ordered, non-overlapping windows and an ungrouped metric")
    metric = definition.metrics.get(metric_id)
    if metric is None or metric.time_property is None:
        raise ValueError("Comparison requires a metric with a declared time property")
    current = _evaluate_metric_window(
        db, definition=definition, metric_id=metric_id, query=query, tenant_id=tenant_id, account_id=account_id
    )
    baseline_query = query.model_copy(update={"start": window.start, "end": window.end, "comparison": None})
    if metric.before_observation:
        baseline_query = baseline_query.model_copy(update={"observed_at": window.end, "historical_state": True})
    baseline = _evaluate_metric_window(
        db, definition=definition, metric_id=metric_id, query=baseline_query, tenant_id=tenant_id, account_id=account_id
    )
    complete = current.complete and baseline.complete
    comparison = MetricComparison(value=baseline.value, complete=complete, reason=current.reason or baseline.reason)
    if complete and current.value is not None and baseline.value is not None:
        reference = Decimal(str(baseline.value))
        comparison.change = Decimal(str(current.value)) - reference
        if reference:
            comparison.change_percent = comparison.change * 100 / abs(reference)
    return current.model_copy(update={"comparison": comparison})


def _evaluate_metric_window(
    db: Session, *, definition: OntologyDefinition, metric_id: str, query: MetricQuery, tenant_id: UUID, account_id: str
) -> MetricResult:
    current = _evaluate_base_metric(
        db, definition=definition, metric_id=metric_id, query=query, tenant_id=tenant_id, account_id=account_id
    )
    formula = definition.metrics[metric_id].formula
    if formula is None:
        return current
    reference = _evaluate_base_metric(
        db, definition=definition, metric_id=formula.metric, query=query, tenant_id=tenant_id, account_id=account_id
    )
    evidence = MetricFormulaEvidence(
        operation=formula.operation,
        base_value=current.value,
        reference_metric=reference.metric,
        reference_value=reference.value,
        reference_asset_id=reference.asset_id,
    )
    value = None
    reason = current.reason or reference.reason
    if current.complete and reference.complete and current.value is not None and reference.value is not None:
        base = Decimal(str(current.value))
        operand = Decimal(str(reference.value))
        if formula.operation == "difference":
            value = base - operand
        elif operand == 0:
            reason = "zero_formula_denominator"
        else:
            value = base / operand
            if formula.operation == "percent":
                value *= 100
    return current.model_copy(
        update={
            "value": value,
            "formula": evidence,
            "complete": value is not None,
            "reason": reason if value is not None or reason is not None else "formula_operand_unavailable",
        }
    )


def _evaluate_base_metric(
    db: Session, *, definition: OntologyDefinition, metric_id: str, query: MetricQuery, tenant_id: UUID, account_id: str
) -> MetricResult:
    if metric_id not in definition.metrics:
        raise ValueError("Unknown ontology metric")
    metric = definition.metrics[metric_id]
    _check_metric_scope(metric, query)
    binding = primary_binding(definition, metric.object_type)
    reason = _coverage_issue(binding, query)
    source_query = query
    if reason == "historical_state_unavailable":
        source_query = None
    elif reason == "source_window_incomplete" and metric.time_property is not None:
        source_query = _covered_query(binding, query)
    properties = {metric.property, *metric.required_filters, *query.filters, *query.group_by}
    logical_fields = definition.object_types[metric.object_type].properties
    if metric.time_property is not None and (
        metric.before_observation or (source_query and (source_query.start or source_query.end))
    ):
        properties.add(metric.time_property)
    if properties - binding.columns.keys():
        raise PermissionError("Metric uses unavailable source properties")
    required = {binding.columns[prop].column for prop in properties}
    if binding.row_access_column is not None:
        required.add(binding.row_access_column)
    if binding.edo_binding is not None:
        asset = authorized_edo_table(tenant_id=tenant_id, binding=binding)
        if required - asset.columns.keys():
            raise PermissionError("Metric uses unavailable EDO columns")
        for prop in sorted(properties):
            if not edo_property_matches(logical_fields[prop], asset.columns[binding.columns[prop].column]):
                raise ValueError(f"EDO column type does not match metric property: {prop}")
        if binding.row_access_column is not None and asset.columns[binding.row_access_column] != "STRING":
            raise ValueError("EDO row access column must be a string")
        if source_query is None:
            return MetricResult(
                metric=metric_id,
                value=None,
                complete=False,
                asset_id=binding.asset_id,
                source_updated_at=None,
                query=query,
                reason=reason,
            )
        sql, parameters = compile_snapshot_metric(
            definition,
            metric_id,
            asset.name,
            source_query,
            account_id=account_id,
            edo_columns=asset.columns,
        )
        if query.group_by:
            sql += f" LIMIT {_MAX_METRIC_GROUPS + 1}"
        result = asset.select(sorted(required), sql, parameters)
        evidence = result.provenance
        decimal_output = asset.columns[binding.columns[metric.property].column] == "DECIMAL" and metric.aggregate in {
            "min",
            "max",
            "sum",
            "avg",
        }
        groups = None
        value = None
        if query.group_by:
            if result.rows or result.complete:
                groups = _metric_groups(result.rows, query.group_by, logical_fields)
            if reason is None and len(result.rows) > _MAX_METRIC_GROUPS:
                reason = "group_limit_reached"
        else:
            value = _edo_metric_value(result, decimal_output=decimal_output)
        if query.historical_state and evidence.synced_at != query.observed_at:
            value = None
            groups = None
            reason = "historical_state_unavailable"
        if reason is None and not result.complete:
            reason = evidence.reason_code or "edo_partial_coverage"
        return MetricResult(
            metric=metric_id,
            value=value,
            complete=result.complete and reason is None,
            asset_id=binding.asset_id,
            source_updated_at=evidence.synced_at,
            query=query,
            groups=groups,
            reason=reason,
            edo=evidence,
        )
    if binding.asset_id.startswith("catalog:"):
        asset = authorized_mysql_asset(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            asset_id=binding.asset_id,
            expected_revision=binding.asset_revision,
        )
        if required - asset.columns:
            raise PermissionError("Metric uses unavailable source properties")
        if source_query is None:
            return MetricResult(
                metric=metric_id,
                value=None,
                complete=False,
                asset_id=asset.id,
                source_updated_at=None,
                query=query,
                reason=reason,
            )
        sql, parameters = compile_snapshot_metric(
            definition, metric_id, asset.table_name, source_query, account_id=account_id, dialect="mysql"
        )
        limit = _MAX_METRIC_GROUPS + 1 if query.group_by else 1
        rows = asset.select(f"{sql} LIMIT {limit}" if query.group_by else sql, parameters, limit=limit)
        if query.group_by and len(rows) > _MAX_METRIC_GROUPS:
            reason = reason or "group_limit_reached"
        value = rows[0][0] if not query.group_by else None
        return MetricResult(
            metric=metric_id,
            value=float(value) if isinstance(value, Decimal) else value,
            complete=reason is None,
            asset_id=asset.id,
            source_updated_at=datetime.now(UTC),
            query=query,
            groups=_metric_groups(rows, query.group_by, logical_fields) if query.group_by else None,
            reason=reason,
        )
    document, table, columns = authorized_snapshot(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        asset_id=binding.asset_id,
        expected_revision=binding.asset_revision,
    )
    if required - columns:
        raise PermissionError("Metric uses unavailable source properties")
    if source_query is None:
        return MetricResult(
            metric=metric_id,
            value=None,
            complete=False,
            asset_id=table.table_id,
            source_updated_at=document.updated_at,
            query=query,
            reason=reason,
        )
    sql, parameters = compile_snapshot_metric(
        definition, metric_id, table.sql_table, source_query, account_id=account_id
    )
    limit = min(_MAX_METRIC_GROUPS + 1, settings.TABLE_QUERY_MAX_ROWS) if query.group_by else 1
    result = run_table_query(
        tenant_id=tenant_id,
        dataset_id=document.dataset_id,
        table_id=table.table_id,
        sql=sql,
        parameters=parameters,
        max_rows=limit,
        max_cols=len(query.group_by) + 1,
        max_bytes=65536 if query.group_by else 4096,
    )
    rows = result["rows"]
    if query.group_by and len(rows) >= limit:
        reason = reason or "group_limit_reached"
    if table.truncated or result["truncated"]:
        reason = reason or "source_truncated"
    return MetricResult(
        metric=metric_id,
        value=rows[0][0] if not query.group_by else None,
        complete=reason is None,
        asset_id=table.table_id,
        source_updated_at=document.updated_at,
        query=query,
        groups=_metric_groups(rows, query.group_by, logical_fields) if query.group_by else None,
        reason=reason,
    )
