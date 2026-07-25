#!/usr/bin/env python3
"""
Seed a reproducible *public* Chinese retrieval benchmark into MimirQ (DB + vector store).

Why:
- Open-source projects cannot ship a single "unified enterprise knowledge base" dataset.
- But we *can* ship a reproducible public benchmark that exercises the real retrieval stack:
  Postgres + Milvus + embeddings (Ollama) + hybrid fusion.

What this script does (MIRACL zh pool v1):
1) Download MIRACL zh topics + qrels (small) from HuggingFace
2) Export a portable regression cases bundle (mimirq.regression_cases.v1)
3) (Optional, --execute) Stream MIRACL zh corpus and seed a "pool-corpus" dataset:
   - Always include per-query positive passages (bounded, e.g. <=3)
   - Include additional hashed-sampled negatives to reach ~target_passages
   - Write chunks into MimirQ via Indexer (vector + BM25 + DB) so retrieval is production-like

Notes:
- Default mode is dry-run (no DB writes).
- Seeding the corpus is intentionally expensive; treat it as a one-time build step.
- Nightly should only run retrieval evaluation (no re-embedding / no reindex).
"""


import argparse
import gzip
import hashlib
import json
import math
import sys
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from huggingface_hub import HfApi, hf_hub_download

import app.models._all  # noqa: F401
from app.core.database import Base, SessionLocal, engine
from app.core.migrations import apply_runtime_migrations
from app.models.dataset import Dataset, DatasetPermissionEnum
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.services.indexer import Indexer
from app.types.indexing import ChunkInput

BENCH_KEY = "public_bench.miracl_zh_pool.v1"
MIRACL_DATASET_REPO = "miracl/miracl"
MIRACL_CORPUS_REPO = "miracl/miracl-corpus"
LANG = "zh"

MANIFEST_SCHEMA = "mimirq.public_bench_manifest.v1"


