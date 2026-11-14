"""
SQLAlchemy-backed CatalogStore implementation.

This store persists DB catalog metadata into the application's primary database.
It intentionally does not commit; callers manage transaction boundaries.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.connectors.catalog import CatalogColumnInput, CatalogTableInput
from app.connectors.profile_privacy import sanitize_db_profile_snapshot
from app.models.db_catalog import DbCatalogColumn, DbCatalogTable, DbProfileSnapshot


class SQLAlchemyCatalogStore:
    def __init__(self, *, db: Session) -> None:
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
                DbCatalogTable.fingerprint == table.fingerprint,
            )
            .first()
        )
        if row is None:
            row = DbCatalogTable(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                connector_config_id=connector_config_id,
                fingerprint=table.fingerprint,
            )
            self._db.add(row)
        elif connector_config_id is not None:
            row.connector_config_id = connector_config_id

        row.engine = table.engine[:32]
        row.db_name = table.db_name[:255]
        row.schema_name = table.schema_name[:255] if table.schema_name is not None else None
        row.table_name = table.table_name[:255]
        row.table_type = table.table_type[:32]
        row.comment = table.comment
        row.last_seen_at = seen_at
        self._db.flush()
        return row.id

    def replace_columns(self, *, table_id: UUID, columns: Sequence[CatalogColumnInput]) -> int:
        self._db.query(DbCatalogColumn).filter(DbCatalogColumn.table_id == table_id).delete(synchronize_session=False)
        for column in columns:
            row = DbCatalogColumn(
                table_id=table_id,
                ordinal=column.ordinal,
                name=column.name[:255],
                data_type=column.data_type[:255] if column.data_type is not None else None,
                nullable=column.nullable,
                comment=column.comment,
            )
            self._db.add(row)
        self._db.flush()
        return len(columns)

    def insert_profile_snapshot(
        self,
        *,
        table_id: UUID,
        entitlement_hash: str,
        profile: dict[str, Any],
        sample_meta: dict[str, Any],
    ) -> UUID:
        safe_profile = sanitize_db_profile_snapshot(profile)
        row = DbProfileSnapshot(
            table_id=table_id,
            entitlement_hash=entitlement_hash[:255],
            profile=safe_profile,
            sample_meta=dict(sample_meta),
        )
        self._db.add(row)
        self._db.flush()
        return row.id
