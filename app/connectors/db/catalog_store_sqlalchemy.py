"""
SQLAlchemy-backed CatalogStore implementation.

This store persists DB catalog metadata into the application's primary database.
It intentionally does not commit; callers manage transaction boundaries.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.connectors.db.catalog_runner import CatalogColumnInput, CatalogStore, CatalogTableInput
from app.connectors.db.profile_privacy import sanitize_db_profile_snapshot
from app.models.db_catalog import DbCatalogColumn, DbCatalogTable, DbProfileSnapshot


class SqlAlchemyCatalogStore(CatalogStore):
    def __init__(self, *, db: Session):
        self._db = db

    def upsert_table(
        self,
        *,
        tenant_id: UUID,
        dataset_id: UUID,
        connector_config_id: UUID | None,
        table: CatalogTableInput,
        seen_at: datetime,
    ) -> UUID:
        row = (
            self._db.query(DbCatalogTable)
            .filter(
                DbCatalogTable.tenant_id == tenant_id,
                DbCatalogTable.dataset_id == dataset_id,
                DbCatalogTable.fingerprint == str(table.fingerprint),
            )
            .first()
        )
        if row is None:
            row = DbCatalogTable(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                connector_config_id=connector_config_id,
                engine=str(table.engine or "")[:32],
                db_name=str(table.db_name or "")[:255],
                schema_name=(str(table.schema_name)[:255] if table.schema_name is not None else None),
                table_name=str(table.table_name or "")[:255],
                table_type=str(table.table_type or "table")[:32],
                comment=(str(table.comment) if table.comment is not None else None),
                fingerprint=str(table.fingerprint)[:80],
                last_seen_at=seen_at,
            )
            self._db.add(row)
            self._db.flush()
            return UUID(str(row.id))

        # Update mutable fields (best-effort).
        if connector_config_id is not None:
            row.connector_config_id = connector_config_id
        row.engine = str(table.engine or "")[:32]
        row.db_name = str(table.db_name or "")[:255]
        row.schema_name = str(table.schema_name)[:255] if table.schema_name is not None else None
        row.table_name = str(table.table_name or "")[:255]
        row.table_type = str(table.table_type or "table")[:32]
        row.comment = str(table.comment) if table.comment is not None else None
        row.last_seen_at = seen_at
        self._db.flush()
        return UUID(str(row.id))

    def replace_columns(self, *, table_id: UUID, columns: Sequence[CatalogColumnInput]) -> int:
        self._db.query(DbCatalogColumn).filter(DbCatalogColumn.table_id == table_id).delete(synchronize_session=False)
        out = 0
        for c in columns or []:
            name = str(getattr(c, "name", "") or "").strip()
            if not name:
                continue
            try:
                ordinal = int(getattr(c, "ordinal", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                ordinal = 0
            row = DbCatalogColumn(
                table_id=table_id,
                ordinal=int(ordinal),
                name=name[:255],
                data_type=(
                    str(getattr(c, "data_type", "") or "")[:255] if getattr(c, "data_type", None) is not None else None
                ),
                nullable=(bool(c.nullable) if getattr(c, "nullable", None) is not None else None),
                comment=(str(c.comment) if getattr(c, "comment", None) is not None else None),
            )
            self._db.add(row)
            out += 1
            if out >= 10_000:
                break
        self._db.flush()
        return int(out)

    def insert_profile_snapshot(
        self,
        *,
        table_id: UUID,
        entitlement_hash: str,
        profile: dict,
        sample_meta: dict,
    ) -> UUID:
        safe_profile = sanitize_db_profile_snapshot(profile)
        row = DbProfileSnapshot(
            table_id=table_id,
            entitlement_hash=str(entitlement_hash or "")[:255],
            profile=dict(safe_profile or {}),
            sample_meta=dict(sample_meta or {}),
        )
        self._db.add(row)
        self._db.flush()
        return UUID(str(row.id))
