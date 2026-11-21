"""
Structured table store (TAG) helpers.

Design goals:
- Deterministic, tenant/dataset/document-scoped storage paths (no user-controlled paths).
- Deterministic table identifiers (table_id) that can be safely exposed via APIs.
- Keep SQL table names internal and generated (avoid SQL injection via identifiers).
"""

import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.infrastructure.config import settings

_TABLE_ID_RE = re.compile(r"^doc:([0-9a-fA-F-]{36}):sheet:(\d+)$")


@dataclass(frozen=True)
class TableId:
    document_id: UUID
    sheet_index: int

    @property
    def id(self) -> str:
        return format_table_id(document_id=self.document_id, sheet_index=self.sheet_index)


def format_table_id(*, document_id: UUID, sheet_index: int) -> str:
    idx = max(0, sheet_index)
    return f"doc:{document_id}:sheet:{idx}"


def parse_table_id(raw: str) -> TableId | None:
    match = _TABLE_ID_RE.fullmatch(raw.strip())
    if match is None:
        return None
    try:
        document_id = UUID(match.group(1))
        sheet_index = int(match.group(2))
    except ValueError:
        return None
    if sheet_index > 100_000:
        return None
    return TableId(document_id=document_id, sheet_index=sheet_index)


def sql_table_name_for_sheet(sheet_index: int) -> str:
    """
    Internal SQLite table name for a given sheet index.

    We keep this deterministic and not user-controlled.
    """
    idx = max(0, sheet_index)
    return f"sheet_{idx}"


def quote_sqlite_ident(name: str) -> str:
    """Quote a SQLite identifier for dynamic internal table names."""
    return '"' + name.replace('"', '""') + '"'


def table_store_path(*, tenant_id: UUID, dataset_id: UUID, document_id: UUID) -> Path:
    """
    Return the SQLite file path for a document-scoped table store.

    Layout:
      {TABLE_STORE_DIR}/{tenant_id}/{dataset_id}/{document_id}.sqlite3
    """
    root = Path(settings.TABLE_STORE_DIR)
    # Avoid accidental relative traversal by always joining deterministic UUID components.
    return root / str(tenant_id) / str(dataset_id) / f"{document_id}.sqlite3"


def ensure_table_store_dir(*, tenant_id: UUID, dataset_id: UUID) -> Path:
    root = Path(settings.TABLE_STORE_DIR)
    out = root / str(tenant_id) / str(dataset_id)
    out.mkdir(parents=True, exist_ok=True)
    return out
