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
        "items": [_build_case_bundle_item(dataset_id=dataset_id, case_item=it) for it in (case_items or [])],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build_case_bundle_item(*, dataset_id: UUID, case_item: CaseItem) -> dict[str, Any]:
    refs = [
        {"chunk_id": str(_uuid_for_chunk(dataset_id=dataset_id, docid=docid))} for docid in case_item.positive_docids
    ]
    return {
        "question": case_item.question,
        "expected_answer": None,
        "reference_sources": refs,
        "tags": [
            "public_bench",
            "miracl",
            f"lang:{LANG}",
            f"split:{case_item.split}",
            f"qid:{case_item.qid}",
        ],
    }


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
        deleted = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
            )
            .delete()
        )
        db.commit()
        return {"deleted_documents": int(deleted or 0), "deleted_vectors_best_effort": int(len(doc_ids))}
    finally:
        db.close()


@dataclass
class _ShardBuffer:
    shard_idx: int = 0
    chunks: list[ChunkInput] | None = None
    chars: int = 0
    seeded_passages: int = 0
    seeded_positive: int = 0
    seeded_negative: int = 0

    def __post_init__(self) -> None:
        if self.chunks is None:
            self.chunks = []


def _positive_docids(case_items: Iterable[CaseItem]) -> set[str]:
    out: set[str] = set()
    for item in case_items or []:
        for docid in item.positive_docids:
            if docid:
                out.add(str(docid))
    return out


def _resolve_target_counts(*, target_passages: int, positive_docids: set[str]) -> tuple[int, int, int]:
    pos_cnt = int(len(positive_docids))
    target = max(0, int(target_passages or 0))
    if target <= 0:
        raise ValueError("--target-passages must be > 0")
    if target < pos_cnt:
        target = pos_cnt
    return pos_cnt, target, max(0, target - pos_cnt)


def _dry_run_seed_result(
    *,
    corpus_filenames: list[str],
    chunks_per_document: int,
    overwrite: bool,
    pos_cnt: int,
    target: int,
    neg_target: int,
) -> dict[str, Any]:
    return {
        "ok": True,
        "plan": {
            "total_docs_in_corpus": None,
            "positive_docids": int(pos_cnt),
            "target_passages": int(target),
            "target_negatives": int(neg_target),
            "negative_sample_rate": None,
            "negative_hash_threshold_u64": None,
            "chunks_per_document": int(chunks_per_document),
            "dry_run": True,
            "overwrite": bool(overwrite),
            "corpus_files": list(corpus_filenames),
            "note": (
                "Run with --execute to download/count corpus and compute the deterministic negative sampling threshold."
            ),
        },
        "seeded": None,
    }


def _build_execute_plan(
    *,
    corpus_filenames: list[str],
    chunks_per_document: int,
    overwrite: bool,
    pos_cnt: int,
    target: int,
    neg_target: int,
    total_docs: int,
    threshold: int,
    elapsed_count_pass_sec: float,
) -> dict[str, Any]:
    non_pos_total = max(1, total_docs - pos_cnt)
    neg_rate = float(neg_target) / float(non_pos_total)
    return {
        "total_docs_in_corpus": int(total_docs),
        "positive_docids": int(pos_cnt),
        "target_passages": int(target),
        "target_negatives": int(neg_target),
        "negative_sample_rate": round(float(neg_rate), 8),
        "negative_hash_threshold_u64": int(threshold),
        "chunks_per_document": int(chunks_per_document),
        "dry_run": False,
        "overwrite": bool(overwrite),
        "elapsed_count_pass_sec": round(float(elapsed_count_pass_sec), 2),
        "corpus_files": list(corpus_filenames),
    }


def _corpus_content(obj: dict[str, Any]) -> tuple[str, str, str] | None:
    docid = str(obj.get("docid") or "").strip()
    if not docid:
        return None
    title = str(obj.get("title") or "").strip()
    text = str(obj.get("text") or "").strip()
    if not text:
        return None
    content = f"{title}\n{text}" if title else text
    return docid, title, content


def _should_include_docid(*, docid: str, positive_docids: set[str], threshold: int) -> bool:
    if docid in positive_docids:
        return True
    return _sha256_u64(docid) < threshold


def _chunk_input_for_doc(*, dataset_id: UUID, docid: str, title: str, content: str) -> ChunkInput:
    chunk_id = _uuid_for_chunk(dataset_id=dataset_id, docid=docid)
    metadata: dict[str, Any] = {
        "chunk_id": str(chunk_id),
        "source": title or "miracl",
        "language": LANG,
        "public_bench": {"key": BENCH_KEY, "docid": docid},
        "miracl_docid": docid,
        "title": title,
    }
    return ChunkInput(
        content=content,
        metadata=metadata,
        page_number=None,
        start_char=None,
        end_char=None,
    )


