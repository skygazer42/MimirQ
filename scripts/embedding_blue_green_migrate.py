#!/usr/bin/env python3
"""
Embedding blue-green migration runner (Gap5).

This script helps backfill active document chunk vectors into a shadow Milvus collection
using the shadow embedding config (EMBEDDING_SHADOW_* + MILVUS_SHADOW_COLLECTION_NAME).

Typical flow:
1) Configure shadow:
   - EMBEDDING_SHADOW_ENABLED=true
   - EMBEDDING_SHADOW_MODEL=...
   - MILVUS_SHADOW_COLLECTION_NAME=documents_<new>
   - (optional) EMBEDDING_SHADOW_PROVIDER / EMBEDDING_SHADOW_API_BASE / EMBEDDING_SHADOW_API_KEY
2) Keep primary query path unchanged (still uses EMBEDDING_* + MILVUS_COLLECTION_NAME)
3) Run backfill:
   python scripts/embedding_blue_green_migrate.py --tenant-id <uuid> --dataset-id <uuid> --execute
4) Validate overlap (optional):
   python scripts/embedding_blue_green_migrate.py --tenant-id <uuid> --dataset-id <uuid> --overlap-check
5) Cutover:
   - Set EMBEDDING_MODEL + MILVUS_COLLECTION_NAME to the new values
   - Disable shadow dual-write after a safety window
"""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

# Ensure repo root is importable when invoked as:
#   python scripts/embedding_blue_green_migrate.py ...
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.core.database import SessionLocal  # noqa: E402
from app.services.embedding_migration import (  # noqa: E402
    resolve_shadow_embedding_config,
    run_embedding_migration_overlap_check,
    run_shadow_collection_backfill,
)


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:  # noqa: BLE001
        raise argparse.ArgumentTypeError("value must be a valid UUID") from exc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run embedding blue-green migration helpers (Gap5).")
    p.add_argument("--tenant-id", type=_parse_uuid, required=True, help="Tenant UUID to operate on")
    p.add_argument("--dataset-id", type=_parse_uuid, default=None, help="Optional dataset UUID filter")
    p.add_argument("--document-limit", type=int, default=0, help="Max documents to scan (0=all)")
    p.add_argument("--chunk-limit-per-document", type=int, default=0, help="Max chunks per document (0=all)")
    p.add_argument("--embed-batch-size", type=int, default=0, help="Embedding API batch size override (0=default)")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan only (no writes). Default.")
    mode.add_argument("--execute", action="store_true", help="Write vectors into shadow collection.")

    p.add_argument(
        "--overlap-check", action="store_true", help="Run a bounded overlap check after (or instead of) backfill."
    )
    p.add_argument("--overlap-sample-n", type=int, default=50, help="Overlap: number of sampled queries (default: 50)")
    p.add_argument("--overlap-top-k", type=int, default=10, help="Overlap: top-k (default: 10)")

    p.add_argument("--out", default="", help="Optional JSON output path (best-effort).")
    args = p.parse_args(argv)

    cfg = resolve_shadow_embedding_config()
    if cfg is None:
        print(json.dumps({"ok": False, "error": "shadow_config_disabled"}, ensure_ascii=False))
        return 2

    execute = bool(args.execute)
    if not bool(args.execute) and not bool(args.dry_run):
        execute = False

    out: dict[str, object] = {"ok": True, "shadow": cfg}

    db = SessionLocal()
    try:
        if not bool(args.overlap_check):
            backfill = run_shadow_collection_backfill(
                db=db,
                tenant_id=args.tenant_id,
                dataset_id=args.dataset_id,
                document_limit=int(args.document_limit or 0),
                chunk_limit_per_document=int(args.chunk_limit_per_document or 0),
                embed_batch_size=(int(args.embed_batch_size) if int(args.embed_batch_size or 0) > 0 else None),
                execute=bool(execute),
            )
            out["backfill"] = backfill

        if bool(args.overlap_check):
            overlap = run_embedding_migration_overlap_check(
                db=db,
                tenant_id=args.tenant_id,
                dataset_id=args.dataset_id,
                sample_n=int(args.overlap_sample_n or 0),
                top_k=int(args.overlap_top_k or 0),
            )
            out["overlap"] = overlap
    finally:
        db.close()

    out_json = json.dumps(out, ensure_ascii=False, indent=2) + "\n"
    if str(args.out or "").strip():
        path = Path(str(args.out).strip())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(out_json, encoding="utf-8")

    print(out_json if str(args.out or "").strip() else json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
