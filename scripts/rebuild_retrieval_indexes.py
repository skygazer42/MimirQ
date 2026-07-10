
import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild persisted sparse/ColBERT retrieval indexes")
    parser.add_argument("--tenant-id", required=True, help="Tenant UUID")
    parser.add_argument("--dataset-id", required=False, help="Optional dataset UUID")
    parser.add_argument("--batch-size", type=int, default=2000, help="DB streaming batch size")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    tenant_id = UUID(str(args.tenant_id))
    dataset_id = UUID(str(args.dataset_id)) if args.dataset_id else None

    from app.core.database import SessionLocal
    from app.rag.retriever import HybridRetriever

    db = SessionLocal()
    try:
        retriever = HybridRetriever(tenant_id=tenant_id, dataset_id=dataset_id)
        result = retriever.rebuild_persisted_retrieval_indexes(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            batch_size=max(1, int(args.batch_size or 1)),
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
