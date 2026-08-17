#!/usr/bin/env python3
"""
Seed a reproducible *public* evidence/citation benchmark into MimirQ (DB + vector store).

Benchmark: CFEVER dev evidence (Chinese FEVER-style claim verification).
Source: HuggingFace dataset `IKMLab-team/cfever` (Apache-2.0).

Why:
- MIRACL covers retrieval relevance/recall well (A/C).
- CFEVER adds a stronger "citation trust" dimension (B): each claim has gold evidence
  pointers (page_title + sentence_id) into a fixed wiki snapshot.

What this script does:
1) Build a regression case bundle (mimirq.regression_cases.v1) from CFEVER dev:
   - question = claim
   - reference_sources = sentence-level evidence chunk UUIDs (deterministic)
2) (Optional, --execute) seed only the required wiki pages (referenced by dev evidence)
   into a dedicated dataset, sentence-per-chunk, indexed via Indexer (DB + Milvus + BM25).

Notes:
- Default mode is dry-run (no DB writes, no big wiki downloads).
- Seeding the wiki subset is a one-time build step; nightly should run retrieval-only eval
  and ablations, not re-embedding the corpus.
"""

import argparse
import json
import re
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

BENCH_KEY = "public_bench.cfever_dev.v1"
REPO_ID = "IKMLab-team/cfever"

SPLIT = "dev"
LANG = "zh"

MANIFEST_SCHEMA = "mimirq.public_bench_manifest.v1"


def write_json_file(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def _list_wiki_files(*, revision: str | None = None) -> list[str]:
    api = HfApi()
    files = api.list_repo_files(repo_id=REPO_ID, repo_type="dataset", revision=revision)
    wiki = [f for f in files if re.fullmatch(r"wiki-\d{3}\.jsonl", f)]
    return sorted(wiki)


def _download_file(filename: str, *, revision: str | None = None) -> Path:
    return Path(hf_hub_download(repo_id=REPO_ID, repo_type="dataset", filename=filename, revision=revision))


def _ensure_schema() -> None:
    apply_runtime_migrations(engine)
    Base.metadata.create_all(bind=engine)
    apply_runtime_migrations(engine)


def _uuid_for_dataset(*, tenant_id: UUID, key: str) -> UUID:
    return uuid5(tenant_id, str(key))


def _uuid_for_sentence(*, dataset_id: UUID, page_title: str, sentence_id: int) -> UUID:
    return uuid5(dataset_id, f"cfever:{SPLIT}:{page_title}:{int(sentence_id)}")


_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_filename(text: str, *, max_chars: int = 120) -> str:
    s = str(text or "").strip()
    s = s.replace("/", "_").replace("\\", "_")
    s = _SAFE_NAME_RE.sub("_", s)
    s = s.strip("._-")
    if not s:
        s = "page"
    if max_chars and len(s) > int(max_chars):
        s = s[: int(max_chars)]
    return s


@dataclass(frozen=True)
class DevCase:
    cid: str
    label: str
    domain: str
    claim: str
    # One evidence "set": list of (page_title, sentence_id)
    evidence: tuple[tuple[str, int], ...]


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _select_evidence_set(raw: Any) -> list[tuple[str, int]]:
    """
    Evidence is a list of evidence-sets; each set is a list of dicts:
      {page_title, sentence_id, ...}

    Our regression case format does not support alternative evidence sets.
    Mainstream compromise: pick the first non-empty evidence set with valid pointers.
    """
    if not isinstance(raw, list):
        return []

    for group in raw:
        if not isinstance(group, list):
            continue
        picked: list[tuple[str, int]] = []
        for ev in group:
            if not isinstance(ev, dict):
                continue
            pt = ev.get("page_title")
            sid = _coerce_int(ev.get("sentence_id"))
            if pt is None or sid is None:
                continue
            title = str(pt).strip()
            if not title:
                continue
            picked.append((title, int(sid)))
        if picked:
            # Dedup stable.
            picked = sorted(set(picked), key=lambda x: (x[0], x[1]))
            return picked

    return []


def build_dev_cases(
    *,
    include_nei: bool,
    max_cases: int,
    max_refs_per_case: int,
    revision: str | None = None,
) -> list[DevCase]:
    path = _download_file(f"{SPLIT}.jsonl", revision=revision)
    rows = _load_jsonl(path)

    out: list[DevCase] = []
    for row in rows:
        cid_raw = row.get("id")
        label = str(row.get("label") or "").strip()
        claim = str(row.get("claim") or "").strip()
        domain = str(row.get("domain") or "").strip()
        if not claim or not label:
            continue
        if label == "NOT ENOUGH INFO" and not include_nei:
            continue

        evidence = _select_evidence_set(row.get("evidence"))
        if label != "NOT ENOUGH INFO" and not evidence:
            # Supports/refutes should have evidence; skip malformed rows.
            continue

        if max_refs_per_case and int(max_refs_per_case) > 0:
            evidence = evidence[: int(max_refs_per_case)]

        out.append(
            DevCase(
                cid=str(cid_raw),
                label=label,
                domain=domain or "unknown",
                claim=claim,
                evidence=tuple(evidence),
            )
        )

    out.sort(key=lambda x: (str(x.label), str(x.cid)))
    if max_cases and int(max_cases) > 0:
        out = out[: int(max_cases)]
    return out


def _required_pages(cases: Iterable[DevCase]) -> dict[str, set[int]]:
    """
    Return {page_title: {sentence_id...}} for evidence pages.
    """
    out: dict[str, set[int]] = {}
    for c in cases:
        for title, sid in c.evidence:
            out.setdefault(title, set()).add(int(sid))
    return out


def export_regression_cases_bundle(*, dataset_id: UUID, cases: list[DevCase], out_path: Path) -> None:
    items: list[dict[str, Any]] = []
    for c in cases or []:
        refs: list[dict[str, Any]] = []
        for title, sid in c.evidence:
            refs.append({"chunk_id": str(_uuid_for_sentence(dataset_id=dataset_id, page_title=title, sentence_id=sid))})

        extra: dict[str, Any] = {}
        if c.label == "NOT ENOUGH INFO":
            # Optional: allows later evaluation of abstain/refusal correctness, even in retrieval-only runs.
            extra["expected_refusal"] = True

        items.append(
            {
                "question": c.claim,
                "expected_answer": c.label,
                "reference_sources": refs,
                "tags": [
                    "public_bench",
                    "cfever",
                    f"split:{SPLIT}",
                    f"label:{c.label.lower().replace(' ', '_')}",
                    f"domain:{c.domain}",
                    f"cid:{c.cid}",
                ],
                "extra": extra or None,
            }
        )

    bundle = {"schema": "mimirq.regression_cases.v1", "dataset_id": str(dataset_id), "items": items}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
        deleted = (
            db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id, DBDocument.dataset_id == dataset_id).delete()
        )
        db.commit()
        return {"deleted_documents": int(deleted or 0), "deleted_vectors_best_effort": int(len(doc_ids))}
    finally:
        db.close()


