"""
DB catalog virtual schema document renderer.

Provides a digest-only document containing table/column metadata and safe
aggregates, so retrieval can find schema knowledge without exposing raw rows.
"""


from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC
from typing import Any
from uuid import UUID

from app.types.indexing import ChunkInput

# Only include allowlisted keys from profiling snapshots to avoid accidentally
# rendering raw values (e.g. sample rows / top values).
_SAFE_PROFILE_KEYS: set[str] = {
    "row_count_estimate",
}


def _norm_str(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# Stable identity for the virtual schema document for a dataset.
def virtual_schema_file_path(dataset_id: str) -> str:
    ds = _norm_str(dataset_id)
    return f"virtual://db_catalog/schema/{ds}"


def virtual_schema_filename(dataset_id: str) -> str:
    ds = _norm_str(dataset_id)
    return f"db_schema_{ds}.md"


def build_virtual_schema_document_fields(
    *,
    tenant_id: str,
    dataset_id: str,
    requested_by: str | None,
    markdown: str,
) -> dict[str, Any]:
    """
    Build a Document-compatible field dict for the virtual schema doc.

    This is a pure helper (testable without DB) used by the upsert flow.
    """
    md = str(markdown or "")
    ds = _norm_str(dataset_id)
    return {
        "tenant_id": _norm_str(tenant_id),
        "dataset_id": ds,
        "filename": virtual_schema_filename(ds),
        "file_type": "md",
        "file_size": int(len(md.encode("utf-8", "ignore"))),
        "file_path": virtual_schema_file_path(ds),
        "owner_id": (_norm_str(requested_by) or None),
        "access_mode": "inherit",
        "status": "completed",
        "processing_progress": 100,
        "current_stage": "completed",
        "error_message": None,
        "doc_metadata": {
            "virtual_schema": True,
            "doc_type_kwd": "db_schema",
            "source": "db_catalog",
            "schema_doc_version": 1,
        },
    }


def chunk_virtual_schema_markdown(
    *,
    markdown: str,
    base_metadata: Mapping[str, Any] | None = None,
    chunk_size: int = 1200,
    chunk_overlap: int = 150,
) -> list[ChunkInput]:
    """
    Chunk the virtual schema markdown using an existing markdown-aware chunker.

    Returns `ChunkInput` items compatible with `Indexer.index_chunks(...)`.
    """
    from langchain_core.documents import Document as LCDocument  # noqa: WPS433

    from app.rag.chunking import chunker_factory  # noqa: WPS433

    md = str(markdown or "")
    meta0 = dict(base_metadata or {})

    chunker = chunker_factory.get_chunker(
        "markdown_outline",
        chunk_size=int(chunk_size or 0) or 1200,
        chunk_overlap=max(0, int(chunk_overlap or 0)),
    )
    docs = chunker.split_documents([LCDocument(page_content=md, metadata=meta0)])

    out: list[ChunkInput] = []
    for d in docs:
        meta = dict(getattr(d, "metadata", None) or {})
        start_i = _safe_int(meta.get("start_char"))
        end_i = _safe_int(meta.get("end_char"))
        out.append(
            ChunkInput(
                content=str(getattr(d, "page_content", None) or ""),
                metadata=meta,
                page_number=None,
                start_char=start_i,
                end_char=end_i,
            )
        )

    return out


def upsert_and_index_virtual_schema_doc(
    *,
    db: Any,
    tenant_id: UUID,
    dataset_id: UUID,
    requested_by: str | None,
    connector_run_id: UUID | None = None,
    chunk_size: int = 1200,
    chunk_overlap: int = 150,
) -> dict[str, Any]:
    """
    Build, upsert, and index the digest-only virtual schema document for a dataset.

    Notes:
    - Best-effort and safe by default: failures should not break catalog sync.
    - This function touches DB + vector/BM25 indexes via `Indexer`.
    """
    import time
    from datetime import datetime

    from sqlalchemy.orm import Session  # noqa: WPS433

    from app.models.db_catalog import DbCatalogColumn, DbCatalogTable, DbProfileSnapshot  # noqa: WPS433
    from app.models.document import Document as DBDocument  # noqa: WPS433
    from app.models.document import DocumentChunk, DocumentParsedContent  # noqa: WPS433
    from app.services.indexer import Indexer  # noqa: WPS433

    if not isinstance(db, Session):
        raise TypeError("db must be a SQLAlchemy Session")

    t0 = time.time()
    now = datetime.now(UTC)

    file_path = virtual_schema_file_path(str(dataset_id))
    filename = virtual_schema_filename(str(dataset_id))

    # 1) Collect catalog tables/columns (+ best-effort latest profile snapshot per table).
    tables = (
        db.query(DbCatalogTable)
        .filter(DbCatalogTable.tenant_id == tenant_id, DbCatalogTable.dataset_id == dataset_id)
        .order_by(DbCatalogTable.engine.asc(), DbCatalogTable.db_name.asc(), DbCatalogTable.schema_name.asc(), DbCatalogTable.table_name.asc())
        .all()
    )
    table_ids = [t.id for t in (tables or []) if getattr(t, "id", None) is not None]

    cols_by_table: dict[UUID, list[dict[str, Any]]] = {}
    if table_ids:
        cols = (
            db.query(DbCatalogColumn)
            .filter(DbCatalogColumn.table_id.in_(table_ids))
            .order_by(DbCatalogColumn.table_id.asc(), DbCatalogColumn.ordinal.asc(), DbCatalogColumn.name.asc(), DbCatalogColumn.id.asc())
            .all()
        )
        for c in cols or []:
            tid = getattr(c, "table_id", None)
            if tid is None:
                continue
            cols_by_table.setdefault(tid, []).append(
                {
                    "ordinal": getattr(c, "ordinal", 0),
                    "name": getattr(c, "name", None),
                    "data_type": getattr(c, "data_type", None),
                    "nullable": getattr(c, "nullable", None),
                    "comment": getattr(c, "comment", None),
                }
            )

    latest_profile_by_table: dict[UUID, dict[str, Any]] = {}
    if table_ids:
        # Fetch in descending order and keep the first per table_id.
        snaps = (
            db.query(DbProfileSnapshot)
            .filter(DbProfileSnapshot.table_id.in_(table_ids))
            .order_by(DbProfileSnapshot.table_id.asc(), DbProfileSnapshot.created_at.desc(), DbProfileSnapshot.id.asc())
            .all()
        )
        for s in snaps or []:
            tid = getattr(s, "table_id", None)
            if tid is None or tid in latest_profile_by_table:
                continue
            prof = getattr(s, "profile", None)
            latest_profile_by_table[tid] = dict(prof or {}) if isinstance(prof, dict) else {}

    table_dicts: list[dict[str, Any]] = []
    for t in tables or []:
        tid = getattr(t, "id", None)
        if tid is None:
            continue
        table_dicts.append(
            {
                "engine": getattr(t, "engine", None),
                "db_name": getattr(t, "db_name", None),
                "schema_name": getattr(t, "schema_name", None),
                "table_name": getattr(t, "table_name", None),
                "table_type": getattr(t, "table_type", None),
                "comment": getattr(t, "comment", None),
                "columns": cols_by_table.get(tid, []),
                "profile": latest_profile_by_table.get(tid, {}),
            }
        )

    md = render_virtual_schema_markdown(
        dataset_id=str(dataset_id),
        tables=table_dicts,
        generated_at_iso=now.isoformat(),
    )

    # 2) Upsert the virtual Document row (stable identity via file_path).
    doc = (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.file_path == file_path,
        )
        .first()
    )

    prev_md = ""
    if doc is not None:
        try:
            row = (
                db.query(DocumentParsedContent.markdown_content)
                .filter(DocumentParsedContent.tenant_id == tenant_id, DocumentParsedContent.document_id == doc.id)
                .first()
            )
            if row and isinstance(row[0], str):
                prev_md = row[0]
        except Exception:
            prev_md = ""

    schema_diff = compute_schema_diff(
        old_schema=extract_schema_from_markdown(prev_md),
        new_schema=extract_schema_from_markdown(md),
        max_items=100,
    )

    fields = build_virtual_schema_document_fields(
        tenant_id=str(tenant_id),
        dataset_id=str(dataset_id),
        requested_by=requested_by,
        markdown=md,
    )
    meta = dict(fields.get("doc_metadata") or {})
    if connector_run_id is not None:
        meta["connector_run_id"] = str(connector_run_id)
    meta["generated_at"] = now.isoformat()
    fields["doc_metadata"] = meta

    if doc is None:
        doc = DBDocument(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            filename=filename,
            file_type="md",
            file_size=int(fields["file_size"]),
            file_path=file_path,
            owner_id=fields.get("owner_id"),
            access_mode=fields.get("access_mode"),
            status="completed",
            processing_progress=100,
            current_stage="completed",
            error_message=None,
            chunk_count=0,
            total_characters=0,
            doc_metadata=meta,
            processed_at=now,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
    else:
        doc.filename = filename
        doc.file_type = "md"
        doc.file_size = int(fields["file_size"])
        doc.file_path = file_path
        doc.owner_id = fields.get("owner_id")
        doc.access_mode = fields.get("access_mode")
        doc.status = "completed"
        doc.processing_progress = 100
        doc.current_stage = "completed"
        doc.error_message = None
        doc.processed_at = now
        doc.doc_metadata = meta
        db.commit()
        db.refresh(doc)

    # 3) Upsert parsed content for debug/audit and UI inspection.
    parsed = (
        db.query(DocumentParsedContent)
        .filter(DocumentParsedContent.tenant_id == tenant_id, DocumentParsedContent.document_id == doc.id)
        .first()
    )
    if parsed is None:
        parsed = DocumentParsedContent(
            tenant_id=tenant_id,
            document_id=doc.id,
            markdown_content=md,
            original_markdown_content=md,
        )
        db.add(parsed)
    else:
        parsed.markdown_content = md
        parsed.original_markdown_content = md
    db.commit()

    # 4) Replace chunks + indexes (idempotent rebuild for this virtual doc).
    Indexer(db).delete_chunk_indexes(tenant_id=tenant_id, document_id=doc.id)
    db.query(DocumentChunk).filter(DocumentChunk.tenant_id == tenant_id, DocumentChunk.document_id == doc.id).delete(
        synchronize_session=False
    )
    db.commit()

    base_chunk_meta = dict(meta)
    base_chunk_meta.setdefault("source", "db_catalog")
    base_chunk_meta.setdefault("doc_type_kwd", "db_schema")
    base_chunk_meta.setdefault("virtual_schema", True)

    chunks = chunk_virtual_schema_markdown(
        markdown=md,
        base_metadata=base_chunk_meta,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    idx = Indexer(db)
    result = idx.index_chunks(document_id=doc.id, tenant_id=tenant_id, chunks=chunks, default_source="db_catalog", commit=True)

    # Keep Document stats accurate for UI/debug.
    doc.chunk_count = int(len(result.db_chunks or []))
    doc.total_characters = int(result.total_characters or 0)
    db.commit()
    db.refresh(doc)

    elapsed = time.time() - t0
    columns_total = 0
    for t in tables or []:
        tid = getattr(t, "id", None)
        if tid is None:
            continue
        columns_total += int(len(cols_by_table.get(tid, [])))

    last_seen_at = None
    for t in tables or []:
        v = getattr(t, "last_seen_at", None)
        if v is None:
            continue
        if last_seen_at is None or v > last_seen_at:
            last_seen_at = v
    catalog_age_sec = None
    if last_seen_at is not None:
        try:
            catalog_age_sec = float((now - last_seen_at).total_seconds())
        except Exception:
            catalog_age_sec = None

    return {
        "document_id": str(doc.id),
        "file_path": file_path,
        "tables": int(len(table_dicts)),
        "columns": int(columns_total),
        "tables_with_profiles": int(len(latest_profile_by_table)),
        "catalog_last_seen_at": (last_seen_at.isoformat() if last_seen_at is not None else None),
        "catalog_age_sec": catalog_age_sec,
        "schema_diff": schema_diff,
        "chunks": int(len(result.db_chunks or [])),
        "elapsed_sec": float(elapsed),
    }


def _table_fqn(*, db_name: str, schema_name: str | None, table_name: str) -> str:
    if schema_name:
        return f"{db_name}.{schema_name}.{table_name}"
    return f"{db_name}.{table_name}"


def _iter_tables_sorted(tables: Sequence[Mapping[str, Any]]) -> Iterable[Mapping[str, Any]]:
    def key(t: Mapping[str, Any]) -> tuple[str, str, str, str]:
        return (
            _norm_str(t.get("engine")).lower(),
            _norm_str(t.get("db_name")).lower(),
            _norm_str(t.get("schema_name")).lower(),
            _norm_str(t.get("table_name")).lower(),
        )

    return sorted(tables or [], key=key)


def _iter_columns_sorted(columns: Sequence[Mapping[str, Any]]) -> Iterable[Mapping[str, Any]]:
    def key(c: Mapping[str, Any]) -> tuple[int, str]:
        try:
            ordinal = int(c.get("ordinal") or 0)
        except Exception:
            ordinal = 0
        return (ordinal, _norm_str(c.get("name")).lower())

    return sorted(columns or [], key=key)


def render_virtual_schema_markdown(
    *,
    dataset_id: str,
    tables: Sequence[Mapping[str, Any]],
    generated_at_iso: str,
) -> str:
    """
    Render a deterministic, digest-only markdown document for DB schema retrieval.

    `tables` expects items shaped like:
      {
        "engine": "mysql"|"sqlserver",
        "db_name": "...",
        "schema_name": str|None,
        "table_name": "...",
        "table_type": "table"|"view",
        "comment": str|None,
        "columns": [{"ordinal": int, "name": str, "data_type": str|None, "nullable": bool|None, "comment": str|None}],
        "profile": dict|None,
      }
    """
    ds = _norm_str(dataset_id)
    gen = _norm_str(generated_at_iso)

    lines: list[str] = []
    lines.append("# Virtual DB Schema")
    lines.append("")
    lines.append("> Digest-only generated document. No raw DB rows are included.")
    lines.append("")
    lines.append(f"- dataset_id: `{ds}`")
    lines.append(f"- generated_at: `{gen}`")
    lines.append("")

    for t in _iter_tables_sorted(tables):
        db_name = _norm_str(t.get("db_name"))
        schema_name_raw = _norm_str(t.get("schema_name")) or ""
        schema_name = schema_name_raw or None
        table_name = _norm_str(t.get("table_name"))
        if not db_name or not table_name:
            continue

        fqn = _table_fqn(db_name=db_name, schema_name=schema_name, table_name=table_name)
        lines.append(f"## {fqn}")
        lines.append("")

        engine = _norm_str(t.get("engine")).lower()
        table_type = _norm_str(t.get("table_type")).lower() or "table"
        comment = _norm_str(t.get("comment")) or None
        if engine:
            lines.append(f"- engine: `{engine}`")
        lines.append(f"- type: `{table_type}`")
        if comment:
            lines.append(f"- comment: {comment}")
        lines.append("")

        cols = t.get("columns")
        cols_list: Sequence[Mapping[str, Any]] = cols if isinstance(cols, list) else []
        if cols_list:
            lines.append("### Columns")
            lines.append("")
            lines.append("| ordinal | name | type | nullable | comment |")
            lines.append("|---:|---|---|:---:|---|")
            for c in _iter_columns_sorted(cols_list):
                try:
                    ordinal = int(c.get("ordinal") or 0)
                except Exception:
                    ordinal = 0
                name = _norm_str(c.get("name"))
                if not name:
                    continue
                dtype = _norm_str(c.get("data_type")) or ""
                nullable_v = c.get("nullable")
                if nullable_v is True:
                    nullable = "Y"
                elif nullable_v is False:
                    nullable = "N"
                else:
                    nullable = ""
                cmt = _norm_str(c.get("comment")) or ""
                lines.append(f"| {ordinal} | `{name}` | {dtype} | {nullable} | {cmt} |")
            lines.append("")

        profile = t.get("profile")
        if isinstance(profile, Mapping):
            safe = {str(k): profile.get(k) for k in profile.keys() if str(k) in _SAFE_PROFILE_KEYS}
            if safe:
                lines.append("### Safe Profile")
                lines.append("")
                for k in sorted(safe.keys()):
                    v = safe.get(k)
                    # Keep primitive values readable; otherwise stringify.
                    if v is None or isinstance(v, (str, int, float, bool)):
                        lines.append(f"- {k}: `{v}`")
                    else:
                        lines.append(f"- {k}: `{str(v)}`")
                lines.append("")

    return "\n".join(lines).strip() + "\n"


def extract_schema_from_markdown(markdown: str) -> dict[str, dict[str, Any]]:
    """
    Best-effort parser for `render_virtual_schema_markdown` output.

    We intentionally parse only the stable subset needed for diffing:
    - table heading (H2)
    - columns markdown table rows
    """
    md = str(markdown or "")
    out: dict[str, dict[str, Any]] = {}

    current_table: str | None = None
    in_columns = False
    skip = 0

    for raw in md.splitlines():
        line = raw.rstrip("\n")
        if line.startswith("## "):
            current_table = line[3:].strip()
            if current_table:
                out.setdefault(current_table, {"columns": {}})
            in_columns = False
            skip = 0
            continue

        if current_table and line.strip() == "### Columns":
            in_columns = True
            skip = 2  # header + separator
            continue

        if not in_columns or not current_table:
            continue

        if skip > 0:
            skip -= 1
            continue

        if not line.strip():
            in_columns = False
            continue

        if not line.lstrip().startswith("|"):
            continue

        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) < 5:
            continue

        name_raw = parts[1].strip()
        name = name_raw.strip("`").strip()
        if not name:
            continue

        dtype = parts[2].strip()
        nullable_raw = parts[3].strip().upper()
        if nullable_raw == "Y":
            nullable: bool | None = True
        elif nullable_raw == "N":
            nullable = False
        else:
            nullable = None

        out[current_table]["columns"][name] = {
            "data_type": (dtype if dtype else None),
            "nullable": nullable,
        }

    return out


def compute_schema_diff(
    *,
    old_schema: Mapping[str, Mapping[str, Any]],
    new_schema: Mapping[str, Mapping[str, Any]],
    max_items: int = 100,
) -> dict[str, Any]:
    """
    Compute a compact schema diff between two extracted schemas.

    Output is designed to be:
    - JSON-serializable
    - small enough for ConnectorRun.stats
    - UI-friendly (counts + a small sample list)
    """
    max_items_eff = max(0, int(max_items or 0))

    old_tables = set(old_schema.keys())
    new_tables = set(new_schema.keys())

    tables_added = sorted(new_tables - old_tables)
    tables_removed = sorted(old_tables - new_tables)

    columns_added: list[str] = []
    columns_removed: list[str] = []
    columns_changed: list[dict[str, Any]] = []

    for table in sorted(old_tables & new_tables):
        old_cols = (old_schema.get(table) or {}).get("columns")
        new_cols = (new_schema.get(table) or {}).get("columns")
        old_cols_map = old_cols if isinstance(old_cols, Mapping) else {}
        new_cols_map = new_cols if isinstance(new_cols, Mapping) else {}

        old_col_names = set(old_cols_map.keys())
        new_col_names = set(new_cols_map.keys())

        for c in sorted(new_col_names - old_col_names):
            columns_added.append(f"{table}.{c}")
        for c in sorted(old_col_names - new_col_names):
            columns_removed.append(f"{table}.{c}")

        for c in sorted(old_col_names & new_col_names):
            old_meta = old_cols_map.get(c) if isinstance(old_cols_map.get(c), Mapping) else {}
            new_meta = new_cols_map.get(c) if isinstance(new_cols_map.get(c), Mapping) else {}
            old_type = str(old_meta.get("data_type") or "").strip() or None
            new_type = str(new_meta.get("data_type") or "").strip() or None
            old_nullable = old_meta.get("nullable")
            new_nullable = new_meta.get("nullable")

            if old_type != new_type or old_nullable != new_nullable:
                columns_changed.append(
                    {
                        "table": table,
                        "column": c,
                        "old": {"data_type": old_type, "nullable": old_nullable},
                        "new": {"data_type": new_type, "nullable": new_nullable},
                    }
                )

    def _pack(items: list[Any]) -> dict[str, Any]:
        total = int(len(items))
        if max_items_eff <= 0:
            return {"count": total, "items": [], "truncated": total > 0}
        sliced = items[:max_items_eff]
        return {"count": total, "items": sliced, "truncated": total > len(sliced)}

    return {
        "tables_added": _pack(tables_added),
        "tables_removed": _pack(tables_removed),
        "columns_added": _pack(columns_added),
        "columns_removed": _pack(columns_removed),
        "columns_changed": _pack(columns_changed),
    }
