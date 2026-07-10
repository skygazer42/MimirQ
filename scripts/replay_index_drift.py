#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
from uuid import UUID

from app.core.database import SessionLocal
from app.services.index_audit_service import replay_index_drift_items


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except Exception as exc:  # noqa: BLE001
        raise argparse.ArgumentTypeError("value must be a valid UUID") from exc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay bounded open index-drift items.")
    p.add_argument("--tenant-id", type=_parse_uuid, required=True, help="Tenant UUID to operate on")
    p.add_argument("--dataset-id", type=_parse_uuid, default=None, help="Optional dataset UUID filter")
    p.add_argument("--limit", type=int, default=50, help="Max open items to inspect (default: 50)")
    p.add_argument("--requested-by", default="system:index-drift", help="Actor label for replay requests")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan only. Default.")
    mode.add_argument("--execute", action="store_true", help="Enqueue replay and update replay counters.")

    p.add_argument("--out", default="", help="Optional output JSON file path")
    args = p.parse_args(argv)

    db = SessionLocal()
    try:
        payload = replay_index_drift_items(
            db=db,
            tenant_id=args.tenant_id,
            dataset_id=args.dataset_id,
            limit=int(args.limit or 0),
            execute=bool(args.execute),
            requested_by=str(args.requested_by or "system:index-drift"),
        )
    finally:
        db.close()

    if str(args.out or "").strip():
        out_path = Path(str(args.out))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
