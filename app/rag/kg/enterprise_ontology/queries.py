"""Execute published business queries over authorized, row-scoped table views."""

import re
import sqlite3
from contextlib import closing
from datetime import date
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.rag.kg.enterprise_ontology.definition import OntologyDefinition, PropertyDefinition, Scalar
from app.rag.kg.enterprise_ontology.objects import find_objects_by_name, primary_binding, read_business_object
from app.rag.kg.enterprise_ontology.snapshots import authorized_snapshot
from app.services.tables.store import run_table_query
from app.services.tables.store_paths import quote_sqlite_ident


class NamedQueryResult(BaseModel):
    query: str
    label: str
    description: str
    parameters: dict[str, Scalar | None] = Field(default_factory=dict)
    columns: list[str]
    rows: list[list[Scalar | None]]
    complete: bool
    document_ids: list[UUID]
    asset_ids: list[str]
    sql: str


def run_named_query(
    db: Session,
    *,
    definition: OntologyDefinition,
    tenant_id: UUID,
    account_id: str,
    query_id: str,
    parameters: dict[str, Scalar | None],
    document_ids: list[UUID] | None = None,
) -> NamedQueryResult:
    configured = definition.named_queries[query_id]
    # CTEs could impersonate a security view's name; published queries use SELECT/subqueries instead.
    if re.search(r"\bWITH\b|--|/\*", configured.sql, re.IGNORECASE):
        raise ValueError("Named queries do not allow CTEs or SQL comments")
    if set(parameters) - configured.parameters.keys():
        raise ValueError("Undeclared business query parameter")
    values = {}
    for name, parameter in configured.parameters.items():
        value = parameters.get(name)
        if value is None:
            if parameter.required:
                raise ValueError(f"Missing business query parameter: {name}")
            values[name] = None
        else:
            parsed = PropertyDefinition(type=parameter.type, enum=parameter.enum).parse(value)
            values[name] = parsed.isoformat() if isinstance(parsed, date) else parsed
    views = {}
    asset_ids = []
    complete = True
    primary = None
    with closing(sqlite3.connect(":memory:")) as literals:

        def literal(value):
            return literals.execute("SELECT quote(?)", (value,)).fetchone()[0]

        for object_type in configured.objects:
            binding = primary_binding(definition, object_type)
            doc, table, allowed = authorized_snapshot(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                asset_id=binding.asset_id,
                expected_revision=binding.asset_revision,
            )
            if document_ids is not None and doc.id not in document_ids:
                raise PermissionError("Business query source is outside the selected documents")
            if primary is None:
                primary = (doc, table, binding)
            elif doc.id != primary[0].id:
                raise ValueError("A named query currently requires sources in one registered workbook")
            fields = []
            for prop, mapping in binding.columns.items():
                if mapping.column not in allowed:
                    continue
                expression = quote_sqlite_ident(mapping.column)
                if mapping.values:
                    cases = " ".join(f"WHEN {literal(k)} THEN {literal(v)}" for k, v in mapping.values.items())
                    expression = f"CASE {expression} {cases} ELSE {expression} END"
                fields.append(f"{expression} AS {quote_sqlite_ident(prop)}")
            if not fields or binding.row_access_column is not None and binding.row_access_column not in allowed:
                raise PermissionError("Business query fields are not accessible")
            projection = f"SELECT {', '.join(fields)} FROM main.{quote_sqlite_ident(table.sql_table)}"
            if binding.row_access_column is not None:
                projection += f" WHERE {quote_sqlite_ident(binding.row_access_column)} = {literal(account_id)}"
            views[object_type] = (table.sql_table, projection)
            asset_ids.append(binding.asset_id)
            complete = complete and not table.truncated
    for name, parameter in configured.parameters.items():
        value = values[name]
        if parameter.object_type is None or value is None:
            continue
        obj = definition.object_types[parameter.object_type]
        if len(obj.key) != 1:
            raise ValueError("Object-bound query parameters require a single business key")
        try:
            read_business_object(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                definition=definition,
                object_type=parameter.object_type,
                key={obj.key[0]: value},
                properties=set(),
            )
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            matches, resolved = find_objects_by_name(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                definition=definition,
                object_type=parameter.object_type,
                name=str(value),
                filters={},
            )
            if not resolved or len(matches) != 1:
                raise ValueError(f"Query parameter {name} does not identify one readable business object") from exc
            values[name] = matches[0].key[obj.key[0]]
    doc, table, binding = primary
    result = run_table_query(
        tenant_id=tenant_id,
        dataset_id=doc.dataset_id,
        table_id=binding.asset_id,
        sql=configured.sql,
        parameters=values,
        max_rows=100,
        max_cols=40,
        max_bytes=64000,
        scoped_views=views,
    )
    return NamedQueryResult(
        query=query_id,
        label=configured.label,
        description=configured.description,
        parameters=values,
        columns=result["columns"],
        rows=result["rows"],
        complete=complete and not result["truncated"],
        document_ids=[doc.id],
        sql=result["sql"],
        asset_ids=asset_ids,
    )
