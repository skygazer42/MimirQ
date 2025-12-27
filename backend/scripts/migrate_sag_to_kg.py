#!/usr/bin/env python3
"""
One-off migration helper: SAG -> KG naming.

Migrates:
- PostgreSQL tables: sag_* -> kg_*
- Milvus collections: sag_* -> kg_* (best-effort copy)

Usage:
  PYTHONPATH=backend python backend/scripts/migrate_sag_to_kg.py --postgres
  PYTHONPATH=backend python backend/scripts/migrate_sag_to_kg.py --milvus
  PYTHONPATH=backend python backend/scripts/migrate_sag_to_kg.py --postgres --milvus
"""

from __future__ import annotations

import argparse
import sys
from typing import List


def migrate_postgres() -> None:
    try:
        from sqlalchemy import create_engine, text
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("sqlalchemy is required for postgres migration") from exc

    from app.core.config import settings

    engine = create_engine(settings.DATABASE_URL)
    stmt = text(
        """
        DO $$
        BEGIN
          IF to_regclass('public.kg_entities') IS NULL AND to_regclass('public.sag_entities') IS NOT NULL THEN
            ALTER TABLE public.sag_entities RENAME TO kg_entities;
          END IF;

          IF to_regclass('public.kg_source_events') IS NULL AND to_regclass('public.sag_source_events') IS NOT NULL THEN
            ALTER TABLE public.sag_source_events RENAME TO kg_source_events;
          END IF;

          IF to_regclass('public.kg_event_entities') IS NULL AND to_regclass('public.sag_event_entities') IS NOT NULL THEN
            ALTER TABLE public.sag_event_entities RENAME TO kg_event_entities;
          END IF;
        END $$;
        """
    )
    with engine.begin() as conn:
        conn.execute(stmt)

    print("[OK] Postgres rename sag_* -> kg_* completed (or already migrated).")


def _schema_field_names(collection) -> List[str]:
    return [f.name for f in collection.schema.fields]


def migrate_milvus(*, batch_size: int) -> None:
    from app.core.config import settings

    try:
        from pymilvus import Collection, connections, utility
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("pymilvus is required for milvus migration") from exc

    connections.connect(
        alias="default",
        host=settings.MILVUS_HOST,
        port=str(settings.MILVUS_PORT),
        user=settings.MILVUS_USER,
        password=settings.MILVUS_PASSWORD,
    )

    pairs = [
        ("sag_entities", "kg_entities"),
        ("sag_events", "kg_events"),
    ]

    for legacy, target in pairs:
        if utility.has_collection(target):
            print(f"[SKIP] Milvus collection already exists: {target}")
            continue
        if not utility.has_collection(legacy):
            print(f"[SKIP] Milvus legacy collection not found: {legacy}")
            continue

        src = Collection(legacy)
        src.load()

        # Create target collection with identical schema.
        Collection(name=target, schema=src.schema)
        dst = Collection(target)

        # Recreate indexes (best-effort).
        try:
            for idx in getattr(src, "indexes", []) or []:
                field_name = getattr(idx, "field_name", None)
                params = getattr(idx, "params", None)
                if field_name and params:
                    dst.create_index(field_name=field_name, index_params=params)
        except Exception:
            pass

        dst.load()

        field_names = _schema_field_names(src)
        if not field_names:
            print(f"[WARN] {legacy}: empty schema, skipping copy")
            continue

        expr = 'id != ""'
        copied = 0

        if hasattr(src, "query_iterator"):
            it = src.query_iterator(expr=expr, output_fields=field_names, batch_size=batch_size)  # type: ignore[attr-defined]
            for rows in it:
                if not rows:
                    continue
                data = {name: [] for name in field_names}
                for row in rows:
                    for name in field_names:
                        data[name].append(row.get(name))
                dst.insert([data[name] for name in field_names])
                copied += len(rows)
        else:
            offset = 0
            while True:
                rows = src.query(expr=expr, output_fields=field_names, limit=batch_size, offset=offset)
                if not rows:
                    break
                data = {name: [] for name in field_names}
                for row in rows:
                    for name in field_names:
                        data[name].append(row.get(name))
                dst.insert([data[name] for name in field_names])
                copied += len(rows)
                offset += len(rows)

        dst.flush()
        print(f"[OK] Milvus copied {copied} rows: {legacy} -> {target}")

    print("[DONE] Milvus migration finished (best-effort).")


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres", action="store_true", help="Rename Postgres tables sag_* -> kg_*")
    parser.add_argument("--milvus", action="store_true", help="Copy Milvus collections sag_* -> kg_*")
    parser.add_argument("--batch-size", type=int, default=1000, help="Milvus batch size")
    args = parser.parse_args(argv)

    if not args.postgres and not args.milvus:
        parser.error("Please pass --postgres and/or --milvus")

    if args.postgres:
        migrate_postgres()
    if args.milvus:
        migrate_milvus(batch_size=max(int(args.batch_size), 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

