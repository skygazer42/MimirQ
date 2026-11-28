"""Validate logical ontology bindings against authorized structured assets."""

import hashlib
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.documents.records import Document
from app.rag.kg.enterprise_ontology.definition import ColumnMapping, ObjectBinding, ObjectDefinition, OntologyDefinition
from app.rag.kg.enterprise_ontology.edo_source import (
    EdoProvenance,
    EdoSourceError,
    authorized_edo_table,
    edo_property_matches,
)
from app.rag.kg.enterprise_ontology.mysql_source import authorized_mysql_asset, mysql_identifier
from app.services.datasets.management import ensure_member, get_dataset
from app.services.documents.read_scope import filter_allowed_document_ids
from app.services.tables.field_security import FlsUserContext, build_fls_column_mask_map, parse_fls_policy_from_metadata
from app.services.tables.store import TableAsset, list_tables_from_metadata, run_table_query
from app.services.tables.store_paths import parse_table_id, quote_sqlite_ident


class BindingIssue(BaseModel):
    code: str
    field: str | None = None


class BindingPreview(BaseModel):
    asset_id: str
    object_type: str
    role: str
    identity_columns: list[str]
    asset_revision: str | None = None
    row_count: int | None = None
    truncated: bool = False
    sample: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[BindingIssue] = Field(default_factory=list)
    edo: EdoProvenance | None = None


def select_columns(sql_table: str, columns: dict[str, ColumnMapping]) -> str:
    quoted = quote_sqlite_ident
    fields = ", ".join(f"{quoted(mapping.column)} AS {quoted(prop)}" for prop, mapping in columns.items())
    return f"SELECT {fields} FROM {quoted(sql_table)}"


def check_sample(
    binding: ObjectBinding,
    definition: ObjectDefinition,
    rows: list[list[Any]] | list[tuple[Any, ...]],
) -> tuple[list[dict[str, Any]], list[BindingIssue]]:
    issues: dict[tuple[str, str], BindingIssue] = {}
    sample: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = {}
        for (prop, mapping), raw in zip(binding.columns.items(), row, strict=True):
            field = definition.properties[prop]
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                if field.required or prop in definition.key:
                    issues["missing_value", prop] = BindingIssue(code="missing_value", field=prop)
                record[prop] = None
                continue
            value = mapping.values.get(str(raw), raw)
            try:
                value = field.parse(value)
            except ValueError:
                issues["invalid_value", prop] = BindingIssue(code="invalid_value", field=prop)
                continue
            record[prop] = value
        sample.append(record)
    return sample, list(issues.values())