def _upsert_seed_document(
    *,
    db: Any,
    dataset_id: UUID,
    tenant_id: UUID,
    shard_idx: int,
    shard_chars: int,
    shard_chunks: list[ChunkInput],
) -> UUID:
    doc_id = uuid5(dataset_id, f"doc:{shard_idx}")
    filename = f"public_bench_miracl_zh_pool_{shard_idx:05}.md"
    file_path = f"miracl://{LANG}/pool/{shard_idx:05}"

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
        return doc_id

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
    return doc_id


def _flush_seed_shard(
    *,
    db: Any,
    indexer: Indexer,
    dataset_id: UUID,
    tenant_id: UUID,
    state: _ShardBuffer,
) -> None:
    shard_chunks = state.chunks or []
    if not shard_chunks:
        return

    doc_id = _upsert_seed_document(
        db=db,
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        shard_idx=state.shard_idx,
        shard_chars=state.chars,
        shard_chunks=shard_chunks,
    )
    filename = f"public_bench_miracl_zh_pool_{state.shard_idx:05}.md"
    indexer.index_chunks(
        document_id=doc_id,
        tenant_id=tenant_id,
        chunks=list(shard_chunks),
        default_source=filename,
        commit=True,
        options=None,
    )
    state.seeded_passages += len(shard_chunks)
    state.shard_idx += 1
    state.chunks = []
    state.chars = 0


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
    positive_docids = _positive_docids(case_items)
    pos_cnt, target, neg_target = _resolve_target_counts(
        target_passages=target_passages,
        positive_docids=positive_docids,
    )
    chunks_per_document = max(1, int(chunks_per_document or 0))

    corpus_filenames = _list_corpus_files(revision=revision)
    if not corpus_filenames:
        raise RuntimeError("No MIRACL corpus files found for zh (repo layout may have changed)")

    # Dry-run must remain cheap: do not download/count the full corpus.
    if dry_run:
        return _dry_run_seed_result(
            corpus_filenames=corpus_filenames,
            chunks_per_document=chunks_per_document,
            overwrite=overwrite,
            pos_cnt=pos_cnt,
            target=target,
            neg_target=neg_target,
        )

    corpus_paths = _download_corpus_files(corpus_filenames, revision=revision)

    t0 = time.time()
    total_docs = _count_corpus_docs(corpus_paths)
    non_pos_total = max(1, total_docs - pos_cnt)
    threshold = _stable_sample_threshold(rate=float(neg_target) / float(non_pos_total))
    plan = _build_execute_plan(
        corpus_filenames=corpus_filenames,
        chunks_per_document=chunks_per_document,
        overwrite=overwrite,
        pos_cnt=pos_cnt,
        target=target,
        neg_target=neg_target,
        total_docs=total_docs,
        threshold=threshold,
        elapsed_count_pass_sec=time.time() - t0,
    )

    if overwrite:
        wipe = _delete_dataset_documents(tenant_id=tenant_id, dataset_id=dataset_id)
    else:
        wipe = None

    db = SessionLocal()
    try:
        indexer = Indexer(db)
        state = _ShardBuffer()

        for obj in _iter_corpus_records(corpus_paths):
            corpus_content = _corpus_content(obj)
            if corpus_content is None:
                continue
            docid, title, content = corpus_content
            if not _should_include_docid(
                docid=docid,
                positive_docids=positive_docids,
                threshold=threshold,
            ):
                continue

            is_pos = docid in positive_docids
            state.chars += len(content)
            (state.chunks or []).append(
                _chunk_input_for_doc(
                    dataset_id=dataset_id,
                    docid=docid,
                    title=title,
                    content=content,
                )
            )
            if is_pos:
                state.seeded_positive += 1
            else:
                state.seeded_negative += 1

            if len(state.chunks or []) >= chunks_per_document:
                _flush_seed_shard(
                    db=db,
                    indexer=indexer,
                    dataset_id=dataset_id,
                    tenant_id=tenant_id,
                    state=state,
                )

        _flush_seed_shard(
            db=db,
            indexer=indexer,
            dataset_id=dataset_id,
            tenant_id=tenant_id,
            state=state,
        )
        db.commit()

        return {
            "ok": True,
            "plan": plan,
            "wipe": wipe,
            "seeded": {
                "passages": int(state.seeded_passages),
                "positive": int(state.seeded_positive),
                "negative": int(state.seeded_negative),
                "documents": int(state.shard_idx),
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
        for docid in it.positive_docids or ():
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


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Seed MIRACL zh pool public benchmark (DB + Milvus) and export cases bundle.")
    )
    parser.add_argument(
        "--tenant-id",
        type=str,
        default="",
        help="Tenant UUID (default: settings.DEFAULT_TENANT_ID)",
    )
    parser.add_argument(
        "--hf-revision",
        type=str,
        default="",
        help=(
            "Pin HuggingFace dataset revision/tag/commit for miracl/miracl "
            "(topics/qrels) (optional; recommended for reproducibility)."
        ),
    )
    parser.add_argument(
        "--hf-revision-corpus",
        type=str,
        default="",
        help=(
            "Pin HuggingFace dataset revision/tag/commit for miracl/miracl-corpus "
            "(optional; recommended for reproducibility)."
        ),
    )
    parser.add_argument(
        "--splits",
        type=str,
        default="train,dev",
        help="Comma-separated MIRACL splits: train,dev (default: %(default)s)",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=0,
        help="Max cases to export (0 = all; keep <= 2000 for import)",
    )
    parser.add_argument(
        "--max-refs-per-case",
        type=int,
        default=3,
        help="Max positive refs per case (default: %(default)s)",
    )
    parser.add_argument(
        "--target-passages",
        type=int,
        default=200_000,
        help="Target passages in pool corpus (default: %(default)s)",
    )
    parser.add_argument(
        "--chunks-per-document",
        type=int,
        default=1000,
        help="Chunks per synthetic document shard (default: %(default)s)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete existing documents for this dataset before seeding",
    )
    parser.add_argument(
        "--out-cases",
        type=str,
        default="",
        help="Write regression case bundle JSON to this path (optional)",
    )
    parser.add_argument(
        "--out-manifest",
        type=str,
        default="",
        help="Write seed manifest JSON to this path (optional)",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan only (no DB writes). Default.")
    mode.add_argument("--execute", action="store_true", help="Execute seeding (writes DB + vector store).")
    return parser


def _normalize_revision(raw_value: str) -> str | None:
    return str(raw_value or "").strip() or None


def _warn_unpinned_revisions(*, hf_revision: str | None, hf_revision_corpus: str | None) -> None:
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


def _normalize_splits(raw_splits: str) -> list[str]:
    splits_raw = [s.strip() for s in str(raw_splits or "").split(",") if s.strip()]
    splits_norm = [str(s).strip().lower() for s in splits_raw if str(s).strip()]
    return splits_norm or ["train", "dev"]


def _build_manifest(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    splits_norm: list[str],
    hf_revision: str | None,
    hf_revision_corpus: str | None,
    args: argparse.Namespace,
    case_items: list[CaseItem],
    res: dict[str, Any],
    dry_run: bool,
    integrity: dict[str, Any] | None,
) -> dict[str, Any]:
    seeded = res.get("seeded")
    plan = res.get("plan")
    topics_files = [f"miracl-v1.0-{LANG}/topics/topics.miracl-v1.0-{LANG}-{s}.tsv" for s in splits_norm]
    qrels_files = [f"miracl-v1.0-{LANG}/qrels/qrels.miracl-v1.0-{LANG}-{s}.tsv" for s in splits_norm]
    corpus_files: list[str] = []
    if isinstance(plan, dict):
        corpus_files = list(plan.get("corpus_files") or [])

    return {
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
                "files": {"corpus_files": corpus_files},
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


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    dry_run = not bool(args.execute)

    from app.core.config import settings

    hf_revision = _normalize_revision(args.hf_revision)
    hf_revision_corpus = _normalize_revision(args.hf_revision_corpus)
    _warn_unpinned_revisions(
        hf_revision=hf_revision,
        hf_revision_corpus=hf_revision_corpus,
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

    splits_norm = _normalize_splits(args.splits)
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
        manifest = _build_manifest(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            splits_norm=splits_norm,
            hf_revision=hf_revision,
            hf_revision_corpus=hf_revision_corpus,
            args=args,
            case_items=case_items,
            res=res,
            dry_run=dry_run,
            integrity=integrity,
        )
        write_json_file(Path(str(args.out_manifest)), manifest)
        print(f"[public_bench] wrote manifest: {args.out_manifest}", file=sys.stderr)

    if integrity and not bool(integrity.get("ok")):
        sample = ", ".join((integrity.get("missing_sample") or [])[:5])
        print(
            (
                "[public_bench] ERROR: reference integrity check failed: "
                f"missing={integrity.get('missing')} (e.g. {sample})"
            ),
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
