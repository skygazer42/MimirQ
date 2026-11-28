"""Resolve business identities through their authorized primary binding."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.rag.kg.enterprise_ontology.definition import Fact, ObjectBinding, OntologyDefinition, Scalar
from app.rag.kg.enterprise_ontology.edo_source import EdoProvenance, authorized_edo_table
from app.rag.kg.enterprise_ontology.mysql_source import authorized_mysql_asset, mysql_identifier
from app.rag.kg.enterprise_ontology.snapshots import authorized_snapshot, check_sample
from app.services.tables.store import run_table_query
from app.services.tables.store_paths import quote_sqlite_ident


class ObjectKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: dict[str, Scalar] = Field(min_length=1, max_length=16)


class BusinessObject(BaseModel):
    tenant_id: UUID
    ontology: str
    object_type: str
    namespace: str
    key: dict[str, Fact]
    attributes: dict[str, Fact | None]
    asset_id: str
    source_updated_at: datetime | None
    edo: EdoProvenance | None = None
    enrichment_assets: list[str] = Field(default_factory=list)


class RelatedObjects(BaseModel):
    relation: str
    objects: list[BusinessObject]
    complete: bool


@dataclass(frozen=True)
class SourceRows:
    columns: list[str]
    rows: list
    observed_at: datetime | None
    complete: bool
    edo: EdoProvenance | None = None


def primary_binding(definition: OntologyDefinition, object_type: str) -> ObjectBinding:
    for binding in definition.bindings:
        if binding.object_type == object_type and binding.role == "primary":
            return binding
    raise ValueError(f"No primary asset for {object_type}")


def _lookup_key(
    definition: OntologyDefinition, binding: ObjectBinding, key: dict[str, Scalar]
) -> dict[str, tuple[Scalar, ...]]:
    obj = definition.object_types[binding.object_type]
    if key.keys() != set(obj.key):
        raise ValueError("Object key must contain exactly the declared business key fields")
    conditions = {}
    for field in obj.key:
        value = obj.properties[field].parse(key[field])
        mapping = binding.columns[field]
        raw = value.isoformat() if isinstance(value, date) else value
        choices = [item for item, mapped in mapping.values.items() if mapped == raw]
        if str(raw) not in mapping.values:
            choices.append(raw)
        if not choices or raw == "":
            raise ValueError(f"Invalid value for business key {field}")
        conditions[mapping.column] = tuple(choices)
    return conditions


def _select_rows(
    table: str,
    fields: list[str],
    filters: dict[str, tuple],
    row_column: str | None,
    account_id: str,
    quote: Callable[[str], str],
    placeholder: str,
    limit: int,
) -> tuple[str, tuple]:
    conditions = []
    params = []
    if row_column:
        conditions.append(f"{quote(row_column)} = {placeholder}")
        params.append(account_id)
    for column, values in filters.items():
        placeholders = ", ".join(placeholder for _ in values)
        conditions.append(f"{quote(column)} IN ({placeholders})")
        params.extend(value.isoformat() if isinstance(value, date) else value for value in values)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    columns = ", ".join(quote(field) for field in fields)
    return f"SELECT {columns} FROM {quote(table)}{where} LIMIT {limit}", tuple(params)


def select_bound_rows(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    binding: ObjectBinding,
    columns: list[str],
    filters: dict[str, tuple],
    required: set[str],
    limit: int,
) -> SourceRows:
    mandatory = required | filters.keys()
    if binding.row_access_column is not None:
        mandatory.add(binding.row_access_column)
    is_mysql = binding.asset_id.startswith("catalog:")
    if binding.edo_binding is not None:
        edo = authorized_edo_table(tenant_id=tenant_id, binding=binding)
        allowed = set(edo.columns)
    elif is_mysql:
        asset = authorized_mysql_asset(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            asset_id=binding.asset_id,
            expected_revision=binding.asset_revision,
        )
        allowed = asset.columns
    else:
        document, table, allowed = authorized_snapshot(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            asset_id=binding.asset_id,
            expected_revision=binding.asset_revision,
        )
    if mandatory - allowed:
        raise PermissionError("Source projection uses unavailable columns")
    fields = list(dict.fromkeys(column for column in columns if column in allowed))
    if binding.edo_binding is not None:
        sql, params = _select_rows(
            edo.name,
            fields,
            filters,
            binding.row_access_column,
            account_id,
            quote_sqlite_ident,
            "?",
            limit + 1,
        )
        result = edo.select(sorted(set(fields) | mandatory), sql, params)
        return SourceRows(
            fields,
            result.rows[:limit],
            result.provenance.synced_at,
            result.complete and len(result.rows) <= limit,
            result.provenance,
        )
    if is_mysql:
        sql, params = _select_rows(
            asset.table_name,
            fields,
            filters,
            binding.row_access_column,
            account_id,
            mysql_identifier,
            "%s",
            limit + 1,
        )
        rows = asset.select(sql, params, limit=limit + 1)
        return SourceRows(fields, rows[:limit], datetime.now(UTC), len(rows) <= limit)
    sql, params = _select_rows(
        table.sql_table,
        fields,
        filters,
        binding.row_access_column,
        account_id,
        quote_sqlite_ident,
        "?",
        limit + 1,
    )
    result = run_table_query(
        tenant_id=tenant_id,
        dataset_id=document.dataset_id,
        table_id=table.table_id,
        sql=sql,
        parameters=params,
        max_rows=limit + 1,
        max_cols=len(fields),
        max_bytes=256 * 1024,
    )
    rows = result["rows"]
    return SourceRows(fields, rows[:limit], document.updated_at, not (result["truncated"] or len(rows) > limit))


def _project_records(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    definition: OntologyDefinition,
    binding: ObjectBinding,
    filters: dict[str, tuple],
    properties: set[str] | None,
    limit: int,
) -> tuple[list[BusinessObject], bool]:
    obj = definition.object_types[binding.object_type]
    fields = {
        name: mapping
        for name, mapping in binding.columns.items()
        if properties is None or name in obj.key or name in properties
    }
    source = select_bound_rows(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        binding=binding,
        columns=[item.column for item in fields.values()],
        filters=filters,
        required=set(binding.identity_columns),
        limit=limit,
    )
    indices = {name: index for index, name in enumerate(source.columns)}
    fields = {name: item for name, item in fields.items() if item.column in indices}
    rows = [[row[indices[item.column]] for item in fields.values()] for row in source.rows]
    records, issues = check_sample(binding.model_copy(update={"columns": fields}), obj, rows)
    if any(issue.field in obj.key for issue in issues):
        raise ValueError("Source row has an invalid business key")
    return [
        BusinessObject(
            tenant_id=tenant_id,
            ontology=definition.ontology,
            object_type=binding.object_type,
            namespace=binding.identity_namespace or binding.asset_id,
            key={field: record[field] for field in obj.key},
            attributes=record,
            asset_id=binding.asset_id,
            source_updated_at=source.observed_at,
            edo=source.edo,
        )
        for record in records
    ], source.complete


def read_business_object(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    definition: OntologyDefinition,
    object_type: str,
    key: dict[str, Scalar],
    properties: set[str] | None = None,
) -> BusinessObject:
    binding = primary_binding(definition, object_type)
    records, complete = _project_records(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        definition=definition,
        binding=binding,
        filters=_lookup_key(definition, binding, key),
        properties=properties,
        limit=1,
    )
    if not records:
        raise HTTPException(status_code=404, detail="No readable object has that business key")
    if not complete:
        raise HTTPException(status_code=409, detail="Business key resolves to multiple source rows")
    record = records[0]
    for enrichment in definition.bindings:
        if enrichment.role != "enrichment" or enrichment.object_type != object_type:
            continue
        requested = {
            name: mapping
            for name, mapping in enrichment.columns.items()
            if name not in record.attributes and (properties is None or name in properties)
        }
        if not requested:
            continue
        raw_key = list(record.key.values())
        try:
            rows = select_bound_rows(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                binding=enrichment,
                columns=[*enrichment.identity_columns, *(field.column for field in requested.values())],
                filters={column: (value,) for column, value in zip(enrichment.identity_columns, raw_key, strict=True)},
                required=set(enrichment.identity_columns),
                limit=1,
            )
        except (HTTPException, PermissionError, FileNotFoundError):
            continue
        if not rows.complete or not rows.rows:
            continue
        info = dict(zip(rows.columns, rows.rows[0], strict=True))
        requested = {name: column for name, column in requested.items() if column.column in info}
        [extra], _ = check_sample(
            enrichment.model_copy(update={"columns": requested}),
            definition.object_types[object_type],
            [[info[column.column] for column in requested.values()]],
        )
        if extra:
            record.attributes.update(extra)
            record.enrichment_assets.append(enrichment.asset_id)
    return record


def read_related_objects(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    definition: OntologyDefinition,
    relation_id: str,
    from_object: str,
    key: dict[str, Scalar],
) -> RelatedObjects:
    relation = definition.relations.get(relation_id)
    mapping = definition.relation_bindings.get(relation_id)
    if relation is None or mapping is None or from_object not in {relation.source_type, relation.target_type}:
        raise ValueError("Relation needs a saved binding and matching origin type")
    forward = from_object == relation.source_type
    other_type = relation.target_type if forward else relation.source_type
    own_columns = mapping.source_columns if forward else mapping.target_columns
    other_columns = mapping.target_columns if forward else mapping.source_columns
    source = primary_binding(definition, from_object)
    target = primary_binding(definition, other_type)
    anchor = select_bound_rows(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        binding=source,
        columns=own_columns,
        filters=_lookup_key(definition, source, key),
        required=set(own_columns),
        limit=1,
    )
    if not anchor.rows:
        raise HTTPException(status_code=404, detail="No readable origin object has that business key")
    if not anchor.complete:
        raise HTTPException(status_code=409, detail="Business key resolves to multiple source rows")
    [values] = anchor.rows
    related = RelatedObjects(relation=relation_id, objects=[], complete=True)
    if any(value is None for value in values):
        return related
    joins: list[Any] = [values]
    if mapping.bridge_asset_id:
        bridge = ObjectBinding(
            object_type=from_object,
            role="enrichment",
            asset_id=mapping.bridge_asset_id,
            row_access_column=mapping.bridge_row_access_column,
        )
        bridge_own = mapping.bridge_source_columns if forward else mapping.bridge_target_columns
        bridge_other = mapping.bridge_target_columns if forward else mapping.bridge_source_columns
        join_rows = select_bound_rows(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            binding=bridge,
            columns=bridge_other,
            filters={column: (value,) for column, value in zip(bridge_own, values, strict=True)},
            required=set(bridge_other),
            limit=50,
        )
        joins = list(dict.fromkeys(tuple(values) for values in join_rows.rows if None not in values))
        related.complete = join_rows.complete
    single = relation.cardinality == "one_to_one" or (
        relation.cardinality == ("many_to_one" if forward else "one_to_many")
    )
    for values in joins:
        records, complete = _project_records(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            definition=definition,
            binding=target,
            filters={column: (value,) for column, value in zip(other_columns, values, strict=True)},
            properties=None,
            limit=2 if single else 50,
        )
        related.objects.extend(records)
        related.complete = related.complete and complete
    unique = {}
    for item in related.objects:
        identity = tuple(item.key[field] for field in definition.object_types[item.object_type].key)
        unique.setdefault(identity, item)
    related.objects = list(unique.values())
    if single and (len(related.objects) > 1 or not related.complete):
        raise HTTPException(status_code=409, detail="Related source data violates the declared cardinality")
    related.complete = related.complete and len(related.objects) <= 50
    related.objects = related.objects[:50]
    return related


def find_objects_by_name(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    definition: OntologyDefinition,
    object_type: str,
    name: str,
    filters: dict[str, Scalar],
) -> tuple[list[BusinessObject], bool]:
    binding = primary_binding(definition, object_type)
    obj = definition.object_types[object_type]
    field = obj.display_property or "name"
    mapping = binding.columns.get(field)
    if mapping is None:
        return [], True
    values = [raw for raw, value in mapping.values.items() if value == name]
    if name not in mapping.values:
        values.append(name)
    if not values:
        return [], True
    criteria = {mapping.column: tuple(values)}
    for field, raw in filters.items():
        if field not in binding.columns or field not in obj.properties or obj.properties[field].multiple:
            raise ValueError(f"Object qualifier must be a mapped scalar property: {field}")
        value = obj.properties[field].parse(raw)
        column = binding.columns[field]
        value = value.isoformat() if isinstance(value, date) else value
        choices = [source for source, mapped in column.values.items() if mapped == value]
        if str(value) not in column.values:
            choices.append(value)
        if column.column in criteria:
            choices = [item for item in choices if item in criteria[column.column]]
        if not choices:
            return [], True
        criteria[column.column] = tuple(choices)
    return _project_records(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        definition=definition,
        binding=binding,
        filters=criteria,
        properties=None,
        limit=6,
    )