def _iter_wiki_pages(paths: Iterable[Path]) -> Iterator[dict[str, Any]]:
    for path in paths:
        with path.open("r", encoding="utf-8-sig") as f:
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


def _iter_page_sentences(lines: str) -> Iterator[tuple[int, str]]:
    for raw in str(lines or "").splitlines():
        if "\t" not in raw:
            continue
        sid_raw, text = raw.split("\t", 1)
        try:
            sid = int(sid_raw)
        except Exception:
            continue
        yield sid, str(text or "").strip()


def seed_wiki_subset(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    required: dict[str, set[int]],
    max_pages: int,
    overwrite: bool,
    dry_run: bool,
    revision: str | None = None,
) -> dict[str, Any]:
    wiki_files = _list_wiki_files(revision=revision)
    if not wiki_files:
        raise RuntimeError("CFEVER wiki files not found (repo layout may have changed)")

    titles = sorted(required.keys())
    if max_pages and int(max_pages) > 0:
        titles = titles[: int(max_pages)]
        required = {k: required[k] for k in titles if k in required}

    plan = {
        "repo_id": REPO_ID,
        "repo_type": "dataset",
        "revision": revision,
        "wiki_files": list(wiki_files),
        "required_pages": int(len(required)),
        "max_pages": int(max_pages or 0),
        "dry_run": bool(dry_run),
        "overwrite": bool(overwrite),
    }

    if dry_run:
        return {"ok": True, "plan": plan, "seeded": None}

    if overwrite:
        wipe = _delete_dataset_documents(tenant_id=tenant_id, dataset_id=dataset_id)
    else:
        wipe = None

    paths = [_download_file(fn, revision=revision) for fn in wiki_files]

    db = SessionLocal()
    try:
        indexer = Indexer(db)

        seeded_pages = 0
        seeded_sentences = 0
        skipped_pages = 0

        for obj in _iter_wiki_pages(paths):
            title = str(obj.get("id") or "").strip()
            if not title:
                continue
            if title not in required:
                continue

            needed_sids = required.get(title) or set()
            filename = f"cfever_{_safe_filename(title)}.md"
            doc_id = uuid5(dataset_id, f"page:{title}")
            file_path = f"cfever://{SPLIT}/wiki/{title}"

            # Parse sentences first so we can size the document row.
            chunks: list[ChunkInput] = []
            total_chars = 0
            for sid, sent in _iter_page_sentences(obj.get("lines") or ""):
                if not sent:
                    # Keep only evidence-targeted empty lines (rare); avoid embedding empty text.
                    if sid not in needed_sids:
                        continue
                    sent = title
                content = f"{title}\n{sent}"
                total_chars += len(content)
                chunk_id = _uuid_for_sentence(dataset_id=dataset_id, page_title=title, sentence_id=sid)
                chunks.append(
                    ChunkInput(
                        content=content,
                        metadata={
                            "chunk_id": str(chunk_id),
                            "source": title,
                            "language": LANG,
                            "page_title": title,
                            "sentence_id": int(sid),
                            "public_bench": {"key": BENCH_KEY, "page_title": title, "sentence_id": int(sid)},
                        },
                        page_number=None,
                        start_char=None,
                        end_char=None,
                    )
                )

            if not chunks:
                skipped_pages += 1
                continue

            # Upsert document row (idempotent).
            row = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id, DBDocument.id == doc_id).first()
            if row is None:
                row = DBDocument(
                    id=doc_id,
                    tenant_id=tenant_id,
                    dataset_id=dataset_id,
                    filename=filename,
                    file_type="md",
                    file_size=int(total_chars),
                    file_path=file_path,
                    status="completed",
                    publication_status="published",
                    chunk_count=len(chunks),
                    total_characters=int(total_chars),
                    doc_metadata={
                        "public_bench": {"key": BENCH_KEY, "split": SPLIT, "lang": LANG},
                        "page_title": title,
                        "source": "cfever",
                    },
                )
                db.add(row)
                db.commit()
            else:
                row.dataset_id = dataset_id
                row.filename = filename
                row.file_type = "md"
                row.file_size = int(total_chars)
                row.file_path = file_path
                row.status = "completed"
                row.error_message = None
                row.publication_status = "published"
                row.chunk_count = len(chunks)
                row.total_characters = int(total_chars)
                meta0 = row.doc_metadata if isinstance(row.doc_metadata, dict) else {}
                meta0["public_bench"] = {"key": BENCH_KEY, "split": SPLIT, "lang": LANG}
                meta0["page_title"] = title
                meta0.setdefault("source", "cfever")
                row.doc_metadata = meta0
                db.commit()

            indexer.index_chunks(
                document_id=doc_id,
                tenant_id=tenant_id,
                chunks=chunks,
                default_source=title,
                commit=True,
                options=None,
            )

            seeded_pages += 1
            seeded_sentences += len(chunks)

            if seeded_pages % 25 == 0:
                db.commit()
                print(f"[cfever_seed] seeded pages={seeded_pages} chunks={seeded_sentences}", file=sys.stderr)

        db.commit()

        return {
            "ok": True,
            "plan": plan,
            "wipe": wipe,
            "seeded": {
                "pages": int(seeded_pages),
                "sentences": int(seeded_sentences),
                "skipped_pages": int(skipped_pages),
            },
        }
    finally:
        db.close()


