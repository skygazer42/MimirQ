"""Preview or explicitly backfill Milvus native BM25 from published PostgreSQL chunks."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_backfill(*, db, corpus_index, scope, apply: bool, batch_size: int) -> dict:
    from app.core.config import settings

    if batch_size < 1:
        raise ValueError("Backfill batch size must be positive")
    count = corpus_index._count_retrieval_docs_in_db(
        db, tenant_id=scope.tenant_id, dataset_ids=scope.dataset_ids, document_ids=list(scope.document_ids)
    )
    limit = settings.RETRIEVAL_REBUILD_MAX_CHUNKS
    if apply:
        count = corpus_index.rebuild(db, scope=scope, batch_size=batch_size)
    return {
        "mode": "apply" if apply else "dry-run",
        "tenant_id": str(scope.tenant_id),
        "dataset_ids": [str(value) for value in scope.dataset_ids],
        "collection": settings.MILVUS_BM25_COLLECTION_NAME,
        "published_chunks": count,
        "within_rebuild_limit": limit <= 0 or count <= limit,
        "reembeds_vectors": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--dataset-id", type=UUID)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--apply", action="store_true", help="Write native BM25 rows; the default only previews PostgreSQL counts"
    )
    args = parser.parse_args(argv)
    from app.core.database import SessionLocal
    from app.rag.retrieval.corpus_index import CorpusScope, get_corpus_index

    scope = CorpusScope(args.tenant_id, (args.dataset_id,) if args.dataset_id is not None else ())
    with SessionLocal() as db:
        result = run_backfill(
            db=db, corpus_index=get_corpus_index(), scope=scope, apply=args.apply, batch_size=args.batch_size
        )
        if args.apply:
            db.commit()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