def snapshot_schema_revision(table: TableAsset) -> str:
    shape = json.dumps(table.columns, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(shape).hexdigest()


def authorized_snapshot(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    asset_id: str,
    expected_revision: str | None = None,
) -> tuple[Document, TableAsset, set[str]]:
    parsed = parse_table_id(asset_id)
    if parsed is None:
        raise HTTPException(status_code=422, detail="Binding requires a registered Table Store asset ID")
    filter_allowed_document_ids(db, tenant_id, account_id, [parsed.document_id])
    doc = db.scalar(select(Document).where(Document.id == parsed.document_id, Document.tenant_id == tenant_id))
    if doc is None or doc.dataset_id is None:
        raise HTTPException(status_code=404, detail="Table asset not found")
    tables = list_tables_from_metadata(doc.doc_metadata)
    table = next((item for item in tables if item.table_id == parsed.id), None)
    if table is None:
        raise HTTPException(status_code=404, detail="Table asset not found")
    if expected_revision is not None and snapshot_schema_revision(table) != expected_revision:
        raise HTTPException(status_code=409, detail="Table asset schema changed; review its binding")
    dataset = get_dataset(db, tenant_id, doc.dataset_id)
    policy = parse_fls_policy_from_metadata(dataset.dataset_metadata)
    columns = {item["name"] for item in table.columns}
    if policy is not None:
        member = ensure_member(db, tenant_id, account_id)
        masked = build_fls_column_mask_map(
            policy,
            source="table_store",
            columns=sorted(columns),
            ctx=FlsUserContext(account_id=account_id, role=member.role.lower()),
        )
        columns -= masked.keys()
    return doc, table, columns


def _preview_edo_binding(
    preview: BindingPreview,
    binding: ObjectBinding,
    obj: ObjectDefinition,
    *,
    tenant_id: UUID,
    account_id: str,
) -> None:
    asset = authorized_edo_table(tenant_id=tenant_id, binding=binding)
    referenced = {mapping.column for mapping in binding.columns.values()} | set(binding.identity_columns)
    row_column = binding.row_access_column
    if row_column is not None:
        referenced.add(row_column)
    preview.issues.extend(
        BindingIssue(code="unavailable_column", field=column) for column in sorted(referenced - asset.columns.keys())
    )
    for name, mapping in binding.columns.items():
        column_type = asset.columns.get(mapping.column)
        if column_type is not None and not edo_property_matches(obj.properties[name], column_type):
            preview.issues.append(BindingIssue(code="edo_column_type_mismatch", field=name))
    if row_column in asset.columns and asset.columns[row_column] != "STRING":
        preview.issues.append(BindingIssue(code="edo_column_type_mismatch", field=row_column))
    if preview.issues:
        return
    quote = quote_sqlite_ident
    scope = f" WHERE {quote(row_column)} = ?" if row_column else ""
    params = (account_id,) if row_column else ()
    sample = asset.select(sorted(referenced), select_columns(asset.name, binding.columns) + scope + " LIMIT 8", params)
    preview.edo = sample.provenance
    preview.row_count = sample.loaded_row_count if row_column is None else None
    preview.truncated = not sample.complete
    preview.sample, preview.issues = check_sample(binding, obj, sample.rows)
    if not sample.complete:
        preview.issues.append(BindingIssue(code=sample.provenance.reason_code or "edo_partial_coverage"))
        return
    if binding.identity_columns:
        keys = ", ".join(quote(key) for key in binding.identity_columns)
        missing_keys = " OR ".join(
            f"{quote(key)} IS NULL OR trim({quote(key)}) = ''" for key in binding.identity_columns
        )
        duplicate = asset.select(
            sorted({*binding.identity_columns, *([row_column] if row_column else [])}),
            f"SELECT 1 AS invalid_key FROM {quote(asset.name)}{scope} GROUP BY {keys} "
            f"HAVING COUNT(*) > 1 OR {missing_keys} LIMIT 1",
            params,
        )
        if not duplicate.complete:
            preview.truncated = True
            preview.issues.append(BindingIssue(code=duplicate.provenance.reason_code or "edo_partial_coverage"))
        elif (sample.provenance.projection_id, sample.provenance.synced_at) != (
            duplicate.provenance.projection_id,
            duplicate.provenance.synced_at,
        ):
            raise EdoSourceError("edo_projection_unavailable", 409)
        elif duplicate.rows:
            preview.issues.append(BindingIssue(code="missing_or_duplicate_identity"))


def preview_bindings(
    db: Session, *, tenant_id: UUID, account_id: str, definition: OntologyDefinition
) -> list[BindingPreview]:
    previews = []
    for binding in definition.bindings:
        preview = BindingPreview(
            asset_id=binding.asset_id,
            object_type=binding.object_type,
            role=binding.role,
            identity_columns=binding.identity_columns,
        )
        previews.append(preview)
        if binding.role == "document_evidence":
            try:
                document_id = UUID(binding.asset_id.removeprefix("document:"))
            except ValueError:
                preview.issues.append(BindingIssue(code="invalid_document_asset"))
            else:
                filter_allowed_document_ids(db, tenant_id, account_id, [document_id])
            continue
        if binding.edo_binding is not None:
            try:
                _preview_edo_binding(
                    preview,
                    binding,
                    definition.object_types[binding.object_type],
                    tenant_id=tenant_id,
                    account_id=account_id,
                )
            except EdoSourceError as exc:
                preview.edo = None
                preview.sample.clear()
                preview.row_count = None
                preview.issues.append(BindingIssue(code=exc.code))
            continue
        if binding.asset_id.startswith("catalog:"):
            asset = authorized_mysql_asset(db, tenant_id=tenant_id, account_id=account_id, asset_id=binding.asset_id)
            preview.asset_revision = asset.revision
            if binding.asset_revision not in {None, preview.asset_revision}:
                preview.issues.append(BindingIssue(code="asset_schema_changed"))
                continue
            fields = {item.column for item in binding.columns.values()} | set(binding.identity_columns)
            if binding.row_access_column is not None:
                fields.add(binding.row_access_column)
            if missing := fields - asset.columns:
                preview.issues.extend(BindingIssue(code="unavailable_column", field=field) for field in sorted(missing))
                continue
            quoted_fields = ", ".join(mysql_identifier(item.column) for item in binding.columns.values())
            row_scope = (
                f" WHERE {mysql_identifier(binding.row_access_column)} = %s" if binding.row_access_column else ""
            )
            params = (account_id,) if binding.row_access_column else ()
            table = mysql_identifier(asset.table_name)
            rows = asset.select(f"SELECT {quoted_fields} FROM {table}{row_scope} LIMIT 8", params, limit=8)
            preview.sample, preview.issues = check_sample(binding, definition.object_types[binding.object_type], rows)
            keys = ", ".join(mysql_identifier(item) for item in binding.identity_columns)
            empty_keys = " OR ".join(
                f"{mysql_identifier(key)} IS NULL OR TRIM({mysql_identifier(key)}) = ''"
                for key in binding.identity_columns
            )
            duplicate = asset.select(
                f"SELECT 1 FROM {table}{row_scope} GROUP BY {keys} HAVING COUNT(*) > 1 OR {empty_keys} LIMIT 1",
                params,
                limit=1,
            )
            if duplicate:
                preview.issues.append(BindingIssue(code="missing_or_duplicate_identity"))
            continue
        doc, table, columns = authorized_snapshot(
            db, tenant_id=tenant_id, account_id=account_id, asset_id=binding.asset_id
        )
        preview.asset_revision = snapshot_schema_revision(table)
        if binding.asset_revision not in {None, preview.asset_revision}:
            preview.issues.append(BindingIssue(code="asset_schema_changed"))
            continue
        preview.row_count = table.row_count if binding.row_access_column is None else None
        preview.truncated = table.truncated
        referenced = {item.column for item in binding.columns.values()} | set(binding.identity_columns)
        if binding.row_access_column is not None:
            referenced.add(binding.row_access_column)
        if missing := referenced - columns:
            preview.issues.extend(BindingIssue(code="unavailable_column", field=field) for field in sorted(missing))
            continue
        sample = run_table_query(
            tenant_id=tenant_id,
            dataset_id=doc.dataset_id,
            table_id=table.table_id,
            sql=select_columns(table.sql_table, binding.columns)
            + (f" WHERE {quote_sqlite_ident(binding.row_access_column)} = ?" if binding.row_access_column else ""),
            max_rows=8,
            max_cols=len(binding.columns),
            max_bytes=128 * 1024,
            parameters=(account_id,) if binding.row_access_column else (),
        )
        preview.sample, preview.issues = check_sample(
            binding, definition.object_types[binding.object_type], sample["rows"]
        )
        quoted = quote_sqlite_ident
        keys = ", ".join(quoted(item) for item in binding.identity_columns)
        scope = f" WHERE {quoted(binding.row_access_column)} = ?" if binding.row_access_column else ""
        missing_keys = " OR ".join(
            f"{quoted(key)} IS NULL OR trim(CAST({quoted(key)} AS TEXT)) = ''" for key in binding.identity_columns
        )
        duplicate = run_table_query(
            tenant_id=tenant_id,
            dataset_id=doc.dataset_id,
            table_id=table.table_id,
            sql=(
                f"SELECT 1 FROM {quoted(table.sql_table)}{scope} GROUP BY {keys} "
                f"HAVING COUNT(*) > 1 OR {missing_keys} LIMIT 1"
            ),
            max_rows=1,
            max_cols=1,
            max_bytes=4096,
            parameters=(account_id,) if binding.row_access_column else (),
        )
        if duplicate["rows"]:
            preview.issues.append(BindingIssue(code="missing_or_duplicate_identity"))
    _check_relation_bindings(db, tenant_id, account_id, definition, previews)
    return previews


def _relation_query(
    table: str,
    columns: list[str],
    unique: bool,
    row_column: str | None,
    quote: Callable[[str], str],
    placeholder: str,
) -> str:
    quoted = ", ".join(quote(name) for name in columns)
    clauses = f" WHERE {quote(row_column)} = {placeholder}" if row_column else ""
    if unique:
        clauses += f" GROUP BY {quoted} HAVING COUNT(*) > 1"
        return f"SELECT COUNT(*) AS occurrences FROM {quote(table)}{clauses} LIMIT 1"
    return f"SELECT {quoted} FROM {quote(table)}{clauses} LIMIT 1"


def _check_relation_side(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    binding: ObjectBinding,
    keys: list[str],
    *,
    unique: bool,
) -> bool:
    required = set(keys)
    row_column = binding.row_access_column
    if row_column:
        required.add(row_column)
    params = (account_id,) if row_column else ()
    if binding.edo_binding is not None:
        asset = authorized_edo_table(tenant_id=tenant_id, binding=binding)
        if required - asset.columns.keys():
            raise PermissionError("Relation columns are unavailable")
        sql = _relation_query(asset.name, keys, unique, row_column, quote_sqlite_ident, "?")
        return unique and bool(asset.select(sorted(required), sql, params).rows)
    if binding.asset_id.startswith("catalog:"):
        asset = authorized_mysql_asset(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            asset_id=binding.asset_id,
            expected_revision=binding.asset_revision,
        )
        if required - asset.columns:
            raise PermissionError("Relation columns are unavailable")
        sql = _relation_query(asset.table_name, keys, unique, row_column, mysql_identifier, "%s")
        return unique and bool(asset.select(sql, params, limit=1))
    doc, table, available = authorized_snapshot(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        asset_id=binding.asset_id,
        expected_revision=binding.asset_revision,
    )
    if required - available:
        raise PermissionError("Relation columns are unavailable")
    sql = _relation_query(table.sql_table, keys, unique, row_column, quote_sqlite_ident, "?")
    outcome = run_table_query(
        tenant_id=tenant_id,
        dataset_id=doc.dataset_id,
        table_id=table.table_id,
        sql=sql,
        parameters=params,
        max_rows=1,
        max_cols=1 if unique else len(keys),
        max_bytes=4096,
    )
    return unique and bool(outcome["rows"])


def _check_relation_bindings(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    definition: OntologyDefinition,
    previews: list[BindingPreview],
) -> None:
    primary = {
        binding.object_type: (binding, preview)
        for binding, preview in zip(definition.bindings, previews, strict=True)
        if binding.role == "primary"
    }
    for relation_id, mapping in definition.relation_bindings.items():
        relation = definition.relations[relation_id]
        one_source = relation.cardinality in {"one_to_one", "one_to_many"}
        one_target = relation.cardinality in {"one_to_one", "many_to_one"}
        source, source_preview = primary[relation.source_type]
        target, target_preview = primary[relation.target_type]
        sides = [
            (source, source_preview, mapping.source_columns, one_source and mapping.bridge_asset_id is None),
            (target, target_preview, mapping.target_columns, one_target and mapping.bridge_asset_id is None),
        ]
        if mapping.bridge_asset_id:
            bridge = ObjectBinding(
                object_type=relation.source_type,
                role="enrichment",
                asset_id=mapping.bridge_asset_id,
                row_access_column=mapping.bridge_row_access_column,
            )
            sides.append((bridge, source_preview, mapping.bridge_source_columns, one_target))
            sides.append((bridge, target_preview, mapping.bridge_target_columns, one_source))
        for bound, preview, keys, unique in sides:
            if preview.issues:
                continue
            try:
                if _check_relation_side(db, tenant_id, account_id, bound, keys, unique=unique):
                    preview.issues.append(BindingIssue(code="relation_cardinality", field=relation_id))
            except (HTTPException, PermissionError, FileNotFoundError):
                preview.issues.append(BindingIssue(code="relation_source_unavailable", field=relation_id))