def _iter_reference_chunk_ids(*, dataset_id: UUID, cases: Iterable[DevCase]) -> list[UUID]:
    """
    Return all unique chunk UUIDs referenced by exported cases (deterministic).
    """
    out: set[UUID] = set()
    for c in cases or []:
        for title, sid in c.evidence or ():
            out.add(_uuid_for_sentence(dataset_id=dataset_id, page_title=title, sentence_id=sid))
    return sorted(out, key=lambda x: str(x))


def verify_reference_integrity(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    cases: list[DevCase],
    batch_size: int = 500,
) -> dict[str, Any]:
    """
    Verify that every reference chunk_id in exported cases exists in DB for this dataset.

    This catches upstream dataset drift (when HF revisions aren't pinned) and partial/incomplete seeding.
    """
    want = _iter_reference_chunk_ids(dataset_id=dataset_id, cases=cases)
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
    p = argparse.ArgumentParser(description="Seed CFEVER dev evidence benchmark (DB + Milvus) and export cases bundle.")
    p.add_argument("--tenant-id", type=str, default="", help="Tenant UUID (default: settings.DEFAULT_TENANT_ID)")

    p.add_argument(
        "--hf-revision",
        type=str,
        default="",
        help="Pin HuggingFace dataset revision/tag/commit for IKMLab-team/cfever (optional; recommended for reproducibility).",
    )

    p.add_argument("--include-nei", action="store_true", help="Include NOT ENOUGH INFO cases in exported cases bundle")
    p.add_argument("--max-cases", type=int, default=0, help="Max cases to export (0=all)")
    p.add_argument("--max-refs-per-case", type=int, default=3, help="Max evidence refs per case (default: %(default)s)")

    p.add_argument("--max-pages", type=int, default=0, help="Max wiki pages to seed (0=all required)")
    p.add_argument("--overwrite", action="store_true", help="Delete existing documents for this dataset before seeding")
    p.add_argument(
        "--out-cases", type=str, default="", help="Write regression case bundle JSON to this path (optional)"
    )
    p.add_argument("--out-manifest", type=str, default="", help="Write seed manifest JSON to this path (optional)")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan only (no DB writes). Default.")
    mode.add_argument("--execute", action="store_true", help="Execute seeding (writes DB + vector store).")

    args = p.parse_args(argv)
    dry_run = not bool(args.execute)

    from app.core.config import settings

    hf_revision = str(args.hf_revision or "").strip() or None
    if not hf_revision:
        print(
            "[cfever_seed] WARN: --hf-revision not set; upstream dataset changes may break reproducibility",
            file=sys.stderr,
        )

    try:
        tenant_id = UUID(str(args.tenant_id or settings.DEFAULT_TENANT_ID))
    except Exception:
        print("[cfever_seed] ERROR: invalid tenant id", file=sys.stderr)
        return 2

    dataset_id = _uuid_for_dataset(tenant_id=tenant_id, key=BENCH_KEY)
    dataset_name = "Public Bench (CFEVER dev evidence v1)"
    dataset_desc = (
        "Reproducible public evidence/citation benchmark seeded from CFEVER (dev).\n"
        "Seeds only wiki pages referenced by dev evidence into sentence-level chunks.\n"
        "Intended for retrieval-only regression and nightly ablations."
    )
    owner_id = "public-bench-bot"

    cases = build_dev_cases(
        include_nei=bool(args.include_nei),
        max_cases=int(args.max_cases or 0),
        max_refs_per_case=int(args.max_refs_per_case or 0),
        revision=hf_revision,
    )
    if not cases:
        print("[cfever_seed] ERROR: zero cases built", file=sys.stderr)
        return 2

    if str(args.out_cases or "").strip():
        export_regression_cases_bundle(dataset_id=dataset_id, cases=cases, out_path=Path(str(args.out_cases)))

    required = _required_pages(cases)

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
                    "source": "CFEVER",
                    "split": SPLIT,
                    "lang": LANG,
                    "required_pages": int(len(required)),
                    "max_pages": int(args.max_pages or 0),
                    "max_refs_per_case": int(args.max_refs_per_case or 0),
                    "include_nei": bool(args.include_nei),
                }
            },
        )

    t0 = time.time()
    res = seed_wiki_subset(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        required=required,
        max_pages=int(args.max_pages or 0),
        overwrite=bool(args.overwrite),
        dry_run=bool(dry_run),
        revision=hf_revision,
    )

    integrity: dict[str, Any] | None = None
    if not dry_run:
        integrity = verify_reference_integrity(tenant_id=tenant_id, dataset_id=dataset_id, cases=cases)

    if str(args.out_manifest or "").strip():
        seeded = res.get("seeded") if isinstance(res, dict) else None
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "generated_at": datetime.now(UTC).isoformat(),
            "bench_key": BENCH_KEY,
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "hf": {
                "repo_id": REPO_ID,
                "repo_type": "dataset",
                "revision": hf_revision,
                "files": {
                    "cases_split": f"{SPLIT}.jsonl",
                    "wiki_files": list((res.get("plan") or {}).get("wiki_files") or [])
                    if isinstance(res, dict)
                    else [],
                },
            },
            "params": {
                "include_nei": bool(args.include_nei),
                "max_cases": int(args.max_cases or 0),
                "max_refs_per_case": int(args.max_refs_per_case or 0),
                "max_pages": int(args.max_pages or 0),
                "overwrite": bool(args.overwrite),
                "dry_run": bool(dry_run),
            },
            "counts": {
                "cases": int(len(cases)),
                "required_pages": int(len(required)),
                "seeded_pages": int((seeded or {}).get("pages") or 0) if not dry_run else None,
                "seeded_chunks": int((seeded or {}).get("sentences") or 0) if not dry_run else None,
            },
            "reference_integrity": integrity,
        }
        write_json_file(Path(str(args.out_manifest)), manifest)
        print(f"[cfever_seed] wrote manifest: {args.out_manifest}", file=sys.stderr)

    if integrity and not bool(integrity.get("ok")):
        sample = ", ".join((integrity.get("missing_sample") or [])[:5])
        print(
            f"[cfever_seed] ERROR: reference integrity check failed: missing={integrity.get('missing')} (e.g. {sample})",
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
                "cases": int(len(cases)),
                "required_pages": int(len(required)),
                "elapsed_sec": round(float(time.time() - t0), 2),
                "result": res,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