def write_json_file(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_tsv_2col(path: Path) -> list[tuple[str, str]]:
    """
    Parse a 2-column TSV file (no header).
    Example: topics.<lang>-train.tsv -> (qid, query)
    """
    out: list[tuple[str, str]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            k = str(parts[0]).strip()
            v = str(parts[1]).strip()
            if k and v:
                out.append((k, v))
    return out


def _load_qrels_positive_docids(path: Path) -> dict[str, list[str]]:
    """
    Parse a TREC-style qrels TSV:
      qid  Q0  docid  rel
    Returns: { qid: [docid...] } where rel > 0.
    """
    out: dict[str, list[str]] = {}
    with path.open("r", encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            qid = str(parts[0]).strip()
            docid = str(parts[2]).strip()
            rel_raw = parts[3]
            try:
                rel = int(rel_raw)
            except Exception:
                rel = 0
            if not qid or not docid or rel <= 0:
                continue
            out.setdefault(qid, []).append(docid)
    # Dedup deterministically.
    for qid, ids in list(out.items()):
        uniq = sorted({str(x).strip() for x in ids if str(x).strip()})
        out[qid] = uniq
    return out


def _uuid_for_dataset(*, tenant_id: UUID, key: str) -> UUID:
    # Use tenant namespace to avoid accidental collisions across tenants.
    return uuid5(tenant_id, str(key))


def _uuid_for_chunk(*, dataset_id: UUID, docid: str) -> UUID:
    # docid is stable in MIRACL corpus (e.g. "13#0").
    return uuid5(dataset_id, f"miracl:{LANG}:{docid}")


def _sha256_u64(text: str) -> int:
    """
    Stable 64-bit hash using the first 8 bytes of sha256.
    """
    h = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:16]
    return int(h, 16)


def _stable_sample_threshold(*, rate: float) -> int:
    """
    Convert a [0,1] rate into a u64 threshold.
    """
    r = float(rate)
    if math.isnan(r) or r <= 0.0:
        return 0
    if r >= 1.0:
        return (1 << 64) - 1
    return int(r * float(1 << 64))


def _download_topics(*, split: str, revision: str | None = None) -> Path:
    filename = f"miracl-v1.0-{LANG}/topics/topics.miracl-v1.0-{LANG}-{split}.tsv"
    return Path(hf_hub_download(repo_id=MIRACL_DATASET_REPO, repo_type="dataset", filename=filename, revision=revision))


def _download_qrels(*, split: str, revision: str | None = None) -> Path:
    filename = f"miracl-v1.0-{LANG}/qrels/qrels.miracl-v1.0-{LANG}-{split}.tsv"
    return Path(hf_hub_download(repo_id=MIRACL_DATASET_REPO, repo_type="dataset", filename=filename, revision=revision))


def _list_corpus_files(*, revision: str | None = None) -> list[str]:
    api = HfApi()
    files = api.list_repo_files(repo_id=MIRACL_CORPUS_REPO, repo_type="dataset", revision=revision)
    prefix = f"miracl-corpus-v1.0-{LANG}/docs-"
    corpus = [f for f in files if f.startswith(prefix) and f.endswith(".jsonl.gz")]
    return sorted(corpus)


def _download_corpus_files(filenames: list[str], *, revision: str | None = None) -> list[Path]:
    out: list[Path] = []
    for fn in filenames:
        p = hf_hub_download(repo_id=MIRACL_CORPUS_REPO, repo_type="dataset", filename=fn, revision=revision)
        out.append(Path(p))
    return out


@dataclass(frozen=True)
class CaseItem:
    qid: str
    question: str
    positive_docids: tuple[str, ...]
    split: str


def build_case_items(
    *,
    splits: list[str],
    max_cases: int,
    max_refs_per_case: int,
    revision: str | None = None,
) -> list[CaseItem]:
    """
    Build a deterministic list of MIRACL cases from topics+qrels.

    We intentionally bound reference_sources per case (default <= 3) to match
    MimirQ's evidence-style retrieval metrics semantics.
    """
    splits_norm = [s.strip().lower() for s in (splits or []) if str(s).strip()]
    if not splits_norm:
        splits_norm = ["train", "dev"]

    items: list[CaseItem] = []
    for split in splits_norm:
        topics_path = _download_topics(split=split, revision=revision)
        qrels_path = _download_qrels(split=split, revision=revision)

        topics = _load_tsv_2col(topics_path)
        qrels = _load_qrels_positive_docids(qrels_path)

        for qid, query in topics:
            pos = qrels.get(qid) or []
            if not pos:
                continue
            picked = tuple(pos[: max(1, int(max_refs_per_case or 0))])
            items.append(CaseItem(qid=qid, question=query, positive_docids=picked, split=split))

    # Stable ordering: split -> qid.
    items.sort(key=lambda x: (str(x.split), str(x.qid)))

    if max_cases and int(max_cases) > 0:
        items = items[: int(max_cases)]

    return items


def export_regression_cases_bundle(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    case_items: list[CaseItem],
    out_path: Path,
) -> None:
    _ = tenant_id
    bundle = {
        "schema": "mimirq.regression_cases.v1",
        "dataset_id": str(dataset_id),
        "items": [
            {
                "question": it.question,
                "expected_answer": None,
                "reference_sources": [{"chunk_id": str(_uuid_for_chunk(dataset_id=dataset_id, docid=docid))} for docid in it.positive_docids],
                "tags": [
                    "public_bench",
                    "miracl",
                    f"lang:{LANG}",
                    f"split:{it.split}",
                    f"qid:{it.qid}",
                ],
            }
            for it in (case_items or [])
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _iter_corpus_records(paths: Iterable[Path]) -> Iterator[dict[str, Any]]:
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    yield obj


def _count_corpus_docs(paths: list[Path]) -> int:
    """
    Count corpus rows without parsing JSON (fast path).
    """
    cnt = 0
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for raw in f:
                if raw.strip():
                    cnt += 1
    return cnt


def _ensure_schema() -> None:
    apply_runtime_migrations(engine)
    Base.metadata.create_all(bind=engine)
    apply_runtime_migrations(engine)


def _upsert_dataset(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    name: str,
    description: str,
    owner_id: str,
    meta: dict[str, Any],
) -> None:
    db = SessionLocal()
    try:
        row = db.query(Dataset).filter(Dataset.tenant_id == tenant_id, Dataset.id == dataset_id).first()
        if row is None:
            row = Dataset(
                id=dataset_id,
                tenant_id=tenant_id,
                name=name,
                description=description or None,
                permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                owner_id=owner_id,
                dataset_metadata=dict(meta or {}),
            )
            db.add(row)
        else:
            row.name = name
            row.description = description or None
            row.owner_id = owner_id
            row.dataset_metadata = dict(meta or {})
        db.commit()
    finally:
        db.close()


def _delete_dataset_documents(*, tenant_id: UUID, dataset_id: UUID) -> dict[str, int]:
    """
    Best-effort wipe for a dataset's documents + vectors.
    Intended for local/dev rebuilds only.
    """
    from app.storage.vector.factory import get_vector_store

    db = SessionLocal()
    try:
        q = db.query(DBDocument.id).filter(DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id)
        doc_ids = [r[0] for r in q.all() if isinstance(r, tuple) and r and isinstance(r[0], UUID)]
        store = get_vector_store()
        for did in doc_ids:
            try:
                store.delete_by_document_id(did, tenant_id=tenant_id)
            except Exception:
                pass
        # Cascade deletes chunks.
        deleted = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id).delete()
        db.commit()
        return {"deleted_documents": int(deleted or 0), "deleted_vectors_best_effort": int(len(doc_ids))}
    finally:
        db.close()


def seed_pool_corpus(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    case_items: list[CaseItem],
    target_passages: int,
    chunks_per_document: int,
    overwrite: bool,
    dry_run: bool,
    revision: str | None = None,
) -> dict[str, Any]:
    """
    Stream the MIRACL corpus and seed a fixed-size "pool" dataset.
    """
    positive_docids: set[str] = set()
    for it in case_items or []:
        for docid in it.positive_docids:
            if docid:
                positive_docids.add(str(docid))

    pos_cnt = int(len(positive_docids))
    target = max(0, int(target_passages or 0))
    if target <= 0:
        raise ValueError("--target-passages must be > 0")
    if target < pos_cnt:
        target = pos_cnt
    neg_target = max(0, target - pos_cnt)

    corpus_filenames = _list_corpus_files(revision=revision)
    if not corpus_filenames:
        raise RuntimeError("No MIRACL corpus files found for zh (repo layout may have changed)")

    # Dry-run must remain cheap: do not download/count the full corpus.
    if dry_run:
        return {
            "ok": True,
            "plan": {
                "total_docs_in_corpus": None,
                "positive_docids": int(pos_cnt),
                "target_passages": int(target),
                "target_negatives": int(neg_target),
                "negative_sample_rate": None,
                "negative_hash_threshold_u64": None,
                "chunks_per_document": int(max(1, int(chunks_per_document or 0))),
                "dry_run": True,
                "overwrite": bool(overwrite),
                "corpus_files": list(corpus_filenames),
                "note": "Run with --execute to download/count corpus and compute the deterministic negative sampling threshold.",
            },
            "seeded": None,
        }

    corpus_paths = _download_corpus_files(corpus_filenames, revision=revision)

    t0 = time.time()
    total_docs = _count_corpus_docs(corpus_paths)
    non_pos_total = max(1, total_docs - pos_cnt)
    neg_rate = float(neg_target) / float(non_pos_total)
    threshold = _stable_sample_threshold(rate=neg_rate)

    plan = {
        "total_docs_in_corpus": int(total_docs),
        "positive_docids": int(pos_cnt),
        "target_passages": int(target),
        "target_negatives": int(neg_target),
        "negative_sample_rate": round(float(neg_rate), 8),
        "negative_hash_threshold_u64": int(threshold),
        "chunks_per_document": int(max(1, int(chunks_per_document or 0))),
        "dry_run": False,
        "overwrite": bool(overwrite),
        "elapsed_count_pass_sec": round(float(time.time() - t0), 2),
        "corpus_files": list(corpus_filenames),
    }

    if overwrite:
        wipe = _delete_dataset_documents(tenant_id=tenant_id, dataset_id=dataset_id)
    else:
        wipe = None

    db = SessionLocal()
    try:
        indexer = Indexer(db)

        chunks_per_document = max(1, int(chunks_per_document or 0))
        shard_idx = 0
        shard_chunks: list[ChunkInput] = []
        shard_chars = 0

        seeded_passages = 0
        seeded_positive = 0
        seeded_negative = 0

        def _flush() -> None:
            nonlocal shard_idx, shard_chunks, shard_chars
            nonlocal seeded_passages, seeded_positive, seeded_negative
            if not shard_chunks:
                return

            doc_id = uuid5(dataset_id, f"doc:{shard_idx}")
            filename = f"public_bench_miracl_zh_pool_{shard_idx:05}.md"
            file_path = f"miracl://{LANG}/pool/{shard_idx:05}"

            # Upsert document row (idempotent across reruns for the same shard id).
            row = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id, DBDocument.id == doc_id).first()
            if row is None:
                row = DBDocument(
                    id=doc_id,
                    tenant_id=tenant_id,
                    dataset_id=dataset_id,
                    filename=filename,
                    file_type="md",
                    file_size=int(shard_chars),
                    file_path=file_path,
                    status="completed",
                    publication_status="published",
                    chunk_count=len(shard_chunks),
                    total_characters=int(shard_chars),
                    doc_metadata={
                        "public_bench": {"key": BENCH_KEY, "lang": LANG},
                        "source": "miracl",
                    },
                )
                db.add(row)
                db.commit()
            else:
                row.dataset_id = dataset_id
                row.filename = filename
                row.file_type = "md"
                row.file_size = int(shard_chars)
                row.file_path = file_path
                row.status = "completed"
                row.error_message = None
                row.publication_status = "published"
                row.chunk_count = len(shard_chunks)
                row.total_characters = int(shard_chars)
                meta0 = row.doc_metadata if isinstance(row.doc_metadata, dict) else {}
                meta0["public_bench"] = {"key": BENCH_KEY, "lang": LANG}
                meta0.setdefault("source", "miracl")
                row.doc_metadata = meta0
                db.commit()

            # Index + persist chunks.
            indexer.index_chunks(
                document_id=doc_id,
                tenant_id=tenant_id,
                chunks=list(shard_chunks),
                default_source=filename,
                commit=True,
                options=None,
            )

            seeded_passages += len(shard_chunks)

            shard_idx += 1
            shard_chunks = []
            shard_chars = 0

        for obj in _iter_corpus_records(corpus_paths):
            docid = str(obj.get("docid") or "").strip()
            if not docid:
                continue

            is_pos = docid in positive_docids
            if not is_pos:
                h = _sha256_u64(docid)
                if h >= threshold:
                    continue

            title = str(obj.get("title") or "").strip()
            text = str(obj.get("text") or "").strip()
            if not text:
                continue

            content = f"{title}\n{text}" if title else text
            shard_chars += len(content)

            chunk_id = _uuid_for_chunk(dataset_id=dataset_id, docid=docid)
            meta: dict[str, Any] = {
                "chunk_id": str(chunk_id),
                "source": title or "miracl",
                "language": LANG,
                "public_bench": {"key": BENCH_KEY, "docid": docid},
                "miracl_docid": docid,
                "title": title,
            }
            shard_chunks.append(ChunkInput(content=content, metadata=meta, page_number=None, start_char=None, end_char=None))

            if is_pos:
                seeded_positive += 1
            else:
                seeded_negative += 1

            if len(shard_chunks) >= chunks_per_document:
                _flush()

        _flush()
        db.commit()

        return {
            "ok": True,
            "plan": plan,
            "wipe": wipe,
            "seeded": {
                "passages": int(seeded_passages),
                "positive": int(seeded_positive),
                "negative": int(seeded_negative),
                "documents": int(shard_idx),
            },
        }
    finally:
        db.close()


def _iter_reference_chunk_ids(*, dataset_id: UUID, case_items: Iterable[CaseItem]) -> list[UUID]:
    """
    Return all unique chunk UUIDs referenced by exported cases (deterministic).
    """
    out: set[UUID] = set()
    for it in case_items or []:
        for docid in (it.positive_docids or ()):
            out.add(_uuid_for_chunk(dataset_id=dataset_id, docid=str(docid)))
    return sorted(out, key=lambda x: str(x))


def verify_reference_integrity(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    case_items: list[CaseItem],
    batch_size: int = 500,
) -> dict[str, Any]:
    """
    Verify that every reference chunk_id in exported cases exists in DB for this dataset.

    This catches upstream dataset drift (when HF revisions aren't pinned) and partial/incomplete seeding.
    """
    want = _iter_reference_chunk_ids(dataset_id=dataset_id, case_items=case_items)
    if not want:
        return {"ok": True, "checked": 0, "missing": 0, "missing_sample": []}

    bs = max(1, min(2000, int(batch_size or 0)))
    db = SessionLocal()
    try:
        found: set[UUID] = set()
        for i in range(0, len(want), bs):
            batch = want[i : i + bs]
            rows = (
                db.query(DocumentChunk.id)
                .join(DBDocument, DBDocument.id == DocumentChunk.document_id)
                .filter(
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.id.in_(batch),
                    DBDocument.tenant_id == tenant_id,
                    DBDocument.dataset_id == dataset_id,
                )
                .all()
            )
            for r in rows:
                cid = r[0] if isinstance(r, tuple) else r
                if cid is None:
                    continue
                try:
                    found.add(UUID(str(cid)))
                except Exception:
                    continue

        missing = [cid for cid in want if cid not in found]
        return {
            "ok": len(missing) == 0,
            "checked": int(len(want)),
            "missing": int(len(missing)),
            "missing_sample": [str(x) for x in missing[:20]],
        }
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Seed MIRACL zh pool public benchmark (DB + Milvus) and export cases bundle.")
    p.add_argument("--tenant-id", type=str, default="", help="Tenant UUID (default: settings.DEFAULT_TENANT_ID)")

    p.add_argument(
        "--hf-revision",
        type=str,
        default="",
        help="Pin HuggingFace dataset revision/tag/commit for miracl/miracl (topics/qrels) (optional; recommended for reproducibility).",
    )
    p.add_argument(
        "--hf-revision-corpus",
        type=str,
        default="",
        help="Pin HuggingFace dataset revision/tag/commit for miracl/miracl-corpus (optional; recommended for reproducibility).",
    )

    p.add_argument("--splits", type=str, default="train,dev", help="Comma-separated MIRACL splits: train,dev (default: %(default)s)")
    p.add_argument("--max-cases", type=int, default=0, help="Max cases to export (0 = all; keep <= 2000 for import)")
    p.add_argument("--max-refs-per-case", type=int, default=3, help="Max positive refs per case (default: %(default)s)")

    p.add_argument("--target-passages", type=int, default=200_000, help="Target passages in pool corpus (default: %(default)s)")
    p.add_argument("--chunks-per-document", type=int, default=1000, help="Chunks per synthetic document shard (default: %(default)s)")
    p.add_argument("--overwrite", action="store_true", help="Delete existing documents for this dataset before seeding")

    p.add_argument("--out-cases", type=str, default="", help="Write regression case bundle JSON to this path (optional)")
    p.add_argument("--out-manifest", type=str, default="", help="Write seed manifest JSON to this path (optional)")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan only (no DB writes). Default.")
    mode.add_argument("--execute", action="store_true", help="Execute seeding (writes DB + vector store).")

    args = p.parse_args(argv)
    dry_run = not bool(args.execute)

    from app.core.config import settings

    hf_revision = str(args.hf_revision or "").strip() or None
    hf_revision_corpus = str(args.hf_revision_corpus or "").strip() or None
    if not hf_revision:
        print(
            "[public_bench] WARN: --hf-revision not set; upstream dataset changes may break reproducibility",
            file=sys.stderr,
        )
    if not hf_revision_corpus:
        print(
            "[public_bench] WARN: --hf-revision-corpus not set; upstream dataset changes may break reproducibility",
            file=sys.stderr,
        )

    try:
        tenant_id = UUID(str(args.tenant_id or settings.DEFAULT_TENANT_ID))
    except Exception:
        print("[public_bench] ERROR: invalid tenant id", file=sys.stderr)
        return 2

    dataset_id = _uuid_for_dataset(tenant_id=tenant_id, key=BENCH_KEY)
    dataset_name = "Public Bench (MIRACL zh pool v1)"
    dataset_desc = (
        "Reproducible public retrieval benchmark seeded from MIRACL zh.\n"
        "Pool-corpus: positives (qrels) + hashed-sampled negatives.\n"
        "Intended for nightly retrieval-only regression and ablations."
    )
    owner_id = "public-bench-bot"

    splits_raw = [s.strip() for s in str(args.splits or "").split(",") if s.strip()]
    splits_norm = [str(s).strip().lower() for s in splits_raw if str(s).strip()]
    if not splits_norm:
        splits_norm = ["train", "dev"]
    case_items = build_case_items(
        splits=splits_norm,
        max_cases=int(args.max_cases or 0),
        max_refs_per_case=int(args.max_refs_per_case or 0),
        revision=hf_revision,
    )
    if not case_items:
        print("[public_bench] ERROR: zero cases built (splits/qrels mismatch?)", file=sys.stderr)
        return 2

    # Export cases bundle (always allowed; does not require DB).
    if str(args.out_cases or "").strip():
        export_regression_cases_bundle(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            case_items=case_items,
            out_path=Path(str(args.out_cases)),
        )

    # Prepare DB schema and dataset row if we plan to execute.
    if not dry_run:
        _ensure_schema()
        _upsert_dataset(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            name=dataset_name,
            description=dataset_desc,
            owner_id=owner_id,
            meta={
                "public_bench": {
                    "key": BENCH_KEY,
                    "source": "MIRACL",
                    "lang": LANG,
                    "splits": splits_norm,
                    "target_passages": int(args.target_passages or 0),
                    "chunks_per_document": int(args.chunks_per_document or 0),
                    "max_refs_per_case": int(args.max_refs_per_case or 0),
                }
            },
        )

    t0 = time.time()
    res = seed_pool_corpus(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        case_items=case_items,
        target_passages=int(args.target_passages or 0),
        chunks_per_document=int(args.chunks_per_document or 0),
        overwrite=bool(args.overwrite),
        dry_run=bool(dry_run),
        revision=hf_revision_corpus,
    )

    integrity: dict[str, Any] | None = None
    if not dry_run:
        integrity = verify_reference_integrity(tenant_id=tenant_id, dataset_id=dataset_id, case_items=case_items)

    if str(args.out_manifest or "").strip():
        seeded = res.get("seeded") if isinstance(res, dict) else None
        plan = res.get("plan") if isinstance(res, dict) else None
        topics_files = [f"miracl-v1.0-{LANG}/topics/topics.miracl-v1.0-{LANG}-{s}.tsv" for s in splits_norm]
        qrels_files = [f"miracl-v1.0-{LANG}/qrels/qrels.miracl-v1.0-{LANG}-{s}.tsv" for s in splits_norm]
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "generated_at": datetime.now(UTC).isoformat(),
            "bench_key": BENCH_KEY,
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "hf": {
                "miracl": {
                    "repo_id": MIRACL_DATASET_REPO,
                    "repo_type": "dataset",
                    "revision": hf_revision,
                    "files": {
                        "topics": topics_files,
                        "qrels": qrels_files,
                    },
                },
                "miracl_corpus": {
                    "repo_id": MIRACL_CORPUS_REPO,
                    "repo_type": "dataset",
                    "revision": hf_revision_corpus,
                    "files": {
                        "corpus_files": list((plan or {}).get("corpus_files") or []) if isinstance(plan, dict) else [],
                    },
                },
            },
            "params": {
                "splits": splits_norm,
                "max_cases": int(args.max_cases or 0),
                "max_refs_per_case": int(args.max_refs_per_case or 0),
                "target_passages": int(args.target_passages or 0),
                "chunks_per_document": int(args.chunks_per_document or 0),
                "overwrite": bool(args.overwrite),
                "dry_run": bool(dry_run),
            },
            "counts": {
                "cases": int(len(case_items)),
                "seeded_passages": int((seeded or {}).get("passages") or 0) if not dry_run else None,
            },
            "plan": plan,
            "reference_integrity": integrity,
        }
        write_json_file(Path(str(args.out_manifest)), manifest)
        print(f"[public_bench] wrote manifest: {args.out_manifest}", file=sys.stderr)

    if integrity and not bool(integrity.get("ok")):
        sample = ", ".join((integrity.get("missing_sample") or [])[:5])
        print(
            f"[public_bench] ERROR: reference integrity check failed: missing={integrity.get('missing')} (e.g. {sample})",
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            {
                "ok": True,
                "bench_key": BENCH_KEY,
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "dry_run": bool(dry_run),
                "cases": int(len(case_items)),
                "elapsed_sec": round(float(time.time() - t0), 2),
                "result": res,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
