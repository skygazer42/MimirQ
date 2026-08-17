#!/usr/bin/env python3

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.core.database import SessionLocal
from app.services.embedding_drift_monitor import run_embedding_drift_monitor


def _utc_compact_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:  # noqa: BLE001
        raise argparse.ArgumentTypeError("value must be a valid UUID") from exc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run a bounded embedding drift snapshot (PII-safe).")
    p.add_argument("--tenant-id", type=_parse_uuid, required=True, help="Tenant UUID to operate on")
    p.add_argument("--dataset-id", type=_parse_uuid, default=None, help="Optional dataset UUID filter")
    p.add_argument("--document-id", type=_parse_uuid, default=None, help="Optional document UUID filter")
    p.add_argument("--sample-n", type=int, default=200, help="Max chunks to sample (default: 200)")
    p.add_argument("--threshold", type=float, default=0.05, help="Drift threshold (default: 0.05)")
    p.add_argument("--max-ids-per-query", type=int, default=128, help="Max Milvus ids per query batch (default: 128)")
    p.add_argument(
        "--max-content-chars", type=int, default=8000, help="Max chars per chunk to re-embed (default: 8000)"
    )
    default_out = str(Path("runs") / "diagnostics" / f"embedding-drift-{_utc_compact_timestamp()}.json")
    p.add_argument("--out", default=default_out, help="Output JSON path (default: runs/diagnostics/...).")
    args = p.parse_args(argv)

    db = SessionLocal()
    try:
        payload = run_embedding_drift_monitor(
            db=db,
            tenant_id=args.tenant_id,
            dataset_id=args.dataset_id,
            document_id=args.document_id,
            sample_n=int(args.sample_n or 0),
            drift_threshold=float(args.threshold),
            max_ids_per_query=int(args.max_ids_per_query or 0),
            max_content_chars=int(args.max_content_chars or 0),
        )
    finally:
        db.close()

    out_path = Path(str(args.out or "").strip() or default_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
